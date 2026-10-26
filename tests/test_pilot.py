"""Behavioral contracts for the authenticated pilot, including PostgreSQL races."""
import asyncio
import copy
import json
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import make_url

from workbench.connector import (Connector, DeliveryError, Outbox, capture_completion,
                                  recover_inflight, response_event)
from workbench.domain import ROOT, digest
from workbench.pilot import auth
from workbench.pilot.api import create_pilot_app
from workbench.pilot.config import Settings
from workbench.pilot.database import (Conflict, Database, jobs, sessions, teams, tokens,
                                      uid, users)
from workbench.pilot.events import Usage, UsageEvent, account, pricebook, recording_events
from workbench.pilot.worker import EvaluationWorker
from test_workbench import fixture_recording


def sample(**changes):
    data = dict(event_id="event-1", task_id="task-1", project="support", stage="draft",
                provider="openai", model="gpt-4.1-2025-04-14",
                occurred_at="2026-10-23T00:00:00Z", status="success", latency_ms=100.0,
                usage_basis="provider_reported", attempt_coverage="single_attempt",
                usage=Usage(prompt_tokens=1000, completion_tokens=100, cached_tokens=200),
                provider_response_id="provider-placeholder")
    return UsageEvent(**(data | changes))


@pytest.fixture(params=["sqlite", "postgres"])
def settings(request, tmp_path):
    if request.param == "sqlite":
        yield Settings(f"sqlite:///{tmp_path / 'pilot.db'}", testing=True)
        return
    url = os.environ.get("WORKBENCH_TEST_DATABASE_URL")
    path = os.environ.get("WORKBENCH_TEST_DATABASE_URL_FILE")
    if path:
        url = Path(path).read_text().strip()
    if not url:
        pytest.skip("Set WORKBENCH_TEST_DATABASE_URL_FILE to run PostgreSQL integration checks")
    schema = "pilot_test_" + uid().replace("-", "")
    engine = create_engine(url, hide_parameters=True)
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    try:
        yield Settings(scoped, testing=True)
    finally:
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture
def pilot(settings):
    app = create_pilot_app(settings)
    database = app.state.database
    password = secrets.token_urlsafe(24)
    team = database.initialize("Test team", "admin", auth.password_hash(password))
    with TestClient(app, base_url=settings.public_origin) as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": password})
        assert response.status_code == 200
        client.headers["X-Workbench-CSRF"] = response.json()["csrf"]
        yield SimpleNamespace(app=app, client=client, db=database, team=team,
                              settings=settings, password=password)


def test_decimal_prices_unknown_is_not_zero_and_unsupported_usage():
    event = sample()
    charge = account(event, pricebook())
    assert charge["api_estimate_usd"] == "0.002500000"
    assert charge["invoice_usd"] is None and charge["hardware_electricity_usd"] is None
    zero = event.model_copy(update={"usage": Usage(prompt_tokens=0, completion_tokens=0)})
    assert account(zero, pricebook())["api_estimate_usd"] == "0.000000000"
    for changes in ({"model": "unpriced"}, {"provider": "bedrock"}, {"usage_basis": "estimated"},
                    {"usage": None}, {"usage": Usage(prompt_tokens=5, completion_tokens=5, cache_creation_tokens=2)}):
        assert account(event.model_copy(update=changes), pricebook())["api_estimate_usd"] is None
    assert not account(sample(attempt_coverage="final_response_only"), pricebook())["attempt_cost_complete"]
    with pytest.raises(ValidationError):
        Usage(prompt_tokens=1, completion_tokens=1, cached_tokens=2)
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(sample().model_dump() | {"cost": 0})
    with pytest.raises(ValidationError):
        sample(occurred_at="2026-10-23T00:00:00")


def test_secure_configuration_rejects_remote_http_and_sqlite_production():
    with pytest.raises(ValueError, match="HTTPS"):
        Settings("postgresql+psycopg://localhost/pilot", public_origin="http://example.com")
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings("sqlite:////tmp/pilot.db")
    assert Settings("postgresql+psycopg://localhost/pilot", public_origin="https://pilot.example").secure_cookie


