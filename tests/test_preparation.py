import json
from collections import Counter

import pytest

from workbench.billing_prepare import prepare, preflight
from workbench.coding import fingerprint, prompt
from workbench.coding_prepare import corpus, plan, verify_baselines


def test_billing_preparation_is_private_incomplete_and_preserves_existing_evidence(tmp_path):
    directory = tmp_path / "private"
    prepare(directory)
    assert directory.stat().st_mode & 0o077 == 0
    for path in directory.iterdir():
        assert path.stat().st_mode & 0o077 == 0
    value = json.loads((directory / "acceptance.json").read_text())
    assert all(v is None for v in value["controls"].values())
    assert value["upload"]["complete_snapshot"] is False
    result = preflight(directory)
    assert result["status"] == "missing_inputs" and len(result["missing"]) == 3
    assert result["aws_calls"] == 0 and result["real_billing_acceptance"] == "pending"
    (directory / "important.csv").write_text("preserve")
    with pytest.raises(FileExistsError):
        prepare(directory)
    assert (directory / "important.csv").read_text() == "preserve"


def test_preflight_cannot_accept_fixture_or_escape_private_directory(tmp_path):
    directory = tmp_path / "kit"
    prepare(directory)
    value = json.loads((directory / "acceptance.json").read_text())
    value["upload"]["files"] = ["../outside.csv"]
    (tmp_path / "outside.csv").write_text("not private evidence")
    (directory / "acceptance.json").write_text(json.dumps(value))
    assert preflight(directory)["status"] == "missing_inputs"


def test_calibration_schedule_freezes_distinct_tasks_and_balanced_candidate_order():
    value = corpus()
    assert len(value["cases"]) == 18
    result = plan(value)
    assert result == plan(value) and result["dataset_sha256"] == fingerprint(value)
    assert result["planned_task_runs"] == 162 and result["model_calls"] == 0
    assert result["approved_api_budget_usd"] is None
    assert result["hardware_and_electricity_cost_usd"] is None
    rows = result["schedule"]
    assert len({(r["case_id"], r["candidate"], r["repetition"]) for r in rows}) == 162
    for offset in range(3):
        assert Counter(row["candidate"] for row in rows[offset::3]) == {
            "candidate-1": 18, "candidate-2": 18, "candidate-3": 18}
    for case in value["cases"]:
        text = prompt(case)
        assert case["reference"] not in text
        assert "acceptance_tests" not in text


def test_baseline_verifier_rejects_a_dataset_that_does_not_catch_the_bug():
    class Runner:
        image = "sha256:test"
        def run(self, source, inputs):
            return {"status": "completed", "values": [{"value": True} for _ in inputs],
                    "duration_ms": 1}
    value = {"cases": [{"id": "ineffective", "source": "", "reference": "",
                       "public_tests": [{"input": {}, "expected": True}], "acceptance_tests": []}]}
    with pytest.raises(ValueError, match="distinguish"):
        verify_baselines(value, Runner())
