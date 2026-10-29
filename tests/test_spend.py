"""Financial invariants, incomplete capture, immutable revisions and scoped access."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, select, update

from test_pilot import pilot, sample, settings
from workbench.pilot.database import events, maintenance, teams, uid, workflows, workflow_revisions
from workbench.spend import Allocation, Budget, allocation_result, budget_status


def budget(**changes):
    return {"reference": "support-budget", "name": "Support budget", "month": "2026-10",
            "limit_usd": "1.00", "cost_basis": "api_estimate_usd", **changes}


def allocation(**changes):
    return {"reference": "shared-plan-line", "name": "Shared coding subscription",
            "month": "2026-10", "amount_usd": "0.01", "category": "subscription",
            "reason": "Allocated by purchased seats",
            "shares": [{"project": "support", "weight": 1}, {"project": "engineering", "weight": 1},
                       {"project": "research", "weight": 1}], **changes}


def captured(pilot, **changes):
    source = pilot.db.create_source(pilot.team, "Spend source", "admin")
    pilot.db.ingest(pilot.team, source, [sample(occurred_at="2026-10-02T00:00:00Z", **changes)])
    return source


@pytest.mark.parametrize("value", [0.1, 1, "NaN", "Infinity", "1e10", "-1", "0.0000000001", "1000000001"])
def test_spend_invalid_amounts_never_become_zero(value):
    with pytest.raises(ValidationError):
        Budget.model_validate(budget(limit_usd=value))
    with pytest.raises(ValidationError):
        Allocation.model_validate(allocation(amount_usd=value))


def test_allocation_conserves_every_unit_and_tie_breaking_is_stable():
    value = Allocation.model_validate(allocation())
    result = allocation_result(value)
    assert result["allocated_total_usd"] == result["declared_total_usd"] == "0.010000000"
    assert result["allocations"] == [
        {"project": "engineering", "weight": 1, "allocated_usd": "0.003333334"},
        {"project": "research", "weight": 1, "allocated_usd": "0.003333333"},
        {"project": "support", "weight": 1, "allocated_usd": "0.003333333"}]
    assert allocation_result(Allocation.model_validate(allocation(shares=list(reversed(allocation()["shares"])))))[
        "allocations"] == result["allocations"]
    assert allocation_result(Allocation.model_validate(allocation(amount_usd="0")))["allocated_total_usd"] == "0.000000000"
    with pytest.raises(ValidationError):
        Allocation.model_validate(allocation(shares=[{"project": "same", "weight": 1}] * 2))


def test_budget_forecast_requires_explicit_coverage_and_preserves_unknowns(pilot):
    source = captured(pilot)
    clock = datetime(2026, 10, 16, tzinfo=timezone.utc)
    policy = Budget.model_validate(budget(source_id=source))
    report = budget_status(pilot.db, pilot.team, policy, now=clock)
    assert report["captured_usd"] == "0.002500000"
    assert report["forecast_usd"] is None and report["status"] == "incomplete"
    confirmed = policy.model_copy(update={"coverage_confirmed": True})
    report = budget_status(pilot.db, pilot.team, confirmed, now=clock)
    assert report["forecast_usd"] == "0.005166667"
    assert report["coverage"] == "administrator_declared"
    pilot.db.ingest(pilot.team, source, [sample(event_id="unpriced", model="unpriced",
                                               occurred_at="2026-10-03T00:00:00Z")])
    report = budget_status(pilot.db, pilot.team, confirmed, now=clock)
    assert report["captured_usd"] == "0.002500000"
    assert report["unknown_amount_records"] == 1 and report["forecast_usd"] is None
    # A known subtotal over the limit still triggers an alert despite incomplete pricing.
    report = budget_status(pilot.db, pilot.team, confirmed.model_copy(update={"limit_usd": "0.001000000"}), now=clock)
    assert report["status"] == "at_limit" and report["unknown_amount_records"] == 1


def test_budget_zero_absence_retention_and_attempt_limits(pilot):
    source = captured(pilot, model="unpriced")
    policy = Budget.model_validate(budget(source_id=source, coverage_confirmed=True))
    clock = datetime(2026, 10, 16, tzinfo=timezone.utc)
    assert budget_status(pilot.db, pilot.team, policy, now=clock)["captured_usd"] is None
    empty = policy.model_copy(update={"project": "empty"})
    assert budget_status(pilot.db, pilot.team, empty, now=clock)["captured_usd"] is None
    from workbench.pilot.events import Usage
    pilot.db.ingest(pilot.team, source, [sample(event_id="free", project="free",
        occurred_at="2026-10-02T00:00:00Z", usage=Usage(prompt_tokens=0, completion_tokens=0))])
    free = policy.model_copy(update={"project": "free"})
    assert budget_status(pilot.db, pilot.team, free, now=clock)["forecast_usd"] == "0.000000000"
    with pilot.db.engine.begin() as db:
        db.execute(insert(maintenance).values(id="retention_cutoff", updated_at=1,
            payload=json.dumps({"occurred_before": "2026-10-05T00:00:00+00:00"})))
    report = budget_status(pilot.db, pilot.team, free, now=clock)
    assert report["retention_limited"] and report["forecast_usd"] is None


def test_spend_revision_replay_archive_and_usage_facts_are_immutable(pilot):
    captured(pilot)
    with pilot.db.engine.connect() as db:
        before = [tuple(row) for row in db.execute(select(events)).all()]
    response = pilot.client.post("/api/pilot/spend/allocations", json={"value": allocation()})
    assert response.status_code == 200, response.text
    original = response.json()
    assert original["revision"] == 1 and original["result"]["invoice_authenticated"] is False
    assert pilot.client.post("/api/pilot/spend/allocations", json={"value": allocation()}).json()["unchanged"]
    revised = copy.deepcopy(original["value"])
    revised["amount_usd"] = "30.00"
    endpoint = "/api/pilot/spend/allocations/" + original["id"]
    assert pilot.client.post(endpoint, json={"value": revised, "revision": 0}).status_code == 409
    current = pilot.client.post(endpoint, json={"value": revised, "revision": 1}).json()
    assert current["revision"] == 2 and current["result"]["allocated_total_usd"] == "30.000000000"
    history = pilot.client.get(f"/api/pilot/spend/allocation/{original['id']}/history").json()
    assert [row["revision"] for row in history["revisions"]] == [2, 1]
    old = pilot.client.get(f"/api/pilot/spend/allocation/{original['id']}/export?revision=1").json()
    assert old["fingerprint"] == original["fingerprint"] and old["value"] == original["value"]
    assert old["result"]["allocated_total_usd"] == "0.010000000"
    archived = current["value"] | {"active": False}
    assert pilot.client.post(endpoint, json={"value": archived, "revision": 2}).json()["revision"] == 3
    with pilot.db.engine.connect() as db:
        assert [tuple(row) for row in db.execute(select(events)).all()] == before
        assert db.execute(select(workflow_revisions.c.revision)).scalars().all() == [1, 2, 3]


def test_spend_fixture_and_team_scope_csrf_and_invalid_basis(pilot):
    created = pilot.client.post("/api/pilot/spend/budgets", json={"value": budget(evidence="fixture")})
    assert created.status_code == 200
    assert pilot.client.get("/api/pilot/spend/budgets").json()["items"] == []
    assert len(pilot.client.get("/api/pilot/spend/budgets?include_fixtures=true").json()["items"]) == 1
    assert pilot.client.post("/api/pilot/spend/budgets", json={"value": budget()},
        headers={"X-Workbench-CSRF": ""}).status_code == 403
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other, name="Other team"))
    from workbench.pilot.workflows import save
    foreign = save(pilot.db, other, "allocation", Allocation.model_validate(allocation()).model_dump(), "operator")
    assert pilot.client.get(f"/api/pilot/spend/allocation/{foreign['id']}/export").status_code == 404
    assert pilot.client.post(f"/api/pilot/spend/allocations/{foreign['id']}",
        json={"value": allocation(), "revision": 1}).status_code == 404
    source = pilot.db.create_source(other, "Other source", "operator")
    assert pilot.client.post("/api/pilot/spend/budgets", json={"value": budget(source_id=source)}).status_code == 404
    source = pilot.db.create_source(pilot.team, "Coding source", "admin", kind="codex")
    assert pilot.client.post("/api/pilot/spend/budgets", json={"value": budget(source_id=source)}).status_code == 422


def test_concurrent_allocation_creates_do_not_duplicate_monthly_pool(pilot):
    if pilot.db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrent writers")
    from workbench.pilot.workflows import save
    value = Allocation.model_validate(allocation()).model_dump()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: save(pilot.db, pilot.team, "allocation", value, "admin"), range(4)))
    assert len({result["id"] for result in results}) == 1
    with pilot.db.engine.connect() as db:
        assert len(db.execute(select(workflows)).all()) == 1
        assert len(db.execute(select(workflow_revisions)).all()) == 1


def test_allocated_budgets_do_not_add_estimates_or_fixtures_and_track_revisions(pilot):
    from workbench.pilot.operations import snapshot
    current = datetime.now(timezone.utc).strftime("%Y-%m")
    captured(pilot)
    root = "/api/pilot/spend"
    saved = pilot.client.post(root + "/allocations", json={"value": allocation(month=current, amount_usd="30")}).json()
    pilot.client.post(root + "/allocations", json={"value": allocation(month=current, evidence="fixture", amount_usd="900")})
    created = pilot.client.post(root + "/budgets", json={"value": budget(month=current, cost_basis="allocated_usd",
        project="support", limit_usd="10", coverage_confirmed=True)}).json()
    assert created["result"]["tracked_usd"] == "10.000000000"
    assert created["result"]["captured_usd"] is None
    assert created["result"]["status"] == "at_limit"
    assert snapshot(pilot.db, pilot.settings, pilot.team)["spend_budget_breaches"] == 1
    real = pilot.client.get(root + "/summary", params={"month": current}).json()
    fiction = pilot.client.get(root + "/summary", params={"month": current, "fixture": "true"}).json()
    assert real["allocated_total_usd"] == "30.000000000" and real["pools"] == 1
    assert fiction["allocated_total_usd"] == "900.000000000"
    pilot.client.post(root + "/allocations/" + saved["id"], json={"value": saved["value"] | {"active": False}, "revision": 1})
    assert pilot.client.get(root + "/summary", params={"month": current}).json()["allocated_total_usd"] is None
    refreshed = pilot.client.get(root + "/budgets").json()["items"][0]["result"]
    assert refreshed["tracked_usd"] is None and refreshed["status"] == "incomplete"
    assert snapshot(pilot.db, pilot.settings, pilot.team)["spend_budget_breaches"] == 0


def test_known_collector_gap_blocks_current_month_projection(pilot):
    from workbench.pilot.events import CollectorHealth
    from workbench.pilot.database import collectors
    source = captured(pilot)
    raw = pilot.db.issue_token(pilot.team, source, "admin")["token"]
    pilot.db.report_collector(raw, CollectorHealth(collector_id="a" * 32,
        pending_events=1, inflight_calls=0, retrying_events=0, oldest_pending_at=None))
    policy = Budget.model_validate(budget(source_id=source, coverage_confirmed=True))
    clock = datetime(2026, 10, 16, tzinfo=timezone.utc)
    state = budget_status(pilot.db, pilot.team, policy, now=clock)
    assert state["collection_gap"] and state["forecast_usd"] is None
    pilot.db.report_collector(raw, CollectorHealth(collector_id="a" * 32,
        pending_events=0, inflight_calls=0, retrying_events=0, oldest_pending_at=None))
    assert budget_status(pilot.db, pilot.team, policy, now=clock)["forecast_usd"] is not None
    with pilot.db.engine.begin() as db:
        db.execute(update(collectors).values(received_at=int(clock.timestamp()) - 181))
    assert budget_status(pilot.db, pilot.team, policy, now=clock)["collection_gap"]


def test_tool_reported_budgets_use_exact_basis_and_leave_codex_money_unknown(pilot, tmp_path):
    from test_coding_tools import NativeOutbox, claude_wire, cursor_wire, START, END, codex
    from workbench.coding_tools import cursor_events
    from workbench.coding_tools_otel import claude_events
    expected = {"claude_code": ("0.324501000", None), "cursor": ("0.201823200", "0.213623200")}
    for tool in ("claude_code", "cursor", "codex"):
        native = NativeOutbox(tmp_path / (tool + ".db"), tool, "coding")
        records = claude_events(claude_wire(), native) if tool == "claude_code" else \
            cursor_events(cursor_wire(), native, start_ms=START, end_ms=END) if tool == "cursor" else codex(native)
        source = pilot.db.create_source(pilot.team, tool, "admin", kind=tool)
        pilot.db.ingest(pilot.team, source, records)
        for basis, index in [("reported_model_estimate_usd", 0), ("reported_charge_usd", 1)]:
            report = budget_status(pilot.db, pilot.team,
                Budget.model_validate(budget(source_id=source, cost_basis=basis, project="coding")),
                now=datetime(2026, 11, 1, tzinfo=timezone.utc))
            target = expected.get(tool, (None, None))[index]
            assert report["tracked_usd"] == target
    policy = Budget.model_validate(budget(cost_basis="reported_charge_usd", project="coding"))
    assert budget_status(pilot.db, pilot.team, policy,
        now=datetime(2026, 11, 1, tzinfo=timezone.utc))["tracked_usd"] == "0.213623200"