def test_authentication_csrf_limits_and_demo_bypass(pilot):
    client = pilot.client
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as anonymous:
        assert anonymous.get("/api/pilot/usage").status_code == 401
        assert anonymous.post("/api/connect", json={}).status_code == 404
        assert anonymous.get("/api/state").status_code == 404
        assert anonymous.get("/api/pilot/evaluations").status_code == 401
        assert anonymous.get("/openapi.json").status_code == 404
    assert client.post("/api/pilot/sources", json={"name": "x"},
                       headers={"X-Workbench-CSRF": ""}).status_code == 403
    assert client.post("/api/pilot/sources", json={"name": "x"},
                       headers={b"X-Workbench-CSRF": b"\xff"}).status_code == 403
    assert client.get("/api/pilot/usage", headers={"Origin": "https://other.example"}).status_code == 403
    assert client.get("/api/pilot/usage", headers={"Host": "other.example"}).status_code == 403
    assert client.post("/api/pilot/sources", content="x", headers={"Content-Type": "text/plain"}).status_code == 415
    response = client.post("/api/auth/login", json={"username": "admin", "password": "x" * 129})
    assert response.status_code == 422 and "xxxx" not in response.text
    assert client.post("/api/auth/login", content=b"x"*16001, headers={"Content-Type": "application/json"}).status_code == 413
    assert "no-store" in client.get("/").headers["cache-control"]
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    assert client.post("/api/auth/logout", json={}).status_code == 200
    assert client.get("/api/pilot/usage").status_code == 401


def test_roles_disable_and_last_admin_protection(pilot):
    client = pilot.client
    for role in ("viewer", "analyst"):
        password = secrets.token_urlsafe(24)
        created = client.post("/api/pilot/users", json={"username": role, "password": password, "role": role})
        assert created.status_code == 200
        with TestClient(pilot.app, base_url=pilot.settings.public_origin) as member:
            signed = member.post("/api/auth/login", json={"username": role, "password": password}).json()
            member.headers["X-Workbench-CSRF"] = signed["csrf"]
            assert member.get("/api/pilot/usage").status_code == 200
            assert member.get("/api/pilot/users").status_code == 403
            assert member.post("/api/pilot/sources", json={"name": "not-allowed"}).status_code == 403
            imported = member.post("/api/pilot/recordings/example", json={})
            assert imported.status_code == (200 if role == "analyst" else 403)
            if role == "viewer":
                assert member.post("/api/pilot/evaluations", json={"recording_id": "a"*64}).status_code == 403
            assert client.post(f"/api/pilot/users/{created.json()['id']}/disable", json={}).status_code == 200
            assert member.get("/api/pilot/usage").status_code == 401
    admin_id = client.get("/api/auth/session").json()["user"]["id"]
    assert client.post(f"/api/pilot/users/{admin_id}/disable", json={}).status_code == 409


def test_session_idle_expiry_and_login_throttle(pilot):
    with pilot.db.engine.begin() as db:
        db.execute(update(sessions).values(last_seen=int(time.time()) - pilot.settings.idle_seconds - 1))
    assert pilot.client.get("/api/pilot/usage").status_code == 401
    for _ in range(10):
        assert pilot.client.post("/api/auth/login", json={"username": "absent-user", "password": "wrong"}).status_code == 401
    response = pilot.client.post("/api/auth/login", json={"username": "absent-user", "password": "wrong"})
    assert response.status_code == 429 and response.headers["retry-after"] == "900"


