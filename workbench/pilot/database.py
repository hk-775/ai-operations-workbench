"""Transactional team data and leased jobs, backed by PostgreSQL in pilot mode."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import (BigInteger, Boolean, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, event,
                        MetaData, String, Table, Text, UniqueConstraint, and_,
                        create_engine, delete, func, insert, or_, select, update)
from sqlalchemy.exc import IntegrityError

from workbench.domain import digest, evaluation_revision, money
from workbench.evidence import verify_recording
from .events import CollectorHealth, UsageEvent, account, pricebook, recording_events

metadata = MetaData()
schema = Table("wb_schema", metadata, Column("version", Integer, primary_key=True))
teams = Table("wb_teams", metadata, Column("id", String(36), primary_key=True),
              Column("name", String(100), nullable=False))
users = Table("wb_users", metadata, Column("id", String(36), primary_key=True),
              Column("team_id", ForeignKey("wb_teams.id"), nullable=False),
              Column("username", String(100), nullable=False, unique=True),
              Column("password_hash", Text, nullable=False),
              Column("role", String(20), nullable=False),
              Column("active", Boolean, nullable=False, default=True),
              Column("created_at", BigInteger, nullable=False))
sessions = Table("wb_sessions", metadata, Column("id", String(64), primary_key=True),
                 Column("user_id", ForeignKey("wb_users.id"), nullable=False),
                 Column("created_at", BigInteger, nullable=False),
                 Column("expires_at", BigInteger, nullable=False),
                 Column("last_seen", BigInteger, nullable=False))
sso_sessions = Table("wb_sso_sessions", metadata,
                     Column("session_id", ForeignKey("wb_sessions.id", ondelete="CASCADE"), primary_key=True))
login_failures = Table("wb_login_failures", metadata,
                       Column("id", String(36), primary_key=True),
                       Column("username_hash", String(64), nullable=False),
                       Column("ip_hash", String(64), nullable=False),
                       Column("created_at", BigInteger, nullable=False))
sources = Table("wb_sources", metadata, Column("id", String(36), primary_key=True),
                Column("team_id", ForeignKey("wb_teams.id"), nullable=False),
                Column("name", String(100), nullable=False),
                Column("kind", String(30), nullable=False),
                Column("created_at", BigInteger, nullable=False),
                UniqueConstraint("team_id", "name"))
tokens = Table("wb_source_tokens", metadata, Column("id", String(64), primary_key=True),
               Column("source_id", ForeignKey("wb_sources.id"), nullable=False),
               Column("prefix", String(16), nullable=False),
               Column("created_at", BigInteger, nullable=False),
               Column("expires_at", BigInteger, nullable=False),
               Column("revoked", Boolean, nullable=False, default=False))
collectors = Table("wb_collectors", metadata,
                   Column("source_id", ForeignKey("wb_sources.id", ondelete="CASCADE"), primary_key=True),
                   Column("collector_id", String(32), primary_key=True),
                   Column("payload", Text, nullable=False),
                   Column("received_at", BigInteger, nullable=False))
books = Table("wb_pricebooks", metadata, Column("id", String(64), primary_key=True),
              Column("payload", Text, nullable=False))
events = Table("wb_events", metadata,
               Column("source_id", ForeignKey("wb_sources.id"), primary_key=True),
               Column("event_id", String(160), primary_key=True),
               Column("team_id", ForeignKey("wb_teams.id"), nullable=False),
               Column("task_id", String(160), nullable=False),
               Column("project", String(100), nullable=False),
               Column("occurred_at", String(50), nullable=False),
               Column("evidence", String(20), nullable=False),
               Column("recording_id", String(64)),
               Column("fingerprint", String(64), nullable=False),
               Column("payload", Text, nullable=False),
               Column("accounting", Text, nullable=False),
               Column("received_at", BigInteger, nullable=False))
Index("wb_events_team_task", events.c.team_id, events.c.source_id, events.c.task_id)
Index("wb_events_team_time", events.c.team_id, events.c.occurred_at)
facts = Table("wb_event_facts", metadata,
              Column("source_id", String(36), primary_key=True),
              Column("event_id", String(160), primary_key=True),
              Column("api_nanodollars", BigInteger),
              Column("attempt_complete", Boolean, nullable=False),
              ForeignKeyConstraint(["source_id", "event_id"],
                                   ["wb_events.source_id", "wb_events.event_id"], ondelete="CASCADE"))
identities = Table("wb_identities", metadata,
                   Column("issuer", String(512), primary_key=True),
                   Column("subject", String(255), primary_key=True),
                   Column("user_id", ForeignKey("wb_users.id"), nullable=False, unique=True))
oidc_states = Table("wb_oidc_states", metadata,
                    Column("id", String(64), primary_key=True),
                    Column("payload", Text, nullable=False),
                    Column("expires_at", BigInteger, nullable=False))
maintenance = Table("wb_maintenance", metadata,
                    Column("id", String(40), primary_key=True),
                    Column("payload", Text, nullable=False),
                    Column("updated_at", BigInteger, nullable=False))
recordings = Table("wb_recordings", metadata,
                   Column("team_id", ForeignKey("wb_teams.id"), primary_key=True),
                   Column("id", String(64), primary_key=True),
                   Column("source_id", ForeignKey("wb_sources.id"), nullable=False),
                   Column("payload", Text, nullable=False),
                   Column("created_at", BigInteger, nullable=False))
jobs = Table("wb_jobs", metadata, Column("id", String(36), primary_key=True),
             Column("team_id", ForeignKey("wb_teams.id"), nullable=False),
             Column("recording_id", String(64), nullable=False),
             Column("revision", String(64), nullable=False),
             Column("status", String(20), nullable=False),
             Column("attempts", Integer, nullable=False, default=0),
             Column("owner", String(36)),
             Column("lease_until", BigInteger),
             Column("created_at", BigInteger, nullable=False),
             Column("started_at", BigInteger),
             Column("finished_at", BigInteger),
             Column("result", Text),
             Column("error", String(300)))
Index("wb_jobs_queue", jobs.c.status, jobs.c.created_at)
workers = Table("wb_workers", metadata, Column("id", String(36), primary_key=True),
                Column("heartbeat_at", BigInteger, nullable=False))
audits = Table("wb_audit", metadata, Column("id", String(36), primary_key=True),
               Column("team_id", ForeignKey("wb_teams.id"), nullable=False),
               Column("actor", String(100), nullable=False),
               Column("action", String(80), nullable=False),
               Column("entity", String(160), nullable=False),
               Column("created_at", BigInteger, nullable=False))
proposals = Table("wb_proposals", metadata,
                  Column("id", String(64), primary_key=True),
                  Column("team_id", ForeignKey("wb_teams.id"), nullable=False),
                  Column("job_id", ForeignKey("wb_jobs.id"), nullable=False),
                  Column("payload", Text, nullable=False),
                  Column("created_at", BigInteger, nullable=False))


def uid() -> str:
    return str(uuid.uuid4())


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Conflict(ValueError):
    pass


class Database:
    def __init__(self, url: str):
        args = {"pool_pre_ping": True, "hide_parameters": True, "pool_timeout": 5}
        if url.startswith("sqlite"):
            args["connect_args"] = {"check_same_thread": False}
        else:
            args["connect_args"] = {"connect_timeout": 5}
        self.engine = create_engine(url, **args)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

    def migrate(self):
        with self.engine.begin() as db:
            if self.engine.dialect.name == "postgresql":
                db.exec_driver_sql("SELECT pg_advisory_xact_lock(2026102301)")
            schema.create(db, checkfirst=True)
            versions = db.execute(select(schema.c.version)).scalars().all()
            if versions and versions not in ([1], [2], [3]):
                raise RuntimeError("Unsupported pilot database schema")
            metadata.create_all(db)
            if versions not in ([2], [3]):
                # Only copy persisted accounting: repricing would rewrite historical evidence.
                while True:
                    batch = db.execute(select(events.c.source_id, events.c.event_id, events.c.accounting)
                        .outerjoin(facts, and_(events.c.source_id == facts.c.source_id,
                                              events.c.event_id == facts.c.event_id))
                        .where(facts.c.event_id.is_(None)).limit(1000)).mappings().all()
                    if not batch:
                        break
                    db.execute(insert(facts), [self.fact(row["source_id"], row["event_id"],
                                                        json.loads(row["accounting"])) for row in batch])
            if versions != [3]:
                # v3 adds collector heartbeats; existing payloads/facts stay byte-for-byte intact.
                db.execute(delete(schema))
                db.execute(insert(schema).values(version=3))
            book = pricebook()
            if not db.execute(select(books.c.id).where(books.c.id == book["id"])).first():
                db.execute(insert(books).values(id=book["id"], payload=json.dumps(book["snapshot"])))

    def check_schema(self):
        with self.engine.connect() as db:
            if db.execute(select(schema.c.version)).scalars().all() != [3]:
                raise RuntimeError("Run the explicit database migration before starting this release")

    @staticmethod
    def fact(source_id, event_id, charge):
        amount = charge["api_estimate_usd"]
        return {"source_id": source_id, "event_id": event_id,
                "api_nanodollars": None if amount is None else int(Decimal(amount) * 1_000_000_000),
                "attempt_complete": charge["attempt_cost_complete"]}

    @staticmethod
    def audit(db, team_id, actor, action, entity):
        db.execute(insert(audits).values(id=uid(), team_id=team_id, actor=actor,
                                        action=action, entity=entity, created_at=int(time.time())))

    def initialize(self, name: str, username: str, password_hash: str):
        with self.engine.begin() as db:
            if self.engine.dialect.name == "postgresql":
                db.exec_driver_sql("SELECT pg_advisory_xact_lock(2026102302)")
            if db.execute(select(teams.c.id)).first():
                raise Conflict("A team already exists; use the team administration screen")
            team, user = uid(), uid()
            db.execute(insert(teams).values(id=team, name=name))
            db.execute(insert(users).values(id=user, team_id=team, username=username,
                password_hash=password_hash, role="admin", active=True, created_at=int(time.time())))
            self.audit(db, team, username, "team.initialized", team)
            return team

    def initialized(self) -> bool:
        with self.engine.connect() as db:
            return db.execute(select(teams.c.id)).first() is not None

    def create_source(self, team_id: str, name: str, actor: str, kind="axonllm"):
        if kind not in {"axonllm", "bedrock"}:
            raise ValueError("Unsupported application connector")
        identity = uid()
        try:
            with self.engine.begin() as db:
                db.execute(insert(sources).values(id=identity, team_id=team_id, name=name,
                                                  kind=kind, created_at=int(time.time())))
                self.audit(db, team_id, actor, "source.created", identity)
        except IntegrityError as exc:
            raise Conflict("A source with that name already exists") from exc
        return identity

    def source(self, team_id: str, source_id: str):
        with self.engine.connect() as db:
            return db.execute(select(sources).where(
                sources.c.team_id == team_id, sources.c.id == source_id)).mappings().first()

    def issue_token(self, team_id: str, source_id: str, actor: str):
        raw, now = "wb_ing_" + secrets.token_urlsafe(32), int(time.time())
        with self.engine.begin() as db:
            source = db.execute(select(sources).where(
                sources.c.id == source_id, sources.c.team_id == team_id).with_for_update()).mappings().first()
            if not source or source["kind"] not in {"axonllm", "bedrock"}:
                raise KeyError("Source not found")
            db.execute(insert(tokens).values(id=hash_secret(raw), source_id=source_id,
                prefix=raw[:15], created_at=now, expires_at=now + 30 * 86400, revoked=False))
            self.audit(db, team_id, actor, "source.token_issued", source_id)
        return {"token": raw, "prefix": raw[:15], "expires_at": now + 30 * 86400}

    def token_source(self, raw: str):
        if not raw.startswith("wb_ing_") or len(raw) > 100:
            return None
        with self.engine.connect() as db:
            return db.execute(select(sources).join(tokens, sources.c.id == tokens.c.source_id).where(
                tokens.c.id == hash_secret(raw), tokens.c.revoked.is_(False),
                tokens.c.expires_at > int(time.time()))).mappings().first()

    def _ingest(self, db, team_id: str, source_id: str, batch: list[UsageEvent]):
        # Serialize writes for one source: a replay cannot race a conflicting batch.
        source = db.execute(select(sources).where(sources.c.id == source_id,
            sources.c.team_id == team_id).with_for_update()).mappings().first()
        if not source:
            raise KeyError("Source not found")
        expected = "bedrock.usage.v1" if source["kind"] == "bedrock" else "axon.usage.v1"
        if any(event.schema_version != expected for event in batch):
            raise Conflict("Event schema does not match this source's connector")
        policy = db.execute(select(maintenance.c.payload).where(
            maintenance.c.id == "retention_cutoff")).scalar_one_or_none()
        if source["kind"] != "recording" and policy:
            cutoff = json.loads(policy)["occurred_before"]
            if any(event.occurred_at < cutoff for event in batch):
                raise Conflict("Batch contains events older than the active retention boundary")
        book, added, duplicated = pricebook(), 0, 0
        existing_ids = dict(db.execute(select(events.c.event_id, events.c.fingerprint).where(
            events.c.source_id == source_id,
            events.c.event_id.in_({event.event_id for event in batch}))).all())
        new_events, new_facts = [], []
        for event in batch:
            payload = event.model_dump()
            fingerprint = digest(payload)
            existing = existing_ids.get(event.event_id)
            if existing is not None:
                if existing != fingerprint:
                    raise Conflict("An event ID was reused with different data; batch rolled back")
                duplicated += 1
                continue
            charge = account(event, book)
            new_events.append(dict(source_id=source_id, event_id=event.event_id,
                team_id=team_id, task_id=event.task_id, project=event.project,
                occurred_at=event.occurred_at, evidence=event.evidence,
                recording_id=event.recording_id, fingerprint=fingerprint,
                payload=json.dumps(payload), accounting=json.dumps(charge),
                received_at=int(time.time())))
            new_facts.append(self.fact(source_id, event.event_id, charge))
            existing_ids[event.event_id] = fingerprint
            added += 1
        if new_events:
            db.execute(insert(events), new_events)
            db.execute(insert(facts), new_facts)
        return {"added_events": added, "duplicate_events": duplicated}

    def ingest(self, team_id: str, source_id: str, batch: list[UsageEvent]):
        with self.engine.begin() as db:
            result = self._ingest(db, team_id, source_id, batch)
            self.audit(db, team_id, f"connector:{source_id}", "usage.ingested", str(result["added_events"]))
            return result

    def ingest_authenticated(self, raw: str, batch: list[UsageEvent]):
        with self.engine.begin() as db:
            source = db.execute(select(sources).join(tokens, sources.c.id == tokens.c.source_id).where(
                tokens.c.id == hash_secret(raw))).mappings().first()
            if not source:
                raise PermissionError("Valid ingestion token required")
            db.execute(select(sources.c.id).where(sources.c.id == source["id"]).with_for_update()).first()
            valid = db.execute(select(tokens.c.id).where(tokens.c.id == hash_secret(raw),
                tokens.c.revoked.is_(False), tokens.c.expires_at > int(time.time()))).first()
            if not valid:
                raise PermissionError("Valid ingestion token required")
            result = self._ingest(db, source["team_id"], source["id"], batch)
            self.audit(db, source["team_id"], f"connector:{source['id']}",
                       "usage.ingested", str(result["added_events"]))
            return result

    def import_recording(self, team_id: str, document: dict, actor: str):
        verify_recording(document)
        identity = digest(document)
        with self.engine.begin() as db:
            db.execute(select(teams).where(teams.c.id == team_id).with_for_update()).first()
            existing = db.execute(select(recordings).where(
                recordings.c.team_id == team_id, recordings.c.id == identity)).mappings().first()
            if existing:
                return {"recording_id": identity, "source_id": existing["source_id"], "deduplicated": True}
            source_id = uid()
            db.execute(insert(sources).values(id=source_id, team_id=team_id,
                name=f"Recorded support comparison · {identity[:12]}", kind="recording",
                created_at=int(time.time())))
            self._ingest(db, team_id, source_id, recording_events(document))
            db.execute(insert(recordings).values(team_id=team_id, id=identity, source_id=source_id,
                payload=json.dumps(document), created_at=int(time.time())))
            self.audit(db, team_id, actor, "recording.imported", identity)
            return {"recording_id": identity, "source_id": source_id, "deduplicated": False}

    def list_sources(self, team_id: str):
        with self.engine.connect() as db:
            result = []
            for source in db.execute(select(sources).where(
                    sources.c.team_id == team_id).order_by(sources.c.created_at.desc())).mappings():
                row = dict(source)
                row["tokens"] = [dict(t) for t in db.execute(select(tokens.c.id, tokens.c.prefix, tokens.c.expires_at,
                    tokens.c.revoked).where(tokens.c.source_id == row["id"])).mappings()]
                row["event_count"] = db.execute(select(func.count()).select_from(events).where(
                    events.c.team_id == team_id, events.c.source_id == row["id"])).scalar_one()
                row["last_received_at"] = db.execute(select(func.max(events.c.received_at)).where(
                    events.c.team_id == team_id, events.c.source_id == row["id"])).scalar_one()
                row["collection"] = self.collection_health(db, row)
                result.append(row)
            return result

    @staticmethod
    def collection_health(db, source):
        now = int(time.time())
        rows = db.execute(select(collectors).where(collectors.c.source_id == source["id"])).mappings().all()
        reports = [json.loads(row["payload"]) for row in rows]
        stale = sum(now - row["received_at"] > 180 for row in rows)
        active_token = any(not t["revoked"] and t["expires_at"] > now for t in source["tokens"])
        state = ("recorded" if source["kind"] == "recording" else
                 "token_required" if not active_token else
                 "unmonitored" if not rows else
                 "stale" if stale else
                 "backlog" if any(r["pending_events"] for r in reports) else "connected")
        return {"status": state, "collectors": len(rows), "stale_collectors": stale,
                "reports": [{"collector_id": r["collector_id"], "last_heartbeat_at": r["received_at"],
                             "stale": now - r["received_at"] > 180} for r in rows],
                "last_heartbeat_at": max((r["received_at"] for r in rows), default=None),
                "pending_events": sum(r["pending_events"] for r in reports) if rows else None,
                "inflight_calls": sum(r["inflight_calls"] for r in reports) if rows else None,
                "retrying_events": sum(r["retrying_events"] for r in reports) if rows else None,
                "oldest_pending_at": min((r["oldest_pending_at"] for r in reports
                                           if r["oldest_pending_at"]), default=None)}

    def report_collector(self, raw: str, report: CollectorHealth):
        with self.engine.begin() as db:
            source = db.execute(select(sources).join(tokens, sources.c.id == tokens.c.source_id)
                .where(tokens.c.id == hash_secret(raw))).mappings().first()
            if not source or source["kind"] not in {"axonllm", "bedrock"}:
                raise PermissionError("Valid ingestion token required")
            db.execute(select(sources.c.id).where(sources.c.id == source["id"]).with_for_update()).first()
            valid = db.execute(select(tokens.c.id).where(tokens.c.id == hash_secret(raw),
                tokens.c.revoked.is_(False), tokens.c.expires_at > int(time.time()))).first()
            if not valid:
                raise PermissionError("Valid ingestion token required")
            where = [collectors.c.source_id == source["id"], collectors.c.collector_id == report.collector_id]
            values = {"payload": report.model_dump_json(), "received_at": int(time.time())}
            if db.execute(select(collectors.c.collector_id).where(*where)).first():
                db.execute(update(collectors).where(*where).values(**values))
            else:
                count = db.execute(select(func.count()).select_from(collectors).where(
                    collectors.c.source_id == source["id"])).scalar_one()
                if count >= 100:
                    raise Conflict("Collector limit reached; use a separate source")
                db.execute(insert(collectors).values(source_id=source["id"],
                    collector_id=report.collector_id, **values))
        return {"accepted": True}

    def retire_collector(self, team_id, source_id, collector_id, actor):
        """Only an administrator can dismiss a stopped collector's stale signal."""
        with self.engine.begin() as db:
            if not db.execute(select(sources.c.id).where(sources.c.team_id == team_id,
                    sources.c.id == source_id).with_for_update()).first():
                raise KeyError("Source not found")
            db.execute(delete(collectors).where(collectors.c.source_id == source_id,
                                                collectors.c.collector_id == collector_id))
            self.audit(db, team_id, actor, "source.collector_retired", collector_id)

    def revoke_tokens(self, team_id: str, source_id: str, actor: str):
        with self.engine.begin() as db:
            if not db.execute(select(sources.c.id).where(
                    sources.c.team_id == team_id, sources.c.id == source_id).with_for_update()).first():
                raise KeyError("Source not found")
            db.execute(update(tokens).where(tokens.c.source_id == source_id).values(revoked=True))
            self.audit(db, team_id, actor, "source.tokens_revoked", source_id)

    def revoke_token(self, team_id: str, source_id: str, token_id: str, actor: str):
        with self.engine.begin() as db:
            if not db.execute(select(sources.c.id).where(sources.c.team_id == team_id,
                    sources.c.id == source_id).with_for_update()).first():
                raise KeyError("Source not found")
            result = db.execute(update(tokens).where(tokens.c.source_id == source_id,
                tokens.c.id == token_id).values(revoked=True))
            if result.rowcount != 1:
                raise KeyError("Token not found")
            self.audit(db, team_id, actor, "source.token_revoked", token_id)

    def usage(self, team_id: str, project: str | None = None, source_id: str | None = None,
              include_fixtures=False, task_id: str | None = None, **pagination):
        from .queries import usage
        return usage(self, team_id, project, source_id, include_fixtures, task_id, **pagination)

    def enqueue(self, team_id: str, recording_id: str, actor: str, max_queued=20):
        revision, now = evaluation_revision()["sha256"], int(time.time())
        with self.engine.begin() as db:
            db.execute(select(teams.c.id).where(teams.c.id == team_id).with_for_update()).first()
            if not db.execute(select(recordings).where(recordings.c.team_id == team_id,
                    recordings.c.id == recording_id).with_for_update()).first():
                raise KeyError("Recording not found")
            previous = db.execute(select(jobs).where(jobs.c.team_id == team_id,
                jobs.c.recording_id == recording_id, jobs.c.revision == revision,
                jobs.c.status.in_(["queued", "running", "complete"])).order_by(
                    jobs.c.created_at.desc())).mappings().first()
            if previous:
                return self.public_job(previous)
            queued = db.execute(select(func.count()).select_from(jobs).where(
                jobs.c.team_id == team_id, jobs.c.status.in_(["queued", "running"]))).scalar_one()
            if queued >= max_queued:
                raise Conflict("Evaluation queue is full; wait for current jobs to finish")
            identity = uid()
            db.execute(insert(jobs).values(id=identity, team_id=team_id, recording_id=recording_id,
                revision=revision, status="queued", attempts=0, created_at=now))
            self.audit(db, team_id, actor, "evaluation.queued", identity)
            return {"id": identity, "status": "queued", "recording_id": recording_id,
                    "created_at": now, "attempts": 0, "revision": revision}

    def save_proposal(self, team_id, job_id, result, actor):
        identity = digest({"team": team_id, "job": job_id, "proposal": result})
        with self.engine.begin() as db:
            db.execute(select(teams.c.id).where(teams.c.id == team_id).with_for_update()).first()
            if not db.execute(select(proposals.c.id).where(proposals.c.id == identity)).first():
                db.execute(insert(proposals).values(id=identity, team_id=team_id, job_id=job_id,
                    payload=json.dumps(result), created_at=int(time.time())))
                self.audit(db, team_id, actor, "proposal.created", identity)
        return {"id": identity, "job_id": job_id, **result}

    def list_proposals(self, team_id):
        with self.engine.connect() as db:
            return [{"id": r["id"], "job_id": r["job_id"], "created_at": r["created_at"],
                     **json.loads(r["payload"])} for r in db.execute(select(proposals).where(
                proposals.c.team_id == team_id).order_by(proposals.c.created_at.desc()).limit(100)).mappings()]

    @staticmethod
    def public_job(row):
        return {key: row[key] for key in ("id", "recording_id", "status", "attempts",
                                         "created_at", "started_at", "finished_at", "error", "revision")}

    def job(self, team_id, identity, with_result=False):
        with self.engine.connect() as db:
            row = db.execute(select(jobs).where(jobs.c.team_id == team_id,
                jobs.c.id == identity)).mappings().first()
            if not row:
                raise KeyError("Evaluation not found")
            value = self.public_job(row)
            if with_result and row["result"]:
                value["analysis"] = json.loads(row["result"])
            return value

    def list_jobs(self, team_id):
        with self.engine.connect() as db:
            return [self.public_job(row) for row in db.execute(select(jobs).where(
                jobs.c.team_id == team_id).order_by(jobs.c.created_at.desc()).limit(100)).mappings()]

    def cancel(self, team_id, identity, actor):
        with self.engine.begin() as db:
            row = db.execute(select(jobs).where(jobs.c.team_id == team_id,
                jobs.c.id == identity).with_for_update()).mappings().first()
            if not row:
                raise KeyError("Evaluation not found")
            if row["status"] in {"queued", "running"}:
                db.execute(update(jobs).where(jobs.c.id == identity).values(
                    status="cancelled", owner=None, lease_until=None, finished_at=int(time.time())))
                self.audit(db, team_id, actor, "evaluation.cancelled", identity)
                return {"id": identity, "status": "cancelled", "cancelled": True}
            return {"id": identity, "status": row["status"], "cancelled": row["status"] == "cancelled"}

    def heartbeat(self, worker_id):
        with self.engine.begin() as db:
            if db.execute(select(workers.c.id).where(workers.c.id == worker_id)).first():
                db.execute(update(workers).where(workers.c.id == worker_id).values(
                    heartbeat_at=int(time.time())))
            else:
                db.execute(insert(workers).values(id=worker_id, heartbeat_at=int(time.time())))

    def worker_healthy(self, worker_id=None) -> bool:
        with self.engine.connect() as db:
            query = select(func.max(workers.c.heartbeat_at))
            if worker_id:
                query = query.where(workers.c.id == worker_id)
            latest = db.execute(query).scalar_one()
        return latest is not None and latest > time.time() - 45

    def claim(self, owner, lease_seconds=30, max_attempts=3):
        now = int(time.time())
        with self.engine.begin() as db:
            stale = db.execute(select(jobs).where(jobs.c.status == "running",
                jobs.c.lease_until < now).with_for_update(skip_locked=True)).mappings().all()
            for row in stale:
                retry = row["attempts"] < max_attempts
                db.execute(update(jobs).where(jobs.c.id == row["id"]).values(
                    status="queued" if retry else "failed", owner=None, lease_until=None,
                    error="Worker lease expired" if not retry else None,
                    finished_at=None if retry else now))
            row = db.execute(select(jobs).where(jobs.c.status == "queued").order_by(
                jobs.c.created_at).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not row:
                return None
            db.execute(update(jobs).where(jobs.c.id == row["id"]).values(status="running",
                owner=owner, lease_until=now + lease_seconds, started_at=now, attempts=row["attempts"] + 1))
            record = db.execute(select(recordings.c.payload).where(
                recordings.c.team_id == row["team_id"],
                recordings.c.id == row["recording_id"])).scalar_one()
            return dict(row) | {"owner": owner, "payload": json.loads(record)}

    def renew(self, identity, owner, lease_seconds=30):
        with self.engine.begin() as db:
            result = db.execute(update(jobs).where(jobs.c.id == identity, jobs.c.owner == owner,
                jobs.c.status == "running", jobs.c.lease_until >= int(time.time())).values(
                    lease_until=int(time.time()) + lease_seconds))
            return result.rowcount == 1

    def finish(self, identity, owner, result=None, error=None):
        with self.engine.begin() as db:
            row = db.execute(select(jobs).where(jobs.c.id == identity, jobs.c.owner == owner,
                jobs.c.status == "running", jobs.c.lease_until >= int(time.time())).with_for_update()).mappings().first()
            if not row:
                return False
            db.execute(update(jobs).where(jobs.c.id == identity).values(
                status="failed" if error else "complete", result=None if error else json.dumps(result),
                error=error, finished_at=int(time.time()), owner=None, lease_until=None))
            self.audit(db, row["team_id"], "worker", "evaluation.failed" if error else "evaluation.completed", identity)
            return True
