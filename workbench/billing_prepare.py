"""Prepare private billing acceptance files without AWS access or invented totals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .billing import BillingUpload
from .billing_acceptance import Controls, read_json, write_private
from .billing_collection import CollectionConfig


def prepare(directory: Path):
    # Exclusive creation preserves existing customer evidence and configurations.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_private(directory / "acceptance.json", {
        "upload": {"format": "legacy-cur", "account_id": None, "month": None,
                   "currency": "USD", "name": "Private billing acceptance",
                   "files": [], "complete_snapshot": False},
        "reconciliation_file": "reconciliation.json",
        "controls": {key: None for key in Controls.model_fields},
    })
    write_private(directory / "collection.json", {
        "name": "Private monthly billing collection", "team_id": None,
        "bucket": None, "bucket_owner": None, "manifest_key": None,
        "account_id": None, "month": None, "currency": "USD",
        "region": "us-east-1", "interval_seconds": 3600,
    })
    write_private(directory / "review.json", {
        "origin_verified": False, "complete_export_generation": False,
        "controls_independent_of_workbench": False,
        "matching_capture_scope_confirmed": False,
        "export_delivery_and_revision_replay_observed": False,
        "collector_failure_and_recovery_observed": False,
    })
    (directory / "README.txt").write_text(
        "PREPARATION ONLY: no real billing acceptance or S3 delivery has been verified.\n"
        "Fill acceptance.json from the billing owner's independent totals and application run log.\n"
        "Keep every CSV part and the downloaded reconciliation.json in this private directory.\n"
        "Do not substitute the fictional billing sample for customer evidence.\n"
        "Fill collection.json only for supported versioned Legacy CUR CSV/gzip assemblies.\n"
        "Review origin, completeness and mappings; record attestations in review.json.\n"
        "Run: uv run --locked python -m workbench.billing_prepare check --directory PATH\n"
        "Then run workbench.billing_acceptance --config PATH/acceptance.json --output PATH/receipt.json\n"
        "Collection dry-run reads S3; offline preparation does not. See docs/BILLING-COLLECTION.md.\n"
        "Scheduled collection needs its own delivery, replacement, replay, and failure/recovery drill.\n"
        "Do not commit this directory, receipts, exports, account IDs, or credentials.\n"
    )
    (directory / "README.txt").chmod(0o600)


def preflight(directory: Path):
    """Return missing-input categories only; never echo billing values or secrets."""
    missing = []
    try:
        config = read_json(directory / "acceptance.json")
        upload = dict(config["upload"])
        files = upload["files"]
        if not files or len(files) > 20:
            raise ValueError
        texts = []
        total_bytes = 0
        for name in files:
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file() or path.stat().st_size > 8_000_000:
                raise ValueError
            total_bytes += path.stat().st_size
            if total_bytes > 8_000_000:
                raise ValueError
            texts.append(path.read_text())
        upload["files"] = texts
        BillingUpload.model_validate(upload)
        if upload["complete_snapshot"] is not True:
            raise ValueError
        Controls.model_validate(config["controls"])
        report = (directory / config["reconciliation_file"]).resolve()
        if not report.is_relative_to(directory.resolve()):
            raise ValueError
        value = read_json(report)
        if value.get("evidence") != "imported":
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        missing.append("complete_billing_files_scope_independent_controls_and_imported_reconciliation")
    try:
        CollectionConfig.model_validate(read_json(directory / "collection.json"))
    except (OSError, ValueError, TypeError):
        missing.append("supported_s3_collection_configuration")
    try:
        review = read_json(directory / "review.json")
        expected = {"origin_verified", "complete_export_generation",
                    "controls_independent_of_workbench", "matching_capture_scope_confirmed"}
        if any(review.get(key) is not True for key in expected):
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError):
        missing.append("billing_owner_attestations")
    return {
        "schema": "workbench.billing.preparation.v1",
        "status": "missing_inputs" if missing else "ready_for_acceptance_check",
        "missing": missing, "aws_calls": 0,
        "real_billing_acceptance": "pending",
        "scheduled_delivery_acceptance": "pending",
        "notice": "Readiness checks shape and local inputs only. Run acceptance and observe S3 delivery separately.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "check"))
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            prepare(args.directory)
        report = preflight(args.directory)
        write_private(args.directory / "readiness.json", report)
        print(json.dumps(report))
        if args.command == "check" and report["missing"]:
            raise SystemExit(2)
    except (OSError, ValueError):
        parser.exit(1, "Preparation failed. Use a new private directory or check the input files.\n")


if __name__ == "__main__":
    main()
