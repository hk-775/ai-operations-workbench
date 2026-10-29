"""Portable routing-review evidence. Hashes detect changes, not provider authenticity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .coding import fingerprint
from .domain import digest, strict_json

SCHEMA = "ai-ops.routing-evidence.v1"
MEMBERS = ("proposal", "analysis", "recording")


def verify_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise ValueError("Unsupported routing evidence bundle")
    manifest = bundle.get("manifest")
    if not isinstance(manifest, dict) or set(manifest) != set(MEMBERS):
        raise ValueError("Incomplete evidence manifest")
    for name in MEMBERS:
        if not isinstance(bundle.get(name), dict) or fingerprint(bundle[name]) != manifest[name]:
            raise ValueError(f"Evidence checksum mismatch: {name}")
    proposal, analysis, recording = (bundle[name] for name in MEMBERS)
    revision = analysis.get("evaluation_revision")
    if (recording.get("schema") != "ai-ops.recording.v1" or recording.get("mode") not in {"live", "fixture"}
            or not isinstance(recording.get("samples"), list) or not recording["samples"]
            or not isinstance(analysis.get("tasks"), list) or not analysis["tasks"]
            or not isinstance(revision, dict) or not isinstance(revision.get("sha256"), str)
            or len(revision["sha256"]) != 64):
        raise ValueError("Incomplete recording or evaluation identity")
    recording_id = digest(recording)
    if proposal.get("recording_id") != recording_id or analysis.get("recording_id") != recording_id:
        raise ValueError("Recording identity does not match the saved review")
    if proposal.get("evaluation_revision") != revision["sha256"]:
        raise ValueError("Evaluator identity does not match the saved review")
    if analysis.get("mode") != recording.get("mode"):
        raise ValueError("Evidence mode does not match the recording")
    return bundle


def evidence_bundle(proposal, analysis, recording):
    members = dict(proposal=proposal, analysis=analysis, recording=recording)
    return verify_bundle({
        "schema": SCHEMA,
        "integrity_note": "Checksums detect edits; they do not attest provider authenticity. "
                          "This is the saved evaluation, not a replay with today's evaluator.",
        "privacy_note": "Contains saved requests, model answers, and assessments. Share only with authorized reviewers.",
        "omitted": ["Workspace account, credential and audit tables", "Other recordings and captured usage",
                    "Evaluator source files (saved hash references are included)"],
        **members,
        "manifest": {name: fingerprint(value) for name, value in members.items()},
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.file.stat().st_size > 32_000_000:
            raise ValueError("Evidence bundle exceeds 32 MB")
        verify_bundle(strict_json(args.file.read_text()))
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        parser.exit(1, f"Verification failed: {exc}\n")
    print(json.dumps({"verified": True, "schema": SCHEMA,
                      "scope": "Saved evidence integrity; no model calls or provider attestation"}))


if __name__ == "__main__":
    main()