def test_https_session_flags_password_reset_and_token_expiry(pilot):
    secure = create_pilot_app(replace(pilot.settings, public_origin="https://pilot.example"))
    with TestClient(secure, base_url="https://pilot.example") as client:
        response = client.post("/api/auth/login", json={"username":"admin", "password":pilot.password})
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert client.get("/api/pilot/usage").status_code == 200
        auth.reset_password(pilot.db, "admin", secrets.token_urlsafe(24))
        assert client.get("/api/pilot/usage").status_code == 401
    source = pilot.db.create_source(pilot.team, "expired-source", "admin")
    token = pilot.db.issue_token(pilot.team, source, "admin")["token"]
    with pilot.db.engine.begin() as db:
        db.execute(update(tokens).where(tokens.c.source_id == source).values(expires_at=int(time.time())-1))
    assert pilot.client.post("/api/pilot/ingest", json={"events":[sample().model_dump()]},
                             headers={"Authorization":f"Bearer {token}"}).status_code == 401


def test_ingestion_dedup_atomic_conflict_scope_and_revocation(pilot):
    client = pilot.client
    source = client.post("/api/pilot/sources", json={"name": "application"}).json()["id"]
    issued = client.post(f"/api/pilot/sources/{source}/token", json={}).json()
    headers = {"Authorization": f"Bearer {issued['token']}"}
    batch = {"events": [sample().model_dump(), sample(event_id="event-2").model_dump()]}
    # Provider response ID is deliberately identical: two real application calls.
    first = client.post("/api/pilot/ingest", headers=headers, json=batch)
    assert first.json() == {"added_events": 2, "duplicate_events": 0}
    assert client.post("/api/pilot/ingest", headers=headers, json=batch).json()["duplicate_events"] == 2
    changed = {"events": [sample(event_id="new-event").model_dump(), sample(stage="tampered").model_dump()]}
    assert client.post("/api/pilot/ingest", headers=headers, json=changed).status_code == 409
    summary = client.get("/api/pilot/usage").json()
    assert summary["events"] == 2 and summary["api_estimate_usd"] == "0.005000000"
    assert client.post("/api/pilot/ingest", headers=headers, json=batch | {"team_id":"another"}).status_code == 422
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as connector:
        assert connector.get("/api/pilot/usage", headers=headers).status_code == 401
    replacement = client.post(f"/api/pilot/sources/{source}/token", json={}).json()["token"]
    with pilot.db.engine.connect() as db:
        old_id = db.execute(select(tokens.c.id).where(tokens.c.prefix == issued["prefix"])).scalar_one()
    assert client.post(f"/api/pilot/sources/{source}/tokens/{old_id}/revoke", json={}).status_code == 200
    assert client.post("/api/pilot/ingest", headers=headers, json=batch).status_code == 401
    assert client.post("/api/pilot/ingest", headers={"Authorization": f"Bearer {replacement}"},
                       json=batch).json()["duplicate_events"] == 2
    assert client.post(f"/api/pilot/sources/{source}/revoke", json={}).status_code == 200
    assert client.post("/api/pilot/ingest", headers=headers, json=batch).status_code == 401
    assert pilot.db.token_source(issued["token"]) is None
    with pilot.db.engine.connect() as db:
        stored = db.execute(select(tokens)).mappings().first()
        assert stored["id"] != issued["token"]


def test_team_boundaries_and_unknown_cost_visibility(pilot):
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other, name="Other isolated team"))
    source = pilot.db.create_source(other, "private", "operator")
    secret = pilot.db.issue_token(other, source, "operator")["token"]
    pilot.db.ingest(other, source, [sample(usage=None, usage_basis="unknown")])
    assert pilot.client.get("/api/pilot/usage").json()["events"] == 0
    assert pilot.client.get(f"/api/pilot/usage?source_id={source}").json()["events"] == 0
    assert pilot.client.post(f"/api/pilot/sources/{source}/token", json={}).status_code == 404
    own = pilot.db.create_source(pilot.team, "own", "admin")
    pilot.db.ingest(pilot.team, own, [sample(usage=None, usage_basis="unknown")])
    summary = pilot.client.get("/api/pilot/usage").json()
    assert summary["unknown_cost_calls"] == 1
    assert summary["tasks"][0]["calls"][0]["api_estimate_usd"] is None
    imported = pilot.db.import_recording(other, fixture_recording(), "operator")
    job = pilot.db.enqueue(other, imported["recording_id"], "operator")
    assert pilot.client.get(f"/api/pilot/recordings/{imported['recording_id']}").status_code == 404
    assert pilot.client.get(f"/api/pilot/evaluations/{job['id']}").status_code == 404
    assert pilot.client.post(f"/api/pilot/evaluations/{job['id']}/cancel", json={}).status_code == 404


