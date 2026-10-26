"""Measure an isolated synthetic PostgreSQL workload; never uses a customer schema."""
import argparse
import json
import os
import secrets
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from workbench.pilot import auth
from workbench.pilot.api import create_pilot_app
from workbench.pilot.config import Settings


def percentile(values, fraction=.95):
    return round(sorted(values)[max(0, int(len(values) * fraction) - 1)] * 1000, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file",type=Path,required=True)
    parser.add_argument("--events",type=int,default=25000)
    parser.add_argument("--output",type=Path,default=Path("artifacts/load-check.json"))
    args = parser.parse_args()
    if not 1000 <= args.events <= 100000 or args.events % 100:
        parser.error("Use 1,000–100,000 events, in batches of 100")
    url = args.database_url_file.read_text().strip()
    schema = "workbench_load_" + secrets.token_hex(6)
    engine = create_engine(url,hide_parameters=True)
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = make_url(url).update_query_dict({"options":f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    try:
        app = create_pilot_app(Settings(scoped))
        password = secrets.token_urlsafe(24)
        app.state.database.initialize("Isolated synthetic load","load-admin",auth.password_hash(password))
        with TestClient(app,base_url="http://127.0.0.1:8768") as client:
            signed = client.post("/api/auth/login",json={"username":"load-admin","password":password}).json()
            client.headers["X-Workbench-CSRF"] = signed["csrf"]
            source = client.post("/api/pilot/sources",json={"name":"Synthetic load fixture"}).json()["id"]
            token = client.post(f"/api/pilot/sources/{source}/token",json={}).json()["token"]
            request_headers = {"Authorization":"Bearer "+token}
            timings = []
            started = time.monotonic()
            for offset in range(0,args.events,100):
                batch = [{"event_id":f"fixture-{n}","task_id":f"task-{n//2}","project":"synthetic-load",
                    "stage":"draft","provider":"openai","model":"gpt-4.1-2025-04-14",
                    "occurred_at":datetime.now(timezone.utc).isoformat(),"status":"success","latency_ms":100.0,
                    "evidence":"fixture","usage_basis":"provider_reported","attempt_coverage":"single_attempt",
                    "usage":{"prompt_tokens":1000,"completion_tokens":100,"cached_tokens":200}}
                    for n in range(offset,offset+100)]
                before = time.monotonic()
                response = client.post("/api/pilot/ingest",json={"events":batch},headers=request_headers)
                assert response.status_code == 200 and response.json()["added_events"] == 100
                timings.append(time.monotonic()-before)
            ingest_seconds = time.monotonic()-started
            query_times = []
            for page in range(20):
                before = time.monotonic()
                response = client.get("/api/pilot/usage",params={"include_fixtures":"true","page":page})
                query_times.append(time.monotonic()-before)
                data = response.json()
                assert response.status_code == 200 and data["events"] == args.events
                assert len(data["tasks"]) == 50
            assert client.get("/api/pilot/usage").json()["events"] == 0
            report = {"workload":"synthetic metadata; not model performance or customer traffic",
                "database":"PostgreSQL","events":args.events,"tasks":args.events//2,
                "batch_size":100,"ingest_seconds":round(ingest_seconds,2),
                "events_per_second":round(args.events/ingest_seconds,2),
                "ingest_batch_p95_ms":percentile(timings),"usage_page_p95_ms":percentile(query_times),
                "correct_totals":True,"fixtures_excluded_by_default":True,
                "limitation":"Single-client local API/database check; not a production capacity guarantee."}
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,indent=2)+"\n")
            print(json.dumps(report))
    finally:
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


if __name__ == "__main__":
    main()
