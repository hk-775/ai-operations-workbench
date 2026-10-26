"""Bounded, restartable retention maintenance with an irreversible cutoff marker."""
from __future__ import annotations

import json
import signal
import time
from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, select, tuple_, update

from .database import (audits, events, jobs, login_failures, maintenance, oidc_states,
                       proposals, recordings, sessions, sources, teams, tokens, workers)


def save(db, identity, payload, now):
    if db.execute(select(maintenance.c.id).where(maintenance.c.id == identity)).first():
        db.execute(update(maintenance).where(maintenance.c.id == identity).values(
            payload=json.dumps(payload), updated_at=now))
    else:
        db.execute(insert(maintenance).values(id=identity, payload=json.dumps(payload), updated_at=now))


def run_once(database, settings, *, dry_run=False, now=None):
    now = int(time.time()) if now is None else now
    cutoff = datetime.fromtimestamp(now - settings.retention_days * 86400, timezone.utc).isoformat()
    with database.engine.begin() as db:
        if database.engine.dialect.name == "postgresql":
            if not db.exec_driver_sql("SELECT pg_try_advisory_xact_lock(2026102602)").scalar_one():
                return {"status": "another_operator_is_running"}
        old_policy = db.execute(select(maintenance.c.payload).where(
            maintenance.c.id == "retention_cutoff")).scalar_one_or_none()
        if old_policy:
            cutoff = max(cutoff, json.loads(old_policy)["occurred_before"])
        # Source locks fence ingestion while moving the boundary and deleting metadata.
        source_ids = db.execute(select(sources.c.id).where(sources.c.kind != "recording")
                                .order_by(sources.c.id).with_for_update()).scalars().all()
        eligible = [events.c.source_id.in_(source_ids), events.c.occurred_at < cutoff]
        count = db.execute(select(func.count()).select_from(events).where(*eligible)).scalar_one() if settings.retention_days else 0
        report = {"status": "preview" if dry_run else "complete", "eligible_events": count,
                  "deleted_events": 0, "retention_days": settings.retention_days,
                  "deleted_recordings": 0, "deleted_audit_events": 0,
                  "evidence_retention_days": settings.evidence_retention_days,
                  "audit_retention_days": settings.audit_retention_days}
        old_recordings = []
        if settings.evidence_retention_days:
            candidates = db.execute(select(recordings.c.team_id, recordings.c.id, recordings.c.source_id)
                .where(recordings.c.created_at < now - settings.evidence_retention_days * 86400)
                .where(~select(jobs.c.id).where(jobs.c.team_id == recordings.c.team_id,
                    jobs.c.recording_id == recordings.c.id, jobs.c.status.in_(["queued","running"])).exists())
                .limit(20).with_for_update(skip_locked=True)).mappings().all()
            for record in candidates:
                active = db.execute(select(jobs.c.id).where(jobs.c.team_id == record["team_id"],
                    jobs.c.recording_id == record["id"], jobs.c.status.in_(["queued", "running"]))).first()
                if not active:
                    old_recordings.append(record)
        old_audits = db.execute(select(audits.c.id).where(
            audits.c.created_at < now - settings.audit_retention_days * 86400)
            .limit(10_000)).scalars().all() if settings.audit_retention_days else []
        report.update(eligible_recordings=len(old_recordings), eligible_audit_events=len(old_audits))
        if dry_run:
            return report
        if settings.retention_days:
            save(db, "retention_cutoff", {"occurred_before": cutoff}, now)
            batch = db.execute(select(events.c.source_id, events.c.event_id).where(*eligible).limit(10_000)).all()
            # Bound IN expressions and transactions for SQLite tests and PostgreSQL operators.
            for offset in range(0, len(batch), 200):
                db.execute(delete(events).where(tuple_(events.c.source_id, events.c.event_id).in_(batch[offset:offset + 200])))
            report["deleted_events"] = len(batch)
        report["remaining_events"] = count - report["deleted_events"]
        db.execute(delete(sessions).where((sessions.c.expires_at <= now) |
                                          (sessions.c.last_seen <= now - settings.idle_seconds)))
        db.execute(delete(oidc_states).where(oidc_states.c.expires_at <= now))
        db.execute(delete(login_failures).where(login_failures.c.created_at <= now - 86400))
        db.execute(delete(tokens).where(tokens.c.expires_at <= now - 86400))
        db.execute(delete(workers).where(workers.c.heartbeat_at < now - 86400))
        for record in old_recordings:
            job_ids = select(jobs.c.id).where(jobs.c.team_id == record["team_id"],
                                             jobs.c.recording_id == record["id"])
            db.execute(delete(proposals).where(proposals.c.job_id.in_(job_ids)))
            db.execute(delete(jobs).where(jobs.c.team_id == record["team_id"], jobs.c.recording_id == record["id"]))
            db.execute(delete(events).where(events.c.source_id == record["source_id"]))
            db.execute(delete(recordings).where(recordings.c.team_id == record["team_id"], recordings.c.id == record["id"]))
            db.execute(delete(sources).where(sources.c.id == record["source_id"]))
            report["deleted_recordings"] += 1
            database.audit(db, record["team_id"], "maintenance", "retention.evidence_deleted", record["id"])
        for offset in range(0, len(old_audits), 200):
            db.execute(delete(audits).where(audits.c.id.in_(old_audits[offset:offset + 200])))
        report["deleted_audit_events"] = len(old_audits)
        report["more_evidence_or_audit"] = len(old_recordings) == 20 or len(old_audits) == 10_000
        save(db, "last_run", report, now)
        if report["deleted_events"]:
            for team in db.execute(select(teams.c.id)).scalars():
                database.audit(db, team, "maintenance", "retention.metadata_deleted", str(report["deleted_events"]))
        return report


def run(database, settings):
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    next_run = 0
    while not stopping:
        if time.monotonic() >= next_run:
            try:
                report = run_once(database, settings)
                print(json.dumps({"event": "maintenance_completed", **report}), flush=True)
                next_run = time.monotonic() + (60 if report.get("remaining_events") or report.get("more_evidence_or_audit") else 3600)
            except Exception:
                print('{"event":"maintenance_failed","detail":"Check database connectivity"}', flush=True)
                next_run = time.monotonic() + 30
        time.sleep(.5)
