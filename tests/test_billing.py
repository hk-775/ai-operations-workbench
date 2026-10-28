"""Billing contracts using authored CSV and synthetic usage, never AWS charges."""
import csv
import io
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, insert, select, update

from workbench.billing import BillingError, BillingMapping, financial, groups, parse_upload, total
from workbench.pilot import billing
from workbench.pilot.api import create_pilot_app
from workbench.pilot.billing_example import example_upload, load_example
from workbench.pilot.database import (Conflict, billing_bindings, billing_families, billing_mappings,
    billing_reports, collectors, events, facts, maintenance, schema, teams, uid)
from workbench.pilot.maintenance import run_once
from test_bedrock import event
from test_pilot import pilot, settings


def upload(*, rows=None, changes=None, **kwargs):
    original = example_upload()
    rows = rows if rows is not None else list(csv.DictReader(io.StringIO(original.files[0])))
    for row in rows:
        row["workbench_evidence"] = ""
        row.update(changes or {})
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
    writer.writeheader()
    writer.writerows(rows)
    return original.model_copy(update={"files": [stream.getvalue()], **kwargs})


def mapped(pilot, *, body=None, usage=None):
    source = pilot.db.create_source(pilot.team, "Billing test", "admin", kind="bedrock")
    if usage is not False:
        pilot.db.ingest(pilot.team, source, [usage or event()])
    imported = billing.import_report(pilot.db, pilot.team, body or upload(), "admin")
    report = billing.reconcile(pilot.db, pilot.team, imported["id"])
    mapping = BillingMapping(name="Declared scope", group_ids=[
        g["id"] for g in report["groups"] if g["eligible"] and g["region"] == "us-east-1"],
        source_ids=[source], model=(usage.model if usage else "amazon.nova-micro-v1:0"),
        region="us-east-1", service_tier="default", performance="standard",
        account_binding_confirmed=True)
    billing.add_mapping(pilot.db, pilot.team, imported["id"], mapping, "admin")
    return imported["id"], mapping


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "-Infinity", "1_000", "١", "1e999", "1e-19",
                                       "1000000000000", None, 1.1])
def test_invalid_money_never_becomes_zero(value):
    with pytest.raises(BillingError):
        financial(value)


def test_decimal_precision_cost_basis_units_and_unattributed_lines():
    data = upload(changes={"lineItem/NetUnblendedCost": "0.123456789012345678",
                           "lineItem/UsageAmount": "0.0001"})
    parsed = parse_upload(data)
    assert len(parsed["snapshot"]["rows"]) == 5  # Missing user/model never discards a charge.
    assert total(r["amount"] for r in parsed["snapshot"]["rows"]) == "0.61728394506172839"
    assert {r["basis"] for r in parsed["snapshot"]["rows"]} == {"net_unblended"}
    assert {g["quantity"] for g in groups(parsed["snapshot"])} == {"0.0001"}
    assert financial("-0.000") == "0" and financial("1e-18") == "0.000000000000000001"
    assert financial(None, optional=True) is None
    assert financial("999999999999.123456789012345678") == "999999999999.123456789012345678"


def test_cur2_projected_columns_and_product_map():
    raw = list(csv.DictReader(io.StringIO(upload().files[0])))
    columns = {
        "identity/LineItemId": "identity_line_item_id", "identity/TimeInterval": "identity_time_interval",
        "lineItem/ProductCode": "line_item_product_code", "lineItem/UsageAccountId": "line_item_usage_account_id",
        "bill/BillingPeriodStartDate": "bill_billing_period_start_date",
        "bill/BillingPeriodEndDate": "bill_billing_period_end_date",
        "lineItem/CurrencyCode": "line_item_currency_code", "lineItem/LineItemType": "line_item_line_item_type",
        "lineItem/UsageStartDate": "line_item_usage_start_date", "lineItem/UsageEndDate": "line_item_usage_end_date",
        "lineItem/UsageType": "line_item_usage_type", "lineItem/Operation": "line_item_operation",
        "lineItem/UsageAmount": "line_item_usage_amount", "lineItem/UnblendedCost": "line_item_unblended_cost",
        "lineItem/NetUnblendedCost": "line_item_net_unblended_cost", "pricing/unit": "pricing_unit",
        "bill/InvoiceId": "bill_invoice_id",
    }
    projected = [{**{columns[k]: v for k, v in row.items() if k in columns},
                  "product": json.dumps({"region_code": row["product/regionCode"]}),
                  "line_item_usage_start_date": "2026-10-27 00:00:00.000"} for row in raw]
    report = parse_upload(upload(rows=projected, format="cur-2.0"))["snapshot"]
    assert total(r["amount"] for r in report["rows"]) == "0.0121475"
    assert sum(g["eligible"] for g in groups(report)) == 3
    assert {r["usage_start"] for r in report["rows"]} == {"2026-10-27T00:00:00+00:00"}
    with pytest.raises(BillingError, match="product"):
        parse_upload(upload(rows=projected, changes={"product": "{not-json"}, format="cur-2.0"))


