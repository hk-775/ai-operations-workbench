"""Lossless financial values and bounded, explicit AWS billing snapshots.

Ledger supplies schema aliases, billed-cost aggregation and integrity checks.
Workbench preserves every charge before adapting it to Ledger's cost engine;
billing units are not converted into captured tokens.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from axonllm_ledger.cost_normalization import normalize_cost_row
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

MAX_ROWS = 20_000
MAX_BYTES = 8_000_000
MAX_GROUPS = 500


class BillingError(ValueError):
    """A safe, authored error; never include imported cell contents."""


class BillingUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["legacy-cur", "cur-2.0"]
    account_id: str = Field(pattern=r"^[0-9]{12}$")
    month: str = Field(pattern=r"^20[0-9]{2}-(0[1-9]|1[0-2])$")
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    files: list[str] = Field(min_length=1, max_length=20)
    complete_snapshot: Literal[True]
    expected_revision: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("files")
    @classmethod
    def bounded_files(cls, value):
        if sum(len(item.encode("utf-8")) for item in value) > MAX_BYTES:
            raise ValueError("Billing upload exceeds the byte limit")
        return value


class BillingMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    group_ids: list[str] = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=2048)
    region: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")
    service_tier: Literal["default", "priority", "flex", "reserved"]
    performance: Literal["standard", "optimized"]
    account_binding_confirmed: Literal[True]

    @field_validator("group_ids", "source_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value) or any(
            not re.fullmatch(r"[a-f0-9-]{32,64}", item) for item in value
        ):
            raise ValueError("Invalid or repeated identifier")
        return sorted(value)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decimal_text(value: Decimal) -> str:
    # Keep every accepted decimal place; normalize negative zero as well.
    return format(value, "f").rstrip("0").rstrip(".") if value and "." in format(value, "f") else (
        format(value, "f") if value else "0")


def financial(value, *, optional=False):
    if value in ("", None):
        if optional:
            return None
        raise BillingError("A Bedrock row is missing a monetary value.")
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(
        r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value.strip()
    ):
        raise BillingError("Billing values must be finite decimal text.")
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        raise BillingError("A billing row has an invalid decimal value.") from None
    if not number.is_finite() or number.copy_abs() >= Decimal("1000000000000"):
        raise BillingError("A billing value is non-finite or outside the supported range.")
    # Retain precision finer than the operational ledger's nanodollars.
    if number.as_tuple().exponent < -18:
        raise BillingError("Billing values support up to 18 decimal places.")
    return decimal_text(number)


def total(values):
    with localcontext() as context:
        context.prec = 50
        return decimal_text(sum((Decimal(v) for v in values), Decimal(0)))


def difference(left, right):
    with localcontext() as context:
        context.prec = 50
        return decimal_text(Decimal(left) - Decimal(right))


def text(value, limit=300):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or any(
        ord(c) < 32 or ord(c) == 127 for c in value
    ):
        raise BillingError("A billing metadata field is invalid or too long.")
    return value.strip()


def pick(row, *keys):
    return next((row[k] for k in keys if row.get(k) not in ("", None)), "")


def utc(value, *, optional=False):
    if not value and optional:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        # AWS CUR/Athena timestamps are UTC, including projected CSV timestamps
        # with no suffix. Never interpret them in the application host's timezone.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise BillingError("A billing timestamp is invalid.") from None


def period(month):
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    end = start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)
    return start.isoformat(), end.isoformat()


def parse_upload(upload: BillingUpload, *, fixture=False):
    start, end = period(upload.month)
    rows, identities, outside_scope, repeated = [], {}, 0, 0
    submitted = []
    for content in upload.files:
        submitted.append(hashlib.sha256(content.encode("utf-8")).hexdigest())
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff"), newline=""), strict=True)
        try:
            headers = reader.fieldnames
            if not headers or len(headers) > 400 or len(set(headers)) != len(headers):
                raise BillingError("CSV headers are missing, repeated, or exceed 400 columns.")
            required = ({"identity/LineItemId", "lineItem/UnblendedCost",
                         "lineItem/UsageAccountId", "lineItem/CurrencyCode",
                         "bill/BillingPeriodStartDate", "bill/BillingPeriodEndDate",
                         "lineItem/LineItemType"} if upload.format == "legacy-cur" else
                        {"identity_line_item_id", "line_item_unblended_cost",
                         "line_item_usage_account_id", "line_item_currency_code",
                         "bill_billing_period_start_date", "bill_billing_period_end_date",
                         "line_item_line_item_type", "line_item_product_code"})
            if not required <= set(headers):
                raise BillingError("The selected CUR format is missing required billing columns.")
            if upload.format == "legacy-cur" and not (
                {"product/servicecode", "lineItem/ProductCode"} & set(headers)
            ):
                raise BillingError("Legacy CUR needs a service/product-code column.")
            for raw in reader:
                if len(rows) + outside_scope + repeated >= MAX_ROWS:
                    raise BillingError("Import at most 20,000 rows in one complete snapshot.")
                if None in raw or any(value is None for value in raw.values()):
                    raise BillingError("A CSV row does not match its header.")
                if raw.get("workbench_evidence") == "fixture" and not fixture:
                    raise BillingError("This is synthetic billing data. Use the billing example action.")
                normalized = normalize_cost_row(raw, schema=upload.format)
                product_code = pick(raw, "lineItem/ProductCode")
                normalized_service = normalized.get("product/servicecode")
                if product_code and normalized_service and product_code != normalized_service:
                    raise BillingError("Conflicting service/product codes occur in a billing row.")
                service = text(product_code or normalized_service, 100)
                if not service:
                    raise BillingError("A billing row is missing its service/product code; its scope cannot be established.")
                if service != "AmazonBedrock":
                    outside_scope += 1
                    continue
                account = text(normalized.get("lineItem/UsageAccountId"), 12)
                currency = text(pick(raw, "lineItem/CurrencyCode", "line_item_currency_code"), 3)
                bill_start = utc(pick(raw, "bill/BillingPeriodStartDate", "bill_billing_period_start_date"))
                bill_end = utc(pick(raw, "bill/BillingPeriodEndDate", "bill_billing_period_end_date"))
                if (account, currency, bill_start, bill_end) != (upload.account_id, upload.currency, start, end):
                    raise BillingError("Bedrock rows must match the selected account, currency and billing month.")
                # Read explicit original cost fields: Ledger aliases alone cannot
                # establish whether a value is net, unblended, or another basis.
                net = pick(raw, "lineItem/NetUnblendedCost", "line_item_net_unblended_cost")
                amount = financial(net if net != "" else pick(
                    raw, "lineItem/UnblendedCost", "line_item_unblended_cost"))
                kind = text(pick(raw, "lineItem/LineItemType", "line_item_line_item_type"), 80)
                line_id = text(normalized.get("identity/LineItemId"), 200)
                if not line_id or not kind:
                    raise BillingError("A Bedrock row needs a line identity and charge type.")
                product = raw.get("product", "") if upload.format == "cur-2.0" else ""
                try:
                    product = json.loads(product) if product else {}
                except (ValueError, TypeError, RecursionError):
                    raise BillingError("CUR 2.0 product maps must be JSON or projected into columns.") from None
                if not isinstance(product, dict):
                    raise BillingError("The CUR 2.0 product field must contain an object.")
                region = text(pick(raw, "product/regionCode", "product_region_code",
                                   "product_regioncode") or pick(product, "region_code", "regionCode"), 40)
                # The region/display-model text is retained, never translated
                # into an SDK model ID or inferred from a resource/profile ARN.
                dimensions = {
                    "charge_type": kind,
                    "usage_type": text(pick(raw, "lineItem/UsageType", "line_item_usage_type"), 200),
                    "operation": text(pick(raw, "lineItem/Operation", "line_item_operation"), 200),
                    "region": region,
                    "unit": text(pick(raw, "pricing/unit", "pricing_unit"), 80),
                    "sku": text(pick(raw, "product/sku", "product_sku") or product.get("sku"), 100),
                    "model_hint": text(pick(raw, "product/modelId", "product_model_id") or
                                       pick(product, "model_id", "modelId", "model"), 300),
                }
                usage_start = utc(normalized.get("lineItem/UsageStartDate"), optional=True)
                usage_end = utc(normalized.get("lineItem/UsageEndDate"), optional=True)
                if usage_start and usage_end and usage_start >= usage_end:
                    raise BillingError("A billing usage interval must have an exclusive end after its start.")
                row = {
                    "line_id": line_id,
                    "identity_interval": text(pick(raw, "identity/TimeInterval", "identity_time_interval"), 150),
                    "usage_start": usage_start, "usage_end": usage_end,
                    "amount": amount, "basis": "net_unblended" if net != "" else "unblended",
                    "quantity": financial(normalized.get("lineItem/UsageAmount"), optional=True),
                    "invoice_id": text(pick(raw, "bill/InvoiceId", "bill_invoice_id"), 150),
                    "dimensions": dimensions, "group_id": fingerprint(dimensions),
                }
                key = fingerprint([line_id, row["identity_interval"], usage_start, usage_end])
                if key in identities:
                    if identities[key] != row:
                        raise BillingError("Conflicting line identities occur within this snapshot; verify the report parts.")
                    repeated += 1
                    continue
                identities[key] = row
                rows.append(row)
        except (csv.Error, UnicodeError):
            raise BillingError("Unable to parse the UTF-8 CSV billing export.") from None
    rows.sort(key=canonical)
    if len({r["group_id"] for r in rows}) > MAX_GROUPS:
        raise BillingError("A snapshot supports at most 500 distinct billing groups.")
    snapshot = {
        "schema": "workbench.billing.cur.v1", "account_id": upload.account_id,
        "month": upload.month, "period_start": start, "period_end": end,
        "currency": upload.currency, "evidence": "fixture" if fixture else "imported",
        "cost_basis": "net_unblended_when_present_else_unblended",
        "rows": rows,
    }
    return {
        "snapshot": snapshot, "fingerprint": fingerprint(snapshot),
        "family_key": fingerprint([upload.account_id, upload.month, upload.currency, snapshot["evidence"]]),
        "submitted_sha256": submitted, "outside_bedrock_rows": outside_scope,
        "duplicate_rows": repeated, "name": upload.name.strip(),
    }


def groups(snapshot, *, ledger=None):
    from .ledger_billing import LedgerBillingSnapshot
    ledger = ledger if ledger is not None else LedgerBillingSnapshot(snapshot)
    result = {}
    for row in snapshot["rows"]:
        group = result.setdefault(row["group_id"], {
            "id": row["group_id"], **row["dimensions"], "quantities": [],
            "row_count": 0, "uninvoiced_rows": 0, "bases": set(), "eligible": True,
        })
        if row["quantity"] is not None:
            group["quantities"].append(row["quantity"])
        group["row_count"] += 1
        group["uninvoiced_rows"] += not bool(row["invoice_id"])
        group["bases"].add(row["basis"])
        group["eligible"] &= bool(
            row["dimensions"]["charge_type"] == "Usage" and Decimal(row["amount"]) >= 0
            and row["dimensions"]["region"] and row["usage_start"] and row["usage_end"]
            and snapshot["period_start"] <= row["usage_start"] < row["usage_end"] <= snapshot["period_end"]
        )
    for group in result.values():
        group["charge_amount"] = ledger.total([group["id"]])
        group["positive_charges"] = ledger.total([group["id"]], sign=1)
        group["negative_adjustments"] = ledger.total([group["id"]], sign=-1)
        quantities = group.pop("quantities")
        group["quantity"] = total(quantities) if len(quantities) == group["row_count"] else None
        group["bases"] = sorted(group["bases"])
        group["unassigned_reason"] = (
            "Choose the captured sources and exact model for this billing group."
            if group["eligible"] else
            "Adjustment, unsupported charge type, missing region, or usage outside this billing month."
        )
    return sorted(result.values(), key=lambda g: (g["charge_type"], g["usage_type"], g["id"]))
