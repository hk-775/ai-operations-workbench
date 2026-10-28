"""Durable billing snapshots and explicit, scoped operational comparisons."""
from __future__ import annotations

import json
import time
from decimal import Decimal, localcontext

from sqlalchemy import and_, case, cast, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB

from workbench.billing import (BillingError, BillingMapping, BillingUpload, canonical,
                               decimal_text, difference, groups, parse_upload, total)
from .database import (Conflict, billing_bindings, billing_families, billing_mappings,
                       billing_reports, events, facts, maintenance, sources, teams, uid)


def report_row(db, team, identity):
    row = db.execute(select(billing_reports).where(
        billing_reports.c.id == identity, billing_reports.c.team_id == team)).mappings().first()
    if row is None:
        raise KeyError("Billing report not found")
    return row


def current(db, row):
    return db.execute(select(billing_families.c.current_revision).where(
        billing_families.c.id == row["family_id"])).scalar_one() == row["revision"]


def mapping_rows(db, report_id):
    return [dict(r) | {"mapping": json.loads(r["payload"])} for r in db.execute(
        select(billing_mappings).where(billing_mappings.c.report_id == report_id)
        .order_by(billing_mappings.c.created_at, billing_mappings.c.id)).mappings()]


def preview(database, team, upload):
    parsed = parse_upload(upload)
    with database.engine.connect() as db:
        family = db.execute(select(billing_families).where(
            billing_families.c.team_id == team,
            billing_families.c.scope_key == parsed["family_key"])).mappings().first()
    snapshot = parsed["snapshot"]
    return {
        "name": parsed["name"], "fingerprint": parsed["fingerprint"],
        "expected_revision": family["current_revision"] if family else 0,
        "account_id": snapshot["account_id"], "month": snapshot["month"],
        "currency": snapshot["currency"], "row_count": len(snapshot["rows"]),
        "imported_charges": total(r["amount"] for r in snapshot["rows"]),
        "outside_bedrock_rows": parsed["outside_bedrock_rows"],
        "duplicate_rows": parsed["duplicate_rows"], "groups": groups(snapshot),
        "uninvoiced_rows": sum(not bool(r["invoice_id"]) for r in snapshot["rows"]),
        "submitted_sha256": parsed["submitted_sha256"],
        "notice": "This is a complete replacement snapshot for the selected account, month and currency. "
                  "Imported files are not independently authenticated AWS invoices.",
    }


def import_report(database, team, upload, actor, *, fixture=False, collection_receipt=None):
    parsed = parse_upload(upload, fixture=fixture)
    with database.engine.begin() as db:
        # The team row exists even for the first report; it fences first-import
        # races as well as refresh/mapping writes. No AWS-wide line-ID dedupe.
        # NO KEY UPDATE serializes billing writers without blocking unrelated
        # foreign-key inserts (events/audits) referencing the same team.
        db.execute(select(teams.c.id).where(teams.c.id == team).with_for_update(key_share=True)).one()
        family = db.execute(select(billing_families).where(
            billing_families.c.team_id == team,
            billing_families.c.scope_key == parsed["family_key"])).mappings().first()
        revision = family["current_revision"] if family else 0
        if family:
            same = db.execute(select(billing_reports).where(
                billing_reports.c.family_id == family["id"],
                billing_reports.c.fingerprint == parsed["fingerprint"])).mappings().first()
            if same:
                if same["revision"] != revision:
                    raise Conflict("That billing snapshot was superseded; import a newer complete export.")
                return {"id": same["id"], "revision": revision, "unchanged": True}
        if upload.expected_revision != revision:
            raise Conflict("The billing report changed after preview. Preview the upload again.")
        if not family:
            family = {"id": uid(), "current_revision": 0}
            db.execute(insert(billing_families).values(id=family["id"], team_id=team,
                scope_key=parsed["family_key"], current_revision=0))
        previous = db.execute(select(billing_reports.c.id).where(
            billing_reports.c.family_id == family["id"],
            billing_reports.c.revision == revision)).scalar_one_or_none()
        identity, now = uid(), int(time.time())
        db.execute(insert(billing_reports).values(
            id=identity, family_id=family["id"], team_id=team, revision=revision + 1,
            fingerprint=parsed["fingerprint"], name=parsed["name"],
            payload=canonical(parsed["snapshot"]),
            provenance=canonical({**{k: parsed[k] for k in
                ("submitted_sha256", "outside_bedrock_rows", "duplicate_rows")},
                **({"collection": collection_receipt} if collection_receipt else {})}),
            created_at=now,
        ))
        # Carry forward only exact, still-eligible group selections. Changed
        # dimensions or removed groups require a new explicit mapping.
        allowed = {g["id"] for g in groups(parsed["snapshot"]) if g["eligible"]}
        if previous:
            for row in mapping_rows(db, previous):
                value = row["mapping"]
                if set(value["group_ids"]) <= allowed:
                    value["carried_from_revision"] = revision
                    db.execute(insert(billing_mappings).values(
                        id=uid(), report_id=identity, payload=canonical(value), created_at=now))
        db.execute(update(billing_families).where(billing_families.c.id == family["id"])
                   .values(current_revision=revision + 1))
        database.audit(db, team, actor, "billing.imported", identity)
    return {"id": identity, "revision": revision + 1, "unchanged": False}