@pytest.mark.parametrize("changes", [
    {"lineItem/UnblendedCost": ""}, {"lineItem/UnblendedCost": "private-invalid-value"},
    {"lineItem/UsageAccountId": "111111111111"}, {"lineItem/CurrencyCode": "EUR"},
    {"bill/BillingPeriodStartDate": "2026-09-01T00:00:00Z"},
    {"lineItem/UsageEndDate": "2026-10-26T00:00:00Z"}, {"identity/LineItemId": ""},
    {"lineItem/ProductCode": ""},
])
def test_bad_snapshot_rejects_atomically_and_does_not_echo_cells(pilot, changes):
    response = pilot.client.post("/api/pilot/billing/imports", json=upload(changes=changes).model_dump())
    assert response.status_code == 422 and "private-invalid-value" not in response.text
    assert billing.list_reports(pilot.db, pilot.team)["reports"] == []


def test_multipart_dedupe_conflicts_service_filter_and_bounds(monkeypatch):
    data = upload()
    parsed = parse_upload(data.model_copy(update={"files": data.files * 2}))
    assert parsed["duplicate_rows"] == 5 and len(parsed["snapshot"]["rows"]) == 5
    assert parsed["fingerprint"] == parse_upload(data)["fingerprint"]
    altered = upload(changes={"lineItem/UnblendedCost": "2"})
    with pytest.raises(BillingError, match="Conflicting line"):
        parse_upload(data.model_copy(update={"files": data.files + altered.files}))
    other = upload(changes={"lineItem/ProductCode": "AmazonEC2"})
    filtered = parse_upload(data.model_copy(update={"files": data.files + other.files}))
    assert filtered["outside_bedrock_rows"] == 5
    with pytest.raises(BillingError, match="synthetic"):
        parse_upload(example_upload())
    with pytest.raises(BillingError, match="header"):
        parse_upload(data.model_copy(update={"files": ["a,a\n1,1\n"]}))
    with pytest.raises(BillingError):
        parse_upload(data.model_copy(update={"files": [data.files[0] + "bad,row\n"]}))
    with pytest.raises(ValidationError):
        type(data).model_validate(data.model_dump() | {"files": ["x" * 8_000_001]})
    monkeypatch.setattr("workbench.billing.MAX_ROWS", 4)
    with pytest.raises(BillingError, match="20,000"):
        parse_upload(data)


def test_example_exact_totals_idempotence_fixture_isolation_and_export(pilot):
    first = pilot.client.post("/api/pilot/billing/example", json={}).json()
    second = pilot.client.post("/api/pilot/billing/example", json={}).json()
    assert first["model_calls"] == 0 and second["unchanged"] and second["id"] == first["id"]
    report = pilot.client.get(f"/api/pilot/billing/reports/{first['id']}/export")
    assert "attachment" in report.headers["content-disposition"]
    report = report.json()
    assert report["evidence"] == "fixture" and report["row_count"] == 5
    assert report["imported_charges"] == "0.0121475"
    assert report["linked_charges"] == "0.0001475" and report["unassigned_charges"] == "0.012"
    assert report["unassigned_positive_charges"] == "0.014"
    assert report["unassigned_adjustments"] == "-0.002"
    assert Decimal(report["imported_charges"]) == Decimal(report["linked_charges"]) + Decimal(report["unassigned_charges"])
    comparison = report["comparisons"][0]
    assert comparison["calls"] == 2 and comparison["tasks"] == 1
    assert comparison["comparable_estimate_usd"] == "0.0001295" and comparison["difference_usd"] == "0.000018"
    assert report["provenance"]["submitted_sha256"] and report["billing_snapshot"]["schema"] == "workbench.billing.cur.v1"
    assert pilot.client.get("/api/pilot/usage").json()["events"] == 0
    real = billing.import_report(pilot.db, pilot.team, upload(), "admin")
    value = BillingMapping.model_validate({k: comparison[k] for k in BillingMapping.model_fields})
    billing.add_mapping(pilot.db, pilot.team, real["id"], value, "admin")
    assert billing.reconcile(pilot.db, pilot.team, real["id"])["comparisons"][0]["calls"] == 0
    with pilot.db.engine.connect() as db:
        assert all(json.loads(v)["invoice_usd"] is None for v in db.execute(select(events.c.accounting)).scalars())


