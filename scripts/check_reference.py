"""Concurrent HTTP, abandoned lease, and separate-container restore reference drill.

Creates and removes only randomly named, disposable Docker Compose projects.
No existing workspace, AWS resource, customer data or model API is used.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from contextlib import closing
import hashlib
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.billing_acceptance import write_private


def percentile(values, fraction=.95):
    if not values:
        return None
    return round(sorted(values)[math.ceil(len(values) * fraction) - 1] * 1000, 3)


class Stack:
    def __init__(self, root, image, postgres_image, label):
        self.project = "wb-reference-" + secrets.token_hex(8) + "-" + label
        self.directory = root / label
        self.directory.mkdir(mode=0o700)
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeError("Docker is required")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.password = secrets.token_urlsafe(28)
        database_password = secrets.token_urlsafe(28)
        for name, value in {
            "admin": self.password, "postgres": secrets.token_urlsafe(28),
            "database": f"postgresql+psycopg://workbench:{database_password}@db:5432/workbench",
            "init.sql": f"CREATE ROLE workbench LOGIN PASSWORD '{database_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;\nCREATE DATABASE workbench OWNER workbench;\n",
        }.items():
            path = self.directory / name
            path.write_text(value)
            path.chmod(0o444 if name in {"postgres", "init.sql"} else 0o600)
        runtime = {
            "image": image, "pull_policy": "never", "init": True, "read_only": True,
            "user": f"{os.getuid()}:{os.getgid()}",
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=256m,mode=1777"],
            "mem_limit": "768m", "cpus": 1.5,
            "environment": {"WORKBENCH_MODE": "pilot",
                "WORKBENCH_DATABASE_URL_FILE": "/run/secrets/database",
                "WORKBENCH_PUBLIC_ORIGIN": self.origin},
            "volumes": [f"{self.directory}/database:/run/secrets/database:ro",
                        f"{self.directory}/admin:/run/secrets/admin:ro"],
        }
        document = {"services": {
            "db": {"image": postgres_image, "pull_policy": "never",
                "environment": {"POSTGRES_PASSWORD_FILE": "/run/secrets/postgres"},
                "volumes": ["data:/var/lib/postgresql/data",
                    f"{self.directory}/postgres:/run/secrets/postgres:ro",
                    f"{self.directory}/init.sql:/docker-entrypoint-initdb.d/workbench.sql:ro"],
                "mem_limit": "512m", "cpus": 1,
                "healthcheck": {"test": ["CMD", "pg_isready", "-U", "workbench", "-d", "workbench"],
                                "interval": "2s", "timeout": "3s", "retries": 30}},
            "app": runtime | {"ports": [f"127.0.0.1:{self.port}:8768"],
                "healthcheck": {"test": ["CMD", "python", "scripts/healthcheck.py"],
                                "interval": "2s", "timeout": "5s", "retries": 30}},
            "worker": runtime | {"command": ["python", "-m", "workbench.pilot", "worker"]},
        }, "volumes": {"data": {}}}
        write_private(self.directory / "compose.json", document)

    def run(self, args, *, input=None, timeout=180):
        # Explicit project and generated configuration; never use a caller's default Compose stack.
        result = subprocess.run([self.docker, "compose", "-p", self.project,
            "-f", str(self.directory / "compose.json"), *args],
            input=input, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("Reference container step failed: " + " ".join(args[:3]))
        return result.stdout

    def python(self, code):
        return self.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-"],
                        input=code.encode())

    def database(self):
        self.run(["up", "-d", "--wait", "db"])

    def bootstrap(self):
        self.run(["run", "--rm", "--no-deps", "-T", "app", "python", "-m", "workbench.pilot",
                  "init", "--team", "Isolated reference", "--username", "reference-admin",
                  "--password-file", "/run/secrets/admin"])

    def start(self):
        self.run(["up", "-d", "--wait", "app", "worker"])

    def close(self):
        self.run(["down", "--volumes", "--remove-orphans"])


def request(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code != 200:
        raise RuntimeError(f"Reference HTTP check failed ({response.status_code})")
    return response.json()


def login(stack, password=None):
    client = httpx.Client(base_url=stack.origin, timeout=60, trust_env=False)
    try:
        signed = request(client, "POST", "/api/auth/login",
                         json={"username": "reference-admin", "password": password or stack.password})
        client.headers["X-Workbench-CSRF"] = signed["csrf"]
        return client
    except Exception:
        client.close()
        raise


def workload(stack, admin, *, events, clients, seconds):
    source = request(admin, "POST", "/api/pilot/sources", json={"name": "Reference load fixture"})["id"]
    token = request(admin, "POST", f"/api/pilot/sources/{source}/token", json={})["token"]
    timestamp = datetime.now(timezone.utc).isoformat()
    batches = [[{"event_id": f"reference-{n}", "task_id": f"task-{n//2}",
        "project": "reference-load", "stage": "draft", "provider": "openai",
        "model": "gpt-4.1-2025-04-14", "occurred_at": timestamp, "status": "success",
        "latency_ms": 100.0, "evidence": "fixture", "usage_basis": "provider_reported",
        "attempt_coverage": "single_attempt",
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 200}}
        for n in range(offset, offset + 100)] for offset in range(0, events, 100)]
    def ingest(index):
        with httpx.Client(base_url=stack.origin, timeout=60, trust_env=False) as client:
            before = time.monotonic()
            value = request(client, "POST", "/api/pilot/ingest",
                            headers={"Authorization": "Bearer " + token},
                            json={"events": batches[index]})
            return value, time.monotonic() - before
    before = time.monotonic()
    # Submit each immutable batch twice, interleaved, including overlapping replay.
    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        replies = list(pool.map(ingest, [n for n in range(len(batches)) for _ in range(2)]))
    ingest_seconds = time.monotonic() - before
    if (sum(row["added_events"] for row, _ in replies) != events or
            sum(row["duplicate_events"] for row, _ in replies) != events):
        raise RuntimeError("Concurrent replay accounting differs")
    deadline = time.monotonic() + seconds
    def reader(_):
        timings = []
        with httpx.Client(base_url=stack.origin, cookies=admin.cookies, timeout=60, trust_env=False) as client:
            while time.monotonic() < deadline:
                started = time.monotonic()
                value = request(client, "GET", "/api/pilot/usage",
                                params={"include_fixtures": "true", "source_id": source,
                                        "page": len(timings) % min(10, events // 100)})
                timings.append(time.monotonic() - started)
                if value["events"] != events or len(value["tasks"]) != 50:
                    raise RuntimeError("Sustained usage pagination lost rows")
                time.sleep(.1)  # Explicit closed-loop pacing; not an arrival-rate capacity claim.
        return timings
    soak_start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        reads = [item for result in pool.map(reader, range(clients)) for item in result]
    if request(admin, "GET", "/api/pilot/usage")["events"] != 0:
        raise RuntimeError("Fixture exclusion differs")
    return {"events": events, "tasks": events // 2, "concurrent_clients": clients,
        "ingest_requests": len(replies), "added_events": events, "duplicate_events": events,
        "ingest_seconds": round(ingest_seconds, 3),
        "ingest_batch_p95_ms": percentile([elapsed for _, elapsed in replies]),
        "soak_requested_seconds": seconds, "soak_elapsed_seconds": round(time.monotonic() - soak_start, 3),
        "read_requests": len(reads), "usage_page_p95_ms": percentile(reads),
        "http_errors": 0, "fixture_exclusion": True,
        "traffic": "Concurrent replay, followed by concurrent reads paced 100 ms per client; synthetic metadata only"}


SNAPSHOT = """
import hashlib,json
from sqlalchemy import select
from workbench.pilot.config import Settings
from workbench.pilot.database import Database,metadata
db=Database(Settings.from_env().database_url)
out={}
with db.engine.connect() as connection:
    role=connection.exec_driver_sql("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").one()
    assert role==(False,False,False)
    for table in metadata.sorted_tables:
        rows=sorted(json.dumps(dict(row),sort_keys=True,default=str) for row in connection.execute(select(table)).mappings())
        out[table.name]={"rows":len(rows),"sha256":hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
db.engine.dispose()
print(json.dumps(out))
"""


def exercise(source, destination, args):
    print("Starting disposable reference services.", flush=True)
    source.database()
    source.bootstrap()
    source.start()
    with closing(login(source)) as client:
        print("Running concurrent ingest/replay and paced HTTP soak.", flush=True)
        load = workload(source, client, events=args.events, clients=args.clients, seconds=args.seconds)
        print("Checking abandoned worker lease recovery and stale-owner fencing.", flush=True)
        recorded = request(client, "POST", "/api/pilot/recordings/example", json={})
        # Stop our worker, abandon a real short lease in a process that exits, then recover it.
        source.run(["stop", "worker"])
        job = request(client, "POST", "/api/pilot/evaluations",
                      json={"recording_id": recorded["recording_id"]})
        source.python("""
from workbench.pilot.database import Database
from workbench.pilot.config import Settings
db=Database(Settings.from_env().database_url)
assert db.claim("reference-abandoned-owner",lease_seconds=5)
db.engine.dispose()
""")
        source.run(["start", "worker"])
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = request(client, "GET", "/api/pilot/evaluations/" + job["id"])
            if result["status"] == "complete":
                break
            if result["status"] == "failed":
                raise RuntimeError("Recovered evaluation failed")
            time.sleep(.5)
        else:
            raise RuntimeError("Expired worker lease did not recover")
        review = request(client, "POST", "/api/pilot/evaluations/" + job["id"] + "/recommend", json={})
        if review["status"] != "no_eligible_model":
            raise RuntimeError("Saved routing review differs")
        bill = request(client, "POST", "/api/pilot/billing/example", json={})
        billing = request(client, "GET", "/api/pilot/billing/reports/" + bill["id"] + "/export")
        if billing["evidence"] != "fixture":
            raise RuntimeError("Reference billing must stay fictional")
        expected_usage = request(client, "GET", "/api/pilot/usage", params={"include_fixtures": "true"})
        recovery = json.loads(source.python("""
import json
from sqlalchemy import select,func
from workbench.pilot.database import Database,jobs,audits
from workbench.pilot.config import Settings
db=Database(Settings.from_env().database_url)
with db.engine.connect() as c:
    job=c.execute(select(jobs)).mappings().one()
    completed=c.execute(select(func.count()).select_from(audits).where(audits.c.action=="evaluation.completed")).scalar_one()
    assert job["attempts"]==2 and completed==1
    identity=job["id"]
assert db.finish(identity,"reference-abandoned-owner",error="stale") is False
print(json.dumps({"expired_lease_reclaimed":True,"attempts":2,"completion_audits":completed,"stale_owner_fenced":True}))
db.engine.dispose()
"""))
    source.run(["stop", "app", "worker"])
    print("Restoring a consistent backup into a separate PostgreSQL container.", flush=True)
    before = json.loads(source.python(SNAPSHOT))
    started = time.monotonic()
    dump = source.run(["exec", "-T", "db", "pg_dump", "-U", "workbench", "-d", "workbench", "-Fc"])
    # Separate server, volume, network and generated database credentials.
    destination.database()
    destination.run(["exec", "-T", "db", "pg_restore", "-U", "workbench", "-d", "workbench",
                     "--no-owner", "--exit-on-error"], input=dump)
    after = json.loads(destination.python(SNAPSHOT))
    if before != after:
        raise RuntimeError("Restored table counts or content hashes differ")
    destination.start()
    with closing(login(destination, source.password)) as client:
        restored = request(client, "GET", "/api/pilot/usage", params={"include_fixtures": "true"})
        if restored != expected_usage:
            raise RuntimeError("Restored HTTP usage differs")
        saved = request(client, "GET", "/api/pilot/evaluations/" + job["id"])
        if saved["status"] != "complete":
            raise RuntimeError("Restored evaluation is unavailable")
        saved_bill = request(client, "GET", "/api/pilot/billing/reports/" + bill["id"] + "/export")
        # Ledger exports may carry execution timestamps; immutable snapshot/accounting must match.
        for key in ("billing_snapshot", "fingerprint", "comparisons", "imported_charges",
                    "linked_charges", "unassigned_charges"):
            if saved_bill[key] != billing[key]:
                raise RuntimeError("Restored Ledger accounting differs")
    return {"schema": "workbench.reference-acceptance.v1", "status": "reference_checks_passed",
        "created_at": datetime.now(timezone.utc).isoformat(), "load": load, "worker": recovery,
        "runtime": {"app_image": args.image, "postgres_image": args.postgres_image,
                    "app_cpus": 1.5, "app_memory_mb": 768, "database_cpus": 1, "database_memory_mb": 512},
        "restore": {"separate_postgres_container": True, "same_docker_host": True,
            "tables_verified": len(before), "table_counts_and_hashes_equal": True,
            "usage_http_equal": True, "evaluation_available": True, "billing_accounting_equal": True,
            "backup_sha256": hashlib.sha256(dump).hexdigest(), "backup_bytes": len(dump),
            "drill_seconds": round(time.monotonic() - started, 3)},
        "model_calls": 0, "external_api_cost_usd": "0", "hardware_and_electricity_cost_usd": None,
        "limitations": [
            "Single Docker host and pilot password login over loopback HTTP; not fresh AWS host, HA, company SSO/TLS or MFA acceptance.",
            "Synthetic paced reference load; no customer capacity/SLO claim or long-term leak certification.",
            "Offline evaluation replays saved evidence. Billing uses the fictional example, not customer bills.",
            "Human alert delivery, real scheduled export delivery and customer traffic acceptance remain pending.",
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Locally built release app image")
    parser.add_argument("--postgres-image", default="ai-operations-workbench-postgres:0.2.0")
    parser.add_argument("--events", type=int, default=25000)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1000 <= args.events <= 100000 or args.events % 100 or not 2 <= args.clients <= 16 or not 10 <= args.seconds <= 3600:
        parser.error("Use 1,000–100,000 events in batches of 100, 2–16 clients, and 10–3,600 soak seconds")
    stacks = []
    try:
        for attribute in ("image", "postgres_image"):
            result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}",
                                     getattr(args, attribute)], capture_output=True, text=True, check=True)
            setattr(args, attribute, result.stdout.strip())
        with tempfile.TemporaryDirectory(prefix="workbench-reference-") as directory:
            try:
                for label in ("source", "restore"):
                    stacks.append(Stack(Path(directory), args.image, args.postgres_image, label))
                report = exercise(*stacks, args)
            finally:
                failures = []
                for stack in reversed(stacks):
                    try:
                        stack.close()
                    except Exception:
                        failures.append(stack.project)
                if failures:
                    print("Cleanup required for owned projects: " + ", ".join(failures), flush=True)
                    raise RuntimeError("Remove these isolated reference projects: " + ", ".join(failures))
        write_private(args.output, report)
        print(json.dumps(report))
    except Exception as exc:
        # Avoid printing Docker/HTTP/DB exception bodies containing private transport details.
        detail = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        parser.exit(1, f"Reference drill failed: {detail}; no acceptance receipt written.\n")


if __name__ == "__main__":
    main()