def test_recording_costs_and_restart_durability(pilot):
    recording = json.loads((ROOT / "data/model-comparison.json").read_text())
    events = recording_events(recording)
    assert len(events) == 144 and {e.evidence for e in events} == {"recorded"}
    response = pilot.client.post("/api/pilot/recordings", json=recording)
    assert response.status_code == 200
    identity = response.json()["recording_id"]
    assert pilot.client.post("/api/pilot/recordings", json=recording).json()["deduplicated"]
    summary = pilot.client.get("/api/pilot/usage").json()
    assert summary["events"] == 144 and summary["task_count"] == 72
    assert summary["api_estimate_usd"] == "0.088074750"
    assert all(task["context"]["kind"] == "support_comparison" for task in summary["tasks"])
    refund = next(task for task in summary["tasks"] if task["context"]["case_id"] == "S01")
    assert refund["context"]["title"] == "Refund inside the window"
    assert refund["context"]["request"] == "Please refund my unused subscription."
    queued = pilot.client.post("/api/pilot/evaluations", json={"recording_id": identity}).json()
    assert EvaluationWorker(pilot.db, pilot.settings).run_once()
    completed = pilot.client.get(f"/api/pilot/evaluations/{queued['id']}").json()
    assert completed["status"] == "complete"
    assert [m["passed"] for m in completed["analysis"]["models"]] == [20, 18, 14]
    proposal = pilot.client.post(f"/api/pilot/evaluations/{queued['id']}/recommend", json={}).json()
    assert proposal["status"] == "no_eligible_model" and proposal["deployment"] == "Not applied"
    fresh = create_pilot_app(pilot.settings)
    with TestClient(fresh, base_url=pilot.settings.public_origin) as restarted:
        restarted.cookies.update(pilot.client.cookies)
        assert restarted.get("/api/pilot/usage").json()["events"] == 144
        assert restarted.get(f"/api/pilot/evaluations/{queued['id']}").json()["analysis"] == completed["analysis"]
        assert restarted.get("/api/pilot/proposals").json()["proposals"][0]["id"] == proposal["id"]
        assert restarted.get("/api/pilot/evaluations").json()["worker_healthy"]


def test_application_case_ids_do_not_acquire_recorded_customer_descriptions(pilot):
    recording = json.loads((ROOT / "data/model-comparison.json").read_text())
    imported = pilot.db.import_recording(pilot.team, recording, "admin")
    source = pilot.db.create_source(pilot.team, "unrelated-application", "admin")
    pilot.db.ingest(pilot.team, source, [
        sample(case_id="S01"),
        sample(event_id="spoofed-recording", task_id="another-task", case_id="S01",
               evidence="recorded", recording_id=imported["recording_id"]),
    ])
    summary = pilot.client.get(f"/api/pilot/usage?source_id={source}").json()
    assert summary["task_count"] == 2
    assert all(task["context"] is None for task in summary["tasks"])


