"""Opt-in scheduled collection of complete, versioned Legacy CUR CSV assemblies."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import signal
import threading
import time
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update

from .billing import BillingError, BillingUpload, MAX_BYTES, canonical, fingerprint, parse_upload
from .billing_acceptance import read_json
from .pilot import billing
from .pilot.database import Conflict, Database, billing_families, maintenance, teams


class CollectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    team_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    bucket_owner: str = Field(pattern=r"^[0-9]{12}$")
    manifest_key: str = Field(min_length=1, max_length=1024)
    account_id: str = Field(pattern=r"^[0-9]{12}$")
    month: str = Field(pattern=r"^20[0-9]{2}-(0[1-9]|1[0-2])$")
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    region: str = Field(default="us-east-1", pattern=r"^[a-z0-9-]{5,40}$")
    profile: str | None = Field(default=None, max_length=100)
    interval_seconds: int = Field(default=3600, ge=300, le=86400)

    @field_validator("manifest_key")
    @classmethod
    def safe_key(cls, value):
        if value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")) or "\\" in value:
            raise ValueError("Use an exact relative S3 manifest key")
        if not value.endswith("-Manifest.json") or len(value.split("/")) < 2:
            raise ValueError("Use the current monthly Legacy CUR manifest")
        return value

    @property
    def identity(self):
        # One scheduler status per billing scope; changing a location cannot hide failure.
        return "billing." + fingerprint([self.team_id, self.account_id, self.month, self.currency])[:32]


def client_for(config):
    import boto3
    from botocore.config import Config
    return boto3.Session(profile_name=config.profile, region_name=config.region).client(
        "s3", config=Config(connect_timeout=5, read_timeout=20,
                            retries={"total_max_attempts": 3, "mode": "standard"}))


def get_bytes(client, config, key, limit, *, etag=None):
    args = {"Bucket": config.bucket, "Key": key, "ExpectedBucketOwner": config.bucket_owner}
    if etag:
        args["IfMatch"] = etag
    response = client.get_object(**args)
    body = response["Body"]
    try:
        if response["ContentLength"] > limit:
            raise BillingError("An S3 billing object exceeds the supported byte limit.")
        content = body.read(limit + 1)
        if len(content) > limit or len(content) != response["ContentLength"]:
            raise BillingError("An S3 billing object is too large or incomplete.")
    finally:
        body.close()
    return content, response


def fetch_assembly(client, config):
    content, response = get_bytes(client, config, config.manifest_key, 1_000_000)
    manifest = json.loads(content)
    if not isinstance(manifest, dict):
        raise BillingError("Expected a Legacy CUR manifest object.")
    assembly, keys = manifest.get("assemblyId"), manifest.get("reportKeys")
    if not isinstance(assembly, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", assembly):
        raise BillingError("Collection requires a versioned Legacy CUR assembly.")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 20 or any(not isinstance(k, str) for k in keys):
        raise BillingError("A complete manifest must list between 1 and 20 report parts.")
    parent = str(PurePosixPath(config.manifest_key).parent)
    prefix = parent + "/" + assembly + "/"
    if len(set(keys)) != len(keys) or any(
        not k.startswith(prefix) or "/" in k[len(prefix):] or
        not k.endswith((".csv", ".csv.gz")) for k in keys
    ):
        raise BillingError("Use CSV or gzip CSV parts from one immutable assembly; overwrite, ZIP and Parquet reports are unsupported.")
    assembly_key = prefix + PurePosixPath(config.manifest_key).name
    assembly_content, _ = get_bytes(client, config, assembly_key, 1_000_000)
    if json.loads(assembly_content) != manifest:
        raise BillingError("The current and assembly manifests differ; retry after export delivery completes.")
    files, receipts, decoded_size, compressed_size = [], [], 0, 0
    for key in keys:
        head = client.head_object(Bucket=config.bucket, Key=key, ExpectedBucketOwner=config.bucket_owner)
        compressed_size += head["ContentLength"]
        if compressed_size > MAX_BYTES:
            raise BillingError("Complete compressed export exceeds the supported byte limit.")
        raw, meta = get_bytes(client, config, key, MAX_BYTES, etag=head["ETag"])
        decoded = raw
        if key.endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as archive:
                decoded = archive.read(MAX_BYTES - decoded_size + 1)
        decoded_size += len(decoded)
        if decoded_size > MAX_BYTES:
            raise BillingError("Complete decoded export exceeds the supported byte limit.")
        files.append(decoded.decode("utf-8"))
        receipts.append({"key": key, "etag": meta["ETag"], "version_id": meta.get("VersionId"),
                         "sha256": hashlib.sha256(raw).hexdigest()})
    # A newer generation invalidates this attempt. Import is still guarded by
    # the DB revision read before any network I/O.
    final, _ = get_bytes(client, config, config.manifest_key, 1_000_000, etag=response["ETag"])
    if final != content:
        raise BillingError("Billing manifest changed during collection; retry.")
    return files, {
        "method": "s3-legacy-cur-versioned-v1", "bucket": config.bucket,
        "manifest_key": config.manifest_key, "assembly_id": assembly,
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "manifest_etag": response["ETag"], "manifest_version_id": response.get("VersionId"),
        "parts": receipts,
        "notice": "Retrieved using configured AWS credentials and expected bucket owner; not independent invoice authentication.",
    }


def state(database, config, value):
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == config.team_id)
                   .with_for_update(key_share=True)).one()
        old = db.execute(select(maintenance).where(maintenance.c.id == config.identity)).mappings().first()
        payload = json.loads(old["payload"]) if old else {}
        payload.update(value, team_id=config.team_id, name=config.name,
                       interval_seconds=config.interval_seconds)
        if old:
            db.execute(update(maintenance).where(maintenance.c.id == config.identity).values(
                payload=canonical(payload), updated_at=int(time.time())))
        else:
            db.execute(insert(maintenance).values(id=config.identity, payload=canonical(payload),
                                                 updated_at=int(time.time())))
    return payload


def statuses(database, team):
    with database.engine.connect() as db:
        rows = db.execute(select(maintenance).where(maintenance.c.id.like("billing.%"))).mappings()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            if team is None or payload.get("team_id") == team:
                value = {key: payload.get(key) for key in (
                    "name", "status", "last_attempt_at", "last_success_at", "report_id",
                    "revision", "error", "interval_seconds")}
                value["stale"] = int(time.time()) - payload.get("last_attempt_at", 0) > 2 * payload["interval_seconds"]
                result.append(value)
    return result


def collect_once(database, config, client, *, dry_run=False):
    scope = fingerprint([config.account_id, config.month, config.currency, "imported"])
    with database.engine.connect() as db:
        if not db.execute(select(teams.c.id).where(teams.c.id == config.team_id)).first():
            raise BillingError("Configured Workbench team does not exist.")
        revision = db.execute(select(billing_families.c.current_revision).where(
            billing_families.c.team_id == config.team_id, billing_families.c.scope_key == scope)).scalar_one_or_none() or 0
    if not dry_run:
        state(database, config, {"status": "collecting", "last_attempt_at": int(time.time()), "error": None})
    try:
        files, receipt = fetch_assembly(client, config)
        upload = BillingUpload(format="legacy-cur", account_id=config.account_id, month=config.month,
                               currency=config.currency, name=config.name, files=files,
                               complete_snapshot=True, expected_revision=revision)
        parsed = parse_upload(upload)
        if dry_run:
            return {"status": "preview", "row_count": len(parsed["snapshot"]["rows"]),
                    "snapshot_sha256": parsed["fingerprint"], "parts": len(files)}
        result = billing.import_report(database, config.team_id, upload, "billing-collector",
                                       collection_receipt=receipt)
        state(database, config, {"status": "unchanged" if result["unchanged"] else "imported",
              "last_success_at": int(time.time()), "error": None, "report_id": result["id"],
              "revision": result["revision"], "manifest_sha256": receipt["manifest_sha256"]})
        return {"status": "unchanged" if result["unchanged"] else "imported", **result}
    except Exception as exc:
        if not dry_run:
            message = ("Collection failed. Check AWS access, complete versioned CSV delivery, configured scope, size limits, and concurrent imports.")
            if isinstance(exc, (BillingError, Conflict)):
                message = str(exc)  # These exceptions contain authored safe messages.
            else:
                from botocore.exceptions import ClientError
                if isinstance(exc, ClientError):
                    message = {
                        "AccessDenied": "AWS denied billing access. Check the configured role, expected bucket owner, and S3/KMS permissions.",
                        "NoSuchKey": "An expected export part is absent. Wait for complete delivery and verify the manifest location.",
                        "PreconditionFailed": "An S3 export changed while it was read. The next scheduled attempt will retry the complete generation.",
                        "ExpiredToken": "AWS credentials expired. Restore the collector's workload credentials.",
                    }.get(exc.response.get("Error", {}).get("Code"), message)
            state(database, config, {"status": "failed",
                "error": message})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.watch and args.dry_run:
        parser.error("Choose scheduled collection or a read-only preview")
    database = None
    try:
        config = CollectionConfig.model_validate(read_json(args.config, 100_000))
        from .pilot.config import Settings
        settings = Settings.from_env()
        database = Database(settings.database_url)
        database.check_schema()
        client = client_for(config)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        # The scheduler runs on one application host. Prevent two local watchers
        # for the same scope; DB revision checks also protect against other writers.
        import fcntl
        lock_path = args.config.parent / (config.identity + ".lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            while not stop.is_set():
                try:
                    print(json.dumps(collect_once(database, config, client, dry_run=args.dry_run)), flush=True)
                except Exception:
                    if not args.watch:
                        raise
                    print('{"status":"failed","detail":"Inspect collection status in Billing reconciliation."}', flush=True)
                if not args.watch:
                    break
                stop.wait(config.interval_seconds)
    except Exception:
        parser.exit(1, "Billing collection failed. Verify private configuration, database schema, AWS access, and supported export format.\n")
    finally:
        if database:
            database.engine.dispose()


if __name__ == "__main__":
    main()
