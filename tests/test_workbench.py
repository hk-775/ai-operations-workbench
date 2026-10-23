import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from workbench.domain import MODELS, cases, contract_hash, false_execution_claim, messages, model_cost, money, score
from workbench.evidence import analyze, recommend, verify_recording
from workbench.governance import create_guard, validate
from workbench.store import Store


def fixture_recording():
    samples = []
    for model in MODELS:
        for case in cases():
            ref = case["expected"]
            triage = json.dumps({"category": ref["category"], "summary": "Fixture triage"})
            draft = json.dumps({k: ref[k] for k in ("category", "resolution", "refund_minor")} |
                               {"citations": [ref["policy"], "P8"], "executed": False,
                                "reply": "This is a synthetic test fixture, not a measured model response."})
            stages = []
            for name, output in [("triage", triage), ("draft", draft)]:
                usage = {"prompt_tokens": 900, "completion_tokens": 100, "cached_tokens": 200}
                stages.append({"name": name, "output": output, "status": "success",
                               "provider_response_id": f"fixture-{model}-{case['id']}-{name}",
                               "messages": messages(case, name, triage),
                               "usage": usage, "estimated_cost_usd": money(model_cost(model, usage)),
                               "latency_ms": 100})
            samples.append({"model": model, "case_id": case["id"], "stages": stages, "latency_ms": 205})
    return {"schema": "ai-ops.recording.v1", "mode": "fixture", "created_at": "2026-10-23T00:00:00Z",
            "contract_hash": contract_hash(), "samples": samples}


def test_rate_calculation_avoids_cached_double_charge():
    assert model_cost(MODELS[0], {"prompt_tokens": 1000, "cached_tokens": 200,
                                 "completion_tokens": 100}) == Decimal("0.0025")
    with pytest.raises(ValueError):
        model_cost(MODELS[0], {"prompt_tokens": 100, "cached_tokens": 200, "completion_tokens": 0})


def test_cases_have_unique_ids_and_do_not_leak_answers():
    corpus = cases()
    assert len({c["id"] for c in corpus}) == 24
    for case in corpus:
        payload = json.loads(messages(case, "triage")[1]["content"])
        assert set(payload) == {"facts", "ticket"}
        assert "expected" not in payload and "critical" not in payload


def test_real_guard_blocks_effects_and_permits_distinct_drafts():
    guard = create_guard()
    try:
        for case in cases():
            for model in MODELS:
                assert validate(guard, "support.draft", {"case_id": case["id"], "model": model})["tier"] == "allow"
        for action in ("billing.refund", "subscription.cancel", "routing.activate"):
            assert validate(guard, action)["tier"] == "block"
    finally:
        guard.shutdown()


def test_false_success_and_boolean_amount_are_not_accepted():
    doc = fixture_recording()
    sample = doc["samples"][0]
    value = json.loads(sample["stages"][1]["output"])
    value["reply"] = "I have processed your refund."
    assert not score(cases()[0], sample["stages"][0]["output"], json.dumps(value))["passed"]
    value["reply"] = "Here is the proposed next step."
    value["refund_minor"] = True
    assert not score(cases()[0], sample["stages"][0]["output"], json.dumps(value))["passed"]


def test_duplicate_json_keys_fail_contract():
    result = score(cases()[0], '{"category":"billing"}', '{"executed":true,"executed":false}')
    assert result["passed"] is False


def test_execution_claim_negation_does_not_hide_later_claim():
    assert not false_execution_claim("No refund has been processed.")
    assert not false_execution_claim("Your refund has not been processed.")
    assert false_execution_claim("The refund has been processed.")
    assert false_execution_claim("No refund has been processed, but I have cancelled the subscription.")


def test_imports_are_idempotent_and_conflicts_roll_back(tmp_path):
    store = Store(tmp_path)
    doc = fixture_recording()
    assert store.import_recording(doc)["added_events"] == 144
    assert store.import_recording(doc)["added_events"] == 0
    changed = copy.deepcopy(doc)
    changed["samples"][0]["stages"][0]["output"] = '{"category":"wrong"}'
    # This is caught by request replay or the event fingerprint.
    with pytest.raises(ValueError):
        store.import_recording(changed)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 144


def test_recording_rejects_price_and_request_tampering():
    doc = fixture_recording()
    verify_recording(doc)
    doc["samples"][0]["stages"][0]["estimated_cost_usd"] = "0.0"
    with pytest.raises(ValueError, match="cost"):
        verify_recording(doc)
    doc = fixture_recording()
    doc["samples"][0]["stages"][0]["messages"][1]["content"] = "spoofed"
    with pytest.raises(ValueError, match="request"):
        verify_recording(doc)


def test_cheapest_failing_model_cannot_win_and_cost_includes_failures():
    doc = fixture_recording()
    bad = next(s for s in doc["samples"] if s["model"] == MODELS[2] and s["case_id"] == "S21")
    decision = json.loads(bad["stages"][1]["output"])
    decision.update(resolution="refund_eligible", refund_minor=19900)
    bad["stages"][1]["output"] = json.dumps(decision)
    report = analyze(doc)
    proposal = recommend(report)
    assert proposal["recommended_model"] == MODELS[1]
    cheap = next(m for m in proposal["candidates"] if m["model"] == MODELS[2])
    assert cheap["critical_failures"] == 1 and not cheap["eligible"]
    assert Decimal(cheap["cost_per_pass_usd"]) > Decimal(cheap["mean_cost_usd"])
    assert recommend(report, max_p95_ms=1)["status"] == "no_eligible_model"
    for model in report["models"]:
        model.update(passed=0, pass_rate=0, critical_failures=0, cost_per_pass_usd=None)
    zero_pass = recommend(report, min_pass_rate=0)
    assert zero_pass["status"] == "no_eligible_model"
    assert all(not m["eligible"] for m in zero_pass["candidates"])


def test_incomplete_or_failed_evidence_cannot_produce_recommendation():
    doc = fixture_recording()
    doc["samples"] = doc["samples"][:3]
    assert recommend(analyze(doc))["status"] == "no_eligible_model"
    doc = fixture_recording()
    stage = doc["samples"][0]["stages"][0]
    stage.update(status="error", output="", usage=None, estimated_cost_usd=None)
    doc["samples"][0]["stages"] = [stage]
    summary = analyze(doc)["models"][0]
    assert summary["failed_requests"] == 1 and not summary["complete"]
    assert summary["mean_cost_usd"] is None and summary["cost_per_pass_usd"] is None
    assert not summary["cost_complete"]


def test_duplicate_events_and_impossible_latency_are_rejected():
    doc = fixture_recording()
    doc["samples"][1]["stages"][0]["provider_response_id"] = doc["samples"][0]["stages"][0]["provider_response_id"]
    with pytest.raises(ValueError, match="duplicate provider"):
        verify_recording(doc)
    doc = fixture_recording()
    doc["samples"][0]["latency_ms"] = 50
    with pytest.raises(ValueError, match="sequential"):
        verify_recording(doc)
