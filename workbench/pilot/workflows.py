"""Scoped, immutable revisions for spend policies and reusable evaluation suites."""
from __future__ import annotations

import json
import time

from sqlalchemy import and_, func, insert, select, update

from workbench.domain import digest
from .database import Conflict, teams, uid, workflow_revisions, workflows


class WorkflowError(ValueError):
    """Messages contain only developer-authored guidance, never submitted fields."""


def document(row):
    return {"id": row["id"], "revision": row["revision"], "kind": row["kind"],
            "fingerprint": row["fingerprint"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "value": json.loads(row["payload"])}


def joined():
    return workflows.join(workflow_revisions, and_(
        workflow_revisions.c.workflow_id == workflows.c.id,
        workflow_revisions.c.revision == workflows.c.revision))


def columns():
    return [workflows, workflow_revisions.c.payload, workflow_revisions.c.fingerprint]


def get(database, team, kind, identity, *, revision=None, db=None):
    def read(connection):
        relation = workflows.join(workflow_revisions, and_(
            workflow_revisions.c.workflow_id == workflows.c.id,
            workflow_revisions.c.revision == (
                workflows.c.revision if revision is None else revision)))
        row = connection.execute(select(*columns()).select_from(relation).where(
            workflows.c.team_id == team, workflows.c.kind == kind,
            workflows.c.id == identity)).mappings().first()
        if not row:
            raise KeyError(identity)
        value = document(row)
        if revision is not None:
            value["revision"] = revision
        return value
    if db is not None:
        return read(db)
    with database.engine.connect() as connection:
        return read(connection)


def list_definitions(database, team, kind, *, page=0, include_fixtures=False, active_only=False, brief=False):
    where = [workflows.c.team_id == team, workflows.c.kind == kind]
    if not include_fixtures:
        where.append(workflows.c.evidence != "fixture")
    if active_only:
        where.append(workflows.c.active.is_(True))
    with database.engine.connect() as db:
        selected = [workflows, workflow_revisions.c.summary.label("payload"),
                    workflow_revisions.c.fingerprint] if brief else columns()
        rows = db.execute(select(*selected).select_from(joined()).where(*where)
            .order_by(workflows.c.updated_at.desc(), workflows.c.id)
            .limit(26).offset(page * 25)).mappings().all()
    return {"items": [document(row) for row in rows[:25]], "page": page, "has_more": len(rows) > 25}


def save(database, team, kind, value, actor, *, expected_revision=0, identity=None):
    if kind not in {"budget", "allocation", "eval_suite"}:
        raise WorkflowError("Unsupported workflow")
    # A reference is stable across name/rule changes. Repeated create requests
    # cannot silently append another copy of the same monthly expense.
    key = digest({"reference": value["reference"], "month": value.get("month"),
                  "evidence": value["evidence"]})
    fingerprint, now = digest(value), int(time.time())
    with database.engine.begin() as db:
        # Serialize configuration changes within a team, without blocking FK
        # references from concurrent ingestion and unrelated audit transactions.
        if not db.execute(select(teams.c.id).where(teams.c.id == team)
                          .with_for_update(key_share=True)).first():
            raise KeyError(team)
        where = [workflows.c.team_id == team, workflows.c.kind == kind]
        where.append(workflows.c.id == identity if identity else workflows.c.scope_key == key)
        row = db.execute(select(*columns()).select_from(joined()).where(*where)).mappings().first()
        if identity and not row:
            raise KeyError(identity)
        if row:
            if row["scope_key"] != key:
                raise WorkflowError("Keep the reference, month and evidence type when editing; create a new record for another scope")
            if row["fingerprint"] == fingerprint:
                return document(row) | {"unchanged": True}
            if expected_revision != row["revision"]:
                raise Conflict("This record changed. Refresh it before saving another revision.")
            identity, revision = row["id"], row["revision"] + 1
        else:
            if expected_revision:
                raise Conflict("The original record is unavailable. Refresh before creating another.")
            identity, revision = uid(), 1
        if value["active"] and (not row or not row["active"]):
            count = db.execute(select(func.count()).select_from(workflows).where(
                workflows.c.team_id == team, workflows.c.kind == kind,
                workflows.c.active.is_(True))).scalar_one()
            if count >= 100:
                raise WorkflowError("Archive an unused record before adding another; at most 100 active records per workflow are supported")
        if row:
            db.execute(update(workflows).where(workflows.c.id == identity).values(
                revision=revision, active=value["active"], updated_at=now))
        else:
            db.execute(insert(workflows).values(id=identity, team_id=team, kind=kind,
                scope_key=key, revision=revision, active=value["active"],
                evidence=value["evidence"], created_at=now, updated_at=now))
        summary = {key: item for key, item in value.items() if key != "cases"}
        if "cases" in value:
            summary["case_count"] = len(value["cases"])
        db.execute(insert(workflow_revisions).values(workflow_id=identity,
            revision=revision, fingerprint=fingerprint, summary=json.dumps(summary), payload=json.dumps(value),
            created_at=now))
        database.audit(db, team, actor, f"{kind}.revision_saved", f"{identity}:{revision}")
        return get(database, team, kind, identity, db=db) | {"unchanged": False}


def history(database, team, kind, identity, *, page=0):
    get(database, team, kind, identity)
    with database.engine.connect() as db:
        rows = db.execute(select(workflow_revisions.c.revision,
            workflow_revisions.c.fingerprint, workflow_revisions.c.created_at)
            .where(workflow_revisions.c.workflow_id == identity)
            .order_by(workflow_revisions.c.revision.desc())
            .limit(26).offset(page * 25)).mappings().all()
    return {"id": identity, "revisions": [dict(row) for row in rows[:25]], "has_more": len(rows) > 25}
