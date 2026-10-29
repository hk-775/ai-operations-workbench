"""Exact SQL totals with bounded task and call pages; no full-ledger Python load."""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, JSON, and_, case, cast, func, or_, select

from workbench.domain import cases, digest, money, strict_json
from .database import events, facts, recordings

COST_BASES = {"api_estimate_usd", "reported_model_estimate_usd", "reported_charge_usd"}


def call_scope(team, source_id, task_id, project=None, include_fixtures=False, start=None, end=None):
    return digest({"team": team, "source": source_id, "task": task_id, "project": project or None,
                   "fixtures": include_fixtures, "start": timestamp(start), "end": timestamp(end)})


def next_cursor(calls, sequence, scope, has_more):
    if not has_more or not calls:
        return None
    last = calls[-1]
    payload = {"v": 1, "sequence": sequence, "scope": scope,
               "time": last["occurred_at"], "event": last["event_id"]}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def cursor_values(value, scope):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2048:
            raise ValueError
        item = strict_json(base64.b64decode(value, altchars=b"-_", validate=True).decode())
        if (not isinstance(item, dict) or set(item) != {"v", "sequence", "scope", "time", "event"}
                or type(item["v"]) is not int or item["v"] != 1
                or item["scope"] != scope or type(item["sequence"]) is not int
                or not 0 <= item["sequence"] < 2**63 or not isinstance(item["time"], str)
                or len(item["time"]) > 50 or timestamp(item["time"]) != item["time"]
                or not isinstance(item["event"], str) or not 1 <= len(item["event"]) <= 160):
            raise ValueError
        return item
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, OverflowError, RecursionError):
        raise ValueError("Invalid call cursor; refresh this task") from None


def call_page(database, team, source_id, task_id, *, project=None, include_fixtures=False,
              start=None, end=None, cursor=None):
    where = conditions(team, project, source_id, include_fixtures, task_id, start, end)
    scope = call_scope(team, source_id, task_id, project, include_fixtures, start, end)
    boundary = cursor_values(cursor, scope) if cursor is not None else None
    with database.engine.connect() as db:
        if db.dialect.name == "postgresql":
            db = db.execution_options(isolation_level="REPEATABLE READ")
        with db.begin():
            sequence = boundary["sequence"] if boundary else db.execute(
                select(func.coalesce(func.max(events.c.ingest_sequence), 0)).where(*where)).scalar_one()
            where.append(events.c.ingest_sequence <= sequence)
            if boundary:
                where.append(or_(events.c.occurred_at < boundary["time"], and_(
                    events.c.occurred_at == boundary["time"], events.c.event_id > boundary["event"])))
            rows = call_rows(db, where, limit=101)
    return {"calls": rows[:100], "has_more": len(rows) > 100,
            "next_cursor": next_cursor(rows[:100], sequence, scope, len(rows) > 100),
            "snapshot_sequence": sequence,
            "snapshot_note": "Calls captured after this view opened appear after refresh. Retention can remove expired calls."}


def json_text(database, column, key):
    if database.engine.dialect.name == "postgresql":
        return cast(column, JSON).op("->>")(key)
    return func.json_extract(column, "$." + key)


def reported_totals(database):
    """All new monetary fields are normalized to nine-place Decimal text on ingest."""
    expressions = []
    for name in ("reported_model_estimate_usd", "reported_charge_usd"):
        value = json_text(database, events.c.accounting, name)
        nanos = cast(func.replace(value, ".", ""), BigInteger)
        expressions.extend((func.sum(nanos).label(name + "_nanos"),
                            func.count(value).label(name + "_records")))
    tool = json_text(database, events.c.payload, "schema_version") == "coding-tool.usage.v1"
    expressions.append(func.coalesce(func.sum(case((tool, 1), else_=0)), 0).label("coding_tool_records"))
    return expressions


def reported_values(row):
    result = {"coding_tool_records": row["coding_tool_records"]}
    for name in ("reported_model_estimate_usd", "reported_charge_usd"):
        count = row[name + "_records"]
        result[name] = None if not count else money(Decimal(row[name + "_nanos"]) / 1_000_000_000)
        result[name + "_records"] = count
    return result


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
          start=None, end=None, page=0, page_size=50, cost_basis="api_estimate_usd"):
    if not 0 <= page <= 100_000 or not 1 <= page_size <= 100:
        raise ValueError("Invalid page")
    if cost_basis not in COST_BASES:
        raise ValueError("Invalid cost basis")
    where = conditions(team, project, source_id, include_fixtures, task_id, start, end)
    joined = events.join(facts, and_(events.c.source_id == facts.c.source_id,
                                    events.c.event_id == facts.c.event_id))
    amount = func.coalesce(func.sum(facts.c.api_nanodollars), 0).label("nanos")
    unknown = func.coalesce(func.sum(case((facts.c.api_nanodollars.is_(None), 1), else_=0)), 0).label("unknown")
    uncovered = func.coalesce(func.sum(case((facts.c.attempt_complete.is_(False), 1), else_=0)), 0).label("uncovered")
    reported = reported_totals(database)
    task_query = select(events.c.source_id, events.c.task_id,
        func.max(events.c.project).label("project"), func.max(events.c.occurred_at).label("occurred_at"),
        amount, unknown, uncovered, *reported, func.count().label("calls"),
        func.max(events.c.ingest_sequence).label("sequence")).select_from(joined).where(*where).group_by(
            events.c.source_id, events.c.task_id)
    with database.engine.connect() as db:
        if database.engine.dialect.name == "postgresql":
            db = db.execution_options(isolation_level="REPEATABLE READ")
        with db.begin():
            totals = db.execute(select(amount, unknown, uncovered, *reported, func.count().label("events"))
                                .select_from(joined).where(*where)).mappings().one()
            count = db.execute(select(func.count()).select_from(task_query.subquery())).scalar_one()
            evidence = dict(db.execute(select(events.c.evidence, func.count()).where(*where)
                                       .group_by(events.c.evidence)).all())
            if cost_basis == "api_estimate_usd":
                rank = func.sum(facts.c.api_nanodollars)
            else:
                value = json_text(database, events.c.accounting, cost_basis)
                rank = func.sum(cast(func.replace(value, ".", ""), BigInteger))
            selected = db.execute(task_query.order_by(rank.desc().nulls_last(), events.c.source_id, events.c.task_id)
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
                    **reported_values(row),
                    "call_count": row["calls"], "unknown_cost_calls": row["unknown"],
                    "uncovered_attempt_calls": row["uncovered"], "calls_has_more": row["calls"] > len(calls),
                    "calls_cursor": next_cursor(calls, row["sequence"], call_scope(
                        team, row["source_id"], row["task_id"], project, include_fixtures, start, end),
                        row["calls"] > len(calls)),
                    "cost_basis": cost_basis})
    return {"api_estimate_usd": money(Decimal(totals["nanos"]) / 1_000_000_000),
            **reported_values(totals),
            "events": totals["events"], "tasks": tasks, "task_count": count,
            "unknown_cost_calls": totals["unknown"], "uncovered_attempt_calls": totals["uncovered"],
            "evidence_counts": evidence, "page": page, "page_size": page_size,
            "has_more": (page + 1) * page_size < count, "start": start, "end": end,
            "invoice_usd": None, "hardware_electricity_usd": None, "cost_basis": cost_basis,
            "cost_note": "Captured-call estimate for this time window. Billing reconciliation compares separately imported charges; invoice costs are not allocated to individual tasks."}