def test_refresh_replaces_not_appends_and_retains_history_and_mapping(pilot):
    identity, mapping = mapped(pilot)
    initial = billing.reconcile(pilot.db, pilot.team, identity)
    body = upload(changes={"lineItem/UnblendedCost": "1"}, expected_revision=1)
    assert billing.preview(pilot.db, pilot.team, body)["expected_revision"] == 1
    revised = billing.import_report(pilot.db, pilot.team, body, "admin")
    assert revised["revision"] == 2 and revised["id"] != identity
    current = billing.reconcile(pilot.db, pilot.team, revised["id"])
    assert current["imported_charges"] == "5"  # complete replacement, not 5 + old charges
    assert current["comparisons"][0]["carried_from_revision"] == 1
    assert not billing.reconcile(pilot.db, pilot.team, identity)["current"]
    assert billing.reconcile(pilot.db, pilot.team, identity)["imported_charges"] == initial["imported_charges"]
    assert billing.list_reports(pilot.db, pilot.team)["reports"][0]["id"] == revised["id"]
    assert billing.import_report(pilot.db, pilot.team, body, "admin")["unchanged"]
    with pytest.raises(Conflict, match="superseded"):
        billing.import_report(pilot.db, pilot.team, upload(), "admin")
    with pytest.raises(Conflict, match="after preview"):
        billing.import_report(pilot.db, pilot.team, upload(changes={"lineItem/UnblendedCost": "2"}), "admin")
    with pytest.raises(Conflict, match="historical"):
        billing.add_mapping(pilot.db, pilot.team, identity, mapping, "admin")
    fresh = create_pilot_app(pilot.settings)
    assert billing.reconcile(fresh.state.database, pilot.team, revised["id"])["fingerprint"] == current["fingerprint"]


def test_groups_and_captured_scope_cannot_be_counted_twice(pilot):
    identity, mapping = mapped(pilot)
    with pytest.raises(Conflict, match="already linked"):
        billing.add_mapping(pilot.db, pilot.team, identity, mapping, "admin")
    report = billing.reconcile(pilot.db, pilot.team, identity)
    old_id = report["comparisons"][0]["id"]
    billing.remove_mapping(pilot.db, pilot.team, identity, old_id, "admin")
    single = mapping.model_copy(update={"group_ids": mapping.group_ids[:1]})
    billing.add_mapping(pilot.db, pilot.team, identity, single, "admin")
    with pytest.raises(Conflict, match="captured-call scope"):
        billing.add_mapping(pilot.db, pilot.team, identity,
                            mapping.model_copy(update={"group_ids": mapping.group_ids[1:]}), "admin")
    other = billing.import_report(pilot.db, pilot.team,
        upload(changes={"lineItem/UsageAccountId": "111111111111"}, account_id="111111111111"), "admin")
    with pytest.raises(Conflict, match="another AWS account"):
        billing.add_mapping(pilot.db, pilot.team, other["id"], single, "admin")


@pytest.mark.parametrize("case", ["absent", "unknown", "incomplete", "retention", "wrong-mode"])
def test_incomplete_capture_has_no_comparable_total_or_variance(pilot, case):
    usage = False if case == "absent" else event()
    if case == "unknown":
        usage = event(usage=None, usage_basis="unknown")
    if case == "incomplete":
        usage = event(attempt_coverage="final_response_only",
            bedrock=event().bedrock.model_copy(update={"sdk_retry_count": 1}))
    if case == "wrong-mode":
        usage = event(bedrock=event().bedrock.model_copy(update={"performance": "optimized"}))
    identity, mapping = mapped(pilot, usage=usage)
    if case == "retention":
        with pilot.db.engine.begin() as db:
            db.execute(insert(maintenance).values(id="retention_cutoff",
                payload=json.dumps({"occurred_before": "2026-10-02T00:00:00+00:00"}), updated_at=1))
    report = billing.reconcile(pilot.db, pilot.team, identity)
    value = report["comparisons"][0]
    assert value["status"] == "incomplete" and value["comparable_estimate_usd"] is None
    assert value["difference_usd"] is None and value["limitations"]
    if case in ("absent", "wrong-mode"):
        assert report["linked_charges"] == "0"
        assert report["unassigned_charges"] == report["imported_charges"]


