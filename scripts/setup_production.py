"""Prepare private production files; does not deploy services or change existing accounts."""
import argparse
import getpass
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def private_write(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--client-id", required=True)
    assurance = parser.add_mutually_exclusive_group(required=True)
    assurance.add_argument("--required-amr", help="Comma-separated MFA methods actually emitted by the provider")
    assurance.add_argument("--required-acr", help="Exact assurance level actually emitted by the provider")
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--evidence-retention-days", type=int, default=365)
    parser.add_argument("--audit-retention-days", type=int, default=730)
    args = parser.parse_args()
    issuer = urlsplit(args.issuer)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", args.domain) or "." not in args.domain:
        parser.error("Provide a DNS hostname without a scheme, path, or port")
    if issuer.scheme != "https" or not issuer.hostname or issuer.query or issuer.fragment or issuer.username:
        parser.error("Provide the exact trusted HTTPS OIDC issuer")
    if any(not 1 <= days <= 3650 for days in
           (args.retention_days, args.evidence_retention_days, args.audit_retention_days)):
        parser.error("Each retention period must be 1–3650 days")
    values = {"WORKBENCH_DOMAIN":args.domain, "WORKBENCH_PUBLIC_ORIGIN":"https://"+args.domain,
              "WORKBENCH_OIDC_ISSUER":args.issuer,"WORKBENCH_OIDC_CLIENT_ID":args.client_id,
              "WORKBENCH_OIDC_REQUIRED_AMR":args.required_amr or "",
              "WORKBENCH_OIDC_REQUIRED_ACR":args.required_acr or "",
              "WORKBENCH_RETENTION_DAYS":str(args.retention_days),
              "WORKBENCH_EVIDENCE_RETENTION_DAYS":str(args.evidence_retention_days),
              "WORKBENCH_AUDIT_RETENTION_DAYS":str(args.audit_retention_days)}
    if any(any(c in value for c in "\r\n'") for value in values.values()):
        parser.error("Configuration values cannot contain newlines or single quotes")
    path = Path(".pilot")
    if (path / "production.env").exists():
        parser.error("Production configuration already exists; edit it deliberately instead of replacing it")
    subprocess.run([sys.executable,"scripts/setup_pilot.py"],check=True)
    if not (path / "oidc_client_secret").exists():
        secret = getpass.getpass("Company OIDC client secret (stored privately): ").strip()
        if not secret:
            parser.error("A confidential OIDC client secret is required")
        private_write(path / "oidc_client_secret",secret)
    if not (path / "metrics_token").exists():
        private_write(path / "metrics_token",secrets.token_urlsafe(48))
    private_write(path / "production.env", (path / "compose.env").read_text() + "\n" +
                  "\n".join(f"{key}='{value}'" for key,value in values.items()) + "\n")
    # This file references a mounted secret, never its value.
    private_write(path / "prometheus.yaml",
        f'global:\n  scrape_interval: 30s\nrule_files: ["/etc/prometheus/workbench-alerts.yaml"]\n'
        f'scrape_configs:\n  - job_name: workbench\n    scheme: https\n'
        f'    authorization:\n      credentials_file: /run/secrets/workbench_metrics_token\n'
        f'    static_configs:\n      - targets: [{json.dumps(args.domain)}]\n')
    print("Prepared private configuration. Follow docs/PRODUCTION.md for migration, identity linking, TLS, monitoring, and restore acceptance.")


if __name__ == "__main__":
    main()
