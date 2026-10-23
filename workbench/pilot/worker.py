"""A supervised offline evaluator with persisted jobs, leases, and fencing."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from workbench.domain import ROOT, evaluation_revision
from .database import Database, uid


class EvaluationWorker:
    def __init__(self, database: Database, settings):
        self.database, self.settings, self.identity = database, settings, uid()
        self.stopping = False

    def run_once(self):
        self.database.heartbeat(self.identity)
        job = self.database.claim(self.identity, self.settings.lease_seconds,
                                  self.settings.max_job_attempts)
        if not job:
            return False
        if job["revision"] != evaluation_revision()["sha256"]:
            self.database.finish(job["id"], self.identity,
                                 error="Evaluator version changed; queue a new evaluation")
            return True
        process = None
        try:
            with tempfile.TemporaryDirectory(prefix="workbench-evaluation-") as directory:
                path = Path(directory)
                (path / "input.json").write_text(json.dumps(job["payload"]))
                # Allowlist only runtime essentials. No database, connector, or provider credentials.
                environment = {key: os.environ[key] for key in (
                    "PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR") if key in os.environ}
                environment["PYTHONUNBUFFERED"] = "1"
                process = subprocess.Popen(
                    [sys.executable, "-m", "workbench.worker", "replay", str(path / "input.json"),
                     "--output", str(path / "result.json")], cwd=ROOT, env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                started, renewed = time.monotonic(), time.monotonic()
                while process.poll() is None:
                    if self.stopping:
                        # Do not acknowledge: the persisted lease makes this job recoverable.
                        return True
                    if time.monotonic() - started > self.settings.job_timeout:
                        self.database.finish(job["id"], self.identity,
                                             error="Evaluation exceeded its execution timeout")
                        return True
                    if time.monotonic() - renewed >= min(5, self.settings.lease_seconds / 3):
                        self.database.heartbeat(self.identity)
                        if not self.database.renew(job["id"], self.identity, self.settings.lease_seconds):
                            return True  # cancelled, reassigned, or expired
                        renewed = time.monotonic()
                    time.sleep(.1)
                if process.returncode or not (path / "result.json").is_file():
                    self.database.finish(job["id"], self.identity,
                                         error="The offline evaluator could not validate this recording")
                    return True
                result = json.loads((path / "result.json").read_text())
                if result["evaluation_revision"]["sha256"] != job["revision"]:
                    self.database.finish(job["id"], self.identity,
                                         error="Evaluator provenance changed during execution")
                else:
                    self.database.finish(job["id"], self.identity, result=result)
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
        return True

    def run(self):
        Path("/tmp/workbench-worker-id").write_text(self.identity)
        def stop(*_):
            self.stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not self.stopping:
            try:
                if not self.run_once():
                    time.sleep(.5)
            except Exception:
                # Database errors may contain transport details: never echo their text.
                print("Worker unavailable; retrying. Check database connectivity.", file=sys.stderr)
                time.sleep(1)
