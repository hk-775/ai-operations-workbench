"""A small durable ledger with transactional, idempotent recording imports."""
import json
import sqlite3
from pathlib import Path

from .domain import digest
from .evidence import verify_recording


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "workbench.sqlite"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, imported_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.database, timeout=10)

    def import_recording(self, document: dict) -> dict:
        verify_recording(document)
        recording_id = digest(document)
        added = 0
        with self.connect() as db:
            for sample in document["samples"]:
                for stage in sample["stages"]:
                    # Provider IDs dedupe overlapping imports, not just identical files.
                    external_id = stage.get("provider_response_id")
                    event_id = ("openai:" + external_id if external_id else
                                f'{recording_id}:{sample["model"]}:{sample["case_id"]}:{stage["name"]}')
                    payload = {"model": sample["model"], "case_id": sample["case_id"], "stage": stage}
                    fingerprint = digest(payload)
                    old = db.execute("SELECT fingerprint FROM events WHERE id=?", (event_id,)).fetchone()
                    if old and old[0] != fingerprint:
                        raise ValueError("Conflicting data for an existing provider event; import rolled back")
                    if not old:
                        db.execute("INSERT INTO events VALUES (?,?,?)",
                                   (event_id, fingerprint, json.dumps(payload)))
                        added += 1
            db.execute("INSERT OR IGNORE INTO recordings(id,payload) VALUES (?,?)",
                       (recording_id, json.dumps(document)))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('active',?)", (recording_id,))
        return {"recording_id": recording_id, "added_events": added, "deduplicated": added == 0}

    def active(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("""SELECT payload FROM recordings
                WHERE id=(SELECT value FROM settings WHERE key='active')""").fetchone()
        return json.loads(row[0]) if row else None