def test_fixture_cannot_support_measured_recommendation(pilot):
    imported = pilot.db.import_recording(pilot.team, fixture_recording(), "admin")
    assert pilot.db.usage(pilot.team)["events"] == 0
    assert pilot.db.usage(pilot.team, include_fixtures=True)["events"] == 144
    queued = pilot.db.enqueue(pilot.team, imported["recording_id"], "admin")
    EvaluationWorker(pilot.db, pilot.settings).run_once()
    response = pilot.client.post(f"/api/pilot/evaluations/{queued['id']}/recommend", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "fixture_only"
    assert response.json()["recommended_model"] is None
    assert response.json()["projected_monthly_api_savings_usd"] is None
    assert all(not c["eligible"] for c in response.json()["candidates"])


def test_worker_lease_recovery_fencing_cancellation_and_attempt_limit(pilot):
    recording = pilot.db.import_recording(pilot.team, fixture_recording(), "admin")
    job = pilot.db.enqueue(pilot.team, recording["recording_id"], "admin")
    assert pilot.db.enqueue(pilot.team, recording["recording_id"], "admin")["id"] == job["id"]
    pilot.db.claim("old-worker", 30, 3)
    with pilot.db.engine.begin() as db:
        db.execute(update(jobs).where(jobs.c.id == job["id"]).values(lease_until=int(time.time())-1))
    reclaimed = pilot.db.claim("new-worker", 30, 3)
    assert reclaimed["id"] == job["id"]
    assert not pilot.db.finish(job["id"], "old-worker", result={"stale": True})
    pilot.db.cancel(pilot.team, job["id"], "admin")
    assert not pilot.db.finish(job["id"], "new-worker", result={"stale": True})
    assert pilot.db.job(pilot.team, job["id"])["status"] == "cancelled"
    retry = pilot.db.enqueue(pilot.team, recording["recording_id"], "admin")
    pilot.db.claim("lost", 30, 1)
    with pilot.db.engine.begin() as db:
        db.execute(update(jobs).where(jobs.c.id == retry["id"]).values(lease_until=int(time.time())-1))
    assert pilot.db.claim("recovery", 30, 1) is None
    assert pilot.db.job(pilot.team, retry["id"])["status"] == "failed"


def test_worker_timeout_without_browser_polling_and_secret_isolation(pilot, monkeypatch):
    imported = pilot.db.import_recording(pilot.team, fixture_recording(), "admin")
    job = pilot.db.enqueue(pilot.team, imported["recording_id"], "admin")
    real_popen, children = subprocess.Popen, []
    monkeypatch.setenv("WORKBENCH_DATABASE_URL", "must-not-reach-evaluator")
    monkeypatch.setenv("PROVIDER_AUTH", "must-not-reach-evaluator")

    def sleeper(*args, **kwargs):
        assert "WORKBENCH_DATABASE_URL" not in kwargs["env"]
        assert "PROVIDER_AUTH" not in kwargs["env"]
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr("workbench.pilot.worker.subprocess.Popen", sleeper)
    worker = EvaluationWorker(pilot.db, replace(pilot.settings, job_timeout=1))
    assert worker.run_once()
    assert pilot.db.job(pilot.team, job["id"])["status"] == "failed"
    assert "timeout" in pilot.db.job(pilot.team, job["id"])["error"]
    assert all(process.poll() is not None for process in children)


def test_concurrent_ingestion_and_claiming_postgres(pilot):
    if pilot.db.engine.dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency contract is PostgreSQL-specific")
    source = pilot.db.create_source(pilot.team, "parallel", "admin")
    with ThreadPoolExecutor(max_workers=6) as pool:
        result = list(pool.map(lambda _: pilot.db.ingest(pilot.team, source, [sample()]), range(12)))
    assert sum(r["added_events"] for r in result) == 1
    imported = pilot.db.import_recording(pilot.team, fixture_recording(), "admin")
    with ThreadPoolExecutor(max_workers=6) as pool:
        queued = list(pool.map(lambda _: pilot.db.enqueue(pilot.team, imported["recording_id"], "admin"), range(12)))
    assert len({j["id"] for j in queued}) == 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda i: pilot.db.claim(f"worker-{i}"), range(6)))
    assert sum(c is not None for c in claims) == 1
    pilot.db.cancel(pilot.team, queued[0]["id"], "admin")
    second = fixture_recording()
    second["created_at"] = "2026-10-22T00:00:00Z"
    other = pilot.db.import_recording(pilot.team, second, "admin")
    def enqueue_once(recording_id):
        try:
            return pilot.db.enqueue(pilot.team, recording_id, "admin", max_queued=1)
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        bounded = list(pool.map(enqueue_once, [imported["recording_id"], other["recording_id"]]))
    assert sum(row is not None for row in bounded) == 1


