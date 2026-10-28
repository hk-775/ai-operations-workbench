"""Check private billing evidence against independently supplied control totals."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .billing import (BillingError, BillingUpload, difference, financial, fingerprint,
                      groups, parse_upload, total)


class Controls(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    imported_charges: str
    positive_charges: str
    negative_adjustments: str
    row_count: int = Field(ge=1, le=20_000)
    captured_calls: int = Field(ge=1)
    comparable_estimate_usd: str
    reviewer: str = Field(min_length=1, max_length=100)


def check(upload: BillingUpload, exported: dict, controls: Controls, *, fixture=False):
    """No writes, repricing, AWS queries, or calls to models."""
    parsed = parse_upload(upload, fixture=fixture)
    snapshot = parsed["snapshot"]
    if exported.get("billing_snapshot") != snapshot or exported.get("fingerprint") != parsed["fingerprint"]:
        raise BillingError("The reconciliation export does not match the supplied complete billing snapshot.")
    if exported.get("evidence") != ("fixture" if fixture else "imported"):
        raise BillingError("Real-data acceptance requires imported evidence, not the fictional example.")
    for key in ("account_id", "month", "currency"):
        if exported.get(key) != snapshot[key]:
            raise BillingError("Reconciliation scope differs from the billing files.")
    values = [r["amount"] for r in snapshot["rows"]]
    from decimal import Decimal
    observed = {
        "imported_charges": total(values),
        "positive_charges": total(v for v in values if Decimal(v) > 0),
        "negative_adjustments": total(v for v in values if Decimal(v) < 0),
        "row_count": len(values),
    }
    comparisons = exported.get("comparisons", [])
    if not comparisons or any(c.get("status") != "comparison_available" or
                              c.get("comparable_estimate_usd") is None or c.get("limitations") or
                              c.get("unknown_cost_calls") or c.get("incomplete_calls") or
                              c.get("usage_retention_gap") or type(c.get("calls")) is not int or
                              c["calls"] < 1 for c in comparisons):
        raise BillingError("Matching captured usage is absent or incomplete; real-data acceptance remains pending.")
    known_groups = {g["id"]: g["charge_amount"] for g in groups(snapshot)}
    linked = set()
    for comparison in comparisons:
        selected = comparison["group_ids"]
        if len(set(selected)) != len(selected) or linked.intersection(selected) or not set(selected) <= known_groups.keys():
            raise BillingError("Comparison groups are invalid or counted more than once.")
        linked.update(selected)
        amount = total(known_groups[g] for g in selected)
        if comparison["billing_charge_amount"] != amount or comparison["difference_usd"] != difference(
                amount, financial(comparison["comparable_estimate_usd"])):
            raise BillingError("A comparison's financial arithmetic does not reconcile.")
    linked_amount = total(known_groups[g] for g in linked)
    unassigned = total(amount for g, amount in known_groups.items() if g not in linked)
    if (exported.get("imported_charges"), exported.get("linked_charges"),
        exported.get("unassigned_charges")) != (observed["imported_charges"], linked_amount, unassigned):
        raise BillingError("Linked and unassigned amounts do not reconcile to the imported total.")
    observed["captured_calls"] = sum(c["calls"] for c in comparisons)
    observed["comparable_estimate_usd"] = total(c["comparable_estimate_usd"] for c in comparisons)
    expected = controls.model_dump(exclude={"reviewer"})
    for name, value in expected.items():
        normalized = financial(value) if isinstance(value, str) else value
        if observed[name] != normalized:
            raise BillingError(f"Independent control mismatch: {name}.")
    return {
        "schema": "workbench.billing.acceptance.v1",
        "status": "fixture_checks_passed" if fixture else "checks_passed",
        "evidence": "fixture" if fixture else "operator_supplied",
        "snapshot_sha256": parsed["fingerprint"],
        "reconciliation_sha256": fingerprint(exported),
        "controls_sha256": fingerprint(controls.model_dump()),
        "checks": list(expected) + ["snapshot_identity", "scope", "comparison_arithmetic",
                                   "unassigned_preserved"],
        "row_count": observed["row_count"], "captured_calls": observed["captured_calls"],
        "limitations": [
            *(["Authored sample only. This is not real-bill acceptance."] if fixture else []),
            "Operator-supplied files and control totals; no independent invoice authentication.",
            "The reviewer must confirm origin, export completeness, source scope, and control-total independence.",
            "Passing this sample does not validate every export configuration or allocate invoice costs to tasks.",
        ],
    }


def read_json(path: Path, limit=16_500_000):
    with path.open("rb") as source:
        content = source.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Input exceeds its size limit")
    return json.loads(content)


def write_private(path: Path, document):
    """Atomic owner-only receipt, including when replacing an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, name = tempfile.mkstemp(prefix=".workbench-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(document, output, indent=2)
            output.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fixture", action="store_true", help="Check explicitly fictional example evidence")
    args = parser.parse_args()
    try:
        config = read_json(args.config, 100_000)
        upload = dict(config["upload"])
        files = []
        for name in upload["files"]:
            path = (args.config.parent / name).resolve()
            if path.stat().st_size > 8_000_000:
                raise ValueError("CSV input exceeds the byte limit")
            files.append(path.read_text(encoding="utf-8"))
        upload["files"] = files
        report = read_json(args.config.parent / config["reconciliation_file"])
        receipt = check(BillingUpload.model_validate(upload), report,
                        Controls.model_validate(config["controls"]), fixture=args.fixture)
        write_private(args.output, receipt)
    except (OSError, ValueError, KeyError, TypeError):
        # Configuration validation can contain original billing cells; keep it private.
        parser.exit(1, "Acceptance failed: verify private inputs, scope, complete usage, and independent control totals.\n")
    print("Fictional sample checks passed; real-bill acceptance remains pending." if args.fixture else
          "Billing acceptance checks passed. Private receipt written; reviewer origin/completeness checks still apply.")


if __name__ == "__main__":
    main()
