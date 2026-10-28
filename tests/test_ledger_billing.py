"""Exercise the real pinned Ledger package with lossless billing projections."""
import copy
import csv
import io
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from workbench.billing import BillingError, groups, parse_upload
from workbench.ledger_billing import AggregationEngine, LedgerBillingSnapshot
from workbench.pilot import billing
from test_billing import upload
from test_pilot import pilot, settings


def test_unattributed_credits_and_prior_usage_stay_in_billing_period():
    rows = list(csv.DictReader(io.StringIO(upload().files[0])))
    for row in rows:
        row["lineItem/UsageAmount"] = "0.0001"
        row["pricing/unit"] = "requests"
        row["lineItem/UsageStartDate"] = "2026-09-01T00:00:00Z"
        row["lineItem/UsageEndDate"] = "2026-09-02T00:00:00Z"
    rows[-1]["lineItem/UsageStartDate"] = ""
    rows[-1]["lineItem/UsageEndDate"] = ""
    snapshot = parse_upload(upload(rows=rows))["snapshot"]
    before = copy.deepcopy(snapshot)
    ledger = LedgerBillingSnapshot(snapshot)
    assert ledger.total() == "0.0121475"
    assert ledger.total(sign=1) == "0.0141475"
    assert ledger.total(sign=-1) == "-0.002"
    assert len(ledger.records) == 5
    assert all(record.userId == record.modelId == "" for record in ledger.records)
    assert all(record.usageStartDate == ledger.period.start for record in ledger.records)
    assert snapshot == before  # Actual usage dates/quantities stay in the source evidence.
    assert all(group["quantity"] == "0.0001" for group in groups(snapshot, ledger=ledger))
    assert ledger.evidence()["budgets_reconciliation"] == "not_connected"
    assert ledger.evidence()["usage_counts"] == "not_exposed_from_billing_projection"


def test_ledger_preserves_fine_precision_foreign_currency_and_partition_signs():
    rows = list(csv.DictReader(io.StringIO(upload().files[0])))[:3]
    amounts = ["999999999999.123456789012345678",
               "999999999999.123456789012345678", "-0.000000000000000001"]
    for row, amount in zip(rows, amounts):
        row["lineItem/UnblendedCost"] = amount
        row["lineItem/CurrencyCode"] = "EUR"
    with localcontext() as context:
        context.prec = 6  # Caller precision must not truncate the billing engine.
        snapshot = parse_upload(upload(rows=rows, currency="EUR"))["snapshot"]
        ledger = LedgerBillingSnapshot(snapshot)
        assert ledger.total() == "1999999999998.246913578024691355"
        assert ledger.total(sign=1) == "1999999999998.246913578024691356"
        assert ledger.total(sign=-1) == "-0.000000000000000001"
        assert ledger.total([]) == "0"
        assert ledger.evidence()["currency"] == "EUR"
        assert context.prec == 6
    with pytest.raises(BillingError, match="partition"):
        ledger.total(["missing"])


def test_real_ledger_engine_drives_preview_report_listing_and_export(pilot, monkeypatch):
    calls = []
    aggregate = AggregationEngine.aggregate_by_account
    def observed(self, period):
        calls.append(len(self._records))
        return aggregate(self, period)
    monkeypatch.setattr(AggregationEngine, "aggregate_by_account", observed)
    preview = billing.preview(pilot.db, pilot.team, upload())
    assert calls and preview["billing_engine"]["name"] == "AxonLLM Ledger"
    assert preview["imported_charges"] == "0.0121475"
    calls.clear()
    first = pilot.client.post("/api/pilot/billing/example", json={}).json()
    report = pilot.client.get(f"/api/pilot/billing/reports/{first['id']}/export").json()
    assert calls and report["billing_engine"]["row_count"] == 5
    assert report["provenance"]["billing_engine"] == report["billing_engine"]
    assert report["imported_charges"] == "0.0121475"
    assert report["linked_charges"] == "0.0001475"
    assert report["unassigned_adjustments"] == "-0.002"
    assert report["comparisons"][0]["difference_usd"] == "0.000018"
    assert report["comparisons"][0]["calls"] == 2
    assert pilot.db.usage(pilot.team)["events"] == 0
    calls.clear()
    listed = billing.list_reports(pilot.db, pilot.team)
    assert calls and listed["reports"][0]["charges"] == report["imported_charges"]
    assert Decimal(report["linked_charges"]) + Decimal(report["unassigned_charges"]) == Decimal(report["imported_charges"])


def test_ledger_integrity_failure_cannot_replace_last_accepted_snapshot(pilot, monkeypatch):
    first = billing.import_report(pilot.db, pilot.team, upload(), "test")
    monkeypatch.setattr(
        "workbench.ledger_billing.DataIntegrityService.validate_cross_dimension_consistency",
        lambda *_: SimpleNamespace(is_consistent=False),
    )
    response = pilot.client.post("/api/pilot/billing/imports", json=upload(
        expected_revision=1, changes={"lineItem/UnblendedCost": "1"}
    ).model_dump())
    assert response.status_code == 422
    assert "Ledger billing integrity check failed." in response.text
    with pytest.raises(BillingError, match="Ledger billing integrity"):
        billing.import_report(pilot.db, pilot.team, upload(
            expected_revision=1, changes={"lineItem/UnblendedCost": "1"}
        ), "test")
    monkeypatch.undo()
    reports = billing.list_reports(pilot.db, pilot.team)["reports"]
    assert len(reports) == 1 and reports[0]["id"] == first["id"] and reports[0]["revision"] == 1
