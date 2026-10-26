"""Idempotent, explicitly requested demo seeding from the bundled real recording."""
import json
import time

from sqlalchemy import func, select

from workbench.domain import ROOT, digest, strict_json
from workbench.evidence import recommend
from .database import Conflict, events, maintenance, teams
from .maintenance import save
from .worker import EvaluationWorker


def seed(database, settings):
    document = strict_json((ROOT / "data/model-comparison.json").read_text())
    recording_id = digest(document)
    with database.engine.begin() as db:
        team = db.execute(select(teams).with_for_update()).mappings().first()
        if not team:
            raise Conflict("Initialize the administrator account before seeding the demo")
        marker = db.execute(select(maintenance.c.payload).where(
            maintenance.c.id == "demo_seed")).scalar_one_or_none()
        if marker:
            marker = json.loads(marker)
            if marker.get("status") == "complete":
                return marker
            if marker.get("recording_id") != recording_id:
                raise Conflict("The bundled demo changed during seeding; inspect the existing seed before retrying")
        count = db.execute(select(func.count()).select_from(events)).scalar_one()
        unrelated = db.execute(select(func.count()).select_from(events).where(
            (events.c.recording_id.is_(None)) | (events.c.recording_id != recording_id))).scalar_one()
        if count and (not marker or unrelated):
            raise Conflict("Demo seeding requires an empty usage ledger; existing company data is never replaced")
        if not marker:
            save(db,"demo_seed",{"status":"seeding","recording_id":recording_id},int(time.time()))
    imported = database.import_recording(team["id"],
        document, "demo-seeder")
    queued = database.enqueue(team["id"], imported["recording_id"], "demo-seeder")
    worker = EvaluationWorker(database, settings)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = database.job(team["id"], queued["id"], with_result=True)
        if job["status"] == "complete":
            break
        if job["status"] in {"failed", "cancelled"}:
            raise Conflict("Demo replay failed; inspect the evaluation status")
        worker.run_once()
        time.sleep(.1)
    else:
        raise Conflict("Demo replay did not finish before the seeding deadline")
    analysis = job["analysis"]
    review = recommend(analysis, min_pass_rate=.95, max_p95_ms=20000, monthly_tasks=10000)
    review.update(recording_id=job["recording_id"], evaluation_revision=job["revision"],
                  scope="Support-v1 saved comparison only; not a recommendation for other captured tasks")
    proposal = database.save_proposal(team["id"], job["id"], review, "demo-seeder")
    summary = {"status":"complete", "mode":"recorded_demo", "recording_id":imported["recording_id"],
               "evaluation_id":job["id"], "proposal_id":proposal["id"],
               "recorded_calls":analysis["total_calls"], "paid_calls_made":0}
    with database.engine.begin() as db:
        save(db,"demo_seed",summary,int(time.time()))
        database.audit(db,team["id"],"demo-seeder","demo.seeded",imported["recording_id"])
    return summary
