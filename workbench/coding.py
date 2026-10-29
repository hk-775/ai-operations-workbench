"""Reproducible coding-task evidence; candidate code runs only in disposable Docker containers."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import selectors
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .billing import decimal_text, financial, fingerprint as json_fingerprint, total
from .billing_acceptance import read_json, write_private

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/coding"
MAX_OUTPUT = 100_000
MAX_OUTPUT_DEPTH = 64
WRAPPER = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('candidate','/task/solution.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
inputs=json.load(sys.stdin)
result=[]
for value in inputs:
    try:
        result.append({'value':module.solve(value)})
    except BaseException:
        result.append({'error':'candidate_exception'})
print(json.dumps(result,allow_nan=False,separators=(',',':')))
"""


def fingerprint(value):
    """Typed canonical JSON with numeric spelling independent of Python/JS writers.

    Values such as 500 and 500.0 are the same JSON number. Preserve type tags so
    an object/string cannot collide with an encoded number. Financial values
    remain Decimal strings and are never converted to floating point.
    """
    def encode(item):
        if item is None:
            return ["null"]
        if isinstance(item, bool):
            return ["bool", item]
        if isinstance(item, (int, float)):
            number = Decimal(str(item))
            if not number.is_finite():
                raise ValueError("Evidence cannot contain non-finite numbers")
            return ["number", decimal_text(number)]
        if isinstance(item, str):
            return ["string", item]
        if isinstance(item, list):
            return ["array", [encode(child) for child in item]]
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            return ["object", [[key, encode(item[key])] for key in sorted(item)]]
        raise ValueError("Evidence must contain JSON values")
    return json_fingerprint(encode(value))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Call(Strict):
    response_id: str = Field(min_length=1, max_length=200)
    response_model: str | None = Field(default=None, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    cached_input_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    api_estimate_usd: str | None
    latency_ms: float | None = Field(ge=0, le=3_600_000, allow_inf_nan=False)
    cost_basis: Literal["fixture", "recorded_estimate", "unknown"]

    @field_validator("api_estimate_usd")
    @classmethod
    def amount(cls, value):
        if value is None:
            return None
        normalized = financial(value)
        if Decimal(normalized) < 0:
            raise ValueError("Call cost cannot be negative")
        return normalized


class Attempt(Strict):
    replacement: str = Field(min_length=1, max_length=32_000)
    calls: list[Call] = Field(max_length=20)
    other_tool_api_usd: str | None
    human_review_ms: float | None = Field(ge=0, le=3_600_000, allow_inf_nan=False)

    @field_validator("other_tool_api_usd")
    @classmethod
    def amount(cls, value):
        return Call.amount(value)


class Sample(Strict):
    candidate: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)
    repetition: int = Field(ge=1, le=20)
    attempts: list[Attempt] = Field(min_length=1, max_length=5)
    observed_end_to_end_duration_ms: float | None = Field(default=None, ge=0, le=86_400_000, allow_inf_nan=False)


