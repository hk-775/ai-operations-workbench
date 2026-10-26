"""Explicit configuration: the pilot never falls back to the unauthenticated demo."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    public_origin: str = "http://127.0.0.1:8768"
    session_seconds: int = 8 * 3600
    idle_seconds: int = 30 * 60
    job_timeout: int = 90
    lease_seconds: int = 30
    max_job_attempts: int = 3
    max_queued_jobs: int = 20
    production: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = field(default="", repr=False)
    oidc_required_amr: tuple[str, ...] = ()
    oidc_required_acr: str = ""
    local_login: bool = True
    metrics_token: str = field(default="", repr=False)
    retention_days: int = 0
    evidence_retention_days: int = 0
    audit_retention_days: int = 0
    cookie_namespace: str = ""
    testing: bool = False

    def __post_init__(self):
        origin = urlsplit(self.public_origin)
        if origin.scheme not in {"http", "https"} or not origin.hostname:
            raise ValueError("WORKBENCH_PUBLIC_ORIGIN must be an HTTP(S) origin")
        if origin.path not in {"", "/"} or origin.query or origin.fragment or origin.username:
            raise ValueError("WORKBENCH_PUBLIC_ORIGIN must not include a path or credentials")
        local = origin.hostname in {"localhost", "127.0.0.1", "::1"}
        if origin.scheme != "https" and not local and not self.testing:
            raise ValueError("Non-loopback pilot access requires an HTTPS public origin")
        if not self.database_url.startswith("postgresql+psycopg://") and not self.testing:
            raise ValueError("Pilot mode requires a PostgreSQL database")
        if self.lease_seconds < 5 or self.job_timeout < 1:
            raise ValueError("Invalid worker lease or timeout")
        if any(not 0 <= days <= 3650 for days in
               (self.retention_days, self.evidence_retention_days, self.audit_retention_days)):
            raise ValueError("Invalid retention period")
        if self.metrics_token and len(self.metrics_token) < 32:
            raise ValueError("Metrics token must have at least 32 characters")
        if not re.fullmatch(r"[A-Za-z0-9_-]{0,40}", self.cookie_namespace):
            raise ValueError("Invalid session cookie namespace")
        if self.oidc_issuer:
            issuer = urlsplit(self.oidc_issuer)
            if issuer.scheme != "https" or not issuer.hostname or issuer.query or issuer.fragment or issuer.username:
                raise ValueError("OIDC issuer must be a trusted HTTPS issuer URL")
            if not self.oidc_client_id or not self.oidc_client_secret:
                raise ValueError("OIDC client ID and secret file are required")
        if self.production and not self.secure_cookie:
            raise ValueError("Production requires an HTTPS public origin")

    def validate_production_app(self):
        if not self.production:
            return
        if not self.oidc_issuer or self.local_login:
            raise ValueError("Production requires company OIDC with local login disabled")
        if not self.oidc_required_amr and not self.oidc_required_acr:
            raise ValueError("Production requires a verified MFA amr or acr claim")
        if not self.metrics_token:
            raise ValueError("Production requires a private metrics token")
        if not self.retention_days:
            raise ValueError("Production requires an explicit usage retention period")
        if not self.evidence_retention_days or not self.audit_retention_days:
            raise ValueError("Production requires explicit evidence and audit retention periods")

    @property
    def secure_cookie(self) -> bool:
        return self.public_origin.startswith("https://")

    @classmethod
    def from_env(cls) -> Settings:
        secret_file = os.environ.get("WORKBENCH_DATABASE_URL_FILE")
        url = Path(secret_file).read_text().strip() if secret_file else os.environ.get(
            "WORKBENCH_DATABASE_URL", "")
        if not url:
            raise ValueError("Set WORKBENCH_DATABASE_URL_FILE or WORKBENCH_DATABASE_URL")
        def private_file(name):
            filename = os.environ.get(name)
            return Path(filename).read_text().strip() if filename else ""

        production = os.environ.get("WORKBENCH_PRODUCTION", "false").lower() == "true"
        return cls(database_url=url, production=production,
                   public_origin=os.environ.get("WORKBENCH_PUBLIC_ORIGIN",
                                                "http://127.0.0.1:8768").rstrip("/"),
                   oidc_issuer=os.environ.get("WORKBENCH_OIDC_ISSUER", ""),
                   oidc_client_id=os.environ.get("WORKBENCH_OIDC_CLIENT_ID", ""),
                   oidc_client_secret=private_file("WORKBENCH_OIDC_CLIENT_SECRET_FILE"),
                   oidc_required_amr=tuple(filter(None, os.environ.get("WORKBENCH_OIDC_REQUIRED_AMR", "").split(","))),
                   oidc_required_acr=os.environ.get("WORKBENCH_OIDC_REQUIRED_ACR", ""),
                   local_login=os.environ.get("WORKBENCH_LOCAL_LOGIN", "false" if production else "true").lower() == "true",
                   metrics_token=private_file("WORKBENCH_METRICS_TOKEN_FILE"),
                   retention_days=int(os.environ.get("WORKBENCH_RETENTION_DAYS", "0")),
                   evidence_retention_days=int(os.environ.get("WORKBENCH_EVIDENCE_RETENTION_DAYS", "0")),
                   audit_retention_days=int(os.environ.get("WORKBENCH_AUDIT_RETENTION_DAYS", "0")),
                   cookie_namespace=os.environ.get("WORKBENCH_COOKIE_NAMESPACE", ""))
