"""AxonLLM Ledger cost aggregation over a lossless billing-period projection.

The projection is private to this adapter: empty identities stay unattributed,
and token/invocation placeholders never become operational usage or an export.
Original usage dates and units remain in Workbench's immutable billing snapshot.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
from importlib.metadata import version

from axonllm_ledger.aggregation import AggregationEngine, TimeRange
from axonllm_ledger.data_integrity import DataIntegrityService
from axonllm_ledger.models import UsageRecord

from .billing import BillingError, decimal_text, fingerprint

LEDGER_VERSION = version("axonllm-ledger")


class _LocalIntegrityFailure:
    def send_alert(self, *, subject, message):
        # No external notification or imported values in the API error.
        raise BillingError("Ledger billing integrity check failed.")


class LedgerBillingSnapshot:
    """Aggregate accepted charge rows without invoking Ledger's lossy importer."""

    def __init__(self, snapshot):
        self.account = snapshot["account_id"]
        self.currency = snapshot["currency"]
        self.period = TimeRange(
            start=datetime.fromisoformat(snapshot["period_start"]),
            end=datetime.fromisoformat(snapshot["period_end"]),
        )
        self.by_group = {}
        self.records = []
        source = fingerprint(snapshot)
        for row in snapshot["rows"]:
            record = UsageRecord(
                recordId=fingerprint([source, row["line_id"], row["identity_interval"],
                                      row["usage_start"], row["usage_end"]]),
                lineItemId=row["line_id"], accountId=self.account,
                userId="", modelId="", serviceName="AmazonBedrock",
                # Roll up the billing month, including fees/credits that lack
                # usage dates or adjust usage in an earlier month.
                usageStartDate=self.period.start, usageEndDate=self.period.end,
                inputTokens=0, outputTokens=0, invocationCount=0,
                cost=Decimal(row["amount"]), ingestedAt=self.period.start,
                sourceExportId=source,
            )
            self.records.append(record)
            self.by_group.setdefault(row["group_id"], []).append(record)
        with localcontext() as context:
            context.prec = 50
            check = DataIntegrityService(
                AggregationEngine(self.records), _LocalIntegrityFailure()
            ).validate_cross_dimension_consistency(self.period)
            if not check.is_consistent or check.account_total != sum(
                (record.cost for record in self.records), Decimal("0")
            ):
                raise BillingError("Ledger billing integrity check failed.")
        self._cache = {}

    def total(self, group_ids=None, *, sign=0):
        """Return only Ledger's cost, never its placeholder usage counters."""
        selected = None if group_ids is None else frozenset(group_ids)
        key = selected, sign
        if key in self._cache:
            return self._cache[key]
        if sign not in (-1, 0, 1) or (
            selected is not None and not selected <= self.by_group.keys()
        ):
            raise BillingError("Invalid Ledger billing partition.")
        records = self.records if selected is None else [
            record for group in sorted(selected) for record in self.by_group[group]
        ]
        if sign:
            records = [record for record in records
                       if (record.cost > 0 if sign == 1 else record.cost < 0)]
        with localcontext() as context:
            context.prec = 50
            values = AggregationEngine(records).aggregate_by_account(self.period)
            if len(values) != bool(records) or (values and values[0].dimension_value != self.account):
                raise BillingError("Ledger returned an inconsistent billing account.")
            amount = values[0].total_cost if values else Decimal("0")
            if not amount.is_finite():
                raise BillingError("Ledger returned a non-finite billing total.")
            result = decimal_text(amount)
        self._cache[key] = result
        return result

    def evidence(self):
        return {
            "name": "AxonLLM Ledger", "version": LEDGER_VERSION,
            "contract": "workbench.ledger.billing-costs.v1",
            "row_count": len(self.records), "currency": self.currency,
            "integrity": "account_and_unattributed_totals_match",
            "time_basis": "billing_period",
            "usage_counts": "not_exposed_from_billing_projection",
            "budgets_reconciliation": "not_connected",
        }
