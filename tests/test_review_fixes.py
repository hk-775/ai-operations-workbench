"""Regressions for the v0.8.0 review; authored inputs, no paid model calls."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from test_bedrock import event as bedrock_event
from test_coding_tools import NativeOutbox, claude_wire
from test_pilot import pilot, sample, settings
from test_workbench import fixture_recording
from workbench.coding_tools_otel import claude_events
from workbench.connector import Connector, DeliveryError, Outbox
from workbench.evidence import analyze, recommend
from workbench.pilot.database import SCHEMA_VERSION, events, jobs, schema, sources, teams, uid
from workbench.pilot.worker import EvaluationWorker
from workbench.proposals import verify_bundle


def connection(pilot, kind, suffix=""):
    identity = pilot.client.post("/api/pilot/sources",
        json={"name": kind + suffix, "kind": kind}).json()["id"]
    token = pilot.client.post(f"/api/pilot/sources/{identity}/token", json={}).json()["token"]
    return identity, token


@pytest.mark.parametrize("kind,wrong_kind", [("axonllm", "bedrock"), ("bedrock", "axonllm")])
def test_wrong_kind_cannot_bind_and_legacy_binding_can_be_repaired(pilot, tmp_path, kind, wrong_kind):
    correct, token = connection(pilot, kind)
    wrong, wrong_token = connection(pilot, wrong_kind)
    box = Outbox(tmp_path / "outbox.db")
    box.put(sample() if kind == "axonllm" else bedrock_event())
    endpoint = pilot.settings.public_origin + "/api/pilot/ingest"
    bad = Connector(endpoint, wrong_token, box, client=pilot.client)
    with pytest.raises(DeliveryError, match="connector type"):
        bad.flush()
    with box.connect() as db:
        assert not db.execute("SELECT * FROM source_binding").fetchall()
        original = tuple(db.execute("SELECT id,fingerprint,payload FROM outbox").fetchone())
        # Reproduce a pre-fix outbox bound before a wrong-schema rejection.
        db.execute("INSERT INTO source_binding VALUES (1,?)", (wrong,))
        db.execute("DELETE FROM connector_binding")  # v0.8.0 had no stored kind.
        db.execute("UPDATE outbox SET retry_after=9999999999")
    with pytest.raises(DeliveryError, match="different source"):
        Connector(endpoint, token, box, client=pilot.client).flush()
    assert bad.repair_source_binding() == {"repaired": True, "pending": 1}
    reopened = Outbox(box.path)
    assert Connector(endpoint, token, reopened, client=pilot.client).flush()["acknowledged"] == 1
    with reopened.connect() as db:
        assert tuple(db.execute("SELECT id,fingerprint,payload FROM outbox").fetchone()) == original
        assert db.execute("SELECT source_id FROM source_binding").fetchone()[0] == correct
    with pytest.raises(DeliveryError, match="safely"):
        bad.repair_source_binding()


def test_uncertain_delivery_and_acknowledged_rows_cannot_be_rebound(pilot, tmp_path):
    identity, token = connection(pilot, "axonllm")
    other, other_token = connection(pilot, "axonllm", "-other")
    wrong, wrong_token = connection(pilot, "bedrock")
    endpoint = pilot.settings.public_origin + "/api/pilot/ingest"
    box = Outbox(tmp_path / "uncertain.db")
    box.put(sample())

    def lost_ack(request):
        if request.method == "GET":
            return pilot.client.get("/api/pilot/ingest", headers=dict(request.headers))
        response = pilot.client.post("/api/pilot/ingest", content=request.content,
                                     headers=dict(request.headers))
        assert response.status_code == 200
        raise httpx.ReadTimeout("Simulated lost acknowledgment")

    with httpx.Client(transport=httpx.MockTransport(lost_ack)) as client:
        with pytest.raises(DeliveryError):
            Connector(endpoint, token, box, client=client).flush()
    assert box.pending() == 1 and pilot.db.usage(pilot.team)["events"] == 1
    for supplied in (token, other_token, wrong_token):
        with pytest.raises(DeliveryError, match="safely"):
            Connector(endpoint, supplied, box, client=pilot.client).repair_source_binding()
    with pytest.raises(DeliveryError, match="different source"):
        Connector(endpoint, other_token, box, client=pilot.client).flush()
    with box.connect() as db:
        db.execute("UPDATE outbox SET retry_after=0")
    Connector(endpoint, token, box, client=pilot.client).flush()
    assert box.pending() == 0 and pilot.db.usage(pilot.team)["events"] == 1


def test_cursor_snapshot_excludes_new_backdated_and_tied_arrivals(pilot):
    identity, _ = connection(pilot, "axonllm")
    original = [sample(event_id=f"call-{n:03}", task_id="long") for n in range(205)]
    pilot.db.ingest(pilot.team, identity, original)
    task = pilot.client.get("/api/pilot/usage", params={"task_id": "long"}).json()["tasks"][0]
    assert task["calls_cursor"]
    pilot.db.ingest(pilot.team, identity, [
        sample(event_id="new", task_id="long", occurred_at="2026-10-24T00:00:00Z"),
        sample(event_id="backdated", task_id="long", occurred_at="2026-10-20T00:00:00Z"),
        sample(event_id="call-100-new-tie", task_id="long"),
    ])
    collected = [c["event_id"] for c in task["calls"]]
    cursor = task["calls_cursor"]
    while cursor:
        response = pilot.client.get("/api/pilot/calls", params={
            "source_id": identity, "task_id": "long", "cursor": cursor})
        assert response.status_code == 200
        page = response.json()
        collected.extend(c["event_id"] for c in page["calls"])
        cursor = page["next_cursor"]
    assert len(collected) == len(set(collected)) == 205
    assert set(collected) == {e.event_id for e in original}
    fresh = pilot.client.get("/api/pilot/usage", params={"task_id": "long"}).json()["tasks"][0]
    assert fresh["call_count"] == 208
    for change in ({"task_id": "other"}, {"project": "changed"}, {"include_fixtures": True},
                   {"cursor": "not-base64"}, {"offset": 100}):
        assert pilot.client.get("/api/pilot/calls", params={
            "source_id": identity, "task_id": "long", "cursor": task["calls_cursor"],
            **change}).status_code == 422


def test_real_schema_four_upgrade_preserves_evidence_and_fences_new_ingest(pilot):
    identity, _ = connection(pilot, "axonllm")
    pilot.db.ingest(pilot.team, identity, [sample()])
    columns = [events.c.payload, events.c.fingerprint, events.c.accounting]
    with pilot.db.engine.begin() as db:
        before = db.execute(select(*columns)).all()
        db.execute(text("ALTER TABLE wb_events DROP COLUMN ingest_sequence"))
        db.execute(text("ALTER TABLE wb_sources DROP COLUMN ingest_sequence"))
        db.execute(update(schema).values(version=4))
    with pytest.raises(RuntimeError, match="migration"):
        pilot.db.check_schema()
    pilot.db.migrate()
    pilot.db.migrate()
    pilot.db.check_schema()
    with pilot.db.engine.connect() as db:
        assert db.execute(select(*columns)).all() == before
        assert db.execute(select(events.c.ingest_sequence)).scalar_one() == 0
        assert db.execute(select(schema.c.version)).scalar_one() == SCHEMA_VERSION
    pilot.db.ingest(pilot.team, identity, [sample(event_id="after-upgrade")])
    with pilot.db.engine.connect() as db:
        assert sorted(db.execute(select(events.c.ingest_sequence)).scalars()) == [0, 1]


def test_concurrent_ingestion_assigns_serial_source_sequences(pilot):
    if pilot.db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock concurrency contract")
    identity, _ = connection(pilot, "axonllm")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: pilot.db.ingest(pilot.team, identity,
            [sample(event_id=f"concurrent-{n}")]), range(8)))
    with pilot.db.engine.connect() as db:
        assert sorted(db.execute(select(events.c.ingest_sequence)).scalars()) == list(range(1, 9))
        assert db.execute(select(sources.c.ingest_sequence).where(sources.c.id == identity)).scalar_one() == 8


def test_reported_amount_ordering_preserves_unknown_zero_and_separate_bases(pilot, tmp_path):
    identity, _ = connection(pilot, "claude_code")
    native = NativeOutbox(tmp_path / "claude.db", "claude_code", "engineering")
    base = list(claude_events(claude_wire(), native))[0]
    records = []
    for name, cost in (("small", "1"), ("large", "100"), ("zero", "0"), ("unknown", None)):
        document = base.model_dump()
        document.update(event_id=name, task_id=name)
        document["coding_tool"]["reported_model_estimate_usd"] = cost
        records.append(type(base).model_validate(document))
    pilot.db.ingest(pilot.team, identity, records)
    result = pilot.client.get("/api/pilot/usage", params={
        "cost_basis": "reported_model_estimate_usd"}).json()
    assert [t["task_id"] for t in result["tasks"]] == ["large", "small", "zero", "unknown"]
    assert result["reported_model_estimate_usd"] == "101.000000000"
    assert result["api_estimate_usd"] == "0.000000000" and result["unknown_cost_calls"] == 4
    assert result["reported_charge_usd"] is None
    assert pilot.client.get("/api/pilot/usage?cost_basis=mixed").status_code == 422


def test_perfect_fixture_never_produces_measured_winner_or_savings():
    proposal = recommend(analyze(fixture_recording()), min_pass_rate=0)
    assert proposal["status"] == "fixture_only"
    assert proposal["recommended_model"] is None and proposal["projected_monthly_api_savings_usd"] is None
    assert all(not c["eligible"] for c in proposal["candidates"])

@pytest.mark.parametrize("answer", ['{"refund_minor":1e309}', '{"refund_minor":NaN}',
                                   '{"value":' + '['*2000+'0'+']'*2000 + '}'],
                         ids=["overflow", "nan", "nesting"])
def test_invalid_support_answer_remains_a_failed_case_with_exportable_cost(answer):
    recording = fixture_recording()
    original_cost = recording["samples"][0]["stages"][1]["estimated_cost_usd"]
    recording["samples"][0]["stages"][1]["output"] = answer
    report = analyze(recording)
    assert not report["tasks"][0]["assessment"]["passed"]
    assert report["tasks"][0]["assessment"]["decision"] is None
    assert report["tasks"][0]["stages"][1]["output"] == answer
    assert report["tasks"][0]["stages"][1]["estimated_cost_usd"] == original_cost
    assert len(report["tasks"]) == 72
    json.dumps(report, allow_nan=False)


def test_full_evidence_export_auth_scope_original_answers_and_offline_integrity(pilot, tmp_path):
    imported = pilot.client.post("/api/pilot/recordings", json=fixture_recording()).json()
    job = pilot.client.post("/api/pilot/evaluations", json={"recording_id": imported["recording_id"]}).json()
    assert EvaluationWorker(pilot.db, pilot.settings).run_once()
    proposal = pilot.client.post(f"/api/pilot/evaluations/{job['id']}/recommend", json={}).json()
    path = f"/api/pilot/proposals/{proposal['id']}/export"
    response = pilot.client.get(path)
    assert response.status_code == 200, response.text
    bundle = verify_bundle(json.loads(response.content))
    assert bundle["proposal"]["status"] == "fixture_only"
    assert bundle["recording"] == fixture_recording()
    assert len(bundle["analysis"]["tasks"]) == 72
    assert bundle["analysis"]["tasks"][0]["stages"][1]["output"]
    from workbench.proposals import main
    file = tmp_path / "evidence.json"
    file.write_bytes(response.content)
    main(["verify", str(file)])
    altered = copy.deepcopy(bundle)
    altered["recording"]["samples"][0]["stages"][1]["output"] = "tampered"
    with pytest.raises(ValueError, match="checksum"):
        verify_bundle(altered)
    from workbench.coding import fingerprint
    malformed = copy.deepcopy(bundle)
    malformed["analysis"]["evaluation_revision"] = []
    malformed["manifest"]["analysis"] = fingerprint(malformed["analysis"])
    with pytest.raises(ValueError, match="identity"):
        verify_bundle(malformed)
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(teams.insert().values(id=other, name="Other team"))
    with pytest.raises(KeyError):
        pilot.db.export_proposal(other, proposal["id"])
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as anonymous:
        assert anonymous.get(path).status_code == 401
    # Export preserves historical evaluator identity rather than regrading.
    with pilot.db.engine.begin() as db:
        db.execute(update(jobs).where(jobs.c.id == job["id"]).values(revision="old revision"))
    assert pilot.client.get(path).content == response.content
    with pilot.db.engine.begin() as db:
        damaged = copy.deepcopy(bundle["analysis"])
        damaged["recording_id"] = "different recording"
        db.execute(update(jobs).where(jobs.c.id == job["id"]).values(result=json.dumps(damaged)))
    assert pilot.client.get(path).status_code == 409
