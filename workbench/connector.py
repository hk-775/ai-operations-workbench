"""Application metadata capture with a durable, replayable local outbox.

No prompts, responses or provider credentials are sent. API prices are determined
by Workbench; native tool-reported amounts use a separate, explicit cost basis.
Call IDs belong to the application; provider response IDs are correlation only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .domain import digest, strict_json
from .evidence import verify_recording
from .pilot.events import CollectorHealth, SOURCE_SCHEMAS, Usage, UsageEvent, event_adapter, recording_events


class DeliveryError(RuntimeError):
    """A bounded delivery failure; no transport or secret details are exposed."""


def now():
    return datetime.now(timezone.utc).isoformat()


class Outbox:
    """One outbox per logical ingestion source, retained across token rotation."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create privately before sqlite opens it; WAL files inherit database permissions.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                retry_after REAL NOT NULL DEFAULT 0)""")
            db.execute("CREATE TABLE IF NOT EXISTS destination (singleton INTEGER PRIMARY KEY, url TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS source_binding (singleton INTEGER PRIMARY KEY, source_id TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS connector_binding (singleton INTEGER PRIMARY KEY, kind TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS collector_identity (singleton INTEGER PRIMARY KEY, id TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO collector_identity VALUES (1, ?)", (uuid.uuid4().hex,))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def bind(self, endpoint):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT url FROM destination WHERE singleton=1").fetchone()
            if row and row["url"] != endpoint:
                raise ValueError("Use a separate outbox for a different Workbench destination")
            if not row:
                db.execute("INSERT INTO destination VALUES (1, ?)", (endpoint,))

    def put(self, event: UsageEvent):
        document = event.model_dump()
        fingerprint = digest(document)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._bind_kind(db, self.event_kind(event))
            row = db.execute("SELECT fingerprint FROM outbox WHERE id=?", (event.event_id,)).fetchone()
            if row and row["fingerprint"] != fingerprint:
                raise ValueError("An application event ID was reused with different data")
            if not row:
                db.execute("INSERT INTO outbox (id, fingerprint, payload) VALUES (?, ?, ?)",
                           (event.event_id, fingerprint, json.dumps(document)))

    def pending(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM outbox WHERE delivered=0").fetchone()[0]

    def bind_source(self, source_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT source_id FROM source_binding WHERE singleton=1").fetchone()
            if existing and existing["source_id"] != source_id:
                raise DeliveryError("Token belongs to a different source; use that source's own outbox")
            if not existing:
                db.execute("INSERT INTO source_binding VALUES (1, ?)", (source_id,))

    @staticmethod
    def event_kind(event):
        if event.schema_version == "coding-tool.usage.v1":
            return event.coding_tool.tool
        return {"axon.usage.v1": "axonllm", "bedrock.usage.v1": "bedrock"}[event.schema_version]

    @staticmethod
    def _kind(db):
        row = db.execute("SELECT kind FROM connector_binding WHERE singleton=1").fetchone()
        if row:
            return row["kind"]
        kinds = {row[0] for row in db.execute("""SELECT DISTINCT CASE
            json_extract(payload,'$.schema_version')
            WHEN 'axon.usage.v1' THEN 'axonllm'
            WHEN 'bedrock.usage.v1' THEN 'bedrock'
            WHEN 'coding-tool.usage.v1' THEN json_extract(payload,'$.coding_tool.tool')
            ELSE 'unsupported' END FROM outbox LIMIT 2""")}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_binding'").fetchone():
            native = db.execute("SELECT tool FROM native_binding WHERE singleton=1").fetchone()
            if native:
                kinds.add(native["tool"])
        if len(kinds) > 1 or any(kind not in SOURCE_SCHEMAS for kind in kinds):
            raise DeliveryError("Outbox contains incompatible connector types; preserve it for operator review")
        if kinds:
            kind = next(iter(kinds))
            db.execute("INSERT INTO connector_binding VALUES (1, ?)", (kind,))
            return kind
        return None

    @classmethod
    def _bind_kind(cls, db, kind):
        previous = cls._kind(db)
        if previous and previous != kind:
            raise DeliveryError("Use a separate outbox for another connector type")
        if not previous:
            db.execute("INSERT INTO connector_binding VALUES (1, ?)", (kind,))

    def connector_kind(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._kind(db)

    def reserve_kind(self, event):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._bind_kind(db, self.event_kind(event))

    def release_wrong_kind_binding(self, source_id, kind):
        """Only detach a source that could not have accepted this event schema."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            expected = self._kind(db)
            bound = db.execute("SELECT source_id FROM source_binding WHERE singleton=1").fetchone()
            if (not expected or kind not in SOURCE_SCHEMAS or expected == kind or not bound
                    or bound["source_id"] != source_id
                    or db.execute("SELECT 1 FROM outbox WHERE delivered=1 LIMIT 1").fetchone()):
                raise DeliveryError("Binding cannot be repaired safely; preserve this outbox for operator review")
            db.execute("DELETE FROM source_binding")
            db.execute("UPDATE outbox SET retry_after=0 WHERE delivered=0")

    def native_tool(self):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_binding'").fetchone():
                return None
            row = db.execute("SELECT tool FROM native_binding WHERE singleton=1").fetchone()
            return row["tool"] if row else None

    def batch(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM outbox WHERE delivered=0 AND retry_after<=? ORDER BY rowid LIMIT 100",
                (time.time(),))]

    def acknowledge(self, rows):
        with self.connect() as db:
            db.executemany("UPDATE outbox SET delivered=1 WHERE id=? AND fingerprint=?",
                           [(row["id"], row["fingerprint"]) for row in rows])

    def defer(self, rows):
        with self.connect() as db:
            for row in rows:
                delay = min(300, 2 ** min(row["attempts"] + 1, 9))
                db.execute("UPDATE outbox SET attempts=attempts+1, retry_after=? WHERE id=? AND delivered=0",
                           (time.time() + delay, row["id"]))

    def recover_interrupted(self):
        """Operator backfill is explicit: all unacknowledged events become retryable."""
        with self.connect() as db:
            db.execute("UPDATE outbox SET retry_after=0 WHERE delivered=0")

    def health(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) AS pending,
                COALESCE(SUM(CASE WHEN attempts>0 THEN 1 ELSE 0 END),0) AS retrying,
                MIN(json_extract(payload,'$.occurred_at')) AS oldest
                FROM outbox WHERE delivered=0""").fetchone()
            identity = db.execute("SELECT id FROM collector_identity WHERE singleton=1").fetchone()[0]
        inflight = sum(1 for _ in Path(str(self.path) + ".inflight").glob("*.json"))
        return CollectorHealth(collector_id=identity, pending_events=row["pending"],
            retrying_events=row["retrying"], oldest_pending_at=row["oldest"], inflight_calls=inflight)


class Connector:
    def __init__(self, endpoint: str, token: str, outbox: Outbox, *, client=None, report_health=False):
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or
                parsed.path.rstrip("/") != "/api/pilot/ingest"):
            raise ValueError("Use the Workbench /api/pilot/ingest endpoint")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Non-loopback connector delivery requires HTTPS")
        if not token.startswith("wb_ing_") or len(token) > 100:
            raise ValueError("An ingestion token is required")
        self.endpoint, self.token, self.outbox = endpoint, token, outbox
        self.outbox.bind(endpoint)
        self.client = client
        self.report_health = report_health

    def heartbeat(self, client):
        try:
            response = client.post(self.endpoint + "/health",
                headers={"Authorization": f"Bearer {self.token}"}, json=self.outbox.health().model_dump())
            if response.status_code != 200 or response.json().get("accepted") is not True:
                raise ValueError("Health report rejected")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DeliveryError("Collector heartbeat failed; check Workbench version and source token") from None

    def flush(self, max_batches=10):
        """Bounded delivery; acknowledgments may be retried safely after a crash."""
        sent = 0
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) if self.client is None else _borrow(self.client) as client:
            try:
                identity = client.get(self.endpoint, headers={"Authorization": f"Bearer {self.token}"})
                if identity.status_code != 200:
                    raise DeliveryError("Cannot verify ingestion source; check token and Workbench availability")
                source_id = identity.json()["source_id"]
                if not isinstance(source_id, str) or len(source_id) != 36:
                    raise ValueError("Invalid source identity")
                kind = self.outbox.connector_kind()
                received_kind = identity.json().get("kind")
                # Older Axon/Bedrock servers may expose the schema without kind.
                if received_kind is None:
                    received_kind = {"axon.usage.v1": "axonllm", "bedrock.usage.v1": "bedrock"}.get(
                        identity.json().get("schema_version"))
                if kind and received_kind != kind:
                    raise DeliveryError("Choose a source token matching this outbox's connector type")
                if kind:
                    self.outbox.bind_source(source_id)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise DeliveryError("Cannot verify ingestion source; events remain in the outbox") from None
            if self.report_health:
                if not identity.json().get("collector_health"):
                    raise DeliveryError("Upgrade Workbench for collector health, or explicitly use --no-health")
                self.heartbeat(client)
            for _ in range(max_batches):
                rows = self.outbox.batch()
                if not rows:
                    break
                try:
                    response = client.post(self.endpoint, headers={"Authorization": f"Bearer {self.token}"},
                        json={"events": [json.loads(row["payload"]) for row in rows]})
                    if response.status_code != 200:
                        self.outbox.defer(rows)
                        if response.status_code in {401, 403}:
                            raise DeliveryError("Ingestion denied; check or rotate the source token")
                        if response.status_code in {409, 413, 422}:
                            raise DeliveryError("Batch rejected; inspect event IDs and schema before retrying")
                        raise DeliveryError("Workbench unavailable; events remain in the outbox")
                    receipt = response.json()
                    if receipt["added_events"] + receipt["duplicate_events"] != len(rows):
                        raise ValueError("Incomplete acknowledgment")
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    self.outbox.defer(rows)
                    raise DeliveryError("No valid acknowledgment; events remain in the outbox") from None
                self.outbox.acknowledge(rows)
                sent += len(rows)
            if self.report_health:
                self.heartbeat(client)
        return {"acknowledged": sent, "pending": self.outbox.pending()}

    def repair_source_binding(self):
        """Authenticate the original wrong-kind source before releasing its fence."""
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) if self.client is None else _borrow(self.client) as client:
            try:
                response = client.get(self.endpoint, headers={"Authorization": f"Bearer {self.token}"},
                                      follow_redirects=False)
                response.raise_for_status()
                identity = response.json()
                kind = identity.get("kind") or {
                    "axon.usage.v1": "axonllm", "bedrock.usage.v1": "bedrock"
                }.get(identity.get("schema_version"))
                self.outbox.release_wrong_kind_binding(identity["source_id"], kind)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise DeliveryError("Cannot verify the original wrong source; binding was preserved") from None
        return {"repaired": True, "pending": self.outbox.pending()}


