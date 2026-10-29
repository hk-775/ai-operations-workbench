"""Custom-suite integrity, typed checks, missing evidence and private run isolation."""
import copy

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, select

from test_pilot import pilot, settings
from workbench.custom_evals import Check, Run, Suite, check_output, evaluate, example
from workbench.pilot.database import teams, uid, workflow_results


def answers(identity, revision=1, **changes):
    return {"suite_id": identity, "revision": revision, "name": "Saved test run", "evidence": "fixture",
            "models": ["candidate"], "cost_basis": "api_estimate_usd",
            "cost_scope": "case_including_all_attempts",
            "responses": [
                {"case_id": "account-access", "model": "candidate",
                 "output": '{"action":"escalate"}', "cost_usd": "0.01", "latency_ms": 10.0},
                {"case_id": "reply-format", "model": "candidate",
                 "output": "not JSON", "cost_usd": "0.02", "latency_ms": 20.0},
            ], **changes}


@pytest.mark.parametrize(("output", "expected", "passed"), [
    ('{"value":true}', "1", False), ('{"value":1}', "1.0", False),
    ('{"value":0.12345678901234567891}', "0.12345678901234567892", False),
    ('{"value":0.12345678901234567891}', "0.12345678901234567891", True),
    ('{"value":null}', "null", True), ('{"other":null}', "null", False),
    ('{"value":1,"value":2}', "2", False), ('{"value":NaN}', "0", False),
    ('{"value":1e999999}', "0", False),
])
def test_json_checks_preserve_types_decimal_precision_and_reject_ambiguous_json(output, expected, passed):
    rule = Check(kind="json_field_equals", pointer="/value", expected=expected)
    assert check_output(rule, output) is passed


def test_custom_checks_are_bounded_literal_rules_not_executable_code():
    assert check_output(Check(kind="exact_text", expected="OK"), "OK")
    assert not check_output(Check(kind="exact_text", expected="OK"), "OK\n")
    assert check_output(Check(kind="contains_text", expected="OK", ignore_case=True), "Looks ok")
    assert not check_output(Check(kind="json_object"), '{"value":' * 40 + "0" + "}" * 40)
    with pytest.raises(ValidationError):
        Check(kind="contains_text", expected="")
    with pytest.raises(ValidationError):
        Check(kind="python", expected="__import__('os')")
    with pytest.raises(ValidationError):
        Check(kind="json_field_equals", pointer="/invalid~2", expected="true")


def test_custom_missing_failures_and_unknown_costs_remain_in_denominator():
    suite = Suite.model_validate(example())
    run = Run.model_validate(answers("a" * 36, models=["candidate", "missing-model"]))
    result = evaluate(suite, run)
    candidate, missing = result["summaries"]
    assert candidate["passed"] == 1 and candidate["known_cost_usd"] == "0.030000000"
    assert candidate["cost_per_passing_case_usd"] == "0.030000000"
    assert missing["missing_cases"] == missing["cases"] == 2
    assert missing["critical_failures"] == 1 and missing["known_cost_usd"] is None
    assert missing["cost_per_passing_case_usd"] is None
    value = answers("a" * 36)
    value["responses"][1]["cost_usd"] = None
    result = evaluate(suite, Run.model_validate(value))
    assert result["summaries"][0]["known_cost_usd"] == "0.010000000"
    assert result["summaries"][0]["cost_per_passing_case_usd"] is None
    entirely_missing = evaluate(suite, Run.model_validate(answers("a" * 36, responses=[])))
    assert entirely_missing["summaries"][0]["missing_cases"] == 2
    assert entirely_missing["summaries"][0]["critical_failures"] == 1


