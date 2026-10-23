"""Explicit configuration: the pilot never falls back to the unauthenticated demo."""
from __future__ import annotations

import os
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
        return cls(database_url=url,
                   public_origin=os.environ.get("WORKBENCH_PUBLIC_ORIGIN",
                                                "http://127.0.0.1:8768").rstrip("/"))
