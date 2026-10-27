"""Bedrock SDK contract, accounting, crash recovery and authenticated delivery.

All model responses are synthetic. Stubber prevents any AWS network operation.
"""
import copy
import json
import secrets
import time
from types import SimpleNamespace

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import insert, select, update

from workbench.bedrock import capture_converse, capture_converse_stream
from workbench.connector import Connector, DeliveryError, Outbox, recover_inflight, reserve_call
from workbench.domain import digest
from workbench.pilot import auth
from workbench.pilot.database import collectors, events, facts, schema, teams, uid
from workbench.pilot.events import (BedrockContext, BedrockUsage, BedrockUsageEvent,
                                    EventBatch, account, event_adapter, pricebook)
from workbench.pilot.operations import Metrics
from test_pilot import pilot, sample, settings


REQUEST = {"modelId": "amazon.nova-micro-v1:0",
    "messages": [{"role": "user", "content": [{"text": "private prompt must stay local"}]}],
    "inferenceConfig": {"maxTokens": 64}}
RESPONSE = {"output": {"message": {"role": "assistant",
    "content": [{"text": "private response must stay local"}]}}, "stopReason": "end_turn",
    "usage": {"inputTokens": 1000, "outputTokens": 100, "totalTokens": 1100},
    "metrics": {"latencyMs": 20}, "ResponseMetadata": {"RequestId": "request-1",
        "RetryAttempts": 0, "HTTPStatusCode": 200, "HTTPHeaders": {"private": "must stay local"}}}


def sdk():
    # Explicit dummy credentials disable every credential lookup; Stubber owns all API responses.
    return boto3.client("bedrock-runtime", region_name="us-east-1",
        aws_access_key_id="test", aws_secret_access_key="test",
        config=Config(retries={"total_max_attempts": 1, "mode": "adaptive"}))


def event(**changes):
    data = dict(schema_version="bedrock.usage.v1", event_id="bedrock-1", task_id="task-1",
        project="test", stage="draft", model="amazon.nova-micro-v1:0",
        occurred_at="2026-10-27T00:00:00Z", status="success", latency_ms=25.0,
        usage_basis="provider_reported", attempt_coverage="single_attempt",
        usage=BedrockUsage(input_tokens=1000, output_tokens=100, total_tokens=1100),
        bedrock=BedrockContext(region="us-east-1", operation="Converse", service_tier="default",
            performance="standard", additional_charges=False, sdk_retry_count=0))
    return BedrockUsageEvent(**(data | changes))


def saved(outbox):
    return [event_adapter.validate_python(json.loads(row["payload"])) for row in outbox.batch()]


def test_real_sdk_shape_metadata_privacy_retry_semantics_and_cache(tmp_path):
    client, outbox = sdk(), Outbox(tmp_path / "sdk.db")
    with Stubber(client) as stub:
        for retries in (0, 2):
            response = copy.deepcopy(RESPONSE)
            response["ResponseMetadata"]["RetryAttempts"] = retries
            stub.add_response("converse", response, REQUEST)
        first = capture_converse(client, outbox, task_id="task", project="app", stage="classify", **REQUEST)
        second = capture_converse(client, outbox, task_id="task", project="app", stage="draft", **REQUEST)
        stub.assert_no_pending_responses()
    assert first["output"] == second["output"] == RESPONSE["output"]
    rows = saved(outbox)
    assert len({row.event_id for row in rows}) == 2  # provider request ID can repeat
    assert rows[0].attempt_coverage == "single_attempt"
    assert rows[1].attempt_coverage == "final_response_only"
    assert rows[1].bedrock.sdk_retry_count == 2
    assert rows[0].bedrock.provider_latency_ms == 20
    assert rows[0].latency_ms >= 0
    assert rows[0].provider_response_id == "request-1"
    assert all("private" not in row["payload"] for row in outbox.batch())
    assert outbox.health().inflight_calls == 0
    cached = copy.deepcopy(RESPONSE)
    cached["usage"].update(cacheReadInputTokens=5000, cacheWriteInputTokens=1000)
    with Stubber(client) as stub:
        stub.add_response("converse", cached, REQUEST)
        capture_converse(client, outbox, task_id="cached", project="app", stage="read", **REQUEST)
    row = saved(outbox)[-1]
    assert row.usage.cache_read_input_tokens == 5000  # never subtracted from inputTokens
    assert account(row, pricebook())["api_estimate_usd"] is None


