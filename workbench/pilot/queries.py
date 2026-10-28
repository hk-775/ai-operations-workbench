"""Exact SQL totals with bounded task and call pages; no full-ledger Python load."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, case, func, select

from workbench.domain import cases, money
from .database import events, facts, recordings


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
            # Only validated, team-owned recordings can use the authored support
            # titles. An application's arbitrary case_id is not a support case.
            recorded_sources = dict(db.execute(select(recordings.c.source_id, recordings.c.id).where(
                recordings.c.team_id == team,
                recordings.c.source_id.in_([row["source_id"] for row in selected]))).all())
            catalog = {item["id"]: item for item in cases()} if recorded_sources else {}
            tasks = []
            for row in selected:
                calls = call_rows(db, [*where, events.c.source_id == row["source_id"],
                                      events.c.task_id == row["task_id"]])
                context = None
                case_ids = {call.get("case_id") for call in calls}
                if (len(case_ids) == 1 and calls and row["source_id"] in recorded_sources
                        and all(call.get("recording_id") == recorded_sources[row["source_id"]]
                                and call["evidence"] in {"recorded", "fixture"} for call in calls)):
                    case_id = next(iter(case_ids))
                    if item := catalog.get(case_id):
                        context = {"kind": "support_comparison", "case_id": case_id,
                                   "title": item["title"], "request": item["ticket"]}
                tasks.append({"source_id": row["source_id"], "task_id": row["task_id"],
                    "project": row["project"], "occurred_at": row["occurred_at"], "calls": calls,
                    "context": context,
                    "api_estimate_usd": money(Decimal(row["nanos"]) / 1_000_000_000),
                    "call_count": row["calls"], "unknown_cost_calls": row["unknown"],
                    "uncovered_attempt_calls": row["uncovered"], "calls_has_more": row["calls"] > len(calls)})
    return {"api_estimate_usd": money(Decimal(totals["nanos"]) / 1_000_000_000),
            "events": totals["events"], "tasks": tasks, "task_count": count,
            "unknown_cost_calls": totals["unknown"], "uncovered_attempt_calls": totals["uncovered"],
            "evidence_counts": evidence, "page": page, "page_size": page_size,
            "has_more": (page + 1) * page_size < count, "start": start, "end": end,
            "invoice_usd": None, "hardware_electricity_usd": None,
            "cost_note": "Captured-call estimate for this time window. Billing reconciliation compares separately imported charges; invoice costs are not allocated to individual tasks."}
