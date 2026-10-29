"""Migration, retention, role boundaries and original JSON integrity."""
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from test_pilot import pilot, sample, settings
from test_spend import allocation, budget
from test_custom_evals import answers
from workbench.custom_evals import example
from workbench.pilot import auth
from workbench.pilot.database import (
    events, facts, schema, workflows, workflow_revisions, workflow_results, SCHEMA_VERSION,
)
from workbench.pilot.maintenance import run_once


def test_schema_five_migration_creates_workflows_without_repricing(pilot):
    source = pilot.db.create_source(pilot.team, "Existing source", "admin")
    pilot.db.ingest(pilot.team, source, [sample(), sample(event_id="unknown", model="unknown")])
    with pilot.db.engine.begin() as db:
        original_events = list(db.execute(select(events)).all())
        original_facts = list(db.execute(select(facts)).all())
        workflow_results.drop(db)
        workflow_revisions.drop(db)
        workflows.drop(db)
        db.execute(update(schema).values(version=5))
    pilot.db.migrate()
    pilot.db.migrate()
    with pilot.db.engine.connect() as db:
        assert list(db.execute(select(events)).all()) == original_events
        assert list(db.execute(select(facts)).all()) == original_facts
        assert db.execute(select(schema.c.version)).scalar_one() == SCHEMA_VERSION == 6
    assert pilot.client.post("/api/pilot/spend/budgets", json={"value": budget()}).status_code == 200


def test_retention_preserves_active_definitions_and_retained_run_dependencies(pilot):
    suite = pilot.client.post("/api/pilot/custom-evals/suites", json={"value": example()}).json()
    run = pilot.client.post("/api/pilot/custom-evals/runs", json=answers(suite["id"])).json()
    revised = suite["value"] | {"description": "Current definition"}
    pilot.client.post("/api/pilot/custom-evals/suites/" + suite["id"], json={"value": revised, "revision": 1})
    pool = pilot.client.post("/api/pilot/spend/allocations", json={"value": allocation()}).json()
    now, past = int(time.time()), int(time.time()) - 60 * 86400
    with pilot.db.engine.begin() as db:
        db.execute(update(workflow_revisions).values(created_at=past))
        db.execute(update(workflows).values(created_at=past, updated_at=past))
    config = replace(pilot.settings, evidence_retention_days=30)
    preview = run_once(pilot.db, config, dry_run=True, now=now)
    assert preview["eligible_custom_runs"] == preview["eligible_workflow_revisions"] == 0
    assert run_once(pilot.db, config, now=now)["deleted_workflows"] == 0
    assert pilot.client.get(f"/api/pilot/custom-evals/suites/{suite['id']}/export?revision=1").status_code == 200
    with pilot.db.engine.begin() as db:
        db.execute(update(workflow_results).values(created_at=past))
    assert run_once(pilot.db, config, dry_run=True, now=now)["eligible_custom_runs"] == 1
    assert pilot.client.get("/api/pilot/custom-evals/runs/" + run["id"]).status_code == 200
    assert run_once(pilot.db, config, now=now)["deleted_custom_runs"] == 1
    assert run_once(pilot.db, config, now=now)["deleted_workflow_revisions"] == 1
    assert pilot.client.get(f"/api/pilot/custom-evals/suites/{suite['id']}/export?revision=1").status_code == 404
    assert pilot.client.get(f"/api/pilot/custom-evals/suites/{suite['id']}/export").json()["revision"] == 2
    assert pilot.client.get(f"/api/pilot/spend/allocation/{pool['id']}/export").status_code == 200
    pilot.client.post("/api/pilot/custom-evals/suites/" + suite["id"],
                     json={"value": revised | {"active": False}, "revision": 2})
    with pilot.db.engine.begin() as db:
        db.execute(update(workflows).where(workflows.c.id == suite["id"]).values(updated_at=past))
    assert run_once(pilot.db, config, now=now)["deleted_workflows"] == 1
    assert pilot.client.get(f"/api/pilot/custom-evals/suites/{suite['id']}/export").status_code == 404


@pytest.mark.parametrize("role", ["viewer", "analyst"])
def test_workflow_permissions_are_enforced_on_server(pilot, role):
    actor = {"team_id": pilot.team, "username": "admin"}
    auth.create_user(pilot.db, actor, "reader", pilot.password, role)
    source = pilot.db.create_source(pilot.team, "Source", "admin")
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as client:
        session = client.post("/api/auth/login", json={"username": "reader", "password": pilot.password}).json()
        client.headers["X-Workbench-CSRF"] = session["csrf"]
        assert client.get("/api/pilot/spend/budgets").status_code == 200
        assert client.get(f"/api/pilot/sources/{source}/setup").status_code == 200
        assert client.post("/api/pilot/spend/budgets", json={"value": budget()}).status_code == 403
        assert client.post("/api/pilot/spend/allocations/preview", json={"value": allocation()}).status_code == 403
        response = client.post("/api/pilot/custom-evals/suites", json={"value": example()})
        assert response.status_code == (200 if role == "analyst" else 403)
        if role == "analyst":
            assert client.post("/api/pilot/custom-evals/runs", json=answers(response.json()["id"])).status_code == 200


def test_original_json_rejected_before_preview_or_save(pilot):
    path = "/api/pilot/custom-evals/suites/preview"
    valid = example()
    assert pilot.client.post(path, json=valid).json() == valid
    invalid = json.dumps(valid).replace('"reference":', '"reference":"ambiguous","reference":')
    assert pilot.client.post(path, content=invalid, headers={"content-type": "application/json"}).status_code == 422
    valid["unexpected"] = "private submitted text"
    response = pilot.client.post(path, json=valid)
    assert response.status_code == 422 and "private submitted text" not in response.text
    for raw in ['{"value":NaN}', '{"value":1e9999}', '{"value":0,"value":1}']:
        response = pilot.client.post("/api/pilot/spend/budgets", content=raw,
                                     headers={"content-type": "application/json"})
        assert response.status_code == 422
    assert pilot.client.post(path, content=" " * 2_000_001, headers={"content-type": "application/json"}).status_code == 413
