import asyncio
import copy
import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from test_pilot import pilot, settings
from workbench.coding import evaluate, fingerprint, verify_recording, verify_result
from workbench.coding_collect import collect, freeze_schedule
from workbench.coding_prepare import corpus
from workbench.domain import MODELS


class Runner:
    image = "test"
    repo_digests = []
    timeout = 8

    def run(self, source, inputs):
        case = next(c for c in corpus()["cases"] if source in (c["source"], c["reference"]))
        tests = case["public_tests"] + case["acceptance_tests"]
        values = [{"value": test["expected"]} for test in tests[:len(inputs)]] if source == case["reference"] else [
            {"error": "broken"} for _ in inputs]
        return {"values": values, "status": "completed", "duration_ms": 1}


class Encoder:
    def encode(self, text):
        return [0] * (len(text) // 2)


@dataclass
class Usage:
    prompt_tokens: int = 100
    completion_tokens: int = 50
    cached_tokens: int = 0


class Router:
    def __init__(self, output, fail=False):
        self.output, self.fail, self.calls = output, fail, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **request):
        saved = json.loads(self.output.with_suffix(".partial.json").read_text())
        assert len(saved["planned_samples"]) == 162
        assert saved["samples"][-1]["attempts"][-1]["calls"][0]["api_estimate_usd"] is None
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("private provider details")
        prompt = json.loads(request["messages"][1]["content"])
        assert "reference" not in prompt and "acceptance_tests" not in prompt
        case = next(c for c in corpus()["cases"] if c["prompt"] == prompt["task"])
        return SimpleNamespace(id=f"response-{len(self.calls)}", model=request["model"],
                               usage=Usage(), choices=[{"message": {"content": case["reference"]}}])


def test_extended_repeated_collection_replay_and_browser_contract(tmp_path):
    output = tmp_path / "recording.json"
    router = Router(output)
    value = asyncio.run(collect(output, list(MODELS), Decimal("5"), 2, Runner(),
                               router=router, encoding=Encoder(), case_data=corpus(), repetitions=3))
    assert len(router.calls) == 162
    assert value["dataset_sha256"] == fingerprint(corpus())
    assert value["planned_samples"] == freeze_schedule(corpus(), MODELS, 3, 20261029)
    assert value["schema"] == "workbench.coding.recording.v2"
    result = evaluate(value, Runner())
    assert verify_result(result) == result
    assert all(row["accepted"] == 54 and row["complete_cases"] for row in result["summary"])
    tampered = copy.deepcopy(value)
    tampered["dataset"]["cases"][0]["reference"] += "\n# different frozen source\n"
    with pytest.raises(ValueError, match="dataset"):
        verify_recording(tampered)
    for change in ("missing", "invalid"):
        tampered = copy.deepcopy(value)
        if change == "missing":
            tampered["planned_samples"].pop()
        else:
            tampered["planned_samples"][0]["case_id"] = []
        with pytest.raises(ValueError):
            verify_recording(tampered)


def test_extended_preview_does_not_change_company_usage(tmp_path, pilot):
    output = tmp_path / "recording.json"
    value = asyncio.run(collect(output, list(MODELS), Decimal("5"), 2, Runner(),
                               router=Router(output), encoding=Encoder(),
                               case_data=corpus(), repetitions=3))
    result = evaluate(value, Runner())
    assert pilot.client.post("/api/pilot/coding/preview", json=result).status_code == 200
    assert pilot.db.usage(pilot.team)["events"] == 0


def test_extended_failure_stops_paid_calls_and_keeps_unrun_models_visible(tmp_path):
    output = tmp_path / "failed.json"
    router = Router(output, fail=True)
    value = asyncio.run(collect(output, list(MODELS), Decimal("5"), 2, Runner(),
                               router=router, encoding=Encoder(), case_data=corpus(), repetitions=3))
    assert len(router.calls) == 1
    assert "private provider details" not in output.read_text()
    result = evaluate(value, Runner())
    assert len(result["summary"]) == 3
    assert all(not row["complete_cases"] for row in result["summary"])
    assert result["tasks"][0]["api_estimate_usd"] is None


def test_extended_schedule_budget_is_checked_before_any_request(tmp_path):
    output = tmp_path / "budget.json"
    router = Router(output)
    with pytest.raises(ValueError, match="budget"):
        asyncio.run(collect(output, list(MODELS), Decimal("1"), 2, Runner(),
                            router=router, encoding=Encoder(), case_data=corpus(), repetitions=3))
    assert not router.calls and not output.exists()


def test_invalid_baseline_cannot_spend_model_budget(tmp_path):
    class InvalidReference(Runner):
        def run(self, source, inputs):
            return {"status": "candidate_error", "values": None, "duration_ms": 1}
    output = tmp_path / "invalid.json"
    router = Router(output)
    with pytest.raises(ValueError, match="baseline"):
        asyncio.run(collect(output, list(MODELS), Decimal("5"), 2, InvalidReference(),
                            router=router, encoding=Encoder(), case_data=corpus(), repetitions=3))
    assert not router.calls and not output.exists()
