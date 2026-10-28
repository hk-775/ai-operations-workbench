import asyncio
import copy
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from test_pilot import pilot, settings
from workbench.coding import (DATA, DockerRunner, dataset, evaluate, fingerprint, grades, prompt,
                              summarize, verify_recording, verify_result)
from workbench.coding_collect import collect, planned_envelope
from workbench.domain import MODELS, prices


def example():
    return json.loads((DATA / "example-recording.json").read_text())


class ContractRunner:
    """Only deterministic test inputs. Actual code execution is covered separately."""
    image = "test-runtime"
    repo_digests = []
    timeout = 8
    def run(self, source, inputs):
        for case in dataset()["cases"]:
            if source in (case["reference"], case["source"]):
                tests = case["public_tests"] + case["acceptance_tests"]
                if source == case["reference"]:
                    values = [{"value": t["expected"]} for t in tests[:len(inputs)]]
                else:
                    values = [{"error": "bug"} for _ in inputs]
                return {"status": "completed", "values": values, "duration_ms": 1}
        return {"status": "candidate_error", "values": None, "duration_ms": 1}


def test_prompt_withholds_acceptance_and_reference():
    for case in dataset()["cases"]:
        view = prompt(case)
        assert set(view) == {"task", "files", "public_tests", "response_contract"}
        assert "reference" not in view and "acceptance_tests" not in view
        assert view["files"] == {"solution.py": case["source"]}


def test_json_number_spelling_round_trips_without_weakening_type_or_cost_identity():
    assert fingerprint({"ms": 500.0, "cost": "0.002"}) == fingerprint({"cost": "0.002", "ms": 500})
    assert fingerprint(0.000001) == fingerprint(1e-6)
    assert fingerprint(1) != fingerprint(True) != fingerprint("1")
    assert fingerprint({"cost": "0.002"}) != fingerprint({"cost": "0.02"})
    with pytest.raises(ValueError, match="non-finite"):
        fingerprint(float("nan"))


def test_all_attempts_and_failed_tasks_count_and_final_patch_controls_acceptance():
    value = evaluate(example(), ContractRunner())
    assert verify_result(value) is value
    by_name = {summary["candidate"]: summary for summary in value["summary"]}
    assert by_name["example-fast"]["accepted"] == 2
    assert by_name["example-fast"]["cost_per_accepted_patch_usd"] == "0.006"
    assert by_name["example-repair"]["attempts"] == 12
    assert by_name["example-repair"]["cost_per_accepted_patch_usd"] == "0.004"
    changed = example()
    changed["samples"][0]["attempts"].append(copy.deepcopy(changed["samples"][0]["attempts"][0]))
    changed["samples"][0]["attempts"][-1]["replacement"] = "def solve(x):\n    return None\n"
    changed["samples"][0]["attempts"][-1]["calls"][0]["response_id"] = "unique-final"
    result = evaluate(changed, ContractRunner())
    assert not result["tasks"][0]["accepted"]  # Earlier success cannot conceal a broken final patch.


def test_missing_costs_and_incomplete_case_coverage_are_not_zero_or_complete():
    recording = example()
    recording["mode"] = "recorded"
    for sample in recording["samples"]:
        for attempt in sample["attempts"]:
            for call in attempt["calls"]:
                call["cost_basis"] = "recorded_estimate"
    recording["samples"][0]["attempts"][0]["calls"][0].update(api_estimate_usd=None, cost_basis="unknown")
    recording["samples"].pop(1)
    result = evaluate(recording, ContractRunner())
    selected = next(s for s in result["summary"] if s["candidate"] == "example-fast")
    assert not selected["cost_complete"] and not selected["complete_cases"]
    assert selected["cost_per_accepted_patch_usd"] is None


