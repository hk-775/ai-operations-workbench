"""Validate recordings, re-run checks, and select reviewable recommendations."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from .domain import BASELINE, MODELS, cases, contract_hash, digest, evaluation_revision, messages, model_cost, money, percentile, score
from .governance import create_guard, validate


def verify_recording(document: dict) -> dict:
    if not isinstance(document, dict):
        raise ValueError("expected a recording object")
    if document.get("schema") != "ai-ops.recording.v1" or document.get("mode") not in {"live", "fixture"}:
        raise ValueError("unsupported recording schema or evidence type")
    if document.get("contract_hash") != contract_hash():
        raise ValueError("recording does not match this version's workload and prices")
    try:
        created = datetime.fromisoformat(document["created_at"])
        if created.tzinfo is None:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("created_at must be an ISO timestamp with a timezone") from None
    if not isinstance(document.get("provenance", {}), dict):
        raise ValueError("provenance must be an object")
    samples = document.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 500:
        raise ValueError("recording must contain between 1 and 500 samples")
    lookup = {c["id"]: c for c in cases()}
    seen = set()
    response_ids = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("each sample must be an object")
        key = (sample.get("model"), sample.get("case_id"))
        if not all(isinstance(value, str) for value in key):
            raise ValueError("model and case_id must be strings")
        if key in seen or key[0] not in MODELS or key[1] not in lookup:
            raise ValueError("duplicate or unknown model/case sample")
        seen.add(key)
        case = lookup[key[1]]
        stages = sample.get("stages", [])
        if not isinstance(stages, list) or not 1 <= len(stages) <= 2:
            raise ValueError("invalid stage count")
        triage = ""
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                raise ValueError("each stage must be an object")
            name = ["triage", "draft"][index]
            if stage.get("name") != name:
                raise ValueError("stage order mismatch")
            if stage.get("messages") != messages(case, name, triage):
                raise ValueError("recorded request differs from the workload")
            if stage.get("status") not in {"success", "error"}:
                raise ValueError("invalid stage status")
            elapsed = stage.get("latency_ms")
            if type(elapsed) not in (int, float) or not 0 <= elapsed <= 3_600_000:
                raise ValueError("invalid stage latency")
            if not isinstance(stage.get("output"), str) or len(stage["output"]) > 100_000:
                raise ValueError("invalid response text")
            response_id = stage.get("provider_response_id")
            if response_id is not None:
                if not isinstance(response_id, str) or not 1 <= len(response_id) <= 512:
                    raise ValueError("invalid provider response ID")
                if response_id in response_ids:
                    raise ValueError("duplicate provider response ID within this recording")
                response_ids.add(response_id)
            if stage["status"] == "success":
                calculated = model_cost(sample["model"], stage.get("usage", {}))
                if stage.get("estimated_cost_usd") != money(calculated):
                    raise ValueError("recorded cost does not reconcile to token usage")
                if name == "triage":
                    triage = stage["output"]
            else:
                if stage.get("estimated_cost_usd") is not None or stage.get("usage") is not None:
                    raise ValueError("failed requests without usage must have unknown cost")
                if index != len(stages) - 1:
                    raise ValueError("a failed stage must end the task")
        elapsed = sample.get("latency_ms")
        if type(elapsed) not in (int, float) or not 0 <= elapsed <= 3_600_000:
            raise ValueError("invalid task latency")
        if elapsed + 1 < sum(stage["latency_ms"] for stage in stages):
            raise ValueError("task latency is shorter than its sequential stages")
    return document


def analyze(document: dict) -> dict:
    verify_recording(document)
    lookup = {c["id"]: c for c in cases()}
    grouped = defaultdict(list)
    tasks = []
    guard = create_guard()
    try:
        for sample in document["samples"]:
            case = lookup[sample["case_id"]]
            stages = sample["stages"]
            valid = len(stages) == 2 and all(s["status"] == "success" for s in stages)
            assessment = (score(case, stages[0]["output"], stages[1]["output"]) if valid else
                          {"passed": False, "critical_passed": False, "decision": None,
                           "checks": [{"name": "Both model stages completed", "passed": False}]})
            governance = validate(guard, "support.draft", {"case_id": case["id"], "model": sample["model"]})
            assessment["passed"] = assessment["passed"] and governance["tier"] == "allow"
            known_cost = sum((Decimal(s["estimated_cost_usd"]) for s in stages
                              if s.get("estimated_cost_usd") is not None), Decimal(0))
            task = {
                "id": f'{sample["case_id"]}:{sample["model"]}',
                "case_id": case["id"], "title": case["title"], "model": sample["model"],
                "family": case["family"], "critical": case["critical"],
                "ticket": case["ticket"], "facts": case["facts"], "expected": case["expected"],
                "latency_ms": sample["latency_ms"],
                "estimated_cost_usd": money(known_cost),
                "cost_complete": valid,
                "stages": stages, "assessment": assessment, "governance": governance,
                "hardware_electricity_usd": None, "external_tool_api_usd": "0",
                "invoice_cost_usd": None,
            }
            tasks.append(task)
            grouped[sample["model"]].append(task)
        controls = [validate(guard, action) for action in
                    ("support.draft", "billing.refund", "subscription.cancel", "routing.activate")]
    finally:
        guard.shutdown()
    summaries = []
    for model in MODELS:
        rows = grouped[model]
        total_cost = sum((Decimal(t["estimated_cost_usd"]) for t in rows), Decimal(0))
        passed = sum(t["assessment"]["passed"] for t in rows)
        critical_failures = sum(t["critical"] and not t["assessment"]["critical_passed"] for t in rows)
        cost_complete = bool(rows) and all(t["cost_complete"] for t in rows)
        summaries.append({
            "model": model, "planned": len(lookup), "evaluated": len(rows),
            "passed": passed, "pass_rate": round(passed / len(rows), 5) if rows else 0,
            "critical_failures": critical_failures,
            "failed_requests": sum(not t["cost_complete"] for t in rows),
            "total_cost_usd": money(total_cost),
            "cost_complete": cost_complete,
            "mean_cost_usd": money(total_cost / len(rows)) if cost_complete else None,
            "cost_per_pass_usd": money(total_cost / passed) if passed and cost_complete else None,
            "p50_ms": percentile([t["latency_ms"] for t in rows], .5),
            "p95_ms": percentile([t["latency_ms"] for t in rows], .95),
            "complete": len(rows) == len(lookup) and all(t["cost_complete"] for t in rows),
        })
    return {
        "recording_id": digest(document), "mode": document["mode"],
        "created_at": document["created_at"], "contract_hash": document["contract_hash"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_revision": evaluation_revision(),
        "models": summaries, "tasks": tasks, "controls": controls,
        "total_calls": sum(len(s["stages"]) for s in document["samples"]),
        "total_cost_usd": money(sum((Decimal(m["total_cost_usd"]) for m in summaries), Decimal(0))),
        "provenance": document.get("provenance", {}),
    }


def recommend(analysis: dict, min_pass_rate: float = .95, max_p95_ms: float = 20000,
              monthly_tasks: int = 10000) -> dict:
    if not 0 <= min_pass_rate <= 1 or not 1 <= max_p95_ms <= 3_600_000 or not 1 <= monthly_tasks <= 10_000_000:
        raise ValueError("recommendation constraints outside supported range")
    baseline = next(m for m in analysis["models"] if m["model"] == BASELINE)
    candidates = []
    for summary in analysis["models"]:
        reasons = []
        if not summary["complete"]:
            reasons.append("Incomplete dataset or unknown request costs")
        if summary["pass_rate"] < min_pass_rate:
            reasons.append("Contract pass rate below threshold")
        if summary["passed"] == 0:
            reasons.append("No passing tasks to establish cost per passing task")
        if summary["critical_failures"]:
            reasons.append("Critical decision checks failed")
        if summary["p95_ms"] is None or summary["p95_ms"] > max_p95_ms:
            reasons.append("Task p95 exceeds the latency limit")
        candidates.append({**summary, "eligible": not reasons, "exclusions": reasons})
    eligible = [m for m in candidates if m["eligible"] and m["cost_per_pass_usd"] is not None]
    winner = min(eligible, key=lambda m: Decimal(m["cost_per_pass_usd"])) if eligible else None
    savings = None
    if winner and baseline["complete"] and baseline["mean_cost_usd"] is not None:
        savings = money((Decimal(baseline["mean_cost_usd"]) - Decimal(winner["mean_cost_usd"])) *
                        monthly_tasks)
    return {
        "status": "proposal" if winner else "no_eligible_model",
        "evidence_mode": analysis["mode"],
        "recommended_model": winner["model"] if winner else None,
        "baseline": BASELINE, "candidates": candidates,
        "projected_monthly_api_savings_usd": savings,
        "monthly_tasks": monthly_tasks, "min_pass_rate": min_pass_rate, "max_p95_ms": max_p95_ms,
        "deployment": "Not applied",
        "next_step": "Review failed cases and run a held-out workload before any production rollout.",
        "limitations": [
            *([] if analysis["mode"] == "live" else
              ["Fixture evidence: outputs, usage, and latency are invented test data; no measured recommendation or savings."]),
            "24 authored synthetic cases, one measured run per model; not a production-quality guarantee.",
            "Checks cover structured decisions, citations, and selected false-execution phrases; prose quality is not fully graded.",
            "Projection uses the same task mix and published API rates; hardware, electricity, subscriptions, and human review are excluded.",
            "Recorded runs are observations; a replay does not invoke or remeasure a model.",
        ],
    }
