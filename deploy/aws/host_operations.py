"""Hosted-test backup and metrics jobs. Secrets stay on the host; output is metadata."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request


def aws(config, *arguments, **kwargs):
    result = subprocess.run(["aws", "--region", config["region"], *arguments],
                            capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError("AWS operation failed: "+" ".join(arguments[:2]))
    return result.stdout


def compose(root, label, *arguments, **kwargs):
    result = subprocess.run([
        "docker", "compose", "--env-file", ".pilot/production.env",
        "-f", "compose.production.yaml", "-f", "compose.hosted-test.yaml", *arguments,
    ], cwd=root/label, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(label+" container operation failed: "+" ".join(arguments[:3]))
    return result.stdout


def backup(root, config):
    results = []
    for label in ("demo", "clean"):
        start = time.time()
        with tempfile.TemporaryDirectory(prefix="workbench-backup-") as temporary:
            dump = Path(temporary)/"database.dump"
            # Stream the dump to a private file; never hold it in a log or terminal.
            with dump.open("wb") as stream:
                dump.chmod(0o600)
                result = subprocess.run([
                    "docker", "compose", "--env-file", ".pilot/production.env",
                    "-f", "compose.production.yaml", "-f", "compose.hosted-test.yaml",
                    "exec", "-T", "db", "pg_dump", "-U", "workbench", "-d", "workbench", "-Fc",
                ], cwd=root/label, stdout=stream, stderr=subprocess.PIPE)
            if result.returncode or dump.stat().st_size < 100:
                raise RuntimeError(label+" database backup failed")
            digest = hashlib.sha256(dump.read_bytes()).hexdigest()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            key = "backups/"+label+"/"+stamp+".dump"
            aws(config, "s3", "cp", str(dump), "s3://"+config["bucket"]+"/"+key,
                "--sse", "AES256", "--only-show-errors")
            head = json.loads(aws(config, "s3api", "head-object",
                                  "--bucket", config["bucket"], "--key", key))
            if head["ContentLength"] != dump.stat().st_size or head["ServerSideEncryption"] != "AES256":
                raise RuntimeError("Off-host backup verification failed")
            receipt = {"instance": label, "key": key, "sha256": digest,
                       "bytes": dump.stat().st_size, "finished_at": time.time(),
                       "duration_seconds": round(time.time()-start, 3)}
            manifest = Path(temporary)/"latest.json"
            manifest.write_text(json.dumps(receipt))
            aws(config, "s3", "cp", str(manifest),
                "s3://"+config["bucket"]+"/backups/"+label+"/latest.json",
                "--sse", "AES256", "--only-show-errors")
            results.append(receipt)
    print(json.dumps({"backup": results}))


def metrics(root, config):
    data = []
    for label in ("demo", "clean"):
        try:
            with urllib.request.urlopen(config["origins"][label]+"/health/ready", timeout=15) as response:
                ready = int(response.status == 200 and json.load(response).get("status") == "ready")
        except Exception:
            ready = 0
        try:
            # The manifest is metadata only. Data dumps are never fetched by monitoring.
            receipt = json.loads(aws(config, "s3", "cp",
                "s3://"+config["bucket"]+"/backups/"+label+"/latest.json", "-", "--only-show-errors"))
            age = max(0, time.time()-receipt["finished_at"])
        except Exception:
            age = 1_000_000
        for name, value in (("Ready", ready), ("BackupAgeSeconds", age)):
            data.append({"MetricName": name, "Dimensions": [
                {"Name": "Deployment", "Value": config["deployment"]},
                {"Name": "Instance", "Value": label}],
                "Value": value, "Unit": "Seconds" if name.endswith("Seconds") else "Count"})
    aws(config, "cloudwatch", "put-metric-data", "--namespace", "Workbench/HostedTest",
        "--metric-data", json.dumps(data))
    print(json.dumps({"published": len(data), "sampled_at": time.time()}))


def restore(root, config, label):
    """Download the actual scheduled backup and restore into an isolated database."""
    receipt = json.loads(aws(config, "s3", "cp",
        "s3://"+config["bucket"]+"/backups/"+label+"/latest.json", "-", "--only-show-errors"))
    database = "restore_"+os.urandom(6).hex()
    with tempfile.TemporaryDirectory(prefix="workbench-restore-") as temporary:
        dump = Path(temporary)/"database.dump"
        aws(config, "s3", "cp", "s3://"+config["bucket"]+"/"+receipt["key"],
            str(dump), "--only-show-errors")
        dump.chmod(0o600)
        if hashlib.sha256(dump.read_bytes()).hexdigest() != receipt["sha256"]:
            raise RuntimeError("Backup checksum mismatch")
        created = False
        started = time.time()
        try:
            compose(root, label, "exec", "-T", "db", "createdb", "-U", "postgres", "-O", "workbench", database)
            created = True
            with dump.open("rb") as stream:
                compose(root, label, "exec", "-T", "db", "pg_restore", "-U", "workbench",
                        "-d", database, "--no-owner", "--exit-on-error", stdin=stream)
            source = r'''
import json, os, sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.engine import make_url
from workbench.pilot.database import Database, teams, identities
base=Path(os.environ["WORKBENCH_DATABASE_URL_FILE"]).read_text().strip()
db=Database(make_url(base).set(database=sys.argv[1]).render_as_string(hide_password=False))
db.check_schema()
with db.engine.connect() as connection:
    team=connection.execute(select(teams.c.id)).scalar_one()
    links=len(connection.execute(select(identities)).all())
usage=db.usage(team)
jobs=db.list_jobs(team)
reviews=db.list_proposals(team)
expected=144 if sys.argv[2]=="demo" else 0
assert usage["events"] == expected
assert usage["api_estimate_usd"] == ("0.088074750" if expected else "0.000000000")
assert links == 1
assert len(jobs) == (1 if expected else 0)
assert len(reviews) == (1 if expected else 0)
if expected:
    assert jobs[0]["status"]=="complete"
    assert reviews[0]["status"]=="no_eligible_model"
db.engine.dispose()
print(json.dumps({"events":usage["events"],"api_estimate_usd":usage["api_estimate_usd"],
                  "identity_links":links,"evaluations":len(jobs),"reviews":len(reviews)}))
'''
            result = json.loads(compose(root, label, "exec", "-T", "app", "python", "-", database, label,
                                        input=source.encode()))
            print(json.dumps({"restore": label, "backup_key": receipt["key"],
                              "checksum_verified": True, "result": result,
                              "seconds": round(time.time()-started, 3)}))
        finally:
            if created:
                compose(root, label, "exec", "-T", "db", "dropdb", "-U", "postgres", database)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "metrics", "restore"])
    parser.add_argument("--root", type=Path, default=Path("/opt/workbench"))
    parser.add_argument("--instance", choices=["demo", "clean"], default="demo")
    args = parser.parse_args()
    configuration = json.loads((args.root/"operations.json").read_text())
    if args.operation == "restore":
        restore(args.root, configuration, args.instance)
    else:
        globals()[args.operation](args.root, configuration)
