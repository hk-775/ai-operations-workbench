"""Validate a fresh isolated database and restore using the shipped container."""
import json
import argparse
import secrets
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--env-file",default=".pilot/compose.env")
parser.add_argument("--compose-file",default="compose.pilot.yaml")
args = parser.parse_args()
compose = ["docker", "compose", "--env-file", args.env_file, "-f", args.compose_file]
identity = "pilot_smoke_" + secrets.token_hex(5)
restored = identity + "_restore"


def run(args, **kwargs):
    result = subprocess.run(compose + args, capture_output=True, **kwargs)
    if result.returncode:
        # Output from these commands can contain database internals; do not print it.
        raise RuntimeError(f"Container smoke step failed: {args[:4]}")
    return result.stdout


seed = r'''
import io, json, os, secrets, subprocess, sys, tempfile, zipfile
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy import select
from fastapi.testclient import TestClient
from workbench.pilot.config import Settings
from workbench.pilot.api import create_pilot_app
from workbench.pilot.database import Database, users
from workbench.pilot.worker import EvaluationWorker

database_name = sys.argv[1]
base = Path(os.environ["WORKBENCH_DATABASE_URL_FILE"]).read_text().strip()
url = make_url(base).set(database=database_name).render_as_string(hide_password=False)
with tempfile.TemporaryDirectory(prefix="pilot-bootstrap-check-") as directory:
    path = Path(directory)
    password = secrets.token_urlsafe(24)
    (path/"password").write_text(password)
    (path/"password").chmod(0o600)
    (path/"database").write_text(url)
    (path/"database").chmod(0o600)
    environment = dict(os.environ, WORKBENCH_DATABASE_URL_FILE=str(path/"database"))
    boot = subprocess.run([sys.executable, "-m", "workbench.pilot", "init",
        "--team", "Isolated smoke test", "--username", "smoke-admin",
        "--password-file", str(path/"password")], env=environment,
        capture_output=True, text=True)
    assert boot.returncode == 0, "Bootstrap failed"
    repeated = subprocess.run([sys.executable, "-m", "workbench.pilot", "init",
        "--team", "Should not replace", "--username", "smoke-admin",
        "--password-file", str(path/"password")], env=environment,
        capture_output=True, text=True)
    assert repeated.returncode != 0, "Bootstrap replaced an existing team"
    settings = Settings(url, public_origin="http://127.0.0.1:8769")
    app = create_pilot_app(settings)
    with app.state.database.engine.connect() as db:
        role = db.exec_driver_sql("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").one()
        assert role == (False,False,False), "Application database role is too privileged"
    with TestClient(app, base_url=settings.public_origin) as client:
        signed = client.post("/api/auth/login",json={"username":"smoke-admin","password":password})
        assert signed.status_code == 200
        client.headers["X-Workbench-CSRF"] = signed.json()["csrf"]
        coding = client.get("/api/pilot/coding/example")
        assert coding.status_code == 200, "Bundled coding evidence is unavailable"
        assert client.post("/api/pilot/coding/preview", json=coding.json()).status_code == 200
        calibration = client.get("/api/pilot/coding/calibration")
        assert calibration.status_code == 200, "Bundled recorded calibration is unavailable"
        assert client.post("/api/pilot/coding/preview", json=calibration.json()).status_code == 200
        assert client.get("/api/pilot/usage").json()["events"] == 0, "Preview changed workspace usage"
        sample = client.get("/api/pilot/billing/example-files")
        assert sample.status_code == 200, "Bundled billing sample is unavailable"
        with zipfile.ZipFile(io.BytesIO(sample.content)) as bundle:
            assert len(bundle.namelist()) == 6
            receipt = json.loads(bundle.read("bedrock-billing-sample/sample-check.json"))
            assert receipt["status"] == "fixture_checks_passed"
        assert client.get("/api/pilot/billing/collection").json() == {"collectors": []}
        imported = client.post("/api/pilot/recordings/example",json={}).json()
        queued = client.post("/api/pilot/evaluations",json={"recording_id":imported["recording_id"]}).json()
        assert EvaluationWorker(app.state.database, settings).run_once()
        result = client.get("/api/pilot/evaluations/"+queued["id"]).json()
        assert result["status"] == "complete", result.get("error")
        review = client.post("/api/pilot/evaluations/"+queued["id"]+"/recommend",json={}).json()
        assert review["status"] == "no_eligible_model"
        summary = client.get("/api/pilot/usage").json()
        assert summary["events"] == 144 and summary["api_estimate_usd"] == "0.088074750"
print(json.dumps({"bootstrap":"passed","nonsuperuser_role":"passed","container_evaluation":"passed",
                  "coding_preview":"passed","recorded_calibration":"passed","billing_sample":"passed"}))
'''

verify = r'''
import json, os, sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.engine import make_url
from workbench.pilot.database import Database, teams
from workbench.pilot.config import Settings
base=Path(os.environ["WORKBENCH_DATABASE_URL_FILE"]).read_text().strip()
url=make_url(base).set(database=sys.argv[1]).render_as_string(hide_password=False)
db=Database(url)
db.migrate()
with db.engine.connect() as connection:
    team=connection.execute(select(teams.c.id)).scalar_one()
usage=db.usage(team)
assert usage["events"] == 144 and usage["api_estimate_usd"] == "0.088074750"
jobs=db.list_jobs(team)
assert len(jobs)==1 and jobs[0]["status"]=="complete"
result=db.job(team,jobs[0]["id"],with_result=True)["analysis"]
assert [m["passed"] for m in result["models"]] == [20,18,14]
assert db.list_proposals(team)[0]["status"] == "no_eligible_model"
db.engine.dispose()
print(json.dumps({"restored_usage":"144 events","restored_estimate":"0.088074750",
                  "restored_evaluation":"passed","restored_routing_review":"passed"}))
'''

created = []
try:
    for name in (identity, restored):
        run(["exec","-T","db","createdb","-U","postgres","-O","workbench",name])
        created.append(name)
    print(run(["exec","-T","app","python","-",identity], input=seed.encode()).decode().strip())
    dump = run(["exec","-T","db","pg_dump","-U","workbench","-d",identity,"-Fc"])
    run(["exec","-T","db","pg_restore","-U","workbench","-d",restored,"--no-owner","--exit-on-error"],
        input=dump)
    print(run(["exec","-T","app","python","-",restored], input=verify.encode()).decode().strip())
finally:
    for name in reversed(created):
        run(["exec","-T","db","dropdb","-U","postgres",name])