def list_reports(database, team, *, page=0):
    with database.engine.connect() as db:
        selected = db.execute(select(billing_reports, billing_families.c.current_revision)
            .join(billing_families, billing_reports.c.family_id == billing_families.c.id)
            .where(billing_reports.c.team_id == team)
            .order_by(billing_reports.c.created_at.desc(), billing_reports.c.revision.desc(),
                      billing_reports.c.id)
            .offset(page * 25).limit(26)).mappings().all()
        output = []
        for row in selected[:25]:
            payload = json.loads(row["payload"])
            output.append({
                "id": row["id"], "name": row["name"], "revision": row["revision"],
                "current": row["revision"] == row["current_revision"],
                "created_at": row["created_at"], "account_id": payload["account_id"],
                "month": payload["month"], "currency": payload["currency"],
                "evidence": payload["evidence"],
                "charges": total(r["amount"] for r in payload["rows"]),
            })
    return {"reports": output, "page": page, "has_more": len(selected) > 25}


def add_mapping(database, team, report_id, mapping: BillingMapping, actor):
    value = mapping.model_dump()
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == team).with_for_update(key_share=True)).one()
        report = report_row(db, team, report_id)
        if not current(db, report):
            raise Conflict("Map the current billing snapshot; historical snapshots are read-only.")
        snapshot = json.loads(report["payload"])
        if snapshot["currency"] != "USD":
            raise BillingError("Captured estimates are USD. No currency conversion or cross-currency comparison is supported.")
        selected = {g["id"]: g for g in groups(snapshot)}
        if any(g not in selected or not selected[g]["eligible"] for g in mapping.group_ids):
            raise BillingError("Only eligible usage groups from this snapshot can be linked.")
        if any(selected[g]["region"] != mapping.region for g in mapping.group_ids):
            raise BillingError("Selected billing groups must have the declared source region.")
        existing = mapping_rows(db, report_id)
        if len(existing) >= 100:
            raise BillingError("A snapshot supports at most 100 comparisons.")
        for row in existing:
            other = row["mapping"]
            if set(other["group_ids"]) & set(mapping.group_ids):
                raise Conflict("A billing group is already linked to another comparison.")
            if (set(other["source_ids"]) & set(mapping.source_ids) and
                all(other[k] == value[k] for k in ("model", "region", "service_tier", "performance"))):
                raise Conflict("This captured-call scope is already used. Combine its billing groups into one comparison.")
        found = db.execute(select(sources).where(
            sources.c.team_id == team, sources.c.id.in_(mapping.source_ids),
            sources.c.kind == "bedrock")).mappings().all()
        if {s["id"] for s in found} != set(mapping.source_ids):
            raise BillingError("Select Bedrock application sources belonging to this team.")
        now = int(time.time())
        for source in found:
            binding = db.execute(select(billing_bindings.c.account_id).where(
                billing_bindings.c.source_id == source["id"])).scalar_one_or_none()
            if binding is not None and binding != snapshot["account_id"]:
                raise Conflict("A selected source is bound to another AWS account. Use a separate source for each account.")
            if binding is None:
                db.execute(insert(billing_bindings).values(
                    source_id=source["id"], team_id=team,
                    account_id=snapshot["account_id"], created_at=now))
        identity = uid()
        db.execute(insert(billing_mappings).values(
            id=identity, report_id=report_id, payload=canonical(value), created_at=now))
        database.audit(db, team, actor, "billing.mapping_created", identity)
    return {"id": identity}


