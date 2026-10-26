"""Container health checks without printing connection details."""
import os
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    if "--worker" in sys.argv or "--maintenance" in sys.argv:
        # Running from /app/scripts does not put the package on sys.path.
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from workbench.pilot.config import Settings
        from workbench.pilot.database import Database
        database = Database(Settings.from_env().database_url)
        if "--maintenance" in sys.argv:
            from sqlalchemy import select
            from workbench.pilot.database import maintenance
            import time
            with database.engine.connect() as db:
                latest = db.execute(select(maintenance.c.updated_at).where(
                    maintenance.c.id == "last_run")).scalar_one_or_none()
            healthy = latest is not None and latest > time.time() - 7200
        else:
            identity = Path("/tmp/workbench-worker-id").read_text().strip()
            healthy = database.worker_healthy(identity)
        database.engine.dispose()
        sys.exit(0 if healthy else 1)
    origin = os.environ["WORKBENCH_PUBLIC_ORIGIN"]
    request = Request("http://127.0.0.1:8768/health/live",
                      headers={"Host": urlsplit(origin).netloc})
    with urlopen(request, timeout=3) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
