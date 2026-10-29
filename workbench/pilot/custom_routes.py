"""Reusable suite revisions and immutable, bounded offline evaluation runs."""
import json
import time

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import insert, select

from workbench.custom_evals import Run, Suite, SuiteChange, compare, evaluate, example
from workbench.domain import digest
from .database import teams, workflow_results
from . import workflows


def stored_run(database, team, identity, *, db=None):
    def read(connection):
        row = connection.execute(select(workflow_results.c.payload).where(
            workflow_results.c.team_id == team, workflow_results.c.id == identity)).scalar_one_or_none()
        if row is None:
            raise KeyError(identity)
        return json.loads(row)
    if db is not None:
        return read(db)
    with database.engine.connect() as connection:
        return read(connection)


def execute(database, team, run, actor):
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == team).with_for_update(key_share=True)).first()
        definition = workflows.get(database, team, "eval_suite", run.suite_id, revision=run.revision, db=db)
        current = workflows.get(database, team, "eval_suite", run.suite_id, db=db)
        if not current["value"]["active"]:
            raise workflows.WorkflowError("Restore this suite before evaluating another saved run")
        suite = Suite.model_validate(definition["value"])
        try:
            result = evaluate(suite, run)
        except ValueError:
            raise workflows.WorkflowError("Saved responses must match this suite revision and its declared model roster") from None
        fingerprint = digest({"input": run.model_dump(), "suite": definition["fingerprint"],
                              "evaluator": result["evaluator_revision"]})
        existing = db.execute(select(workflow_results.c.id).where(
            workflow_results.c.team_id == team, workflow_results.c.id == fingerprint)).first()
        if existing:
            return stored_run(database, team, fingerprint, db=db) | {"unchanged": True}
        result.update(id=fingerprint, name=run.name, input_fingerprint=digest(run.model_dump()),
                      created_at=int(time.time()), source=run.model_dump())
        summary = {key: result[key] for key in ("id", "name", "suite_id", "suite_revision",
                                               "evidence", "created_at", "summaries", "cost_basis")}
        db.execute(insert(workflow_results).values(team_id=team, id=fingerprint,
            workflow_id=run.suite_id, revision=run.revision, summary=json.dumps(summary), payload=json.dumps(result),
            created_at=result["created_at"]))
        database.audit(db, team, actor, "custom_evaluation.completed", fingerprint)
        return result | {"unchanged": False}


def register(app, database, member, analyst):
    @app.get("/api/pilot/custom-evals/example")
    def sample(actor=Depends(member)):
        return example()

    @app.get("/api/pilot/custom-evals/suites")
    def suites(page: int = Query(0, ge=0, le=100_000), include_fixtures: bool = False,
               actor=Depends(member)):
        return workflows.list_definitions(database, actor["team_id"], "eval_suite",
                                            page=page, include_fixtures=include_fixtures, brief=True)

    @app.post("/api/pilot/custom-evals/suites")
    def create_suite(payload: SuiteChange, actor=Depends(analyst)):
        return workflows.save(database, actor["team_id"], "eval_suite",
            payload.value.model_dump(), actor["username"], expected_revision=payload.revision)

    @app.post("/api/pilot/custom-evals/suites/preview")
    def preview_suite(payload: dict, actor=Depends(analyst)):
        # The request boundary validates the original JSON, including duplicate
        # keys. Never let browser JSON.parse silently rewrite invalid evidence.
        value = payload.get("value", payload)
        try:
            return Suite.model_validate(value).model_dump()
        except ValidationError:
            raise workflows.WorkflowError("Use a valid suite definition with supported, bounded checks") from None

    @app.post("/api/pilot/custom-evals/suites/{identity}")
    def update_suite(identity: str, payload: SuiteChange, actor=Depends(analyst)):
        return workflows.save(database, actor["team_id"], "eval_suite",
            payload.value.model_dump(), actor["username"], expected_revision=payload.revision, identity=identity)

    @app.get("/api/pilot/custom-evals/suites/{identity}/history")
    def history(identity: str, page: int = Query(0, ge=0, le=100_000), actor=Depends(member)):
        return workflows.history(database, actor["team_id"], "eval_suite", identity, page=page)

    @app.get("/api/pilot/custom-evals/suites/{identity}/export")
    def export_suite(identity: str, revision: int | None = Query(None, ge=1), actor=Depends(member)):
        return JSONResponse(workflows.get(database, actor["team_id"], "eval_suite", identity, revision=revision),
            headers={"Content-Disposition": 'attachment; filename="workbench-evaluation-suite.json"'})

    @app.get("/api/pilot/custom-evals/suites/{identity}/template")
    def template(identity: str, actor=Depends(member)):
        suite = workflows.get(database, actor["team_id"], "eval_suite", identity)
        return JSONResponse({
            "suite_id": identity, "revision": suite["revision"], "name": "Saved answer comparison",
            "evidence": "fixture", "models": ["candidate"],
            "cost_basis": "unknown", "cost_scope": "case_including_all_attempts",
            "responses": [{"model": "candidate", "case_id": case["id"], "status": "success",
                           "output": "", "cost_usd": None, "latency_ms": None}
                          for case in suite["value"]["cases"]]},
            headers={"Content-Disposition": 'attachment; filename="workbench-saved-answers-template.json"'})

    @app.post("/api/pilot/custom-evals/runs")
    def run(payload: Run, actor=Depends(analyst)):
        return execute(database, actor["team_id"], payload, actor["username"])

    @app.get("/api/pilot/custom-evals/runs")
    def runs(page: int = Query(0, ge=0, le=100_000), actor=Depends(member)):
        with database.engine.connect() as db:
            rows = db.execute(select(workflow_results.c.summary).where(
                workflow_results.c.team_id == actor["team_id"]).order_by(
                    workflow_results.c.created_at.desc(), workflow_results.c.id).limit(26).offset(page * 25)).scalars().all()
        return {"items": [json.loads(row) for row in rows[:25]],
                "has_more": len(rows) > 25, "page": page}

    @app.get("/api/pilot/custom-evals/runs/{identity}")
    def result(identity: str, actor=Depends(member)):
        return stored_run(database, actor["team_id"], identity)

    @app.get("/api/pilot/custom-evals/runs/{identity}/export")
    def export(identity: str, actor=Depends(member)):
        return JSONResponse(stored_run(database, actor["team_id"], identity),
            headers={"Content-Disposition": 'attachment; filename="workbench-custom-evaluation.json"'})

    @app.get("/api/pilot/custom-evals/runs/{identity}/compare/{baseline}")
    def comparison(identity: str, baseline: str, actor=Depends(member)):
        current = stored_run(database, actor["team_id"], identity)
        previous = stored_run(database, actor["team_id"], baseline)
        try:
            return compare(previous, current) | {"before": baseline, "after": identity}
        except ValueError as error:
            raise workflows.WorkflowError(str(error)) from None