def test_custom_suite_runs_replay_history_comparison_and_restart(pilot):
    original = pilot.client.post("/api/pilot/custom-evals/suites", json={"value": example()})
    assert original.status_code == 200, original.text
    suite = original.json()
    assert pilot.client.get("/api/pilot/custom-evals/suites").json()["items"] == []
    assert len(pilot.client.get("/api/pilot/custom-evals/suites?include_fixtures=true").json()["items"]) == 1
    value = answers(suite["id"])
    response = pilot.client.post("/api/pilot/custom-evals/runs", json=value)
    assert response.status_code == 200, response.text
    before = response.json()
    assert before["summaries"][0]["passed"] == 1
    assert pilot.client.post("/api/pilot/custom-evals/runs", json=value).json()["unchanged"]
    updated = copy.deepcopy(value)
    updated["responses"][0]["output"] = '{"action":"allow"}'
    after = pilot.client.post("/api/pilot/custom-evals/runs", json=updated).json()
    comparison = pilot.client.get(
        f"/api/pilot/custom-evals/runs/{after['id']}/compare/{before['id']}").json()
    assert comparison["critical_regressions"] == 1
    assert comparison["regressions"] == [{"case_id": "account-access", "model": "candidate", "critical": True}]
    revised = copy.deepcopy(suite["value"])
    revised["description"] = "A new contract revision"
    assert pilot.client.post(f"/api/pilot/custom-evals/suites/{suite['id']}",
        json={"value": revised, "revision": 1}).json()["revision"] == 2
    old = pilot.client.get(f"/api/pilot/custom-evals/suites/{suite['id']}/export?revision=1").json()
    assert old["fingerprint"] == suite["fingerprint"]
    second_revision = pilot.client.post("/api/pilot/custom-evals/runs",
                                        json=answers(suite["id"], revision=2)).json()
    assert pilot.client.get(
        f"/api/pilot/custom-evals/runs/{second_revision['id']}/compare/{before['id']}").status_code == 422
    listed = pilot.client.get("/api/pilot/custom-evals/runs").json()["items"]
    assert len(listed) == 3 and all("source" not in row and "cases" not in row for row in listed)
    from workbench.pilot.api import create_pilot_app
    fresh = create_pilot_app(pilot.settings)
    from workbench.pilot.custom_routes import stored_run
    assert stored_run(fresh.state.database, pilot.team, before["id"])["input_fingerprint"] == before["input_fingerprint"]
    fresh.state.database.engine.dispose()


def test_custom_run_rejects_unknown_cases_duplicates_wrong_team_and_unsafe_fields(pilot):
    suite = pilot.client.post("/api/pilot/custom-evals/suites", json={"value": example()}).json()
    value = answers(suite["id"])
    value["responses"][0]["case_id"] = "unknown-case"
    assert pilot.client.post("/api/pilot/custom-evals/runs", json=value).status_code == 422
    value = answers(suite["id"])
    value["responses"].append(value["responses"][0])
    assert pilot.client.post("/api/pilot/custom-evals/runs", json=value).status_code == 422
    value = answers(suite["id"], cost_basis="unknown")
    assert pilot.client.post("/api/pilot/custom-evals/runs", json=value).status_code == 422
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other, name="Another team"))
    from workbench.pilot.workflows import save
    foreign = save(pilot.db, other, "eval_suite", Suite.model_validate(example()).model_dump(), "operator")
    assert pilot.client.post("/api/pilot/custom-evals/runs", json=answers(foreign["id"])).status_code == 404
    assert pilot.client.get(f"/api/pilot/custom-evals/suites/{foreign['id']}/template").status_code == 404
    assert pilot.client.post("/api/pilot/custom-evals/suites", json={"value": example()},
        headers={"X-Workbench-CSRF": ""}).status_code == 403
    value = example()
    value["private_sentinel"] = "must-not-be-echoed"
    response = pilot.client.post("/api/pilot/custom-evals/suites", json={"value": value})
    assert response.status_code == 422 and "must-not-be-echoed" not in response.text
    with pilot.db.engine.connect() as db:
        assert not db.execute(select(workflow_results)).all()
