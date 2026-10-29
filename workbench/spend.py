"""Spend policies and declared allocation; original captured accounting is immutable."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import BigInteger, and_, cast, func, select

from workbench.domain import digest, money
from workbench.pilot.database import collectors, events, facts, maintenance, sources
from workbench.pilot.queries import json_text
from workbench.pilot.workflows import WorkflowError

BASIS_KINDS = {
    "api_estimate_usd": ("axonllm", "bedrock"),
    "reported_model_estimate_usd": ("claude_code", "cursor"),
    "reported_charge_usd": ("cursor",),
    "allocated_usd": (),
}
NANOS = Decimal(1_000_000_000)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Definition(Input):
    reference: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    active: bool = True
    evidence: Literal["declared", "fixture"] = "declared"


class MonthlyDefinition(Definition):
    month: str = Field(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")


def exact_amount(value):
    # Financial inputs must be decimal text, never binary floating-point numbers.
    if not isinstance(value, str) or len(value) > 30:
        raise ValueError("Use a decimal amount")
    import re
    if not re.fullmatch(r"(?:0|[1-9]\d{0,9})(?:\.\d{1,9})?", value):
        raise ValueError("Use a nonnegative decimal amount with at most nine decimal places")
    number = Decimal(value)
    if number > Decimal("1000000000"):
        raise ValueError("Amount exceeds the supported bound")
    return money(number)


class Budget(MonthlyDefinition):
    limit_usd: str
    cost_basis: Literal["api_estimate_usd", "reported_model_estimate_usd", "reported_charge_usd", "allocated_usd"]
    warning_percent: int = Field(default=80, ge=1, le=100)
    project: str | None = Field(default=None, min_length=1, max_length=100)
    source_id: str | None = Field(default=None, min_length=1, max_length=36)
    coverage_confirmed: bool = False

    @field_validator("limit_usd")
    @classmethod
    def amount(cls, value):
        result = exact_amount(value)
        if Decimal(result) == 0:
            raise ValueError("Budget must be positive")
        return result


class Share(Input):
    project: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    weight: int = Field(ge=1, le=1_000_000)


class Allocation(MonthlyDefinition):
    amount_usd: str
    category: Literal["subscription", "infrastructure", "human_review", "other"]
    reason: str = Field(min_length=1, max_length=500, pattern=r".*\S.*")
    shares: list[Share] = Field(min_length=1, max_length=100)

    @field_validator("amount_usd")
    @classmethod
    def amount(cls, value):
        return exact_amount(value)

    @model_validator(mode="after")
    def unique_projects(self):
        if len({share.project for share in self.shares}) != len(self.shares):
            raise ValueError("Each project can appear only once")
        return self


class BudgetChange(Input):
    value: Budget
    revision: int = Field(default=0, ge=0, le=1_000_000)


class AllocationChange(Input):
    value: Allocation
    revision: int = Field(default=0, ge=0, le=1_000_000)


def window(month):
    year, number = map(int, month.split("-"))
    start = datetime(year, number, 1, tzinfo=timezone.utc)
    end = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


def validate_scope(database, team, budget):
    if budget.source_id:
        source = database.source(team, budget.source_id)
        if not source:
            raise KeyError(budget.source_id)
        if source["kind"] not in BASIS_KINDS[budget.cost_basis]:
            raise WorkflowError("Choose a cost basis supported by this source")


def budget_status(database, team, budget, *, now=None, db=None):
    now = now or datetime.now(timezone.utc)
    if budget.cost_basis == "allocated_usd":
        return allocated_budget_status(database, team, budget, now=now)
    start, end = window(budget.month)
    before = min(end, max(start, now))
    where = [
        events.c.team_id == team,
        events.c.evidence == ("fixture" if budget.evidence == "fixture" else "observed"),
        events.c.occurred_at >= start.isoformat(), events.c.occurred_at < before.isoformat(),
        sources.c.kind.in_(BASIS_KINDS[budget.cost_basis]),
    ]
    if budget.source_id:
        where.append(events.c.source_id == budget.source_id)
    if budget.project:
        where.append(events.c.project == budget.project)
    if budget.cost_basis == "api_estimate_usd":
        value = facts.c.api_nanodollars
    else:
        value = cast(func.replace(json_text(database, events.c.accounting,
                                            budget.cost_basis), ".", ""), BigInteger)
    relation = events.join(facts, and_(events.c.source_id == facts.c.source_id,
                                      events.c.event_id == facts.c.event_id)).join(
                                          sources, sources.c.id == events.c.source_id)

    def query(connection):
        row = connection.execute(select(func.count().label("records"),
            func.count(value).label("known"), func.sum(value).label("nanos"))
            .select_from(relation).where(*where)).mappings().one()
        incomplete = connection.execute(select(func.count()).select_from(relation)
            .where(*where, facts.c.attempt_complete.is_(False))).scalar_one() \
            if budget.cost_basis == "api_estimate_usd" else 0
        marker = connection.execute(select(maintenance.c.payload).where(
            maintenance.c.id == "retention_cutoff")).scalar_one_or_none()
        collector_scope = [sources.c.team_id == team, sources.c.kind.in_(BASIS_KINDS[budget.cost_basis])]
        if budget.source_id:
            collector_scope.append(sources.c.id == budget.source_id)
        health = connection.execute(select(collectors.c.received_at, collectors.c.payload)
            .select_from(collectors.join(sources, collectors.c.source_id == sources.c.id))
            .where(*collector_scope)).all() if start <= now < end and budget.evidence != "fixture" else []
        collection_gap = any(now.timestamp() - received > 180 or
            json.loads(payload)["pending_events"] or json.loads(payload)["inflight_calls"]
            for received, payload in health)
        return row, incomplete, marker, collection_gap

    if db is None:
        with database.engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                row, incomplete, marker, collection_gap = query(connection)
    else:
        row, incomplete, marker, collection_gap = query(db)
    retained_from = json.loads(marker)["occurred_before"] if marker else None
    retention_limited = bool(retained_from and retained_from > start.isoformat())
    captured = Decimal(str(row["nanos"])) / NANOS if row["known"] else None
    unknown = row["records"] - row["known"]
    reasons = []
    if now < start:
        reasons.append("This budget month has not started.")
    if not row["records"]:
        reasons.append("No captured records are available in this scope.")
    if unknown:
        reasons.append("Some captured records have no amount for this cost basis.")
    if incomplete:
        reasons.append("Some captured calls have incomplete attempt costs.")
    if retention_limited:
        reasons.append("Retention has removed part of this month's capture window.")
    if collection_gap:
        reasons.append("A collector in this scope is stale or reports unfinished delivery or calls.")
    if not budget.coverage_confirmed:
        reasons.append("An administrator has not confirmed capture coverage for this scope.")
    elapsed = (before - start).total_seconds()
    if 0 <= elapsed < 86400:
        reasons.append("At least one full day is needed for a spending-pace projection.")
    forecast = None
    if not reasons and captured is not None:
        with localcontext() as context:
            context.prec = 50
            forecast = captured * Decimal(str((end - start).total_seconds())) / Decimal(str(elapsed))
    limit = Decimal(budget.limit_usd)
    percent = None if captured is None else captured * 100 / limit
    if captured is not None and captured >= limit:
        status = "at_limit"
    elif percent is not None and percent >= budget.warning_percent:
        status = "warning"
    elif forecast is not None and forecast > limit:
        status = "projected_over"
    elif reasons:
        status = "incomplete"
    else:
        status = "within_budget"
    return {
        "status": status, "as_of": now.isoformat(), "month": budget.month,
        "cost_basis": budget.cost_basis, "captured_usd": money(captured) if captured is not None else None,
        "tracked_usd": money(captured) if captured is not None else None,
        "allocated_usd": None, "record_kind": "captured usage",
        "limit_usd": budget.limit_usd,
        "forecast_usd": money(forecast) if forecast is not None else None,
        "percent_of_budget": str(percent.quantize(Decimal(".01"))) if percent is not None else None,
        "records": row["records"], "priced_records": row["known"], "unknown_amount_records": unknown,
        "incomplete_attempt_records": incomplete, "retention_limited": retention_limited,
        "collection_gap": bool(collection_gap),
        "coverage": "administrator_declared" if budget.coverage_confirmed else "unconfirmed",
        "projection_unavailable_reasons": reasons,
        "projection_basis": "Linear pace of captured amounts in the UTC calendar month; not a verified bill.",
        "amount_note": "Captured subtotal only. Cost bases are separate; uncaptured usage is not included.",
    }


def allocation_result(allocation):
    """Largest-remainder allocation in integer nanodollars; every unit is conserved."""
    total = int(Decimal(allocation.amount_usd) * NANOS)
    weights = sum(share.weight for share in allocation.shares)
    rows = []
    for share in sorted(allocation.shares, key=lambda share: share.project):
        nanos, remainder = divmod(total * share.weight, weights)
        rows.append({"project": share.project, "weight": share.weight,
                     "nanos": nanos, "remainder": remainder})
    remaining = total - sum(row["nanos"] for row in rows)
    order = sorted(rows, key=lambda row: (-row["remainder"], row["project"]))
    for row in order[:remaining]:
        row["nanos"] += 1
    results = [{"project": row["project"], "weight": row["weight"],
                "allocated_usd": money(Decimal(row["nanos"]) / NANOS)} for row in rows]
    return {"month": allocation.month, "category": allocation.category,
            "declared_total_usd": allocation.amount_usd, "allocations": results,
            "allocated_total_usd": money(sum((Decimal(row["allocated_usd"]) for row in results), Decimal(0))),
            "unallocated_usd": "0.000000000", "method": "declared_weights_largest_remainder",
            "cost_basis": "administrator_declared_allocation",
            "invoice_authenticated": False, "per_call_accounting_changed": False,
            "rule_fingerprint": digest(allocation.model_dump()),
            "note": "A distribution of an administrator-entered cost pool, not a verified invoice or additional API usage."}


def allocation_totals(database, team, month, *, fixture=False):
    from workbench.pilot.workflows import joined
    from workbench.pilot.database import workflow_revisions, workflows
    with database.engine.connect() as db:
        values = db.execute(select(workflow_revisions.c.payload).select_from(joined()).where(
            workflows.c.team_id == team, workflows.c.kind == "allocation", workflows.c.active.is_(True),
            workflows.c.evidence == ("fixture" if fixture else "declared"),
            json_text(database, workflow_revisions.c.payload, "month") == month)).scalars().all()
    totals = {}
    for value in values:
        result = allocation_result(Allocation.model_validate_json(value))
        for row in result["allocations"]:
            current = totals.setdefault(row["project"], {"amount": Decimal(0), "pools": 0})
            current["amount"] += Decimal(row["allocated_usd"])
            current["pools"] += 1
    return {"month": month, "pools": len(values),
            "allocated_total_usd": money(sum((row["amount"] for row in totals.values()), Decimal(0))) if values else None,
            "projects": [{"project": project, "allocated_usd": money(row["amount"]), "pools": row["pools"]}
                         for project, row in sorted(totals.items())],
            "cost_basis": "administrator_declared_allocation",
            "note": "Current, non-voided cost pools only. Do not add tool-reported model amounts to subscription allocations."}


def allocated_budget_status(database, team, budget, *, now):
    totals = allocation_totals(database, team, budget.month, fixture=budget.evidence == "fixture")
    project = next((row for row in totals["projects"] if row["project"] == budget.project), None)
    amount = (project["allocated_usd"] if project else None) if budget.project else totals["allocated_total_usd"]
    records = (project["pools"] if project else 0) if budget.project else totals["pools"]
    total = Decimal(amount) if amount is not None else None
    limit = Decimal(budget.limit_usd)
    percent = None if total is None else total * 100 / limit
    reasons = [] if budget.coverage_confirmed else ["An administrator has not confirmed that all relevant monthly cost pools are entered."]
    if not records:
        reasons.append("No allocated cost pools are available in this scope.")
    return {"status": "at_limit" if total is not None and total >= limit else
            "warning" if percent is not None and percent >= budget.warning_percent else
            "incomplete" if reasons else "within_budget",
            "month": budget.month, "as_of": now.isoformat(), "cost_basis": "allocated_usd",
            "captured_usd": None, "tracked_usd": amount, "allocated_usd": amount,
            "record_kind": "declared cost pools", "limit_usd": budget.limit_usd,
            "forecast_usd": amount if not reasons else None,
            "percent_of_budget": str(percent.quantize(Decimal(".01"))) if percent is not None else None,
            "records": records, "priced_records": records, "unknown_amount_records": 0,
            "incomplete_attempt_records": 0, "retention_limited": False,
            "coverage": "administrator_declared" if budget.coverage_confirmed else "unconfirmed",
            "projection_unavailable_reasons": reasons,
            "projection_basis": "Administrator-entered totals for the whole month; no daily run-rate extrapolation.",
            "amount_note": "Allocated expense pools are separate from API estimates and tool-reported model amounts."}


def budget_alert_counts(database, team=None):
    from workbench.pilot.workflows import joined
    from workbench.pilot.database import workflow_revisions, workflows
    current = datetime.now(timezone.utc).strftime("%Y-%m")
    where = [workflows.c.kind == "budget", workflows.c.active.is_(True),
             workflows.c.evidence != "fixture",
             json_text(database, workflow_revisions.c.payload, "month") == current]
    if team:
        where.append(workflows.c.team_id == team)
    with database.engine.connect() as db:
        definitions = db.execute(select(workflows.c.team_id, workflow_revisions.c.payload)
            .select_from(joined()).where(*where)).all()
    result = {"spend_budget_breaches": 0, "spend_budget_warnings": 0}
    for owner, payload in definitions:
        state = budget_status(database, owner, Budget.model_validate_json(payload))
        result["spend_budget_breaches"] += state["status"] == "at_limit"
        result["spend_budget_warnings"] += state["status"] in {"warning", "projected_over"}
    return result