def test_non_usd_and_net_zero_adjustment_groups_remain_visible(pilot):
    data = upload(currency="EUR", changes={"lineItem/CurrencyCode": "EUR"})
    source = pilot.db.create_source(pilot.team, "Euro", "admin", kind="bedrock")
    record = billing.import_report(pilot.db, pilot.team, data, "admin")
    report = billing.reconcile(pilot.db, pilot.team, record["id"])
    assert report["currency"] == "EUR" and report["unassigned_charges"] == report["imported_charges"]
    with pytest.raises(BillingError, match="currency"):
        billing.add_mapping(pilot.db, pilot.team, record["id"], BillingMapping(
            name="No FX", group_ids=[g["id"] for g in report["groups"] if g["eligible"]],
            source_ids=[source], model="m", region="us-east-1", service_tier="default",
            performance="standard", account_binding_confirmed=True), "admin")
    row = list(csv.DictReader(io.StringIO(upload().files[0])))[0]
    rows = [row | {"identity/LineItemId": str(i), "lineItem/UnblendedCost": cost}
            for i, cost in enumerate(["3.125", "-3.125"])]
    grouped = groups(parse_upload(upload(rows=rows))["snapshot"])[0]
    assert grouped["charge_amount"] == "0" and not grouped["eligible"]
    assert grouped["positive_charges"] == "3.125" and grouped["negative_adjustments"] == "-3.125"

def test_zero_usage_and_removed_groups_on_refresh(pilot):
    from workbench.pilot.events import BedrockUsage
    identity, mapping = mapped(pilot, usage=event(
        usage=BedrockUsage(input_tokens=0, output_tokens=0, total_tokens=0)))
    report = billing.reconcile(pilot.db, pilot.team, identity)
    assert report["comparisons"][0]["comparable_estimate_usd"] == "0"
    assert report["comparisons"][0]["difference_usd"] == "0.0001475"
    body = upload(expected_revision=1)
    rows = list(csv.DictReader(io.StringIO(body.files[0])))
    refreshed = billing.import_report(pilot.db, pilot.team,
        upload(rows=[r for r in rows if "OutputTokens" not in r["lineItem/UsageType"]], expected_revision=1), "admin")
    assert billing.reconcile(pilot.db, pilot.team, refreshed["id"])["comparisons"] == []


def test_access_csrf_team_scope_body_limits_and_safe_validation(pilot):
    identity, mapping = mapped(pilot)
    base = f"/api/pilot/billing/reports/{identity}"
    for role in ("viewer", "analyst"):
        password = secrets.token_urlsafe(24)
        pilot.client.post("/api/pilot/users", json={"username": role, "password": password, "role": role})
        with TestClient(pilot.app, base_url=pilot.settings.public_origin) as member:
            login = member.post("/api/auth/login", json={"username": role, "password": password})
            member.headers["X-Workbench-CSRF"] = login.json()["csrf"]
            assert member.get(base).status_code == 200
            assert member.get(base + "/export").status_code == 200
            for path, payload in (("/api/pilot/billing/imports", upload().model_dump()),
                ("/api/pilot/billing/preview", upload().model_dump()), ("/api/pilot/billing/example", {}),
                (base + "/mappings", mapping.model_dump()), (base + "/mappings/missing/remove", {})):
                assert member.post(path, json=payload).status_code == 403
    with TestClient(pilot.app, base_url=pilot.settings.public_origin) as anonymous:
        assert anonymous.get(base).status_code == 401
    assert pilot.client.post("/api/pilot/billing/imports", json=upload().model_dump(),
                             headers={"X-Workbench-CSRF": ""}).status_code == 403
    assert pilot.client.post("/api/pilot/billing/preview", content=b" " * 16_500_001,
                             headers={"Content-Type": "application/json"}).status_code == 413
    invalid = pilot.client.post("/api/pilot/billing/imports", json=upload().model_dump() |
                                {"account_id": "private-value", "team_id": "private-value"})
    assert invalid.status_code == 422 and "private-value" not in invalid.text
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other, name="Other"))
    foreign = billing.import_report(pilot.db, other, upload(), "operator")
    assert pilot.client.get(f"/api/pilot/billing/reports/{foreign['id']}").status_code == 404
    source = pilot.db.create_source(other, "Foreign", "operator", kind="bedrock")
    fresh = billing.import_report(pilot.db, pilot.team,
        upload(changes={"lineItem/UsageAccountId": "222222222222"}, account_id="222222222222"), "admin")
    with pytest.raises(BillingError, match="this team"):
        billing.add_mapping(pilot.db, pilot.team, fresh["id"],
                            mapping.model_copy(update={"source_ids": [source]}), "admin")


