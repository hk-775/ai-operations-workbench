"""Authenticated single-team pilot. Browser actions only replay saved evidence."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import Headers, MutableHeaders

from workbench.domain import ROOT, evaluation_revision, strict_json
from workbench.billing import BillingError
from workbench.evidence import recommend
from . import auth
from .config import Settings
from .database import Conflict, Database, audits, recordings, users, events
from .events import CollectorHealth, EventBatch
from .identity import BINDING_COOKIE, CALLBACK, CompanyIdentity, provision
from .operations import Instrumentation, Metrics, snapshot
from .queries import call_rows, conditions


class Boundary:
    """Bound request bodies before parsing, including chunked requests."""
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)

        async def secured_send(message):
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["cache-control"] = "no-store"
                h["x-content-type-options"] = "nosniff"
                h["referrer-policy"] = "no-referrer"
                h["content-security-policy"] = (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
                if self.settings.secure_cookie:
                    h["strict-transport-security"] = "max-age=31536000"
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, secured_send)

        if headers.get("host", "").lower() != urlsplit(self.settings.public_origin).netloc.lower():
            return await reject(403, "Unrecognized host")
        origin = headers.get("origin")
        if origin and origin != self.settings.public_origin:
            return await reject(403, "Cross-origin access is disabled")
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            if headers.get("content-type", "").split(";")[0] != "application/json":
                return await reject(415, "JSON content type required")
            limit = (16_500_000 if scope["path"] in {"/api/pilot/billing/preview", "/api/pilot/billing/imports"}
                     else 8_000_000 if scope["path"] == "/api/pilot/recordings"
                     else 512_000 if scope["path"] == "/api/pilot/ingest" else 16_000)
            length = headers.get("content-length")
            if length and (not length.isdigit() or int(length) > limit):
                return await reject(413, "Request body is too large")
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > limit:
                            return await reject(413, "Request body is too large")
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "Request body timed out")
            original_receive, delivered = receive, False

            async def buffered():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = buffered
        await self.app(scope, receive, secured_send)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Input):
    username: str = Field(min_length=3, max_length=80)
    password: SecretStr = Field(min_length=1, max_length=128)


class NewUser(Login):
    password: SecretStr = Field(min_length=14, max_length=128)
    role: Literal["admin", "analyst", "viewer"]

class NewIdentity(Input):
    username: str = Field(min_length=3, max_length=80)
    subject: str = Field(min_length=1, max_length=255)
    role: Literal["admin", "analyst", "viewer"]


class SourceName(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    kind: Literal["axonllm", "bedrock"] = "axonllm"


class Evaluation(Input):
    recording_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class Constraints(Input):
    min_pass_rate: float = Field(default=.95, ge=0, le=1, allow_inf_nan=False)
    max_p95_ms: float = Field(default=20000, ge=1, le=3_600_000, allow_inf_nan=False)
    monthly_tasks: int = Field(default=10000, ge=1, le=10_000_000)


def create_pilot_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate_production_app()
    database = Database(settings.database_url)
    database.check_schema() if settings.production else database.migrate()
    company = CompanyIdentity(database, settings) if settings.oidc_issuer else None
    metrics = Metrics()
    cookie_name = auth.COOKIE + ("_" + settings.cookie_namespace if settings.cookie_namespace else "")
    binding_cookie = BINDING_COOKIE + ("_" + settings.cookie_namespace if settings.cookie_namespace else "")
    logging.getLogger("workbench.operations").setLevel(logging.INFO)

    @asynccontextmanager
    async def lifespan(app):
        yield
        database.engine.dispose()

    app = FastAPI(title="AI Operations Workbench · Team pilot", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.database, app.state.settings = database, settings
    app.state.company_identity = company
    app.add_middleware(Boundary, settings=settings)
    app.add_middleware(Instrumentation, metrics=metrics)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Never echo invalid inputs: these can include passwords or connector tokens.
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(BillingError)
    async def billing_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Record not found"}, status_code=404)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse({"detail": "Database unavailable; retry shortly"}, status_code=503)

    def member(request: Request):
        token = request.cookies.get(cookie_name)
        actor = auth.principal(database, token, settings)
        if not actor:
            raise HTTPException(401, "Sign in to your team")
        if request.method not in {"GET", "HEAD"}:
            supplied = request.headers.get("x-workbench-csrf", "")
            if not supplied.isascii() or not hmac.compare_digest(supplied, auth.csrf_token(token)):
                raise HTTPException(403, "Refresh your session before making changes")
        return actor

    def analyst(actor=Depends(member)):
        if actor["role"] not in {"admin", "analyst"}:
            raise HTTPException(403, "Analyst or administrator role required")
        return actor

    def admin(actor=Depends(member)):
        if actor["role"] != "admin":
            raise HTTPException(403, "Administrator role required")
        return actor

    from .billing_routes import register as register_billing
    register_billing(app, database, member, admin)

    @app.get("/health/live")
    def live():
        return {"status": "up"}

    @app.get("/health/ready")
    def ready():
        healthy = database.worker_healthy()
        if settings.production:
            state = snapshot(database, settings)
            healthy = healthy and state["maintenance_age_seconds"] is not None and state["maintenance_age_seconds"] < 7200
        return JSONResponse({"status": "ready" if healthy else "worker_unavailable"},
                            status_code=200 if healthy else 503)

    @app.get("/metrics")
    def operational_metrics(request: Request):
        token = request.headers.get("authorization", "")
        expected = "Bearer " + settings.metrics_token
        if not settings.metrics_token or not token.isascii() or not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Valid monitoring credentials required")
        return Response(metrics.render(snapshot(database, settings)),
                        media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/api/pilot/operations")
    def operations(actor=Depends(admin)):
        return snapshot(database, settings, actor["team_id"])

    @app.get("/api/auth/session")
    def session(request: Request):
        token = request.cookies.get(cookie_name)
        actor = auth.principal(database, token, settings)
        return {"initialized": database.initialized(), "user": actor,
                "csrf": auth.csrf_token(token) if actor else None,
                "deployment": "hosted_test" if settings.hosted_test else "production" if settings.production else "pilot",
                "login_methods": {"local": settings.local_login, "company": company is not None}}

    def signed_in(token):
        response = JSONResponse({"user": auth.principal(database, token, settings),
                                 "csrf": auth.csrf_token(token)})
        response.set_cookie(cookie_name, token, max_age=settings.session_seconds,
                            httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")
        return response

    @app.get("/api/auth/oidc/start")
    async def company_login():
        if company is None:
            raise HTTPException(404, "Company sign-in is not configured")
        try:
            url, binding = await company.begin()
        except Conflict:
            raise HTTPException(429, "Company sign-in is busy; retry shortly") from None
        except Exception:
            raise HTTPException(503, "Company sign-in is unavailable; contact your administrator") from None
        response = RedirectResponse(url, status_code=302)
        response.set_cookie(binding_cookie, binding, max_age=600, httponly=True,
                            secure=settings.secure_cookie, samesite="lax", path="/api/auth/oidc")
        return response

    @app.get(CALLBACK)
    async def company_callback(request: Request):
        if company is None:
            raise HTTPException(404, "Company sign-in is not configured")
        try:
            token = await company.complete(request.query_params.get("state"),
                request.cookies.get(binding_cookie), request.query_params.get("code"))
        except Exception:
            # Never reflect identity-provider errors, authorization codes, or token content.
            response = RedirectResponse("/?signin=failed", status_code=303)
        else:
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(cookie_name, token, max_age=settings.session_seconds,
                httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")
        response.delete_cookie(binding_cookie, path="/api/auth/oidc", secure=settings.secure_cookie,
                               httponly=True, samesite="lax")
        return response

    @app.post("/api/auth/login")
    def login(payload: Login, request: Request):
        if not settings.local_login:
            raise HTTPException(403, "Use company sign-in")
        try:
            token = auth.authenticate(database, payload.username, payload.password.get_secret_value(),
                request.client.host if request.client else "unknown", settings)
        except Conflict as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "900"}) from None
        except ValueError:
            token = None
        if not token:
            raise HTTPException(401, "Invalid username or password")
        return signed_in(token)

    @app.post("/api/auth/logout")
    def logout(request: Request, actor=Depends(member)):
        auth.logout(database, request.cookies[cookie_name], actor)
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(cookie_name, path="/", secure=settings.secure_cookie,
                               httponly=True, samesite="strict")
        return response

    @app.post("/api/pilot/ingest")
    def ingest(payload: EventBatch, request: Request):
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer wb_ing_") or len(authorization) > 107:
            raise HTTPException(401, "Valid ingestion token required")
        try:
            return database.ingest_authenticated(authorization[7:], payload.events)
        except PermissionError:
            raise HTTPException(401, "Valid ingestion token required") from None

    @app.get("/api/pilot/ingest")
    def ingestion_identity(request: Request):
        authorization = request.headers.get("authorization", "")
        source = database.token_source(authorization[7:]) if authorization.startswith("Bearer ") else None
        if not source:
            raise HTTPException(401, "Valid ingestion token required")
        version = "bedrock.usage.v1" if source["kind"] == "bedrock" else "axon.usage.v1"
        return {"source_id": source["id"], "schema_version": version, "collector_health": True}

    @app.post("/api/pilot/ingest/health")
    def collector_health(payload: CollectorHealth, request: Request):
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Valid ingestion token required")
        try:
            return database.report_collector(authorization[7:], payload)
        except PermissionError:
            raise HTTPException(401, "Valid ingestion token required") from None

    @app.get("/api/pilot/usage")
    def usage(project: str | None = None, source_id: str | None = None,
              task_id: str | None = None, include_fixtures: bool = False,
              start: str | None = Query(None, max_length=50), end: str | None = Query(None, max_length=50),
              page: int = Query(0, ge=0, le=100_000), page_size: int = Query(50, ge=1, le=100),
              actor=Depends(member)):
        try:
            return database.usage(actor["team_id"], project, source_id, include_fixtures, task_id,
                                  start=start, end=end, page=page, page_size=page_size)
        except ValueError:
            raise HTTPException(422, "Invalid usage filters") from None

    @app.get("/api/pilot/calls")
    def calls(source_id: str, task_id: str, project: str | None = None,
              start: str | None = None, end: str | None = None,
              include_fixtures: bool = False, offset: int = Query(0, ge=0, le=1_000_000),
              actor=Depends(member)):
        try:
            where = conditions(actor["team_id"], project=project, source_id=source_id, task_id=task_id,
                               include_fixtures=include_fixtures, start=start, end=end)
        except ValueError:
            raise HTTPException(422, "Invalid time window") from None
        with database.engine.connect() as db:
            rows = call_rows(db, where, limit=101, offset=offset)
        return {"calls": rows[:100], "has_more": len(rows) > 100, "offset": offset}

    @app.get("/api/pilot/sources")
    def sources(actor=Depends(member)):
        return {"sources": database.list_sources(actor["team_id"])}

    @app.post("/api/pilot/sources")
    def create_source(payload: SourceName, actor=Depends(admin)):
        return {"id": database.create_source(actor["team_id"], payload.name.strip(), actor["username"], payload.kind)}

    @app.post("/api/pilot/sources/{identity}/collectors/{collector_id}/retire")
    def retire_collector(identity: str, collector_id: str, actor=Depends(admin)):
        if len(collector_id) != 32 or any(char not in "0123456789abcdef" for char in collector_id):
            raise HTTPException(422, "Invalid collector ID")
        database.retire_collector(actor["team_id"], identity, collector_id, actor["username"])
        return {"retired": True}

    @app.post("/api/pilot/sources/{identity}/token")
    def source_token(identity: str, actor=Depends(admin)):
        return database.issue_token(actor["team_id"], identity, actor["username"])

    @app.post("/api/pilot/sources/{identity}/revoke")
    def revoke(identity: str, actor=Depends(admin)):
        database.revoke_tokens(actor["team_id"], identity, actor["username"])
        return {"revoked": True}

    @app.post("/api/pilot/sources/{identity}/tokens/{token_id}/revoke")
    def revoke_one(identity: str, token_id: str, actor=Depends(admin)):
        database.revoke_token(actor["team_id"], identity, token_id, actor["username"])
        return {"revoked": True}

    @app.get("/api/pilot/recordings")
    def list_recordings(actor=Depends(member)):
        with database.engine.connect() as db:
            return {"recordings": [dict(r) for r in db.execute(select(
                recordings.c.id, recordings.c.source_id, recordings.c.created_at).where(
                    recordings.c.team_id == actor["team_id"]).order_by(
                        recordings.c.created_at.desc()).limit(100)).mappings()]}

    @app.post("/api/pilot/recordings")
    def import_recording(payload: dict, actor=Depends(analyst)):
        try:
            return database.import_recording(actor["team_id"], payload, actor["username"])
        except (TypeError, ValueError, KeyError):
            raise HTTPException(422, "Recording does not satisfy the support-v1 evidence contract") from None

    @app.post("/api/pilot/recordings/example")
    def example(actor=Depends(analyst)):
        return database.import_recording(actor["team_id"],
            strict_json((ROOT / "data/model-comparison.json").read_text()), actor["username"])

    @app.get("/api/pilot/recordings/{identity}")
    def export_recording(identity: str, actor=Depends(member)):
        with database.engine.connect() as db:
            result = db.execute(select(recordings.c.payload).where(
                recordings.c.team_id == actor["team_id"], recordings.c.id == identity)).scalar_one_or_none()
            if result is None:
                raise HTTPException(404, "Recording not found")
            return JSONResponse(json.loads(result), headers={
                "Content-Disposition": 'attachment; filename="workbench-recording.json"'})

    @app.get("/api/pilot/evaluations")
    def evaluations(actor=Depends(member)):
        return {"evaluations": database.list_jobs(actor["team_id"]),
                "worker_healthy": database.worker_healthy()}

    @app.post("/api/pilot/evaluations")
    def enqueue(payload: Evaluation, actor=Depends(analyst)):
        return database.enqueue(actor["team_id"], payload.recording_id, actor["username"],
                                settings.max_queued_jobs)

    @app.get("/api/pilot/evaluations/{identity}")
    def evaluation(identity: str, actor=Depends(member)):
        return database.job(actor["team_id"], identity, with_result=True)

    @app.post("/api/pilot/evaluations/{identity}/cancel")
    def cancel(identity: str, actor=Depends(analyst)):
        return database.cancel(actor["team_id"], identity, actor["username"])

    @app.post("/api/pilot/evaluations/{identity}/recommend")
    def recommendation(identity: str, payload: Constraints, actor=Depends(analyst)):
        job = database.job(actor["team_id"], identity, with_result=True)
        if job["status"] != "complete" or "analysis" not in job:
            raise HTTPException(409, "Complete the evidence replay first")
        if job["revision"] != evaluation_revision()["sha256"]:
            raise HTTPException(409, "Evaluator changed; queue a new replay before making a proposal")
        analysis = job["analysis"]
        result = recommend(analysis, **payload.model_dump())
        if analysis["mode"] != "live":
            result.update(status="fixture_only", recommended_model=None,
                          projected_monthly_api_savings_usd=None)
            for candidate in result["candidates"]:
                candidate["eligible"] = False
                candidate["exclusions"].insert(0, "Fixture evidence cannot justify a measured recommendation")
        result.update(recording_id=job["recording_id"], evaluation_revision=job["revision"],
                      scope="Support-v1 saved comparison only; not a recommendation for other captured tasks")
        return database.save_proposal(actor["team_id"], identity, result, actor["username"])

    @app.get("/api/pilot/proposals")
    def proposals(actor=Depends(member)):
        return {"proposals": database.list_proposals(actor["team_id"])}

    @app.get("/api/pilot/users")
    def team_users(actor=Depends(admin)):
        with database.engine.connect() as db:
            return {"users": [dict(r) for r in db.execute(select(users.c.id, users.c.username,
                users.c.role, users.c.active, users.c.created_at).where(
                    users.c.team_id == actor["team_id"]).order_by(users.c.created_at)).mappings()]}

    @app.post("/api/pilot/users")
    def new_user(payload: NewUser, actor=Depends(admin)):
        if not settings.local_login:
            raise HTTPException(403, "Provision a company identity instead")
        try:
            return auth.create_user(database, actor, payload.username,
                                    payload.password.get_secret_value(), payload.role)
        except ValueError as exc:
            if isinstance(exc, Conflict):
                raise
            raise HTTPException(422, "Invalid username or password length") from None

    @app.post("/api/pilot/identities")
    def new_identity(payload: NewIdentity, actor=Depends(admin)):
        if company is None:
            raise HTTPException(409, "Configure company sign-in first")
        try:
            return provision(database, actor, payload.username, payload.subject,
                             payload.role, settings.oidc_issuer)
        except Conflict:
            raise
        except ValueError:
            raise HTTPException(422, "Invalid company identity") from None

    @app.post("/api/pilot/users/{identity}/disable")
    def disable(identity: str, actor=Depends(admin)):
        auth.disable_user(database, actor, identity)
        return {"disabled": True}

    @app.get("/api/pilot/audit")
    def audit(actor=Depends(admin)):
        with database.engine.connect() as db:
            return {"events": [dict(r) for r in db.execute(select(audits).where(
                audits.c.team_id == actor["team_id"]).order_by(audits.c.created_at.desc()).limit(100)).mappings()]}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web/pilot.html")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
