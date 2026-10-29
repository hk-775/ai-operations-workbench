"""Spend planning routes use company scope, administrator writes and immutable revisions."""
from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from workbench.spend import (Allocation, AllocationChange, Budget, BudgetChange,
                             allocation_result, allocation_totals, budget_status, validate_scope)
from . import workflows


def register(app, database, member, admin):
    def evaluated(actor, kind, document):
        value = document["value"]
        result = budget_status(database, actor["team_id"], Budget.model_validate(value)) \
            if kind == "budget" else allocation_result(Allocation.model_validate(value))
        return document | {"result": result}

    @app.get("/api/pilot/spend/summary")
    def summary(month: str = Query(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$"),
                fixture: bool = False, actor=Depends(member)):
        return allocation_totals(database, actor["team_id"], month, fixture=fixture)

    @app.get("/api/pilot/spend/budgets")
    def budgets(page: int = Query(0, ge=0, le=100_000), include_fixtures: bool = False,
                actor=Depends(member)):
        listing = workflows.list_definitions(database, actor["team_id"], "budget",
                                              page=page, include_fixtures=include_fixtures)
        return listing | {"items": [evaluated(actor, "budget", row) for row in listing["items"]]}

    @app.post("/api/pilot/spend/budgets")
    def create_budget(payload: BudgetChange, actor=Depends(admin)):
        validate_scope(database, actor["team_id"], payload.value)
        return evaluated(actor, "budget", workflows.save(database, actor["team_id"], "budget",
            payload.value.model_dump(), actor["username"], expected_revision=payload.revision))

    @app.post("/api/pilot/spend/budgets/{identity}")
    def update_budget(identity: str, payload: BudgetChange, actor=Depends(admin)):
        validate_scope(database, actor["team_id"], payload.value)
        return evaluated(actor, "budget", workflows.save(database, actor["team_id"], "budget",
            payload.value.model_dump(), actor["username"], expected_revision=payload.revision, identity=identity))

    @app.get("/api/pilot/spend/allocations")
    def allocations(page: int = Query(0, ge=0, le=100_000), include_fixtures: bool = False,
                    actor=Depends(member)):
        listing = workflows.list_definitions(database, actor["team_id"], "allocation",
                                              page=page, include_fixtures=include_fixtures)
        return listing | {"items": [evaluated(actor, "allocation", row) for row in listing["items"]]}

    @app.post("/api/pilot/spend/allocations/preview")
    def preview_allocation(payload: AllocationChange, actor=Depends(admin)):
        return allocation_result(payload.value)

    @app.post("/api/pilot/spend/allocations")
    def create_allocation(payload: AllocationChange, actor=Depends(admin)):
        return evaluated(actor, "allocation", workflows.save(database, actor["team_id"], "allocation",
            payload.value.model_dump(), actor["username"], expected_revision=payload.revision))

    @app.post("/api/pilot/spend/allocations/{identity}")
    def update_allocation(identity: str, payload: AllocationChange, actor=Depends(admin)):
        return evaluated(actor, "allocation", workflows.save(database, actor["team_id"], "allocation",
            payload.value.model_dump(), actor["username"], expected_revision=payload.revision, identity=identity))

    @app.get("/api/pilot/spend/{kind}/{identity}/history")
    def history(kind: str, identity: str, page: int = Query(0, ge=0, le=100_000), actor=Depends(member)):
        if kind not in {"budget", "allocation"}:
            raise KeyError(kind)
        return workflows.history(database, actor["team_id"], kind, identity, page=page)

    @app.get("/api/pilot/spend/{kind}/{identity}/export")
    def export(kind: str, identity: str, revision: int | None = Query(None, ge=1), actor=Depends(member)):
        if kind not in {"budget", "allocation"}:
            raise KeyError(kind)
        document = workflows.get(database, actor["team_id"], kind, identity, revision=revision)
        return JSONResponse(evaluated(actor, kind, document),
            headers={"Content-Disposition": 'attachment; filename="workbench-spend-evidence.json"'})