class Recording(Strict):
    schema_name: Literal["workbench.coding.recording.v1", "workbench.coding.recording.v2"] = Field(alias="schema")
    mode: Literal["fixture", "recorded"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_dataset: dict | None = Field(default=None, alias="dataset")
    planned_samples: list[dict] | None = Field(default=None, max_length=1000)
    provenance: str = Field(min_length=1, max_length=2000)
    samples: list[Sample] = Field(min_length=1, max_length=1000)


class TestCase(Strict):
    input: Any
    expected: Any


class CodingCase(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=8000)
    source: str = Field(min_length=1, max_length=32_000)
    reference: str = Field(min_length=1, max_length=32_000)
    public_tests: list[TestCase] = Field(min_length=1, max_length=64)
    acceptance_tests: list[TestCase] = Field(min_length=1, max_length=128)


class CodingDataset(Strict):
    schema_name: Literal["workbench.coding.cases.v1", "workbench.coding.calibration.v1",
                         "workbench.coding.private.v1"] = Field(alias="schema")
    cases: list[CodingCase] = Field(min_length=1, max_length=100)


def dataset():
    return read_json(DATA / "cases.json")


def validate_dataset(value):
    """Validate data only. References and candidate code are never executed here."""
    CodingDataset.model_validate(value)
    identities = [case["id"] for case in value["cases"]]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate coding task identity")
    fingerprint(value)  # Reject non-finite numbers and non-JSON test values.
    if len(json.dumps(value).encode()) > 4_000_000:
        raise ValueError("Coding dataset exceeds its byte limit")
    return value


def recording_dataset(value):
    version = value.schema_name if isinstance(value, Recording) else value["schema"]
    embedded = value.case_dataset if isinstance(value, Recording) else value.get("dataset")
    if version == "workbench.coding.recording.v1":
        if embedded is not None:
            raise ValueError("Version 1 recordings cannot replace the installed dataset")
        return dataset()
    if version != "workbench.coding.recording.v2" or embedded is None:
        raise ValueError("Version 2 recordings require an embedded frozen dataset")
    return validate_dataset(embedded)


def prompt(case):
    """The candidate receives the broken snapshot and public tests only."""
    return {"task": case["prompt"], "files": {"solution.py": case["source"]},
            "public_tests": case["public_tests"],
            "response_contract": "Return only the complete replacement contents of solution.py."}


def verify_recording(value):
    recording = Recording.model_validate(value)
    cases = recording_dataset(recording)
    if recording.dataset_sha256 != fingerprint(cases):
        raise ValueError("Recording dataset differs from the installed coding contract")
    known = {case["id"] for case in cases["cases"]}
    planned = None
    if recording.schema_name == "workbench.coding.recording.v2":
        if not recording.planned_samples:
            raise ValueError("Version 2 recordings require the complete planned schedule")
        planned = set()
        for row in recording.planned_samples:
            if set(row) != {"candidate", "case_id", "repetition"} or (
                not isinstance(row["candidate"], str) or not 1 <= len(row["candidate"]) <= 100 or
                not isinstance(row["case_id"], str) or row["case_id"] not in known or type(row["repetition"]) is not int or
                not 1 <= row["repetition"] <= 20
            ):
                raise ValueError("Invalid planned coding sample")
            key = (row["candidate"], row["case_id"], row["repetition"])
            if key in planned:
                raise ValueError("Duplicate planned coding sample")
            planned.add(key)
        candidates = {candidate for candidate, _, _ in planned}
        repetitions = {repetition for _, _, repetition in planned}
        expected = {(candidate, case_id, repetition) for candidate in candidates
                    for case_id in known for repetition in repetitions}
        if planned != expected or repetitions != set(range(1, max(repetitions) + 1)):
            raise ValueError("Planned candidates must cover every case and repetition equally")
    elif recording.planned_samples is not None:
        raise ValueError("Version 1 recordings cannot replace the installed schedule")
    seen, responses = set(), set()
    for sample in recording.samples:
        key = (sample.candidate, sample.case_id, sample.repetition)
        if key in seen or sample.case_id not in known:
            raise ValueError("Duplicate or unknown candidate/case/repetition")
        if planned is not None and key not in planned:
            raise ValueError("Recorded sample was not in the frozen schedule")
        seen.add(key)
        latencies = [c.latency_ms for a in sample.attempts for c in a.calls]
        if sample.observed_end_to_end_duration_ms is not None and all(t is not None for t in latencies):
            if sample.observed_end_to_end_duration_ms < sum(latencies):
                raise ValueError("End-to-end duration cannot be shorter than sequential model calls")
        for attempt in sample.attempts:
            for call in attempt.calls:
                if call.response_id in responses:
                    raise ValueError("A model call is counted more than once")
                responses.add(call.response_id)
                if (call.cost_basis == "fixture") != (recording.mode == "fixture"):
                    raise ValueError("Fixture and recorded evidence must remain separate")
                if (call.api_estimate_usd is None) != (call.cost_basis == "unknown"):
                    raise ValueError("Unknown costs must remain unknown")
    return recording


class DockerRunner:
    def __init__(self, image: str, *, timeout=8):
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeError("Docker is required; candidate code never runs on the host")
        info = subprocess.run([self.docker, "image", "inspect", image], check=True,
                              capture_output=True, text=True, timeout=15)
        details = json.loads(info.stdout)[0]
        self.image = details["Id"]
        self.repo_digests = details.get("RepoDigests", [])
        self.timeout = timeout

    def run(self, source, inputs):
        """Bound CPU, memory, processes, output and time; do not expose host secrets."""
        name = "workbench-coding-" + uuid.uuid4().hex
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="workbench-coding-") as directory:
            target = Path(directory)
            target.chmod(0o755)
            (target / "solution.py").write_text(source)
            (target / "solution.py").chmod(0o444)
            command = [
                self.docker, "run", "--rm", "--name", name, "--pull=never",
                "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=32",
                "--cpus=1", "--memory=128m", "--memory-swap=128m",
                "--user=65534:65534", "--ulimit=nofile=64:64",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=8m", "--log-driver=none",
                "--mount", f"type=bind,source={directory},target=/task,readonly",
                "--entrypoint=python", "-i", self.image, "-I", "-B", "-c", WRAPPER,
            ]
            status, output = "completed", bytearray()
            # A file avoids blocking on a pipe while a candidate floods stdout.
            with tempfile.TemporaryFile() as input_file:
                input_file.write(json.dumps(inputs).encode())
                input_file.seek(0)
                process = subprocess.Popen(command, stdin=input_file, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT)
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        eof = False
                        while not eof:
                            if time.monotonic() - started > self.timeout:
                                status = "timeout"
                                break
                            for key, _ in selector.select(.1):
                                part = os.read(key.fileobj.fileno(), 8192)
                                if not part:
                                    eof = True
                                    break
                                output.extend(part)
                                if len(output) > MAX_OUTPUT:
                                    status = "output_limit"
                                    eof = True
                                    break
                    if status != "completed":
                        process.kill()
                    process.wait(timeout=5)
                    if status == "completed" and process.returncode:
                        status = "candidate_error"
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    process.stdout.close()
                    subprocess.run([self.docker, "rm", "-f", name], capture_output=True, timeout=15)
        values = None
        if status == "completed":
            try:
                values = candidate_values(output, len(inputs))
            except (ValueError, UnicodeError, RecursionError, OverflowError):
                status = "invalid_output"
        return {"status": status, "values": values, "duration_ms": round((time.monotonic() - started) * 1000, 3)}


