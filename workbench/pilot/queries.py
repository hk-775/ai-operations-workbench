"""Exact SQL totals with bounded task and call pages; no full-ledger Python load."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, case, func, select

from workbench.domain import money
from .database import events, facts


def timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Time filters require a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def conditions(team, project=None, source_id=None, include_fixtures=False, task_id=None,
               start=None, end=None):
    start, end = timestamp(start), timestamp(end)
    if start and end and start >= end:
        raise ValueError("Start must be before end")
    result = [events.c.team_id == team]
    for column, value in ((events.c.project, project), (events.c.source_id, source_id),
                          (events.c.task_id, task_id)):
        if value:
            result.append(column == value)
    if not include_fixtures:
        result.append(events.c.evidence != "fixture")
    if start:
        result.append(events.c.occurred_at >= start)
    if end:
        result.append(events.c.occurred_at < end)
    return result


def call_rows(db, where, limit=100, offset=0):
    rows = db.execute(select(events).where(*where).order_by(
        events.c.occurred_at.desc(), events.c.event_id).limit(limit).offset(offset)).mappings()
    return [json.loads(row["payload"]) | json.loads(row["accounting"]) |
            {"received_at": row["received_at"]} for row in rows]


def usage(database, team, project=None, source_id=None, include_fixtures=False, task_id=None,
          start=None, end=None, page=0, page_size=50):
    if not 0 <= page <= 100_000 or not 1 <= page_size <= 100:
        raise ValueError("Invalid page")
    where = conditions(team, project, source_id, include_fixtures, task_id, start, end)
    joined = events.join(facts, and_(events.c.source_id == facts.c.source_id,
                                    events.c.event_id == facts.c.event_id))
    amount = func.coalesce(func.sum(facts.c.api_nanodollars), 0).label("nanos")
    unknown = func.coalesce(func.sum(case((facts.c.api_nanodollars.is_(None), 1), else_=0)), 0).label("unknown")
    uncovered = func.coalesce(func.sum(case((facts.c.attempt_complete.is_(False), 1), else_=0)), 0).label("uncovered")
    task_query = select(events.c.source_id, events.c.task_id,
        func.max(events.c.project).label("project"), func.max(events.c.occurred_at).label("occurred_at"),
        amount, unknown, uncovered, func.count().label("calls")).select_from(joined).where(*where).group_by(
            events.c.source_id, events.c.task_id)
    with database.engine.connect() as db:
        if database.engine.dialect.name == "postgresql":
            db = db.execution_options(isolation_level="REPEATABLE READ")
        with db.begin():
            totals = db.execute(select(amount, unknown, uncovered, func.count().label("events"))
                                .select_from(joined).where(*where)).mappings().one()
            count = db.execute(select(func.count()).select_from(task_query.subquery())).scalar_one()
            evidence = dict(db.execute(select(events.c.evidence, func.count()).where(*where)
                                       .group_by(events.c.evidence)).all())
            selected = db.execute(task_query.order_by(amount.desc(), events.c.source_id, events.c.task_id)
                                  .limit(page_size).offset(page * page_size)).mappings().all()
            tasks = []
            for row in selected:
                calls = call_rows(db, [*where, events.c.source_id == row["source_id"],
                                      events.c.task_id == row["task_id"]])
                tasks.append({"source_id": row["source_id"], "task_id": row["task_id"],
                    "project": row["project"], "occurred_at": row["occurred_at"], "calls": calls,
                    "api_estimate_usd": money(Decimal(row["nanos"]) / 1_000_000_000),
                    "call_count": row["calls"], "unknown_cost_calls": row["unknown"],
                    "uncovered_attempt_calls": row["uncovered"], "calls_has_more": row["calls"] > len(calls)})
    return {"api_estimate_usd": money(Decimal(totals["nanos"]) / 1_000_000_000),
            "events": totals["events"], "tasks": tasks, "task_count": count,
            "unknown_cost_calls": totals["unknown"], "uncovered_attempt_calls": totals["uncovered"],
            "evidence_counts": evidence, "page": page, "page_size": page_size,
            "has_more": (page + 1) * page_size < count, "start": start, "end": end,
            "invoice_usd": None, "hardware_electricity_usd": None,
            "cost_note": "Captured-call estimate for this time window; provider invoices and missing calls are not reconciled."}