def test_schema_three_migration_and_financial_retention(pilot):
    identity, mapping = mapped(pilot)
    with pilot.db.engine.begin() as db:
        before = [dict(r) for r in db.execute(select(events)).mappings()]
        before_facts = [dict(r) for r in db.execute(select(facts)).mappings()]
        db.execute(update(schema).values(version=3))
        # Simulate the previous release: no new billing tables.
        for table in (billing_mappings, billing_reports, billing_bindings, billing_families):
            table.drop(db)
    pilot.db.migrate()
    with pilot.db.engine.connect() as db:
        assert db.execute(select(schema.c.version)).scalars().all() == [4]
        assert [dict(r) for r in db.execute(select(events)).mappings()] == before
        assert [dict(r) for r in db.execute(select(facts)).mappings()] == before_facts
        assert db.execute(select(collectors)).all() == []
    record = billing.import_report(pilot.db, pilot.team, upload(), "admin")
    billing.add_mapping(pilot.db, pilot.team, record["id"], mapping, "admin")
    now = int(time.time())
    with pilot.db.engine.begin() as db:
        db.execute(update(billing_reports).values(created_at=now-10*86400))
    policy = replace(pilot.settings, retention_days=0, evidence_retention_days=5)
    preview = run_once(pilot.db, policy, dry_run=True, now=now)
    assert preview["eligible_billing_reports"] == 1 and preview["deleted_billing_reports"] == 0
    result = run_once(pilot.db, policy, now=now)
    assert result["deleted_billing_reports"] == 1
    with pilot.db.engine.connect() as db:
        assert not db.execute(select(billing_reports)).all()
        assert not db.execute(select(billing_mappings)).all()
        assert not db.execute(select(billing_families)).all()
        assert db.execute(select(billing_bindings)).first()  # account configuration persists
        assert [dict(r) for r in db.execute(select(events)).mappings()] == before


def test_postgres_concurrent_import_refresh_and_mapping(pilot):
    if pilot.db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock contract")
    def attempt(body):
        try:
            return billing.import_report(pilot.db, pilot.team, body, "admin")
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = list(pool.map(attempt, [upload(), upload()]))
    assert len({r["id"] for r in first}) == 1
    assert sorted(r["unchanged"] for r in first) == [False, True]
    bodies = [upload(expected_revision=1, changes={"lineItem/UnblendedCost": cost}) for cost in ("1", "2")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        refreshed = list(pool.map(attempt, bodies))
    assert sum(r == "conflict" for r in refreshed) == 1
    identity = next(r["id"] for r in refreshed if isinstance(r, dict))
    source = pilot.db.create_source(pilot.team, "Race", "admin", kind="bedrock")
    report = billing.reconcile(pilot.db, pilot.team, identity)
    value = BillingMapping(name="Race", group_ids=[g["id"] for g in report["groups"]
        if g["eligible"] and g["region"] == "us-east-1"], source_ids=[source],
        model="amazon.nova-micro-v1:0", region="us-east-1", service_tier="default",
        performance="standard", account_binding_confirmed=True)
    def link(_):
        try:
            billing.add_mapping(pilot.db, pilot.team, identity, value, "admin")
            return "created"
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(link, range(2))) == ["conflict", "created"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        examples = list(pool.map(lambda _: load_example(pilot.db, pilot.team, "admin"), range(2)))
    assert len({value["id"] for value in examples}) == 1
    assert len(billing.reconcile(pilot.db, pilot.team, examples[0]["id"])["comparisons"]) == 1


def test_postgres_billing_does_not_block_unrelated_audit_transaction(pilot):
    if pilot.db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL foreign-key lock contract")
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with pilot.db.engine.begin() as db:
            # Inserting a referencing audit holds KEY SHARE on its team until
            # commit. Billing must finish while that audit is still uncommitted.
            pilot.db.audit(db, pilot.team, "admin", "test.unrelated", "fixture")
            imported = pool.submit(billing.import_report, pilot.db, pilot.team, upload(), "admin")
            assert imported.result(timeout=3)["revision"] == 1
            maintained = pool.submit(run_once, pilot.db, pilot.settings, dry_run=True)
            assert maintained.result(timeout=3)["status"] == "preview"
    finally:
        pool.shutdown(wait=True)