def candidate_values(output, count):
    def invalid_constant(_):
        raise ValueError("Nonfinite candidate output")
    def unique_keys(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate candidate output field")
            result[key] = value
        return result
    values = json.loads(output, parse_constant=invalid_constant, object_pairs_hook=unique_keys)
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("Candidate output count differs")
    pending = [(values, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > MAX_OUTPUT_DEPTH or isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Unsupported candidate output")
        if isinstance(value, (dict, list)):
            pending.extend((child, depth + 1) for child in
                           (value.values() if isinstance(value, dict) else value))
    return values


def grades(run, tests):
    if run["status"] != "completed":
        return [False] * len(tests)
    # Expected values belong to the trusted, validated dataset. Candidate
    # serialization failures must not terminate the remaining benchmark.
    expected = [fingerprint(test["expected"]) for test in tests]
    result = []
    for actual, target in zip(run["values"], expected):
        try:
            result.append(isinstance(actual, dict) and set(actual) == {"value"} and
                          fingerprint(actual["value"]) == target)
        except (ValueError, RecursionError, OverflowError):
            result.append(False)
    return result


def evaluate(value, runner):
    recording = verify_recording(value)
    cases = {case["id"]: case for case in recording_dataset(recording)["cases"]}
    baselines, original_checks = {}, {}
    for identity, case in cases.items():
        tests = case["public_tests"] + case["acceptance_tests"]
        original = runner.run(case["source"], [t["input"] for t in tests])
        reference = runner.run(case["reference"], [t["input"] for t in tests])
        baseline_checks = grades(original, tests)
        reference_checks = grades(reference, tests)
        if all(baseline_checks) or not all(reference_checks):
            raise ValueError("Broken/reference baseline contract failed; no benchmark result is valid")
        baselines[identity] = {"broken_passed": sum(baseline_checks), "reference_passed": sum(reference_checks),
                               "test_count": len(tests)}
        original_checks[identity] = baseline_checks
    tasks = []
    for sample in recording.samples:
        case = cases[sample.case_id]
        tests = case["public_tests"] + case["acceptance_tests"]
        attempts = []
        for index, attempt in enumerate(sample.attempts):
            run = runner.run(attempt.replacement, [t["input"] for t in tests])
            checked = grades(run, tests)
            visible = len(case["public_tests"])
            regression = any(was_passed and not now_passed for was_passed, now_passed in
                             zip(original_checks[sample.case_id], checked))
            calls = [call.model_dump() for call in attempt.calls]
            costs = [call.api_estimate_usd for call in attempt.calls]
            complete = all(cost is not None for cost in costs) and attempt.other_tool_api_usd is not None
            api = total(cost for cost in costs if cost is not None)
            diff = "".join(difflib.unified_diff(case["source"].splitlines(True),
                           attempt.replacement.splitlines(True), fromfile="a/solution.py", tofile="b/solution.py"))
            attempts.append({
                "number": index + 1, "passed": all(checked), "public_passed": sum(checked[:visible]),
                "acceptance_passed": sum(checked[visible:]), "regression": regression,
                "execution_status": run["status"], "test_duration_ms": run["duration_ms"],
                "calls": calls, "api_estimate_usd": total([api, attempt.other_tool_api_usd]) if complete else None,
                "known_api_estimate_usd": api, "other_tool_api_usd": attempt.other_tool_api_usd,
                "human_review_ms": attempt.human_review_ms, "patch": diff,
                "source_sha256": hashlib.sha256(attempt.replacement.encode()).hexdigest(),
            })
        costs = [a["api_estimate_usd"] for a in attempts]
        call_times = [c["latency_ms"] for a in attempts for c in a["calls"]]
        tasks.append({
            "candidate": sample.candidate, "case_id": sample.case_id, "title": case["title"],
            "repetition": sample.repetition, "attempts": attempts, "accepted": attempts[-1]["passed"],
            "regression": attempts[-1]["regression"],
            "public_tests": len(case["public_tests"]), "acceptance_tests": len(case["acceptance_tests"]),
            "api_estimate_usd": total(costs) if all(c is not None for c in costs) else None,
            "known_api_estimate_usd": total(a["known_api_estimate_usd"] for a in attempts),
            "other_tool_api_usd": total(a["other_tool_api_usd"] for a in attempts) if all(
                a["other_tool_api_usd"] is not None for a in attempts) else None,
            "recorded_model_duration_ms": sum(call_times) if all(t is not None for t in call_times) else None,
            "test_duration_ms": round(sum(a["test_duration_ms"] for a in attempts), 3),
            "hardware_electricity_usd": None,
            "human_review_ms": sum(a["human_review_ms"] for a in attempts) if all(
                a["human_review_ms"] is not None for a in attempts) else None,
            "observed_end_to_end_duration_ms": sample.observed_end_to_end_duration_ms,
        })
    report = {
        "schema": "workbench.coding.result.v1", "mode": recording.mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recording_sha256": fingerprint(value), "dataset_sha256": recording.dataset_sha256,
        "grader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "recording": value, "baselines": baselines, "tasks": tasks,
        "runtime": {"image_id": runner.image, "repo_digests": runner.repo_digests,
                    "network": "none", "memory_mb": 128, "cpus": 1, "attempt_timeout_seconds": runner.timeout,
                    "verifier_api_calls": 0, "verifier_external_api_usd": "0"},
        "limitations": [
            "Authored Python function repairs are a calibration workload, not evidence of representative repository-level coding performance.",
            "Acceptance tests are withheld from model prompts. Public bundled cases are not a secret holdout; private datasets require independent review.",
            ("Fixture patches, tokens, API estimates and model latency are authored; only container test duration/outcomes are measured."
             if recording.mode == "fixture" else
             "Model outputs, usage and latency are recorded by the collector; container test outcomes are measured independently during replay."),
            "Imported model recordings are operator-supplied, not independently authenticated.",
            "Cost per accepted patch includes every submitted attempt, including failed tasks. Missing costs remain unknown.",
            "Replay measures test execution, not end-to-end model/agent duration. Hardware, electricity and human review costs are unmeasured.",
            "Native coding-tool usage connectors are separate from this coding evaluation; usage alone does not establish code quality. No production routing activation.",
        ],
    }
    report["summary"] = summarize(report)
    report["sha256"] = fingerprint(report)
    return report


def summarize(report):
    summaries = []
    candidates = sorted({task["candidate"] for task in report["tasks"]} |
                        {row["candidate"] for row in report["recording"].get("planned_samples", [])})
    case_ids = {case["id"] for case in recording_dataset(report["recording"])["cases"]}
    for candidate in candidates:
        rows = [task for task in report["tasks"] if task["candidate"] == candidate]
        accepted = sum(task["accepted"] for task in rows)
        costs = [task["api_estimate_usd"] for task in rows]
        complete_cost = all(cost is not None for cost in costs)
        amount = total(costs) if complete_cost else None
        repetitions = {row["repetition"] for row in rows}
        complete_cases = all({row["case_id"] for row in rows if row["repetition"] == repetition} == case_ids for repetition in repetitions)
        planned = report["recording"].get("planned_samples")
        if planned is not None:
            expected = {(row["case_id"], row["repetition"]) for row in planned if row["candidate"] == candidate}
            complete_cases = complete_cases and expected == {(row["case_id"], row["repetition"]) for row in rows}
        summaries.append({
            "candidate": candidate, "tasks": len(rows), "accepted": accepted,
            "failed": len(rows) - accepted, "attempts": sum(len(row["attempts"]) for row in rows),
            "regressions": sum(row["regression"] for row in rows),
            "api_estimate_usd": amount,
            "cost_per_accepted_patch_usd": decimal_text(Decimal(amount) / accepted) if accepted and amount is not None else None,
            "complete_cases": complete_cases, "cost_complete": complete_cost,
            "repetitions": len(repetitions),
        })
    return summaries


def verify_result(value):
    """Integrity checks for display; hashes do not authenticate the executor."""
    if not isinstance(value, dict) or value.get("schema") != "workbench.coding.result.v1":
        raise ValueError("Unsupported coding result")
    if value.get("sha256") != fingerprint({k: v for k, v in value.items() if k != "sha256"}):
        raise ValueError("Coding result checksum differs")
    recording = verify_recording(value["recording"])
    if value.get("recording_sha256") != fingerprint(value["recording"]) or value["mode"] != recording.mode:
        raise ValueError("Coding recording identity differs")
    if value["dataset_sha256"] != recording.dataset_sha256 or value["summary"] != summarize(value):
        raise ValueError("Coding summary or dataset differs")
    if not isinstance(value.get("limitations"), list) or not 1 <= len(value["limitations"]) <= 30 or any(
            not isinstance(text, str) or len(text) > 2000 for text in value["limitations"]):
        raise ValueError("Invalid evidence limitations")
    if value.get("runtime", {}).get("verifier_api_calls") != 0 or value["runtime"].get("verifier_external_api_usd") != "0":
        raise ValueError("Offline replay cannot claim provider API execution")
    tasks = value["tasks"]
    if len(tasks) != len(recording.samples):
        raise ValueError("Coding tasks differ from recorded samples")
    cases = {case["id"]: case for case in recording_dataset(recording)["cases"]}
    for sample, task in zip(recording.samples, tasks):
        if (task["candidate"], task["case_id"], task["repetition"]) != (
                sample.candidate, sample.case_id, sample.repetition) or len(task["attempts"]) != len(sample.attempts):
            raise ValueError("Coding sample identity differs")
        case = cases[sample.case_id]
        for key, expected in (("public_tests", len(case["public_tests"])),
                              ("acceptance_tests", len(case["acceptance_tests"]))):
            if type(task.get(key)) is not int or task[key] != expected:
                raise ValueError("Task test counts differ from the dataset")
        amounts = []
        for index, (saved, attempt) in enumerate(zip(task["attempts"], sample.attempts)):
            if type(saved.get("number")) is not int or saved["number"] != index + 1:
                raise ValueError("Invalid attempt sequence")
            for key, maximum in (("public_passed", len(case["public_tests"])),
                                 ("acceptance_passed", len(case["acceptance_tests"]))):
                if type(saved.get(key)) is not int or not 0 <= saved[key] <= maximum:
                    raise ValueError("Invalid saved test count")
            elapsed = saved.get("test_duration_ms")
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 86_400_000:
                raise ValueError("Invalid test duration")
            if type(saved.get("regression")) is not bool or saved.get("execution_status") not in {
                    "completed", "timeout", "output_limit", "candidate_error", "invalid_output"}:
                raise ValueError("Invalid execution outcome")
            if saved["source_sha256"] != hashlib.sha256(attempt.replacement.encode()).hexdigest() or saved["calls"] != [
                    call.model_dump() for call in attempt.calls]:
                raise ValueError("Coding attempt does not match its recording")
            diff = "".join(difflib.unified_diff(case["source"].splitlines(True),
                attempt.replacement.splitlines(True), fromfile="a/solution.py", tofile="b/solution.py"))
            if saved["patch"] != diff:
                raise ValueError("Final patch differs from recorded source")
            all_known = all(call.api_estimate_usd is not None for call in attempt.calls) and attempt.other_tool_api_usd is not None
            amount = total([call.api_estimate_usd for call in attempt.calls] + [attempt.other_tool_api_usd]) if all_known else None
            if saved["api_estimate_usd"] != amount:
                raise ValueError("Attempt API accounting differs")
            amounts.append(amount)
            passed = (saved["execution_status"] == "completed" and
                      saved["public_passed"] == len(case["public_tests"]) and
                      saved["acceptance_passed"] == len(case["acceptance_tests"]))
            if type(saved["passed"]) is not bool or saved["passed"] != passed:
                raise ValueError("Saved test result is inconsistent")
        task_amount = total(amounts) if all(a is not None for a in amounts) else None
        if (task["api_estimate_usd"] != task_amount or type(task["accepted"]) is not bool or
            task["accepted"] != task["attempts"][-1]["passed"] or type(task["regression"]) is not bool or
            task["regression"] != task["attempts"][-1]["regression"]):
            raise ValueError("Task result or API accounting differs")
        if (task["observed_end_to_end_duration_ms"] != sample.observed_end_to_end_duration_ms or
            task["test_duration_ms"] != round(sum(a["test_duration_ms"] for a in task["attempts"]), 3)):
            raise ValueError("Task timing differs from the recording or replay attempts")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    run = command.add_parser("evaluate")
    run.add_argument("--recording", type=Path, default=DATA / "example-recording.json")
    run.add_argument("--image", required=True, help="Already pulled Docker Python image; execution uses its resolved content ID")
    run.add_argument("--output", type=Path, required=True)
    prompts = command.add_parser("prompts")
    prompts.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prompts":
            write_private(args.output, {case["id"]: prompt(case) for case in dataset()["cases"]})
        else:
            recording = read_json(args.recording, 8_000_000)
            runner = DockerRunner(args.image)
            report = evaluate(recording, runner)
            write_private(args.output, report)
            print(json.dumps(report["summary"], indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        parser.exit(1, "Coding run failed. Check Docker, the locally available Python image, and the recording contract.\n")


if __name__ == "__main__":
    main()
