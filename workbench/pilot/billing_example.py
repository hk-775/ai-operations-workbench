"""An explicitly requested fictional billing example; zero provider calls."""
import csv
import io
import json
import time

from sqlalchemy import insert, select

from workbench.billing import BillingError, BillingMapping, BillingUpload, groups, parse_upload
from workbench.domain import digest
from .billing import add_mapping, import_report, mapping_rows
from .database import Conflict, maintenance, sources, teams, uid
from .events import BedrockContext, BedrockUsage, BedrockUsageEvent
from .maintenance import save

HEADERS = [
    "identity/LineItemId", "identity/TimeInterval", "lineItem/ProductCode",
    "lineItem/UsageAccountId", "bill/BillingPeriodStartDate", "bill/BillingPeriodEndDate",
    "lineItem/CurrencyCode", "lineItem/LineItemType", "lineItem/UsageStartDate",
    "lineItem/UsageEndDate", "lineItem/UsageType", "lineItem/Operation",
    "lineItem/UsageAmount", "lineItem/UnblendedCost", "lineItem/NetUnblendedCost",
    "product/regionCode", "product/modelId", "pricing/unit", "bill/InvoiceId",
    "workbench_evidence",
]


def example_upload():
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=HEADERS)
    writer.writeheader()
    for identity, kind, usage_type, region, quantity, cost in (
        ("input", "Usage", "Synthetic-NovaMicro-InputTokens", "us-east-1", "2500", "0.0000875"),
        ("output", "Usage", "Synthetic-NovaMicro-OutputTokens", "us-east-1", "300", "0.0000600"),
        ("unlinked", "Usage", "Synthetic-OtherModel-Tokens", "us-west-2", "100", "0.004"),
        ("fee", "Fee", "Synthetic-ServiceFee", "", "", "0.01"),
        ("credit", "Credit", "Synthetic-Credit", "", "", "-0.002"),
    ):
        writer.writerow({
            "identity/LineItemId": "billing-example-" + identity,
            "identity/TimeInterval": "2026-10-01T00:00:00Z/2026-11-01T00:00:00Z",
            "lineItem/ProductCode": "AmazonBedrock", "lineItem/UsageAccountId": "000000000000",
            "bill/BillingPeriodStartDate": "2026-10-01T00:00:00Z",
            "bill/BillingPeriodEndDate": "2026-11-01T00:00:00Z",
            "lineItem/CurrencyCode": "USD", "lineItem/LineItemType": kind,
            "lineItem/UsageStartDate": "2026-10-27T00:00:00Z",
            "lineItem/UsageEndDate": "2026-10-28T00:00:00Z",
            "lineItem/UsageType": usage_type, "lineItem/Operation": "SyntheticInference",
            "lineItem/UsageAmount": quantity, "lineItem/UnblendedCost": cost,
            "product/regionCode": region, "product/modelId": "Synthetic model display name",
            "pricing/unit": "Tokens" if quantity else "", "workbench_evidence": "fixture",
        })
    return BillingUpload(format="legacy-cur", account_id="000000000000", month="2026-10",
                         currency="USD", name="Fictional Bedrock bill · October",
                         files=[stream.getvalue()], complete_snapshot=True)


def load_example(database, team, actor):
    marker_id = "bill_example_" + digest(team)[:27]
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == team).with_for_update(key_share=True)).one()
        cutoff = db.execute(select(maintenance.c.payload).where(
            maintenance.c.id == "retention_cutoff")).scalar_one_or_none()
        if cutoff and json.loads(cutoff)["occurred_before"] > "2026-10-27T00:00:00+00:00":
            raise BillingError("The historical example is outside usage retention. Explore it in a local test workspace.")
        marker = db.execute(select(maintenance.c.payload).where(
            maintenance.c.id == marker_id)).scalar_one_or_none()
        if marker:
            source_id = json.loads(marker)["source_id"]
        else:
            source_id = uid()
            db.execute(insert(sources).values(id=source_id, team_id=team,
                name="Billing example · synthetic " + source_id[:8], kind="bedrock",
                created_at=int(time.time())))
            save(db, marker_id, {"source_id": source_id}, int(time.time()))
        batch = []
        for stage, inputs, outputs in (("classify", 1000, 100), ("draft", 1500, 200)):
            batch.append(BedrockUsageEvent(
                schema_version="bedrock.usage.v1", event_id="billing-example-v1:" + stage,
                task_id="billing-example-v1", project="billing-example", stage=stage,
                model="amazon.nova-micro-v1:0", occurred_at="2026-10-27T00:00:00Z",
                status="success", evidence="fixture", usage_basis="provider_reported",
                attempt_coverage="single_attempt", latency_ms=100.0,
                usage=BedrockUsage(input_tokens=inputs, output_tokens=outputs, total_tokens=inputs + outputs),
                bedrock=BedrockContext(region="us-east-1", operation="Converse",
                    service_tier="default", performance="standard", additional_charges=False,
                    sdk_retry_count=0),
            ))
        database._ingest(db, team, source_id, batch)
    upload = example_upload()
    imported = import_report(database, team, upload, actor, fixture=True)
    with database.engine.connect() as db:
        mapped = mapping_rows(db, imported["id"])
    if not mapped:
        selected = [g["id"] for g in groups(parse_upload(upload, fixture=True)["snapshot"])
                    if g["eligible"] and g["region"] == "us-east-1"]
        value = BillingMapping(
            name="Fictional two-call task", group_ids=selected, source_ids=[source_id],
            model="amazon.nova-micro-v1:0", region="us-east-1", service_tier="default",
            performance="standard", account_binding_confirmed=True,
        )
        try:
            add_mapping(database, team, imported["id"], value, actor)
        except Conflict:
            # A concurrent request can finish the same idempotent example after
            # our initial read. Only accept an exact existing mapping.
            with database.engine.connect() as db:
                matched = any(row["mapping"] == value.model_dump()
                              for row in mapping_rows(db, imported["id"]))
            if not matched:
                raise
    return imported | {"evidence": "fixture", "model_calls": 0}
