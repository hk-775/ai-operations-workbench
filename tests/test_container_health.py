"""The lightweight probe must preserve per-worker and maintenance freshness."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import insert

from workbench.pilot.database import Database, workers, maintenance
from test_pilot import settings  # shared isolated SQLite/PostgreSQL fixture

spec = importlib.util.spec_from_file_location(
    "container_health", Path(__file__).parents[1]/"scripts"/"healthcheck.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_postgres_probe_checks_own_worker_and_fresh_maintenance(settings, tmp_path):
    if settings.database_url.startswith("sqlite"):
        pytest.skip("Shipped containers require PostgreSQL")
    database = Database(settings.database_url)
    database.migrate()
    url = tmp_path/"database-url"
    url.write_text(settings.database_url)
    worker = tmp_path/"worker-id"
    worker.write_text("this-worker")
    now = 1_800_000_000
    try:
        assert not probe.database_health(url, worker_file=worker, now=now)
        assert not probe.database_health(url, maintenance=True, now=now)
        with database.engine.begin() as connection:
            connection.execute(insert(workers).values(id="different-worker", heartbeat_at=now))
        assert not probe.database_health(url, worker_file=worker, now=now)
        with database.engine.begin() as connection:
            connection.execute(insert(workers).values(id="this-worker", heartbeat_at=now-44))
            connection.execute(insert(maintenance).values(
                id="last_run", payload="{}", updated_at=now-7199))
        assert probe.database_health(url, worker_file=worker, now=now)
        assert not probe.database_health(url, worker_file=worker, now=now+1)
        assert probe.database_health(url, maintenance=True, now=now)
        assert not probe.database_health(url, maintenance=True, now=now+1)
    finally:
        database.engine.dispose()
