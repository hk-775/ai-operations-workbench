"""Write an explicitly fictional Bedrock billing bundle and verify its controls."""
import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from workbench.billing import parse_upload, total
from workbench.billing_acceptance import Controls, check
from workbench.pilot.billing import reconcile
from workbench.pilot.billing_example import example_upload, load_example
from workbench.pilot.database import Database, events, teams


def main():
    output = ROOT / "data/billing-sample"
    output.mkdir(exist_ok=True)
    upload = example_upload()
    (output / "legacy-cur.csv").write_text(upload.files[0], newline="")
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
        "bill/InvoiceId": "bill_invoice_id", "product/regionCode": "product_region_code",
        "product/modelId": "product_model_id", "workbench_evidence": "workbench_evidence",
    }
    rows = [{columns[key]: value for key, value in row.items()} for row in csv.DictReader(io.StringIO(upload.files[0]))]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns.values()))
    writer.writeheader()
    writer.writerows(rows)
    (output / "cur-2.0.csv").write_text(stream.getvalue(), newline="")
    expected = {
        "evidence": "fixture", "account_id": "000000000000", "month": "2026-10",
        "currency": "USD", "imported_charges": "0.0121475", "positive_charges": "0.0141475",
        "negative_adjustments": "-0.002", "row_count": 5, "captured_calls": 2,
        "comparable_estimate_usd": "0.0001295", "linked_charges": "0.0001475",
        "unassigned_charges": "0.012", "charges_minus_estimate": "0.000018",
    }
    with tempfile.TemporaryDirectory(prefix="workbench-billing-sample-") as directory:
        db = Database(f"sqlite:///{Path(directory)/'sample.db'}")
        try:
            db.migrate()
            team = "00000000-0000-0000-0000-000000000001"
            with db.engine.begin() as connection:
                connection.execute(teams.insert().values(id=team, name="Fictional sample"))
            result = load_example(db, team, "fixture-builder")
            export = reconcile(db, team, result["id"], export=True)
            with db.engine.connect() as connection:
                usage = [json.loads(row.payload) for row in connection.execute(select(events.c.payload))]
            controls = Controls(**{key: expected[key] for key in (
                "imported_charges", "positive_charges", "negative_adjustments", "row_count",
                "captured_calls", "comparable_estimate_usd")}, reviewer="Authored fixture controls")
            receipt = check(upload, export, controls, fixture=True)
            second = upload.model_copy(update={"format": "cur-2.0", "files": [stream.getvalue()]})
            assert parse_upload(second, fixture=True)["snapshot"] == export["billing_snapshot"]
            assert export["comparisons"][0]["difference_usd"] == expected["charges_minus_estimate"]
            assert load_example(db, team, "fixture-builder")["unchanged"]
        finally:
            db.engine.dispose()
    for name, value in (("matching-usage.json", {"evidence": "fixture", "model_calls_made": 0, "events": usage}),
                        ("expected-totals.json", expected), ("sample-check.json", receipt)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    archive = ROOT / "artifacts/bedrock-billing-sample.zip"
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.iterdir()):
            if path.is_file():
                bundle.write(path, arcname="bedrock-billing-sample/" + path.name)
    print("Created fictional Legacy CUR and CUR 2.0 CSVs, matching usage, expected totals, and a verified sample receipt.")
    print(archive)


if __name__ == "__main__":
    main()