def remove_mapping(database, team, report_id, identity, actor):
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == team).with_for_update(key_share=True)).one()
        report = report_row(db, team, report_id)
        if not current(db, report):
            raise Conflict("Historical billing snapshots are read-only.")
        result = db.execute(delete(billing_mappings).where(
            billing_mappings.c.id == identity, billing_mappings.c.report_id == report_id))
        if not result.rowcount:
            raise KeyError("Mapping not found")
        database.audit(db, team, actor, "billing.mapping_removed", identity)


def payload_field(db, *path):
    if db.dialect.name == "postgresql":
        return func.jsonb_extract_path_text(cast(events.c.payload, JSONB), *path)
    return func.json_extract(events.c.payload, "$." + ".".join(path))


def captured(db, team, snapshot, mapping):
    joined = events.join(facts, and_(events.c.source_id == facts.c.source_id,
                                    events.c.event_id == facts.c.event_id))
    where = [
        events.c.team_id == team, events.c.source_id.in_(mapping["source_ids"]),
        events.c.occurred_at >= snapshot["period_start"], events.c.occurred_at < snapshot["period_end"],
        payload_field(db, "schema_version") == "bedrock.usage.v1",
        payload_field(db, "model") == mapping["model"],
        payload_field(db, "bedrock", "region") == mapping["region"],
        payload_field(db, "bedrock", "service_tier") == mapping["service_tier"],
        payload_field(db, "bedrock", "performance") == mapping["performance"],
        events.c.evidence == "fixture" if snapshot["evidence"] == "fixture" else events.c.evidence != "fixture",
    ]
    aggregates = db.execute(select(
        func.count().label("calls"),
        func.coalesce(func.sum(facts.c.api_nanodollars), 0).label("nanos"),
        func.coalesce(func.sum(case((facts.c.api_nanodollars.is_(None), 1), else_=0)), 0).label("unknown"),
        func.coalesce(func.sum(case((facts.c.attempt_complete.is_(False), 1), else_=0)), 0).label("incomplete"),
        func.max(events.c.received_at).label("last_received"),
    ).select_from(joined).where(*where)).mappings().one()
    with localcontext() as context:
        context.prec = 50
        known = decimal_text(Decimal(aggregates["nanos"]) / Decimal(1_000_000_000))
    tasks = select(events.c.source_id, events.c.task_id).where(*where).group_by(
        events.c.source_id, events.c.task_id)
    count = db.execute(select(func.count()).select_from(tasks.subquery())).scalar_one()
    cutoff = db.execute(select(maintenance.c.payload).where(
        maintenance.c.id == "retention_cutoff")).scalar_one_or_none()
    expired = bool(cutoff and json.loads(cutoff)["occurred_before"] > snapshot["period_start"])
    reasons = []
    if not aggregates["calls"]:
        reasons.append("No captured calls match this declared scope.")
    if aggregates["unknown"]:
        reasons.append("Some captured calls have no supported price or usage.")
    if aggregates["incomplete"]:
        reasons.append("Some attempts or additional charges are not completely captured.")
    if expired:
        reasons.append("Usage retention has removed part of this billing window.")
    return {
        "calls": aggregates["calls"], "tasks": count, "unknown_cost_calls": aggregates["unknown"],
        "incomplete_calls": aggregates["incomplete"], "usage_retention_gap": expired,
        "known_estimate_usd": known,
        "comparable_estimate_usd": None if reasons else known,
        "last_received_at": aggregates["last_received"], "limitations": reasons,
    }