def test_source_and_accounting_tampering_are_rejected_even_with_recomputed_outer_hash():
    result = evaluate(example(), ContractRunner())
    for field, replacement in [("patch", "unexecuted patch"), ("api_estimate_usd", "0")]:
        altered = copy.deepcopy(result)
        altered["tasks"][0]["attempts"][0][field] = replacement
        altered["sha256"] = fingerprint({k: v for k, v in altered.items() if k != "sha256"})
        with pytest.raises(ValueError):
            verify_result(altered)
    value = example()
    value["samples"].append(value["samples"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        verify_recording(value)
    altered = copy.deepcopy(result)
    altered["tasks"][0]["public_tests"] = '<img src=x onerror="alert(1)">'
    altered["sha256"] = fingerprint({k: v for k, v in altered.items() if k != "sha256"})
    with pytest.raises(ValueError, match="test counts"):
        verify_result(altered)


def test_read_only_result_preview_auth_csrf_and_no_usage_side_effects(pilot):
    document = evaluate(example(), ContractRunner())
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as client:
        assert client.get("/api/pilot/coding/example").status_code == 401
    assert pilot.client.post("/api/pilot/coding/preview", json=document).status_code == 200
    assert pilot.client.post("/api/pilot/coding/preview", json=document,
                             headers={"X-Workbench-CSRF": ""}).status_code == 403
    altered = copy.deepcopy(document)
    altered["summary"][0]["accepted"] = 1000
    assert pilot.client.post("/api/pilot/coding/preview", json=altered).status_code == 422
    assert pilot.db.usage(pilot.team)["events"] == 0


def test_opt_in_model_recorder_uses_same_cases_no_hidden_feedback_and_preserves_failed_cost(tmp_path):
    class Encoder:
        def encode(self, value):
            return [0] * len(value)
    @dataclass
    class Usage:
        prompt_tokens: int = 100
        completion_tokens: int = 50
        cached_tokens: int = 0
    class Router:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        async def create(self, **request):
            # Check private in-flight evidence exists before the network operation.
            partial = json.loads(output.with_suffix(".partial.json").read_text())
            assert partial["samples"][-1]["attempts"][-1]["calls"][0]["api_estimate_usd"] is None
            self.calls.append(copy.deepcopy(request))
            if len(self.calls) == 1:
                raise RuntimeError("private provider error")
            case = json.loads(request["messages"][1]["content"])
            assert "acceptance_tests" not in case and "reference" not in case
            original = next(c for c in dataset()["cases"] if c["prompt"] == case["task"])
            return SimpleNamespace(id=f"response-{len(self.calls)}",
                                   model="unexpected-model" if len(self.calls) == 2 else request["model"], usage=Usage(),
                                   choices=[{"message": {"content": original["reference"]}}])
    output = tmp_path / "recording.json"
    router = Router()
    result = asyncio.run(collect(output, [MODELS[0]], Decimal("5"), 2, ContractRunner(),
                                 router=router, encoding=Encoder()))
    assert len(result["samples"]) == 6
    assert result["samples"][0]["attempts"][0]["calls"][0]["api_estimate_usd"] is None
    assert result["samples"][1]["attempts"][0]["calls"][0]["response_model"] == "unexpected-model"
    assert result["samples"][1]["attempts"][0]["calls"][0]["api_estimate_usd"] is None
    assert result["samples"][1]["attempts"][0]["replacement"] == dataset()["cases"][1]["source"]
    assert len(router.calls) == 6
    assert "private provider error" not in output.read_text()
    with pytest.raises(ValueError, match="budget"):
        asyncio.run(collect(tmp_path/"small.json", [MODELS[0]], Decimal("0.000001"), 2, ContractRunner(),
                            router=router, encoding=Encoder()))
    assert len(router.calls) == 6  # Insufficient budget never dispatches.


@pytest.mark.skipif(not os.environ.get("WORKBENCH_CODING_IMAGE"), reason="Explicit Docker sandbox verification")
def test_real_container_contract_and_execution_limits(tmp_path):
    runner = DockerRunner(os.environ["WORKBENCH_CODING_IMAGE"], timeout=4)
    case = dataset()["cases"][1]
    tests = case["public_tests"] + case["acceptance_tests"]
    assert all(grades(runner.run(case["reference"], [test["input"] for test in tests]), tests))
    assert not all(grades(runner.run(case["source"], [test["input"] for test in tests]), tests))
    assert runner.run("def solve(x):\n    while True: pass\n", [{}])["status"] == "timeout"
    assert runner.run("def solve(x):\n    print('x' * 200000)\n    return x\n", [{}])["status"] == "output_limit"
    isolation = "import os,socket\n\ndef solve(x):\n    blocked=False\n    try:\n        open('/task/tampered','w')\n    except OSError:\n        blocked=True\n    return {'uid':os.getuid(),'read_only':blocked,'key_present':'OPENAI_API_KEY' in os.environ}\n"
    result = runner.run(isolation, [{}])
    assert result["values"] == [{"value": {"uid": 65534, "read_only": True, "key_present": False}}]