def test_decimal_region_mode_time_and_unknown_costs():
    good = event()
    charge = account(good, pricebook())
    assert charge["api_estimate_usd"] == "0.000049000"
    assert charge["cost_basis"] == "estimated" and charge["attempt_cost_complete"]
    assert charge["invoice_usd"] is None and charge["hardware_electricity_usd"] is None
    assert account(event(usage=BedrockUsage(input_tokens=0, output_tokens=0, total_tokens=0)),
                   pricebook())["api_estimate_usd"] == "0.000000000"
    for context in ({"region": "us-west-2"}, {"service_tier": "flex"}, {"performance": "optimized"},
                    {"additional_charges": True}, {"capture_issue": "invalid_metadata"}):
        assert account(event(bedrock=good.bedrock.model_copy(update=context)), pricebook())["api_estimate_usd"] is None
    for changes in ({"model": "us.amazon.nova-micro-v1:0"}, {"model": "unpriced"},
                    {"occurred_at": "2026-09-01T00:00:00Z"},
                    {"usage": None, "usage_basis": "unknown"},
                    {"usage": BedrockUsage(input_tokens=1, output_tokens=2, total_tokens=100)}):
        assert account(event(**changes), pricebook())["api_estimate_usd"] is None
    expired = pricebook()
    expired["snapshot"]["bedrock"]["rates"][0]["review_expires_at"] = "2026-10-26T00:00:00+00:00"
    assert account(good, expired)["api_estimate_usd"] is None
    partial = event(attempt_coverage="final_response_only",
                    bedrock=good.bedrock.model_copy(update={"sdk_retry_count": 2}))
    assert account(partial, pricebook())["api_estimate_usd"] == "0.000049000"
    assert not account(partial, pricebook())["attempt_cost_complete"]
    with pytest.raises(ValidationError):
        event(attempt_coverage="single_attempt", bedrock=good.bedrock.model_copy(update={"sdk_retry_count": 2}))
    with pytest.raises(ValidationError):
        EventBatch.model_validate({"events": [good.model_dump() | {"price": "0"}]})
    # Historic Axon payload/fingerprint must not acquire newly defaulted fields.
    old = sample().model_dump()
    assert digest(EventBatch.model_validate({"events": [old]}).events[0].model_dump()) == digest(old)


def test_failure_crash_recovery_and_persistence_before_paid_call(tmp_path, monkeypatch):
    client, outbox = sdk(), Outbox(tmp_path / "failure.db")
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code="ThrottlingException",
                              service_message="private diagnostic", expected_params=REQUEST)
        with pytest.raises(ClientError):
            capture_converse(client, outbox, task_id="failed", project="app", stage="draft", **REQUEST)
    failed = saved(outbox)[0]
    assert failed.status == "error" and failed.usage is None
    assert "private" not in failed.model_dump_json()
    interrupted = event(event_id="orphan", status="interrupted", usage=None, usage_basis="unknown",
                        attempt_coverage="unknown", latency_ms=None)
    reserve_call(outbox, interrupted)
    assert outbox.health().inflight_calls == 1
    assert recover_inflight(outbox) == 1
    assert recover_inflight(outbox) == 0
    assert saved(outbox)[-1].latency_ms is None
    # A crash after enqueue but before unlink must not create an extra charge.
    reserve_call(outbox, failed)
    assert recover_inflight(outbox) == 0
    assert len(saved(outbox)) == 2
    def disk_failure(*args):
        raise OSError("simulated full disk")
    monkeypatch.setattr("workbench.bedrock.reserve_call", disk_failure)
    with Stubber(client):  # any invocation would fail as an unexpected AWS call
        with pytest.raises(OSError):
            capture_converse(client, outbox, task_id="not-called", project="app", stage="draft", **REQUEST)


class Stream:
    def __init__(self, items):
        self.items, self.closed = iter(items), False
    def __iter__(self):
        return self
    def __next__(self):
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        return item
    def close(self):
        self.closed = True


def streaming_client(items):
    stream = Stream(items)
    client = SimpleNamespace(meta=sdk().meta, converse_stream=lambda **kw: {
        "stream": stream, "ResponseMetadata": RESPONSE["ResponseMetadata"]})
    return client, stream


def test_streaming_completion_early_close_missing_metadata_and_errors(tmp_path):
    items = [{"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": "private streamed text"}, "contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": RESPONSE["usage"], "metrics": RESPONSE["metrics"]}}]
    for name, sequence, consume, expected in (
        ("complete", items, True, "success"), ("early", items, False, "interrupted"),
        ("no-metadata", items[:-1], True, "interrupted"),
        ("stream-error", items[:2]+[RuntimeError("private exception")], True, "error"),
        ("error-event", items[:2]+[{"modelStreamErrorException": {"message": "private"}}], True, "error"),
    ):
        outbox = Outbox(tmp_path / f"{name}.db")
        client, raw = streaming_client(sequence)
        try:
            with capture_converse_stream(client, outbox, task_id=name, project="app", stage="draft", **REQUEST) as stream:
                if consume:
                    list(stream)
                else:
                    next(stream)
        except RuntimeError:
            assert name == "stream-error"
        assert raw.closed
        row, = saved(outbox)
        assert row.status == expected
        assert "private" not in row.model_dump_json()
        assert outbox.health().inflight_calls == 0
        if expected != "success":
            assert account(row, pricebook())["api_estimate_usd"] is None