def reconcile(database, team, report_id, *, export=False):
    with database.engine.connect() as db:
        if db.dialect.name == "postgresql":
            db = db.execution_options(isolation_level="REPEATABLE READ")
        with db.begin():
            row = report_row(db, team, report_id)
            snapshot = json.loads(row["payload"])
            grouped = {g["id"]: g for g in groups(snapshot)}
            comparisons, linked, selected_ids = [], set(), set()
            for stored in mapping_rows(db, report_id):
                mapping = stored["mapping"]
                evidence = captured(db, team, snapshot, mapping)
                selected_ids.update(mapping["group_ids"])
                billed = total(grouped[g]["charge_amount"] for g in mapping["group_ids"])
                if evidence["calls"]:
                    linked.update(mapping["group_ids"])
                comparisons.append({
                    "id": stored["id"], **mapping, **evidence, "billing_charge_amount": billed,
                    "difference_usd": None if evidence["comparable_estimate_usd"] is None else
                                      difference(billed, evidence["comparable_estimate_usd"]),
                    "status": "incomplete" if evidence["limitations"] else "comparison_available",
                })
            for identity, group in grouped.items():
                group["selected"] = identity in selected_ids
                group["linked"] = identity in linked
                if group["selected"] and not group["linked"]:
                    group["unassigned_reason"] = "A mapping exists, but no captured calls match it."
                if snapshot["currency"] != "USD":
                    group["unassigned_reason"] = "Imported currency differs from the USD operational estimates."
            unassigned = [g for g in grouped.values() if not g["linked"]]
            sources_available = [dict(r) for r in db.execute(select(
                sources.c.id, sources.c.name).where(sources.c.team_id == team,
                                                   sources.c.kind == "bedrock")).mappings()]
            response = {
                "id": row["id"], "name": row["name"], "revision": row["revision"],
                "current": current(db, row), "created_at": row["created_at"],
                "fingerprint": row["fingerprint"], "provenance": json.loads(row["provenance"]),
                **{k: snapshot[k] for k in ("account_id", "month", "period_start", "period_end",
                                           "currency", "evidence", "cost_basis")},
                "row_count": len(snapshot["rows"]),
                "uninvoiced_rows": sum(not bool(r["invoice_id"]) for r in snapshot["rows"]),
                "imported_charges": total(r["amount"] for r in snapshot["rows"]),
                "linked_charges": total(grouped[g]["charge_amount"] for g in linked),
                "unassigned_charges": total(g["charge_amount"] for g in unassigned),
                "unassigned_positive_charges": total(g["positive_charges"] for g in unassigned),
                "unassigned_adjustments": total(g["negative_adjustments"] for g in unassigned),
                "unassigned_groups": len(unassigned), "groups": list(grouped.values()),
                "comparisons": comparisons, "sources": sources_available,
                "calculated_at": int(time.time()),
                "scope_note": "Billing groups are linked by an administrator's declared account/model/source scope. "
                              "This does not authenticate an invoice, prove complete capture, allocate invoices to individual "
                              "tasks, measure answer quality, or establish realized savings. Per-call invoice costs remain unknown.",
            }
            if export:
                response["billing_snapshot"] = snapshot
    return response
