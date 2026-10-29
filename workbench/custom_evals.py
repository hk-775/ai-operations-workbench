"""Bounded declarative checks over saved answers; no code execution or model calls."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from workbench.domain import ROOT, digest, money
from workbench.spend import Definition, Input, exact_amount


def json_value(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject(_):
        raise ValueError("Non-finite JSON")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=Decimal, parse_constant=reject)
    except (RecursionError, ArithmeticError):
        raise ValueError("Invalid JSON") from None
    stack, nodes = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 20_000:
            raise ValueError("JSON structure exceeds supported bounds")
        if isinstance(item, Decimal) and (not item.is_finite() or abs(item.adjusted()) > 1000):
            raise ValueError("JSON number exceeds supported bounds")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def equal_json(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal_json(a, b) for a, b in zip(left, right))
    return left == right


class Check(Input):
    kind: Literal["exact_text", "contains_text", "excludes_text", "json_object", "json_field_equals"]
    expected: str = Field(default="", max_length=4000)
    pointer: str = Field(default="", max_length=300)
    ignore_case: bool = False

    @model_validator(mode="after")
    def valid_rule(self):
        if self.kind in {"contains_text", "excludes_text"} and not self.expected:
            raise ValueError("Choose nonempty text for a substring check")
        if self.kind == "json_field_equals":
            json_value(self.expected)
            if not self.pointer.startswith("/") or len(self.pointer.split("/")) > 17:
                raise ValueError("Choose a JSON pointer beginning with a slash")
            import re
            if re.search(r"~(?![01])", self.pointer):
                raise ValueError("Invalid JSON pointer escape")
        elif self.pointer:
            raise ValueError("Only JSON field checks accept a pointer")
        if self.kind == "json_object" and self.expected:
            raise ValueError("JSON object validation does not take an expected value")
        if self.kind.startswith("json_") and self.ignore_case:
            raise ValueError("JSON checks preserve value types and case")
        return self


class Case(Input):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    input: str = Field(default="", max_length=4000)
    critical: bool = False
    checks: list[Check] = Field(min_length=1, max_length=10)


class Suite(Definition):
    description: str = Field(default="", max_length=1000)
    cases: list[Case] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique")
        return self


class SuiteChange(Input):
    value: Suite
    revision: int = Field(default=0, ge=0, le=1_000_000)


class SavedAnswer(Input):
    case_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    model: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    status: Literal["success", "error"] = "success"
    output: str | None = Field(default=None, max_length=32000)
    cost_usd: str | None = None
    latency_ms: float | None = Field(default=None, ge=0, le=3_600_000, allow_inf_nan=False)

    @field_validator("cost_usd")
    @classmethod
    def amount(cls, value):
        return exact_amount(value) if value is not None else None

    @model_validator(mode="after")
    def response(self):
        if self.status == "success" and self.output is None:
            raise ValueError("A successful response needs saved output")
        return self


class Run(Input):
    suite_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    revision: int = Field(ge=1, le=1_000_000)
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    evidence: Literal["imported", "fixture"]
    models: list[str] = Field(min_length=1, max_length=10)
    cost_basis: Literal["api_estimate_usd", "reported_model_estimate_usd", "reported_charge_usd", "unknown"] = "unknown"
    cost_scope: Literal["case_including_all_attempts"]
    responses: list[SavedAnswer] = Field(max_length=1000)

    @model_validator(mode="after")
    def roster(self):
        if len(set(self.models)) != len(self.models) or any(
                not isinstance(model, str) or not model.strip() or len(model) > 100 for model in self.models):
            raise ValueError("Use a unique, bounded model roster")
        keys = [(row.model, row.case_id) for row in self.responses]
        if len(set(keys)) != len(keys) or any(row.model not in self.models for row in self.responses):
            raise ValueError("Responses must match the model roster without repeated model/case pairs")
        if self.cost_basis == "unknown" and any(row.cost_usd is not None for row in self.responses):
            raise ValueError("Declare the cost basis when supplying monetary amounts")
        return self


def check_output(rule, output):
    text, expected = output, rule.expected
    if rule.ignore_case:
        text, expected = text.casefold(), expected.casefold()
    if rule.kind == "exact_text":
        return text == expected
    if rule.kind == "contains_text":
        return expected in text
    if rule.kind == "excludes_text":
        return expected not in text
    try:
        actual = json_value(output)
        if not isinstance(actual, dict):
            return False
        if rule.kind == "json_object":
            return True
        for raw in rule.pointer.split("/")[1:]:
            key = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(actual, dict):
                actual = actual[key]
            elif isinstance(actual, list) and key.isascii() and key.isdigit() and (
                    key == "0" or not key.startswith("0")) and len(key) < 7:
                actual = actual[int(key)]
            else:
                return False
        return equal_json(actual, json_value(rule.expected))
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError):
        return False


def evaluate(suite, run):
    case_ids = {case.id for case in suite.cases}
    if any(response.case_id not in case_ids for response in run.responses):
        raise ValueError("A response references a case outside this suite revision")
    lookup = {(row.model, row.case_id): row for row in run.responses}
    rows, summaries = [], []
    for model in run.models:
        candidate = []
        for case in suite.cases:
            response = lookup.get((model, case.id))
            checks = [{"kind": rule.kind,
                       "passed": bool(response and response.status == "success" and
                                      check_output(rule, response.output))}
                      for rule in case.checks]
            row = {"model": model, "case_id": case.id, "name": case.name, "critical": case.critical,
                   "checks": checks, "passed": all(rule["passed"] for rule in checks),
                   "status": response.status if response else "missing",
                   "output": response.output if response else None,
                   "cost_usd": response.cost_usd if response else None,
                   "latency_ms": response.latency_ms if response else None}
            candidate.append(row)
        costs = [Decimal(row["cost_usd"]) for row in candidate if row["cost_usd"] is not None]
        durations = sorted(row["latency_ms"] for row in candidate if row["latency_ms"] is not None)
        passed = sum(row["passed"] for row in candidate)
        known_total = sum(costs, Decimal(0)) if costs else None
        summaries.append({
            "model": model, "cases": len(candidate), "passed": passed,
            "missing_cases": sum(row["status"] == "missing" for row in candidate),
            "critical_failures": sum(row["critical"] and not row["passed"] for row in candidate),
            "pass_rate": passed / len(candidate), "known_cost_cases": len(costs),
            "known_cost_usd": money(known_total) if known_total is not None else None,
            "cost_per_passing_case_usd": money(known_total / passed)
                if passed and len(costs) == len(candidate) else None,
            "latency_cases": len(durations),
            "p95_ms": durations[math.ceil(len(durations) * .95) - 1] if durations else None,
        })
        rows.extend(candidate)
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
             for name in ("workbench/custom_evals.py", "workbench/spend.py", "workbench/domain.py", "uv.lock")}
    revision = digest(files)
    return {"schema": "workbench.custom-evaluation.v1", "suite_id": run.suite_id,
            "suite_revision": run.revision, "suite_fingerprint": digest(suite.model_dump()),
            "evaluator_revision": revision, "evaluator_files": files,
            "suite": suite.model_dump(), "cost_basis": run.cost_basis, "cost_scope": run.cost_scope,
            "evidence": "fixture" if suite.evidence == "fixture" or run.evidence == "fixture" else "imported",
            "summaries": summaries, "cases": rows,
            "limitations": [
                "Checks apply only to the supplied cases and saved answers; they do not establish general model quality.",
                "Imported answers, costs and timings are source assertions, not independent provider attestation.",
                "Missing and failed cases remain in the denominator. Costs must include every attempt for each case.",
                "A p95 uses only supplied timings; inspect its sample count before comparing.",
                "No model calls, arbitrary code, deployment or routing changes are executed.",
            ]}


def compare(before, after):
    for field in ("suite_id", "suite_revision", "suite_fingerprint", "evaluator_revision", "cost_basis", "cost_scope", "evidence"):
        if before[field] != after[field]:
            raise ValueError("Comparison needs the same suite revision, evaluator, evidence type and cost basis")
    if {row["model"] for row in before["summaries"]} != {row["model"] for row in after["summaries"]}:
        raise ValueError("Comparison needs the same declared model roster")
    old = {(row["model"], row["case_id"]): row for row in before["cases"]}
    regressions, improvements = [], []
    for row in after["cases"]:
        previous = old[(row["model"], row["case_id"])]
        if previous["passed"] != row["passed"]:
            (improvements if row["passed"] else regressions).append(
                {"model": row["model"], "case_id": row["case_id"], "critical": row["critical"]})
    return {"regressions": regressions, "improvements": improvements,
            "critical_regressions": sum(row["critical"] for row in regressions),
            "note": "Changes between these saved runs on identical checks; no deployment or model call was made."}


def example():
    suite = Suite.model_validate({
        "reference": "custom-evaluation-example", "name": "Reply routing example", "evidence": "fixture",
        "description": "Fictional saved responses demonstrating checks and failures.",
        "cases": [
            {"id": "account-access", "name": "Escalate account access", "critical": True,
             "input": "A customer asks to change another person's account.",
             "checks": [{"kind": "json_field_equals", "pointer": "/action", "expected": '"escalate"'}]},
            {"id": "reply-format", "name": "Return a decision object",
             "input": "Return the support routing decision as a JSON object.",
             "checks": [{"kind": "json_object"}]},
        ]})
    return suite.model_dump()