def test_missing_or_changed_sdk_metadata_records_gap_instead_of_dropping_response(tmp_path):
    outbox = Outbox(tmp_path / "changed.db")
    for usage in (None, {"inputTokens": -2}, {"inputTokens": "100", "outputTokens": 1, "totalTokens": 101}):
        response = copy.deepcopy(RESPONSE)
        response["usage"] = usage
        client = SimpleNamespace(meta=sdk().meta, converse=lambda **kw: response)
        assert capture_converse(client, outbox, task_id="changed", project="app", stage="draft", **REQUEST) is response
    assert len(saved(outbox)) == 3
    assert all(row.usage is None and row.bedrock.capture_issue for row in saved(outbox))
    assert outbox.health().inflight_calls == 0
    changed = copy.deepcopy(RESPONSE)
    changed["usage"]["cacheDetails"] = [{"inputTokens": 500, "ttl": "1h"}]
    client = SimpleNamespace(meta=sdk().meta, converse=lambda **kw: changed)
    capture_converse(client, outbox, task_id="cache-details", project="app", stage="draft", **REQUEST)
    assert saved(outbox)[-1].bedrock.capture_issue == "invalid_metadata"
    assert account(saved(outbox)[-1], pricebook())["api_estimate_usd"] is None


def source(pilot, name="Bedrock application"):
    response = pilot.client.post("/api/pilot/sources", json={"name": name, "kind": "bedrock"})
    assert response.status_code == 200
    identity = response.json()["id"]
    token = pilot.client.post(f"/api/pilot/sources/{identity}/token", json={}).json()["token"]
    return identity, token


def test_bedrock_delivery_health_scoping_dedup_retries_and_task_totals(pilot, tmp_path):
    identity, token = source(pilot)
    outbox = Outbox(tmp_path / "delivery.db")
    outbox.put(event())
    outbox.put(event(event_id="bedrock-2", stage="classify"))
    endpoint = pilot.settings.public_origin + "/api/pilot/ingest"
    connector = Connector(endpoint, token, outbox, client=pilot.client, report_health=True)
    assert connector.flush() == {"acknowledged": 2, "pending": 0}
    summary = pilot.client.get("/api/pilot/usage").json()
    assert summary["task_count"] == 1 and summary["events"] == 2
    assert summary["api_estimate_usd"] == "0.000098000"
    assert len(summary["tasks"][0]["calls"]) == 2
    assert summary["tasks"][0]["context"] is None  # usage alone is not quality evidence
    state = pilot.client.get("/api/pilot/sources").json()["sources"][0]["collection"]
    assert state["status"] == "connected" and state["pending_events"] == 0
    # Reopening and token rotation keep source binding and collector identity.
    reopened = Outbox(outbox.path)
    assert reopened.health().collector_id == outbox.health().collector_id
    token2 = pilot.db.issue_token(pilot.team, identity, "admin")["token"]
    assert Connector(endpoint, token2, reopened, client=pilot.client, report_health=True).flush()["acknowledged"] == 0
    assert pilot.db.ingest(pilot.team, identity, [event()])["duplicate_events"] == 1
    # Lost POST acknowledgment: replay identical data, never increment spend twice.
    reopened.put(event(event_id="bedrock-3"))
    def lose_ack(request):
        path = request.url.path
        headers = {"Authorization":request.headers["authorization"]}
        response = (pilot.client.get(path, headers=headers) if request.method == "GET" else
                    pilot.client.post(path, json=json.loads(request.content), headers=headers))
        if path == "/api/pilot/ingest" and request.method == "POST":
            assert response.status_code == 200
            raise httpx.ReadTimeout("simulated lost acknowledgment")
        return httpx.Response(response.status_code, json=response.json())
    with httpx.Client(transport=httpx.MockTransport(lose_ack)) as client:
        with pytest.raises(DeliveryError):
            Connector(endpoint, token2, reopened, client=client, report_health=True).flush()
    assert reopened.health().retrying_events == 1
    assert pilot.db.usage(pilot.team)["events"] == 3
    reopened.recover_interrupted()
    Connector(endpoint, token2, reopened, client=pilot.client, report_health=True).flush()
    assert pilot.db.usage(pilot.team)["api_estimate_usd"] == "0.000147000"
    axon = pilot.db.create_source(pilot.team, "Wrong kind", "admin")
    wrong = pilot.db.issue_token(pilot.team, axon, "admin")["token"]
    assert pilot.client.post("/api/pilot/ingest", json={"events":[event().model_dump()]},
                             headers={"Authorization":f"Bearer {wrong}"}).status_code == 409
    assert pilot.client.post("/api/pilot/ingest", json={"events":[sample().model_dump()]},
                             headers={"Authorization":f"Bearer {token}"}).status_code == 409


