import copy

import pytest

from test_billing import mapped, upload
from test_pilot import pilot, settings
from workbench.billing import BillingError
from workbench.billing_acceptance import Controls, check, write_private
from workbench.pilot import billing


def controls():
    return Controls(imported_charges="0.0121475", positive_charges="0.0141475",
                    negative_adjustments="-0.002", row_count=5, captured_calls=1,
                    comparable_estimate_usd="0.000049", reviewer="Fixture test reviewer")


def test_independent_controls_and_raw_export_integrity(pilot):
    identity, _ = mapped(pilot)
    exported = billing.reconcile(pilot.db, pilot.team, identity, export=True)
    receipt = check(upload(), exported, controls())
    assert receipt["status"] == "checks_passed" and receipt["captured_calls"] == 1
    assert "account_id" not in receipt and "imported_charges" not in receipt
    altered = controls().model_copy(update={"positive_charges": "0.01"})
    with pytest.raises(BillingError, match="Independent"):
        check(upload(), exported, altered)
    altered = copy.deepcopy(exported)
    altered["billing_snapshot"]["rows"][0]["amount"] = "0"
    with pytest.raises(BillingError, match="does not match"):
        check(upload(), altered, controls())
    altered = copy.deepcopy(exported)
    altered["unassigned_charges"] = "0"
    with pytest.raises(BillingError, match="unassigned"):
        check(upload(), altered, controls())


def test_absent_usage_cannot_pass_acceptance(pilot):
    identity, _ = mapped(pilot, usage=False)
    with pytest.raises(BillingError, match="pending"):
        check(upload(), billing.reconcile(pilot.db, pilot.team, identity, export=True), controls())


def test_private_receipt_replaces_permissive_file(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("old")
    path.chmod(0o644)
    write_private(path, {"status": "pending"})
    assert path.stat().st_mode & 0o777 == 0o600


def test_downloadable_sample_is_marked_and_matches_both_formats(pilot):
    import csv
    import io
    import json
    import zipfile
    from workbench.billing import BillingUpload, parse_upload
    from workbench.pilot.billing_example import example_upload, load_example
    response = pilot.client.get("/api/pilot/billing/example-files")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        legacy = bundle.read("bedrock-billing-sample/legacy-cur.csv").decode()
        cur2 = bundle.read("bedrock-billing-sample/cur-2.0.csv").decode()
        expected = json.loads(bundle.read("bedrock-billing-sample/expected-totals.json"))
        assert all(row["workbench_evidence"] == "fixture" for row in csv.DictReader(io.StringIO(legacy)))
    original = example_upload()
    a = original.model_copy(update={"files": [legacy]})
    b = original.model_copy(update={"files": [cur2], "format": "cur-2.0"})
    assert parse_upload(a, fixture=True)["snapshot"] == parse_upload(b, fixture=True)["snapshot"]
    with pytest.raises(BillingError, match="synthetic"):
        parse_upload(a)
    imported = load_example(pilot.db, pilot.team, "admin")
    exported = billing.reconcile(pilot.db, pilot.team, imported["id"], export=True)
    value = Controls(**{key: expected[key] for key in controls().model_dump() if key != "reviewer"},
                     reviewer="Sample controls")
    receipt = check(a, exported, value, fixture=True)
    assert receipt["status"] == "fixture_checks_passed"
    with pytest.raises(BillingError):
        check(a, exported, value)
