"""Authored native-wire fixtures; no model calls, login credentials or vendor APIs."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
import json

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from workbench.coding_tools import (NativeInputError, NativeOutbox, codex_events, cursor_events,
                                    cursor_fetch, document, milliseconds)
from workbench.coding_tools_otel import claude_events, receiver
from workbench.connector import Connector, DeliveryError
from workbench.domain import digest
from workbench.pilot.events import CodingToolContext, account, event_adapter, pricebook
from test_pilot import pilot, sample, settings

STAMP = "2026-10-28T12:00:00Z"
START = milliseconds("2026-10-28T00:00:00Z")
END = milliseconds("2026-10-29T00:00:00Z") - 1
PRIVATE = "PRIVATE_PROMPT_RESPONSE_EMAIL_SENTINEL"


def codex_wire():
    return [
        {"type": "thread.started", "thread_id": "sample-thread"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"text": PRIVATE, "command": PRIVATE}},
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 12,
                                           "cached_input_tokens": 80, "reasoning_output_tokens": 2}},
    ]


def codex(native, rows=None, **kwargs):
    return list(codex_events((json.dumps(row).encode() for row in rows or codex_wire()), native,
        capture_id="sample-invocation", started_at=STAMP, model="configured-codex-model", **kwargs))


def attr(key, value):
    return {"key": key, "value": {"intValue" if isinstance(value, int) else "stringValue": str(value)}}


def claude_wire(*, event="api_request", sequence=5):
    attrs = {"event.name": event, "event.timestamp": STAMP, "event.sequence": sequence,
        "session.id": "sample-session", "prompt.id": "sample-prompt", "model": "sample-claude-model",
        "request_id": "sample-request", "input_tokens": 100, "output_tokens": 20,
        "cache_read_tokens": 200, "cache_creation_tokens": 300, "cost_usd_micros": 324501,
        "duration_ms": 125, "user.email": PRIVATE, "prompt": PRIVATE, "error": PRIVATE,
        "tool_parameters": PRIVATE}
    return {"resourceLogs": [{"resource": {"attributes": [attr("user.email", PRIVATE)]},
        "scopeLogs": [{"scope": {"name": "claude-code"}, "logRecords": [
            {"timeUnixNano": str(milliseconds(STAMP) * 1_000_000), "body": {"stringValue": PRIVATE},
             "attributes": [attr(k, v) for k, v in attrs.items()]},
            {"body": {"stringValue": "claude_code.assistant_response"},
             "attributes": [attr("message", PRIVATE)]}]}]}]}


def cursor_wire():
    return {"totalUsageEventsCount": 2, "period": {"startDate": START, "endDate": END},
        "usageEvents": [
            {"timestamp": str(milliseconds(STAMP)), "userEmail": PRIVATE, "conversationId": "sample-session",
             "model": "sample-cursor-model", "kind": "Usage-based", "isTokenBasedCall": True,
             "requestsCosts": 5000, "chargedCents": Decimal("21.36232"), "cursorTokenFee": Decimal("1.18"),
             "tokenUsage": {"inputTokens": 126, "outputTokens": 450, "cacheWriteTokens": 6112,
                            "cacheReadTokens": 11964, "totalCents": Decimal("20.18232")},
             "prompt": PRIVATE, "response": PRIVATE},
            {"timestamp": str(milliseconds(STAMP) + 1), "userEmail": PRIVATE,
             "model": "sample-cursor-model", "kind": "Included in Business", "isTokenBasedCall": False,
             "requestsCosts": 9000, "isChargeable": False, "chargedCents": 0}]}


def test_codex_turns_cache_semantics_privacy_interruption_and_replay(tmp_path):
    native = NativeOutbox(tmp_path / "codex.db", "codex", "project")
    events = codex(native)
    first = events[0]
    assert first.coding_tool.record_kind == "turn" and first.latency_ms is None
    assert first.coding_tool.model_basis == "configured"
    assert first.coding_tool.timestamp_basis == "capture_start"
    assert first.usage.input_tokens == 100 and first.usage.cache_read_tokens == 80
    assert first.usage.reasoning_output_tokens == 2
    assert first.attempt_coverage == "unknown"
    assert PRIVATE not in first.model_dump_json()
    assert native.save(events) == {"added": 1, "duplicates": 0}
    assert native.key not in native.outbox.health().model_dump_json()
    assert native.key not in events[0].model_dump_json()
    assert native.save(codex(native)) == {"added": 0, "duplicates": 1}
    other = NativeOutbox(tmp_path / "codex.db", "codex", "project")
    assert codex(other)[0].event_id == first.event_id
    interrupted = codex(native, codex_wire()[:-1])[0]
    assert interrupted.status == "interrupted" and interrupted.usage is None
    with pytest.raises(NativeInputError, match="changed"):
        native.save([interrupted])
    assert native.outbox.pending() == 1
    with pytest.raises(NativeInputError):
        codex(native, [{"type": "turn.completed", "usage": {}}])
    with pytest.raises(NativeInputError):
        NativeOutbox(tmp_path / "codex.db", "cursor", "project")
    with pytest.raises(NativeInputError):
        NativeOutbox(tmp_path / "codex.db", "codex", "project", evidence="fixture")


def test_claude_metadata_only_otlp_retry_identity_and_cost_basis(tmp_path):
    native = NativeOutbox(tmp_path / "claude.db", "claude_code", "project")
    events = claude_events(claude_wire(), native)
    assert len(events) == 1
    event = events[0]
    assert event.usage.input_semantics == "excludes_cache"
    assert event.usage.cache_read_tokens > event.usage.input_tokens
    assert event.coding_tool.reported_model_estimate_usd == "0.324501000"
    assert event.latency_ms == 125 and event.coding_tool.task_scope == "prompt"
    assert PRIVATE not in event.model_dump_json()
    native.save(events)
    replay = claude_wire()
    replay["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["observedTimeUnixNano"] = "999999"
    assert native.save(claude_events(replay, native))["duplicates"] == 1
    # A process restart can reuse a sequence; source time/request metadata distinguish it.
    newer = claude_wire(sequence=6)
    assert native.save(claude_events(newer, native))["added"] == 1
    failure = claude_events(claude_wire(event="api_error"), native)[0]
    assert failure.status == "error" and failure.usage is None
    assert failure.coding_tool.reported_model_estimate_usd is None
    charge = account(event, pricebook())
    assert charge["api_estimate_usd"] is None and charge["invoice_usd"] is None
    assert charge["reported_model_estimate_usd"] == "0.324501000"
    assert charge["hardware_electricity_usd"] is None and not charge["attempt_cost_complete"]


def test_authenticated_otlp_receiver_discards_content_and_rejects_batches_atomically(tmp_path):
    native = NativeOutbox(tmp_path / "receiver.db", "claude_code", "project")
    token = "local-telemetry-test-" + "a" * 32
    with TestClient(receiver(native, token)) as client:
        assert client.post("/v1/logs", json=claude_wire()).status_code == 401
        headers = {"Authorization": "Bearer " + token}
        assert client.post("/v1/logs", json=claude_wire(), headers=headers | {"Origin": "https://other.example"}).status_code == 401
        assert client.post("/v1/logs", content=b"binary", headers=headers | {"Content-Type": "application/x-protobuf"}).status_code == 415
        broken = claude_wire()
        records = broken["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        second = copy.deepcopy(records[0])
        second["attributes"].append(attr("input_tokens", "private-bad-value"))
        records.append(second)
        rejected = client.post("/v1/logs", json=broken, headers=headers)
        assert rejected.status_code == 422 and PRIVATE not in rejected.text
        assert native.outbox.pending() == 0
        assert client.post("/v1/logs", json=claude_wire(), headers=headers).json() == {}
        assert client.post("/v1/logs", json=claude_wire(), headers=headers).status_code == 200
        assert native.outbox.pending() == 1
    for row in native.outbox.batch():
        assert PRIVATE not in row["payload"]


def test_cursor_decimal_amounts_multiplicity_frozen_windows_and_no_request_unit_prices(tmp_path):
    native = NativeOutbox(tmp_path / "cursor.db", "cursor", "project")
    wire = cursor_wire()
    events = cursor_events(wire, native, start_ms=START, end_ms=END)
    first, included = events
    assert first.coding_tool.reported_model_estimate_usd == "0.201823200"
    assert first.coding_tool.reported_charge_usd == "0.213623200"  # not requestsCosts or model cost
    assert first.latency_ms is None and first.status == "unknown"
    assert included.usage is None and included.coding_tool.reported_charge_usd == "0.000000000"
    assert account(included, pricebook())["invoice_usd"] is None
    assert all(PRIVATE not in event.model_dump_json() for event in events)
    assert native.save(events, window=(START, END))["added"] == 2
    wire["usageEvents"].reverse()
    assert native.save(cursor_events(wire, native, start_ms=START, end_ms=END),
                       window=(START, END))["duplicates"] == 2
    changed = copy.deepcopy(wire)
    changed["usageEvents"][0]["chargedCents"] = 9
    with pytest.raises(NativeInputError, match="changed"):
        native.save(cursor_events(changed, native, start_ms=START, end_ms=END), window=(START, END))
    with pytest.raises(NativeInputError, match="overlaps"):
        native.save(events, window=(START + 1, END + 1))
    assert native.outbox.pending() == 2
    duplicate = cursor_wire()
    duplicate["usageEvents"] = [duplicate["usageEvents"][0]] * 2
    values = cursor_events(duplicate, native, start_ms=START, end_ms=END)
    assert len({event.event_id for event in values}) == 2
    del wire["usageEvents"][1]["chargedCents"]
    assert cursor_events(wire, native, start_ms=START, end_ms=END)[1].coding_tool.reported_charge_usd is None


def test_cursor_pagination_http_failure_and_no_credential_redirects(tmp_path):
    native = NativeOutbox(tmp_path / "cursor.db", "cursor", "project")
    original = cursor_wire()
    calls = []
    def handler(request):
        calls.append(request)
        page = json.loads(request.content)["page"]
        assert request.url == "https://api.cursor.com/teams/filtered-usage-events"
        row = original["usageEvents"][page - 1]
        # An actual JSON response uses JSON numbers; parse_float=Decimal preserves them.
        raw = json.dumps({"usageEvents": [row], "totalUsageEventsCount": 2,
            "period": original["period"], "pagination": {"currentPage": page, "hasNextPage": page == 1}},
            default=float).encode()
        return httpx.Response(200, content=raw)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = cursor_fetch("synthetic-cursor-admin-key", START, END, client=client)
    assert len(calls) == 2
    assert len(cursor_events(payload, native, start_ms=START, end_ms=END)) == 2
    assert native.outbox.pending() == 0  # reads do not commit a partial window
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            302, headers={"Location": "https://untrusted.example"})), follow_redirects=True) as client:
        with pytest.raises(NativeInputError, match="rejected"):
            cursor_fetch("synthetic-cursor-admin-key", START, END, client=client)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=b" " * 8_000_001))) as client:
        with pytest.raises(NativeInputError, match="size"):
            cursor_fetch("synthetic-cursor-admin-key", START, END, client=client)
    partial = cursor_wire(); partial["totalUsageEventsCount"] = 3
    with pytest.raises(NativeInputError, match="incomplete"):
        cursor_events(partial, native, start_ms=START, end_ms=END)
    with pytest.raises(NativeInputError):
        document(b'{"cost": 0.1, "cost": 0.2}')
    with pytest.raises(NativeInputError):
        document(b'{"cost": NaN}')


def test_source_fences_delivery_sql_totals_unknowns_and_legacy_accounting(pilot, tmp_path):
    original = sample()
    assert digest(event_adapter.validate_python(original.model_dump()).model_dump()) == digest(original.model_dump())
    expected = {"claude_code": ("0.324501000", None), "cursor": ("0.201823200", "0.213623200"),
                "codex": (None, None)}
    sources = {}
    for tool in ("claude_code", "cursor", "codex"):
        native = NativeOutbox(tmp_path / (tool + ".db"), tool, "coding")
        rows = (claude_events(claude_wire(), native) if tool == "claude_code" else
                cursor_events(cursor_wire(), native, start_ms=START, end_ms=END) if tool == "cursor" else codex(native))
        native.save(rows)
        response = pilot.client.post("/api/pilot/sources", json={"name": tool, "kind": tool})
        assert response.status_code == 200
        source = response.json()["id"]; sources[tool] = source
        token = pilot.client.post(f"/api/pilot/sources/{source}/token", json={}).json()["token"]
        connector = Connector(pilot.settings.public_origin + "/api/pilot/ingest", token,
                              native.outbox, client=pilot.client, report_health=True)
        assert connector.flush()["pending"] == 0
        value = pilot.db.usage(pilot.team, source_id=source)
        assert value["reported_model_estimate_usd"] == expected[tool][0]
        assert value["reported_charge_usd"] == expected[tool][1]
        assert value["unknown_cost_calls"] == value["events"]
        assert value["invoice_usd"] is None
        if tool == "cursor":
            assert all(task["reported_charge_usd"] is not None for task in value["tasks"])
        assert all("private" not in call["event_id"] for task in value["tasks"] for call in task["calls"])
        wrong = codex(NativeOutbox(tmp_path / ("wrong-" + tool + ".db"), "codex", "coding"))[0]
        if tool != "codex":
            rejected = pilot.client.post("/api/pilot/ingest", json={"events": [wrong.model_dump()]},
                headers={"Authorization": "Bearer " + token})
            assert rejected.status_code == 409
    combined = pilot.db.usage(pilot.team)
    assert combined["coding_tool_records"] == 4
    assert combined["reported_model_estimate_usd"] == "0.526324200"
    assert combined["reported_charge_usd"] == "0.213623200"
    assert combined["reported_charge_usd_records"] == 2
    assert combined["api_estimate_usd"] == "0.000000000" and combined["unknown_cost_calls"] == 4
    empty = pilot.db.usage(pilot.team, project="another-project")
    assert empty["reported_charge_usd"] is None and empty["coding_tool_records"] == 0
    for invalid in ("NaN", "-1", "bad", "1000001", "0.0000000001"):
        with pytest.raises(ValidationError):
            CodingToolContext(tool="claude_code", transport="otel_logs", record_kind="api_response",
                task_scope="session", reported_model_estimate_usd=invalid)


def test_wrong_tool_token_does_not_bind_or_strand_native_outbox(pilot, tmp_path):
    native = NativeOutbox(tmp_path / "codex.db", "codex", "engineering")
    native.save(codex(native))
    tokens = {}
    for tool in ("cursor", "codex"):
        source = pilot.client.post("/api/pilot/sources",
            json={"name": tool, "kind": tool}).json()["id"]
        tokens[tool] = pilot.client.post(f"/api/pilot/sources/{source}/token", json={}).json()["token"]
    endpoint = pilot.settings.public_origin + "/api/pilot/ingest"
    with pytest.raises(DeliveryError, match="native coding tool"):
        Connector(endpoint, tokens["cursor"], native.outbox, client=pilot.client).flush()
    with native.outbox.connect() as db:
        assert db.execute("SELECT * FROM source_binding").fetchone() is None
    assert native.outbox.pending() == 1 and pilot.db.usage(pilot.team)["events"] == 0
    assert Connector(endpoint, tokens["codex"], native.outbox,
                     client=pilot.client).flush()["acknowledged"] == 1


def test_expected_tool_unknowns_do_not_mask_or_trigger_api_pricing_alerts(pilot, tmp_path):
    from workbench.pilot.operations import Metrics, snapshot
    native = NativeOutbox(tmp_path / "codex.db", "codex", "engineering")
    stamp = datetime.now(timezone.utc).isoformat()
    event = next(codex_events((json.dumps(row).encode() for row in codex_wire()), native,
        capture_id="operations-check", started_at=stamp, model="configured-codex-model"))
    for kind, row in (("codex", event), ("axonllm", sample(model="unpriced", occurred_at=stamp))):
        source = pilot.client.post("/api/pilot/sources",
            json={"name": kind, "kind": kind}).json()["id"]
        token = pilot.client.post(f"/api/pilot/sources/{source}/token", json={}).json()["token"]
        assert pilot.client.post("/api/pilot/ingest", json={"events": [row.model_dump()]},
            headers={"Authorization": "Bearer " + token}).status_code == 200
        state = snapshot(pilot.db, pilot.settings, pilot.team)
        assert state["observed_coding_tool_records_24h"] == 1
        assert state["unknown_cost_calls_24h"] == state["observed_calls_24h"] == (kind == "axonllm")
        assert any("unknown costs" in alert["message"] for alert in state["alerts"]) == (kind == "axonllm")
        assert "workbench_observed_coding_tool_records_24h 1.0" in Metrics().render(state).decode()