def test_health_staleness_revocation_roles_isolation_and_retirement(pilot, tmp_path):
    identity, token = source(pilot)
    outbox = Outbox(tmp_path / "health.db")
    outbox.put(event())
    headers = {"Authorization":f"Bearer {token}"}
    report = outbox.health().model_dump()
    assert pilot.client.post("/api/pilot/ingest/health", json=report).status_code == 401
    assert pilot.client.post("/api/pilot/ingest/health", json=report | {"source_id":"forged"}, headers=headers).status_code == 422
    assert pilot.client.post("/api/pilot/ingest/health", json=report, headers=headers).status_code == 200
    state = pilot.db.list_sources(pilot.team)[0]["collection"]
    assert state["status"] == "backlog"
    with pilot.db.engine.begin() as db:
        db.execute(update(collectors).values(received_at=int(time.time())-181))
    assert pilot.db.list_sources(pilot.team)[0]["collection"]["status"] == "stale"
    operations = pilot.client.get("/api/pilot/operations").json()
    assert operations["collection"]["stale_sources"] == 1
    assert any("collector health" in a["message"] for a in operations["alerts"])
    metrics = Metrics().render(operations).decode()
    assert "workbench_stale_usage_sources 1.0" in metrics
    assert "workbench_backlog_usage_sources 1.0" in metrics
    assert identity not in metrics and report["collector_id"] not in metrics
    # One healthy collector must not hide another collector that stopped.
    second = report | {"collector_id": "a"*32, "pending_events":0, "oldest_pending_at":None}
    assert pilot.client.post("/api/pilot/ingest/health", json=second, headers=headers).status_code == 200
    assert pilot.db.list_sources(pilot.team)[0]["collection"]["stale_collectors"] == 1
    password = secrets.token_urlsafe(24)
    auth.create_user(pilot.db, {"team_id":pilot.team, "username":"admin"}, "reader", password, "viewer")
    retire = f"/api/pilot/sources/{identity}/collectors/{report['collector_id']}/retire"
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as reader:
        session = reader.post("/api/auth/login",json={"username":"reader","password":password}).json()
        reader.headers["X-Workbench-CSRF"] = session["csrf"]
        assert reader.get("/api/pilot/sources").status_code == 200
        assert reader.post(retire, json={}).status_code == 403
    other_team = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other_team, name="Another team"))
    assert pilot.db.list_sources(other_team) == []
    with pytest.raises(KeyError):
        pilot.db.retire_collector(other_team, identity, report["collector_id"], "other-admin")
    assert pilot.client.post(retire, json={}).status_code == 200
    assert pilot.db.list_sources(pilot.team)[0]["collection"]["status"] == "connected"
    pilot.db.revoke_tokens(pilot.team, identity, "admin")
    assert pilot.client.post("/api/pilot/ingest/health", json=report, headers=headers).status_code == 401
    assert pilot.db.list_sources(pilot.team)[0]["collection"]["status"] == "token_required"


def test_v2_migration_preserves_payload_facts_pricebooks_and_requires_explicit_upgrade(pilot):
    identity = pilot.db.create_source(pilot.team, "Legacy source", "admin")
    pilot.db.ingest(pilot.team, identity, [sample()])
    with pilot.db.engine.begin() as db:
        before = db.execute(select(events)).mappings().all()
        before_facts = db.execute(select(facts)).mappings().all()
        collectors.drop(db)
        db.execute(update(schema).values(version=2))
    with pytest.raises(RuntimeError, match="migration"):
        pilot.db.check_schema()
    pilot.db.migrate()
    pilot.db.migrate()
    pilot.db.check_schema()
    with pilot.db.engine.connect() as db:
        assert db.execute(select(schema.c.version)).scalars().all() == [3]
        assert db.execute(select(events)).mappings().all() == before
        assert db.execute(select(facts)).mappings().all() == before_facts
    assert pilot.db.ingest(pilot.team, identity, [sample()])["duplicate_events"] == 1
