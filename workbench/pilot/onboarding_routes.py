"""Source-scoped setup information without fetching vendor credentials."""
from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from workbench.onboarding import guide


def register(app, database, settings, member):
    @app.get("/api/pilot/sources/{identity}/setup")
    def setup(identity: str, project: str = Query("engineering", min_length=1, max_length=100, pattern=r".*\S.*"),
              actor=Depends(member)):
        return guide(database, settings, actor["team_id"], identity, project)

    @app.get("/api/pilot/sources/{identity}/setup/export")
    def export(identity: str, project: str = Query("engineering", min_length=1, max_length=100, pattern=r".*\S.*"),
               actor=Depends(member)):
        return JSONResponse(guide(database, settings, actor["team_id"], identity, project),
            headers={"Content-Disposition": 'attachment; filename="workbench-connection-setup.json"'})
