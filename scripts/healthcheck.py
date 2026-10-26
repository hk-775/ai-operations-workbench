"""Lightweight container checks without importing the application or printing secrets."""
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def database_health(url_file, *, maintenance=False, worker_file="/tmp/workbench-worker-id", now=None):
    # Importing Database also loads evaluation dependencies. Container probes only
    # need two indexed schema-v2 lookups, and must stay cheap under startup load.
    import psycopg

    raw = Path(url_file).read_text().strip()
    if not raw.startswith("postgresql+psycopg://"):
        raise ValueError("Container health requires the PostgreSQL runtime")
    connection_url = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url, connect_timeout=3) as connection:
        connection.execute("SET statement_timeout = 3000")
        if maintenance:
            row = connection.execute(
                "SELECT updated_at FROM wb_maintenance WHERE id = %s", ("last_run",)).fetchone()
            freshness = 7200
        else:
            identity = Path(worker_file).read_text().strip()
            row = connection.execute(
                "SELECT heartbeat_at FROM wb_workers WHERE id = %s", (identity,)).fetchone()
            freshness = 45
    return row is not None and row[0] is not None and row[0] > (time.time() if now is None else now) - freshness


def main():
    try:
        if "--worker" in sys.argv or "--maintenance" in sys.argv:
            return 0 if database_health(os.environ["WORKBENCH_DATABASE_URL_FILE"],
                                       maintenance="--maintenance" in sys.argv) else 1
        origin = os.environ["WORKBENCH_PUBLIC_ORIGIN"]
        request = Request("http://127.0.0.1:8768/health/live",
                          headers={"Host": urlsplit(origin).netloc})
        with urlopen(request, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