class _borrow:
    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self.client

    def __exit__(self, *_):
        return False


def response_event(response, *, event_id, task_id, project, stage, latency_ms,
                   occurred_at=None, usage_basis="unknown", attempt_coverage="final_response_only"):
    """Adapt AxonLLM's public ChatCompletionResponse without copying its content.

    Mark usage provider_reported only after verifying the provider adapter. Some
    adapters estimate missing usage. Default coverage never claims retries are captured.
    """
    usage = response.usage
    return UsageEvent(event_id=event_id, task_id=task_id, project=project, stage=stage,
        provider=response.provider, model=response.provider_model or response.model,
        occurred_at=occurred_at or now(), status="success", usage_basis=usage_basis,
        attempt_coverage=attempt_coverage,
        usage=Usage(**{key: getattr(usage, key, 0) for key in Usage.model_fields}),
        latency_ms=float(latency_ms), provider_response_id=response.id)


async def capture_completion(router, outbox: Outbox, *, task_id: str, project: str,
                             stage: str, usage_basis="unknown", attempt_coverage="final_response_only",
                             **request):
    """Wrap a nonstreaming call; network delivery is a separate supervised process.

    Durably enqueue a pending event before calling the model. A crash can leave
    that pending call unknown; it cannot masquerade as a free or missing call.
    This function raises if local persistence fails instead of silently losing usage.
    """
    if request.get("stream"):
        raise ValueError("This pilot connector supports nonstreaming completions")
    identity, started, timestamp = uuid.uuid4().hex, time.monotonic(), now()
    pending = UsageEvent(event_id=identity, task_id=task_id, project=project, stage=stage,
        model=request["model"], provider="unknown", occurred_at=timestamp,
        status="interrupted", latency_ms=0.0)
    # A mutable local reservation is not eligible for delivery until finalized.
    call_file = reserve_call(outbox, pending)
    try:
        response = await router.chat.completions.create(**request)
    except BaseException as exc:
        event = pending.model_copy(update={"status": "interrupted" if isinstance(
            exc, asyncio.CancelledError) else "error", "latency_ms": (time.monotonic() - started) * 1000})
        outbox.put(event)
        call_file.unlink()
        raise
    event = response_event(response, event_id=identity, task_id=task_id, project=project,
        stage=stage, latency_ms=(time.monotonic() - started) * 1000, occurred_at=timestamp,
        usage_basis=usage_basis, attempt_coverage=attempt_coverage)
    outbox.put(event)
    call_file.unlink()
    return response