def test_outbox_offline_retry_after_server_ack_loss_and_reopen(pilot, tmp_path):
    source = pilot.db.create_source(pilot.team, "outbox", "admin")
    token = pilot.db.issue_token(pilot.team, source, "admin")["token"]
    outbox = Outbox(tmp_path / "usage.outbox.db")
    outbox.put(sample())
    destination = pilot.settings.public_origin + "/api/pilot/ingest"

    def lost_ack(request):
        if request.method == "GET":
            response = pilot.client.get("/api/pilot/ingest", headers={"Authorization": request.headers["authorization"]})
            return httpx.Response(response.status_code, json=response.json())
        payload = json.loads(request.content)
        response = pilot.client.post("/api/pilot/ingest", json=payload,
                                     headers={"Authorization": request.headers["authorization"]})
        assert response.status_code == 200
        raise httpx.ReadTimeout("simulated lost acknowledgment")

    with httpx.Client(transport=httpx.MockTransport(lost_ack)) as client:
        with pytest.raises(DeliveryError):
            Connector(destination, token, outbox, client=client).flush()
    assert outbox.pending() == 1 and pilot.db.usage(pilot.team)["events"] == 1
    reopened = Outbox(outbox.path)
    reopened.recover_interrupted()
    connector = Connector(destination, token, reopened, client=pilot.client)
    assert connector.flush() == {"acknowledged": 1, "pending": 0}
    assert pilot.db.usage(pilot.team)["events"] == 1
    another = pilot.db.create_source(pilot.team, "different-source", "admin")
    other_token = pilot.db.issue_token(pilot.team, another, "admin")["token"]
    with pytest.raises(DeliveryError, match="different source"):
        Connector(destination, other_token, reopened, client=pilot.client).flush()
    with pytest.raises(ValueError, match="different data"):
        reopened.put(sample(stage="changed"))
    assert reopened.path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        Connector("http://public.example/api/pilot/ingest", token, reopened)


def test_actual_axon_response_adapter_and_interrupted_capture(tmp_path):
    from axonllm import ChatCompletionResponse, TokenUsage
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=100, total_tokens=1100, cached_tokens=200)
    response = ChatCompletionResponse(id="placeholder", choices=[{"message":{"content":"private response"}}],
        usage=usage, model="logical-model", provider="openai", provider_model="gpt-4.1-2025-04-14")
    adapted = response_event(response, event_id="app-event", task_id="task", project="support",
                             stage="draft", latency_ms=100)
    assert adapted.model == "gpt-4.1-2025-04-14"
    assert account(adapted, pricebook())["api_estimate_usd"] is None
    assert "private response" not in adapted.model_dump_json()
    outbox = Outbox(tmp_path / "capture.outbox.db")

    async def complete(**request):
        assert request["messages"][0]["content"] == "private prompt"
        return response

    router = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    captured = asyncio.run(capture_completion(router, outbox, task_id="task", project="support",
        stage="draft", model="logical-model", messages=[{"role":"user","content":"private prompt"}],
        usage_basis="provider_reported", attempt_coverage="single_attempt"))
    assert captured is response and outbox.pending() == 1
    assert "private" not in outbox.batch()[0]["payload"]

    async def fails(**request):
        raise RuntimeError("provider secret must not be recorded")

    router.chat.completions.create = fails
    with pytest.raises(RuntimeError):
        asyncio.run(capture_completion(router, outbox, task_id="failed", project="support",
            stage="draft", model="logical-model"))
    assert outbox.pending() == 2
    rows = [json.loads(r["payload"]) for r in outbox.batch()]
    assert rows[-1]["status"] == "error" and rows[-1]["usage"] is None
    assert "provider secret" not in json.dumps(rows)
    reservation = Path(str(outbox.path) + ".inflight") / "orphan.json"
    reservation.write_text(sample(event_id="orphan", usage=None, usage_basis="unknown",
                                  status="interrupted").model_dump_json())
    assert recover_inflight(outbox) == 1
    assert outbox.pending() == 3
