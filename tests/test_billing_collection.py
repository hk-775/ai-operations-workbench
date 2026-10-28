"""S3 protocol failures and durable import behavior, using authored objects."""
import gzip
import hashlib
import io
import json
import time

import pytest
from sqlalchemy import insert, select

from test_billing import upload
from test_pilot import pilot, settings
from workbench.billing import BillingError
from workbench.billing_collection import CollectionConfig, collect_once, fetch_assembly, get_bytes, state, statuses
from workbench.pilot import billing
from workbench.pilot.database import Conflict, teams, uid
from workbench.pilot.operations import snapshot


class S3:
    def __init__(self, config, content=None, assembly="generation-1"):
        self.config = config
        parent = config.manifest_key.rsplit("/", 1)[0]
        key = parent + f"/{assembly}/part-1.csv.gz"
        manifest = json.dumps({"assemblyId": assembly, "reportKeys": [key]}).encode()
        self.objects = {config.manifest_key: manifest,
                        parent + f"/{assembly}/report-Manifest.json": manifest,
                        key: gzip.compress((content or upload().files[0]).encode())}
        self.part = key
        self.reads = []

    def head_object(self, *, Bucket, Key, ExpectedBucketOwner):
        assert Bucket == self.config.bucket and ExpectedBucketOwner == self.config.bucket_owner
        raw = self.objects[Key]
        return {"ContentLength": len(raw), "ETag": '"' + hashlib.sha256(raw).hexdigest() + '"'}

    def get_object(self, **kwargs):
        self.reads.append(kwargs["Key"])
        etag = kwargs.pop("IfMatch", None)
        meta = self.head_object(**kwargs)
        if etag and etag != meta["ETag"]:
            raise RuntimeError("precondition failed")
        return {**meta, "Body": io.BytesIO(self.objects[kwargs["Key"]])}


def config(team):
    return CollectionConfig(name="Authored collector", team_id=team, bucket="test-billing",
                            bucket_owner="123456789012", account_id="000000000000",
                            manifest_key="reports/20261001-20261101/report-Manifest.json", month="2026-10")


def test_full_assembly_import_replay_refresh_and_durable_status(pilot):
    cfg = config(pilot.team)
    client = S3(cfg)
    assert collect_once(pilot.db, cfg, client, dry_run=True)["status"] == "preview"
    assert statuses(pilot.db, pilot.team) == []
    first = collect_once(pilot.db, cfg, client)
    assert first["revision"] == 1
    assert collect_once(pilot.db, cfg, client)["unchanged"]
    report = billing.reconcile(pilot.db, pilot.team, first["id"], export=True)
    assert report["imported_charges"] == "0.0121475"
    assert report["provenance"]["collection"]["parts"][0]["sha256"]
    changed = S3(cfg, upload(changes={"lineItem/UnblendedCost": "0.5"}).files[0], "generation-2")
    assert collect_once(pilot.db, cfg, changed)["revision"] == 2
    assert billing.reconcile(pilot.db, pilot.team, first["id"])["imported_charges"] == "0.0121475"
    with pytest.raises(Conflict, match="superseded"):
        collect_once(pilot.db, cfg, client)
    status = statuses(pilot.db, pilot.team)[0]
    assert status["status"] == "failed" and status["revision"] == 2 and status["last_success_at"]
    assert snapshot(pilot.db, pilot.settings, pilot.team)["failed_billing_collectors"] == 1


@pytest.mark.parametrize("failure", ["missing-part", "wrong-account", "manifest-change", "gzip-bomb", "overwrite", "cross-prefix"])
def test_invalid_or_changing_delivery_never_replaces_snapshot(pilot, failure):
    cfg = config(pilot.team)
    good = collect_once(pilot.db, cfg, S3(cfg))
    broken = S3(cfg, assembly="generation-2")
    if failure == "missing-part":
        del broken.objects[broken.part]
    elif failure == "wrong-account":
        broken = S3(cfg, upload(changes={"lineItem/UsageAccountId": "111111111111"}).files[0], "generation-2")
    elif failure == "gzip-bomb":
        broken.objects[broken.part] = gzip.compress(b"x" * 8_000_001)
    elif failure in ("overwrite", "cross-prefix"):
        body = json.loads(broken.objects[cfg.manifest_key])
        body["reportKeys"] = [cfg.manifest_key.rsplit("/", 1)[0] + "/part.csv.gz" if failure == "overwrite" else "another-report/generation-2/part.csv.gz"]
        broken.objects[cfg.manifest_key] = json.dumps(body).encode()
    else:
        original = broken.get_object
        def change(**kwargs):
            if kwargs["Key"] == broken.part:
                broken.objects[cfg.manifest_key] += b" "
            return original(**kwargs)
        broken.get_object = change
    with pytest.raises((BillingError, KeyError, RuntimeError)):
        collect_once(pilot.db, cfg, broken)
    reports = billing.list_reports(pilot.db, pilot.team)["reports"]
    assert len(reports) == 1 and reports[0]["id"] == good["id"]
    assert statuses(pilot.db, pilot.team)[0]["status"] == "failed"


def test_competing_manual_import_is_not_overwritten(pilot):
    cfg = config(pilot.team)
    client = S3(cfg)
    original = client.get_object
    def concurrent(**kwargs):
        if not client.reads:
            billing.import_report(pilot.db, pilot.team, upload(changes={"lineItem/UnblendedCost": "5"}), "admin")
        return original(**kwargs)
    client.get_object = concurrent
    with pytest.raises(Conflict, match="changed"):
        collect_once(pilot.db, cfg, client)
    assert billing.list_reports(pilot.db, pilot.team)["reports"][0]["charges"] == "25"


def test_collection_status_is_team_scoped_and_stale(pilot):
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other, name="Other"))
    state(pilot.db, config(other), {"status": "failed", "last_attempt_at": int(time.time())})
    cfg = config(pilot.team)
    state(pilot.db, cfg, {"status": "unchanged", "last_attempt_at": 1})
    response = pilot.client.get("/api/pilot/billing/collection")
    assert response.status_code == 200 and len(response.json()["collectors"]) == 1
    assert response.json()["collectors"][0]["stale"]
    assert "team_id" not in response.text and "bucket" not in response.text


def test_s3_get_protocol_and_stream_close():
    import boto3
    from botocore.response import StreamingBody
    from botocore.stub import Stubber
    cfg = config("00000000-0000-0000-0000-000000000000")
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    stream = io.BytesIO(b"bounded")
    with Stubber(client) as stub:
        stub.add_response("get_object", {"Body": StreamingBody(stream, 7), "ContentLength": 7, "ETag": '"etag"'},
                          {"Bucket": cfg.bucket, "Key": "part", "ExpectedBucketOwner": cfg.bucket_owner, "IfMatch": '"etag"'})
        assert get_bytes(client, cfg, "part", 8, etag='"etag"')[0] == b"bounded"
        assert stream.closed