def reserve_call(outbox, pending):
    """Persist metadata before the billable operation; sync directory entries too."""
    outbox.reserve_kind(pending)
    reservation = Path(str(outbox.path) + ".inflight")
    reservation.mkdir(mode=0o700, exist_ok=True)
    call_file = reservation / (pending.event_id + ".json")
    descriptor = os.open(call_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(pending.model_dump(), handle)
        handle.flush()
        os.fsync(handle.fileno())
    for directory in (reservation, reservation.parent):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return call_file


def recover_inflight(outbox):
    """Run only after stopping capture processes; an interrupted call has unknown cost."""
    directory = Path(str(outbox.path) + ".inflight")
    if not directory.exists():
        return 0
    recovered = 0
    for path in directory.glob("*.json"):
        event = event_adapter.validate_python(strict_json(path.read_text()))
        with outbox.connect() as db:
            exists = db.execute("SELECT id FROM outbox WHERE id=?", (event.event_id,)).fetchone()
        if not exists:
            outbox.put(event)
            recovered += 1
        path.unlink()
    return recovered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outbox", type=Path, required=True)
    command = parser.add_subparsers(dest="command", required=True)
    backfill = command.add_parser("backfill")
    backfill.add_argument("recording", type=Path)
    command.add_parser("recover-inflight")
    command.add_parser("status")
    command.add_parser("repair-source-binding",
        help="Use the ORIGINAL wrong-kind source token to repair an unacknowledged outbox")
    delivery = command.add_parser("deliver")
    delivery.add_argument("--watch", action="store_true")
    delivery.add_argument("--no-health", action="store_true", help="Compatibility with pre-connector-health servers")
    args = parser.parse_args()
    outbox = Outbox(args.outbox)
    if args.command == "backfill":
        recording = strict_json(args.recording.read_text())
        verify_recording(recording)
        for event in recording_events(recording):
            outbox.put(event)
        print(f"{outbox.pending()} recorded events ready for delivery. No model calls made.")
    elif args.command == "recover-inflight":
        print(f"{recover_inflight(outbox)} interrupted calls recovered with unknown costs.")
    elif args.command == "status":
        print(outbox.health().model_dump_json())
    else:
        token_file = os.environ.get("WORKBENCH_INGEST_TOKEN_FILE")
        token = Path(token_file).read_text().strip() if token_file else os.environ.get("WORKBENCH_INGEST_TOKEN", "")
        connector = Connector(os.environ.get("WORKBENCH_INGEST_URL", ""), token, outbox,
                              report_health=not getattr(args, "no_health", False))
        if args.command == "repair-source-binding":
            try:
                print(json.dumps(connector.repair_source_binding()))
            except DeliveryError as exc:
                parser.exit(1, f"{exc}\n")
            return
        while True:
            try:
                result = connector.flush()
                if not args.watch:
                    print(json.dumps(result))
                    if result["pending"]:
                        parser.exit(1, "Events remain pending; retry after backoff or use --watch.\n")
            except DeliveryError as exc:
                if not args.watch:
                    parser.exit(1, f"{exc}\n")
                print(str(exc), flush=True)
            if not args.watch:
                break
            time.sleep(5)


if __name__ == "__main__":
    main()
