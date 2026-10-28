"""Authenticated billing routes; all writes are administrator and CSRF protected."""
from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from workbench.billing import BillingMapping, BillingUpload
from . import billing
from .billing_example import load_example


def register(app, database, member, admin):
    @app.get("/api/pilot/billing/example-files")
    def example_files(actor=Depends(member)):
        import io
        import zipfile
        from fastapi.responses import Response
        from workbench.domain import ROOT
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in ("README.md", "legacy-cur.csv", "cur-2.0.csv", "matching-usage.json",
                         "expected-totals.json", "sample-check.json"):
                bundle.writestr("bedrock-billing-sample/" + name, (ROOT / "data/billing-sample" / name).read_bytes())
        return Response(buffer.getvalue(), media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="bedrock-billing-sample.zip"'})

    @app.get("/api/pilot/billing/collection")
    def collection_status(actor=Depends(member)):
        from workbench.billing_collection import statuses
        return {"collectors": statuses(database, actor["team_id"])}

    @app.post("/api/pilot/billing/preview")
    def preview(payload: BillingUpload, actor=Depends(admin)):
        return billing.preview(database, actor["team_id"], payload)

    @app.post("/api/pilot/billing/imports")
    def ingest(payload: BillingUpload, actor=Depends(admin)):
        return billing.import_report(database, actor["team_id"], payload, actor["username"])

    @app.post("/api/pilot/billing/example")
    def example(actor=Depends(admin)):
        return load_example(database, actor["team_id"], actor["username"])

    @app.get("/api/pilot/billing/reports")
    def reports(page: int = Query(0, ge=0, le=100_000), actor=Depends(member)):
        return billing.list_reports(database, actor["team_id"], page=page)

    @app.get("/api/pilot/billing/reports/{identity}")
    def report(identity: str, actor=Depends(member)):
        return billing.reconcile(database, actor["team_id"], identity)

    @app.get("/api/pilot/billing/reports/{identity}/export")
    def export(identity: str, actor=Depends(member)):
        return JSONResponse(billing.reconcile(database, actor["team_id"], identity, export=True),
            headers={"Content-Disposition": 'attachment; filename="workbench-billing-reconciliation.json"'})

    @app.post("/api/pilot/billing/reports/{identity}/mappings")
    def mapping(identity: str, payload: BillingMapping, actor=Depends(admin)):
        return billing.add_mapping(database, actor["team_id"], identity, payload, actor["username"])

    @app.post("/api/pilot/billing/reports/{identity}/mappings/{mapping_id}/remove")
    def remove(identity: str, mapping_id: str, actor=Depends(admin)):
        billing.remove_mapping(database, actor["team_id"], identity, mapping_id, actor["username"])
        return {"removed": True}
