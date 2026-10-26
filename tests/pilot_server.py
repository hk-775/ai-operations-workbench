"""Isolated browser-test host; never bootstraps the user's pilot database."""
import multiprocessing
import os
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from workbench.pilot import auth
from workbench.pilot.api import create_pilot_app
from workbench.pilot.config import Settings
from workbench.pilot.database import Database, uid
from workbench.pilot.worker import EvaluationWorker


def worker_process(settings):
    database = Database(settings.database_url)
    EvaluationWorker(database, settings).run()


def main():
    port = int(os.environ.get("WORKBENCH_PILOT_TEST_PORT", "18770"))
    url = os.environ.get("WORKBENCH_TEST_DATABASE_URL")
    if path := os.environ.get("WORKBENCH_TEST_DATABASE_URL_FILE"):
        url = Path(path).read_text().strip()
    schema, engine = "pilot_browser_" + uid().replace("-", ""), None
    with tempfile.TemporaryDirectory(prefix="workbench-pilot-browser-") as directory:
        if url:
            engine = create_engine(url, hide_parameters=True)
            with engine.begin() as db:
                db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
        else:
            url = f"sqlite:///{Path(directory) / 'pilot.db'}"
        settings = Settings(url, public_origin=f"http://127.0.0.1:{port}", testing=True)
        app = create_pilot_app(settings)
        db = app.state.database
        password = os.environ["WORKBENCH_BROWSER_PASSWORD"]
        team = db.initialize("Support operations", "admin", auth.password_hash(password))
        auth.create_user(db, {"team_id":team, "username":"admin"}, "viewer", password, "viewer")
        worker = multiprocessing.Process(target=worker_process, args=(settings,), daemon=True)
        worker.start()
        try:
            uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)
        finally:
            worker.terminate()
            worker.join(5)
            if worker.is_alive():
                worker.kill()
                worker.join()
            db.engine.dispose()
            if engine:
                with engine.begin() as connection:
                    connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
                engine.dispose()


if __name__ == "__main__":
    main()
