"""Prepare and restore a private backup bundle on a disposable SSM-only host.

Run as the dedicated workbench user. Never install source-host backup/metric
timers on the recovery host. No credential values or database rows are logged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

PRIVATE_FILES = ("production.env", "init.sql", "database_url", "postgres_admin_password",
                 "oidc_client_secret", "metrics_token", "admin_password")
SNAPSHOT = """
import hashlib,json,sys
from sqlalchemy import select
from sqlalchemy.engine import make_url
from workbench.pilot.config import Settings
from workbench.pilot.database import Database,metadata,teams,identities
url=Settings.from_env().database_url
if len(sys.argv)>1:
    url=make_url(url).set(database=sys.argv[1]).render_as_string(hide_password=False)
db=Database(url)
db.check_schema()
out={}
with db.engine.connect() as connection:
    role=connection.exec_driver_sql("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").one()
    assert role==(False,False,False)
    for table in metadata.sorted_tables:
        rows=sorted(json.dumps(dict(row),sort_keys=True,default=str) for row in connection.execute(select(table)).mappings())
        out[table.name]={"rows":len(rows),"sha256":hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
    team=connection.execute(select(teams.c.id)).scalar_one()
    links=len(connection.execute(select(identities)).all())
usage=db.usage(team)
result={"tables":out,"events":usage["events"],"api_estimate_usd":usage["api_estimate_usd"],
        "identity_links":links,"evaluations":len(db.list_jobs(team)),"reviews":len(db.list_proposals(team))}
db.engine.dispose()
print(json.dumps(result))
"""


def command(arguments, **kwargs):
    response = subprocess.run(arguments, capture_output=True, **kwargs)
    if response.returncode:
        # Diagnostics can include private paths. Keep them on the execution host.
        descriptor = os.open("/opt/workbench/recovery-command-error.log",
                             os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab") as log:
            log.write(response.stdout + b"\n" + response.stderr + b"\n")
        raise RuntimeError("Recovery command failed; inspect private host diagnostics")
    return response.stdout


def compose(root, label, *arguments, **kwargs):
    return command(["docker", "compose", "--env-file", ".pilot/production.env",
                    "-f", "compose.production.yaml", "-f", "compose.hosted-test.yaml",
                    *arguments], cwd=root/label, **kwargs)


def transfer(region, bucket, key, path, *, upload=False):
    remote = "s3://" + bucket + "/" + key
    arguments = ["aws", "--region", region, "s3", "cp"]
    arguments += [str(path), remote, "--sse", "AES256"] if upload else [remote, str(path)]
    command(arguments + ["--only-show-errors"])
    if not upload:
        path.chmod(0o600)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2))
    path.chmod(0o600)


def extract(archive, root, *, strip_root=False):
    """Only bounded regular files, unique safe names, and no symlinks."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) > 2000 or sum(item.size for item in members) > 150_000_000:
            raise ValueError("Recovery archive exceeds limits")
        seen = set()
        prefixes = set()
        for item in members:
            parts = Path(item.name).parts
            if not item.isfile() or not parts or Path(item.name).is_absolute() or ".." in parts:
                raise ValueError("Recovery archive contains an unsafe entry")
            if strip_root:
                prefixes.add(parts[0])
                parts = parts[1:]
            if not parts or parts in seen:
                raise ValueError("Recovery archive contains an ambiguous entry")
            seen.add(parts)
        if strip_root and len(prefixes) != 1:
            raise ValueError("Source archive must have one root")
        for item in members:
            parts = Path(item.name).parts[1:] if strip_root else Path(item.name).parts
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError("Recovery never overwrites existing files")
            with bundle.extractfile(item) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            target.chmod(0o600 if ".pilot" in parts else 0o644)


def prepare(args):
    """Read scheduled backups; restore controls to temporary source databases."""
    config = json.loads((args.root/"operations.json").read_text())
    metadata = {"schema": "workbench.recovery.inputs.v1", "created_at": time.time(), "workspaces": {},
                "source_machine_sha256": digest(Path("/etc/machine-id"))}
    with tempfile.TemporaryDirectory(prefix="workbench-recovery-inputs-") as temporary:
        staging = Path(temporary)
        for label in ("demo", "clean"):
            receipt_path = staging/(label+"-latest.json")
            transfer(args.region, args.bucket, "backups/"+label+"/latest.json", receipt_path)
            receipt = json.loads(receipt_path.read_text())
            if not receipt["key"].startswith("backups/"+label+"/") or not re.fullmatch(r"[a-f0-9]{64}", receipt["sha256"]):
                raise ValueError("Unexpected backup receipt")
            dump = staging/(label+".dump")
            transfer(args.region, args.bucket, receipt["key"], dump)
            if digest(dump) != receipt["sha256"]:
                raise ValueError("Scheduled backup checksum differs")
            database = "recovery_control_" + os.urandom(6).hex()
            created = False
            try:
                compose(args.root, label, "exec", "-T", "db", "createdb", "-U", "postgres", "-O", "workbench", database)
                created = True
                with dump.open("rb") as stream:
                    compose(args.root, label, "exec", "-T", "db", "pg_restore", "-U", "workbench",
                            "-d", database, "--no-owner", "--exit-on-error", stdin=stream)
                control = json.loads(compose(args.root, label, "exec", "-T", "app", "python", "-", database,
                                             input=SNAPSHOT.encode()))
            finally:
                if created:
                    compose(args.root, label, "exec", "-T", "db", "dropdb", "-U", "postgres", database)
            metadata["workspaces"][label] = {"backup": receipt, "control": control}
            target = staging/label/".pilot"
            target.mkdir(parents=True, mode=0o700)
            for name in PRIVATE_FILES:
                source = args.root/label/".pilot"/name
                if not source.is_file() or source.is_symlink():
                    raise ValueError("Missing private recovery configuration")
                shutil.copyfile(source, target/name)
                (target/name).chmod(0o600)
        # Pin account-owned origins without exposing them in terminal output.
        metadata["origins"] = config["origins"]
        write(staging/"inputs.json", metadata)
        archive = staging/"inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for label in ("demo", "clean"):
                for name in PRIVATE_FILES:
                    path = staging/label/".pilot"/name
                    bundle.add(path, arcname=str(path.relative_to(staging)), recursive=False)
            bundle.add(staging/"inputs.json", arcname="inputs.json", recursive=False)
        archive.chmod(0o600)
        transfer(args.region, args.bucket, args.prefix+"inputs.tar.gz", archive, upload=True)
        receipt = {"prepared": True, "input_sha256": digest(archive),
                   "workspaces": {label: {"tables": len(item["control"]["tables"]),
                                          "events": item["control"]["events"]}
                                  for label, item in metadata["workspaces"].items()}}
        print(json.dumps(receipt))


def restore(args):
    """Restore onto new volumes only; compare every table before workers start."""
    if not args.input_sha256 or not args.source_sha256:
        raise ValueError("Both private input and published source checksums are required")
    if any((args.root/label).exists() for label in ("demo", "clean")):
        raise ValueError("Recovery requires a fresh host without workspace directories")
    if not (args.root/"bootstrap-ready").is_file():
        raise ValueError("Host bootstrap is incomplete")
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="workbench-recovery-") as temporary:
        staging = Path(temporary)
        inputs, source = staging/"inputs.tar.gz", staging/"source.tar.gz"
        transfer(args.region, args.bucket, args.prefix+"inputs.tar.gz", inputs)
        transfer(args.region, args.bucket, args.prefix+"source.tar.gz", source)
        if digest(inputs) != args.input_sha256 or digest(source) != args.source_sha256:
            raise ValueError("Recovery input/source checksum differs")
        extract(inputs, staging/"private")
        metadata = json.loads((staging/"private"/"inputs.json").read_text())
        if metadata["source_machine_sha256"] == digest(Path("/etc/machine-id")):
            raise ValueError("Recovery must run on an independently provisioned machine")
        for label in ("demo", "clean"):
            root = args.root/label
            root.mkdir(mode=0o700)
            extract(source, root, strip_root=True)
            shutil.copytree(staging/"private"/label/".pilot", root/".pilot")
            (root/".pilot").chmod(0o700)
            for name in ("init.sql", "postgres_admin_password"):
                (root/".pilot"/name).chmod(0o444)
            environment = root/".pilot"/"production.env"
            text = environment.read_text()
            for key, value in (("WORKBENCH_RUN_UID", os.getuid()), ("WORKBENCH_RUN_GID", os.getgid())):
                text = re.sub(r"(?m)^"+key+r"=.*\n?", "", text)
                text += f"\n{key}={value}\n"
            environment.write_text(text)
        compose(args.root, "demo", "build", "app", "db")
        results = {}
        for label in ("demo", "clean"):
            compose(args.root, label, "up", "-d", "--wait", "db")
            expected = metadata["workspaces"][label]
            dump = staging/(label+".dump")
            transfer(args.region, args.bucket, expected["backup"]["key"], dump)
            if digest(dump) != expected["backup"]["sha256"]:
                raise ValueError("Backup changed after control preparation")
            with dump.open("rb") as stream:
                compose(args.root, label, "exec", "-T", "db", "pg_restore", "-U", "workbench",
                        "-d", "workbench", "--no-owner", "--exit-on-error", stdin=stream)
            actual = json.loads(compose(args.root, label, "run", "--rm", "--no-deps", "-T",
                                        "app", "python", "-", input=SNAPSHOT.encode()))
            if actual != expected["control"]:
                raise ValueError("Fresh-host database controls differ")
            compose(args.root, label, "run", "--rm", "--no-deps", "-T", "app",
                    "python", "-m", "workbench.pilot", "check-production")
            compose(args.root, label, "up", "-d", "--wait", "app", "worker", "maintenance")
            checks = json.loads(compose(args.root, label, "exec", "-T", "app", "python", "-", input=b"""
import json,os,urllib.request,urllib.error
from urllib.parse import urlsplit
checks={}
host=urlsplit(os.environ['WORKBENCH_PUBLIC_ORIGIN']).netloc
for path,expected in [('/health/ready',200),('/api/pilot/usage',401),('/metrics',401)]:
    request=urllib.request.Request('http://127.0.0.1:8768'+path,headers={'Host':host})
    try:
        with urllib.request.urlopen(request,timeout=15) as response:
            status=response.status
    except urllib.error.HTTPError as error:
        status=error.code
    checks[path]=status==expected
try:
    urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8768/health/ready',
                           headers={'Host':'invalid.example'}),timeout=15)
    checks['unrecognized_host_rejected']=False
except urllib.error.HTTPError as error:
    checks['unrecognized_host_rejected']=error.code==403
assert all(checks.values())
print(json.dumps(checks))
"""))
            results[label] = {"tables_verified": len(actual["tables"]), "all_table_hashes_equal": True,
                              "events": actual["events"], "identity_links": actual["identity_links"],
                              "evaluations": actual["evaluations"], "reviews": actual["reviews"],
                              "configuration_valid": True, "http_checks": checks,
                              "backup_age_seconds": round(started-expected["backup"]["finished_at"], 3)}
        receipt = {"schema": "workbench.recovery.result.v1", "passed": True,
                   "independent_host": True, "source_sha256": args.source_sha256,
                   "input_sha256": args.input_sha256, "workspaces": results,
                   "elapsed_seconds": round(time.time()-started, 3),
                   "scope": "Private fresh-host restore and local HTTP boundaries. No public DNS failover or new interactive SSO acceptance.",
                   "source_workspaces_restored_over": False, "source_timers_installed": False}
        path = staging/"result.json"
        write(path, receipt)
        transfer(args.region, args.bucket, args.prefix+"evidence/result.json", path, upload=True)
        print(json.dumps(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "restore"])
    parser.add_argument("--root", type=Path, default=Path("/opt/workbench"))
    parser.add_argument("--region", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--input-sha256")
    parser.add_argument("--source-sha256")
    args = parser.parse_args()
    if not re.fullmatch(r"bootstrap/recovery-[a-z0-9-]+/", args.prefix):
        parser.error("Use a dedicated bootstrap/recovery-<id>/ prefix")
    try:
        globals()[args.operation](args)
    except Exception:
        parser.exit(1, "Recovery failed. Preserve private evidence and inspect the disposable host; no credentials are printed.\n")


if __name__ == "__main__":
    main()
