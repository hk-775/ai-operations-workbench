"""Local-only dashboard API. Browser actions never call a model provider."""
from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .domain import BASELINE, ROOT, cases, digest, money, strict_json
from .evidence import recommend
from .store import Store
from .worker import write_json


class Constraints(BaseModel):
    min_pass_rate: float = Field(default=.95, ge=0, le=1)
    max_p95_ms: float = Field(default=20000, ge=1, le=3_600_000)
    monthly_tasks: int = Field(default=10000, ge=1, le=10_000_000)


def create_app(state_dir: Path | None = None, recording: Path | None = None) -> FastAPI:
    state_dir = state_dir or Path(os.environ.get("WORKBENCH_STATE_DIR", ROOT / ".state"))
    recording = recording or ROOT / "data/model-comparison.json"
    store = Store(state_dir)

    @asynccontextmanager
    async def lifespan(app):
        yield
        for job in app.state.jobs.values():
            process = job["process"]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    app = FastAPI(title="AI Operations Workbench", docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.state.jobs = {}
    app.state.analysis = {}
    app.state.recording = recording

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "This demonstration serves loopback hosts only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin access is disabled"}, status_code=403)
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 8_000_000):
                return JSONResponse({"detail": "Import exceeds 8 MB"}, status_code=413)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "JSON content type required"}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'")
        return response

    def active():
        document = store.active()
        if document is None:
            raise HTTPException(409, "Connect a recording first")
        return document

    def analysis():
        document = active()
        result = app.state.analysis.get(digest(document))
        if result is None:
            raise HTTPException(409, "Run the evaluation replay first")
        return result

    @app.get("/api/state")
    def state():
        document = store.active()
        source = {"available": recording.is_file(), "name": "Recorded AxonLLM usage",
                  "description": "Synthetic workload · real model calls · published-rate API estimates"}
        if not document:
            return {"connected": False, "source": source, "evaluated": False}
        tasks = []
        lookup = {c["id"]: c for c in cases()}
        for sample in document["samples"]:
            if sample["model"] != BASELINE:
                continue
            amount = sum((Decimal(s["estimated_cost_usd"]) for s in sample["stages"]
                          if s.get("estimated_cost_usd") is not None), Decimal(0))
            case = lookup[sample["case_id"]]
            tasks.append({"id": sample["case_id"], "title": case["title"], "family": case["family"],
                          "cost_usd": money(amount), "latency_ms": sample["latency_ms"],
                          "cost_complete": len(sample["stages"]) == 2 and
                          all(s["status"] == "success" for s in sample["stages"]),
                          "model": sample["model"], "ticket": case["ticket"], "facts": case["facts"],
                          "stages": sample["stages"]})
        tasks.sort(key=lambda t: Decimal(t["cost_usd"]), reverse=True)
        all_stages = [s for sample in document["samples"] for s in sample["stages"]]
        amount = sum((Decimal(s["estimated_cost_usd"]) for s in all_stages
                      if s.get("estimated_cost_usd") is not None), Decimal(0))
        return {
            "connected": True, "source": source, "recording_id": digest(document),
            "mode": document["mode"], "created_at": document["created_at"],
            "calls": len(all_stages), "tasks": tasks, "samples": len(document["samples"]),
            "models_recorded": len({s["model"] for s in document["samples"]}),
            "unknown_cost_calls": sum(s.get("estimated_cost_usd") is None for s in all_stages),
            "incomplete_tasks": sum(len(s["stages"]) != 2 or
                                    any(stage["status"] != "success" for stage in s["stages"])
                                    for s in document["samples"]),
            "api_cost_usd": money(amount), "evaluated": digest(document) in app.state.analysis,
            "provenance": document.get("provenance", {}),
            "baseline": BASELINE,
        }

    @app.post("/api/connect")
    def connect():
        if not recording.is_file():
            raise HTTPException(409, "No bundled recording. Collect or import one using the README.")
        try:
            return store.import_recording(strict_json(recording.read_text()))
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/import")
    async def import_recording(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 8_000_000:
                raise HTTPException(413, "Import exceeds 8 MB")
            body.extend(chunk)
        try:
            document = strict_json(body.decode())
            return store.import_recording(document)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/evaluate")
    def evaluate():
        document = active()
        recording_id = digest(document)
        for job_id, job in app.state.jobs.items():
            if job["recording_id"] == recording_id and job["process"].poll() is None:
                return {"job_id": job_id, "status": "running"}
        job_id = uuid.uuid4().hex
        directory = state_dir / "jobs" / job_id
        directory.mkdir(parents=True)
        input_path, result_path = directory / "input.json", directory / "result.json"
        write_json(input_path, document)
        log_path = directory / "worker.log"
        # Offline workers inherit no provider credentials.
        environment = {k: v for k, v in os.environ.items()
                       if not any(part in k.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "workbench.worker", "replay", str(input_path),
                 "--output", str(result_path)], cwd=ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        app.state.jobs[job_id] = {"recording_id": recording_id, "process": process,
                                 "result": result_path, "started": time.monotonic()}
        return {"job_id": job_id, "status": "running"}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        job = app.state.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown evaluation")
        code = job["process"].poll()
        if code is None and time.monotonic() - job["started"] > 90:
            job["process"].terminate()
            return {"status": "failed", "detail": "The evidence replay exceeded its time limit"}
        if code is None:
            return {"status": "running"}
        if code != 0 or not job["result"].is_file():
            return {"status": "failed", "detail": "The evidence worker could not verify this recording"}
        result = json.loads(job["result"].read_text())
        app.state.analysis[job["recording_id"]] = result
        return {"status": "complete", "analysis": result}

    @app.get("/api/analysis")
    def get_analysis():
        return analysis()

    @app.post("/api/recommend")
    def recommendation(constraints: Constraints):
        return recommend(analysis(), **constraints.model_dump())

    @app.get("/api/recording")
    def download_recording():
        return JSONResponse(active(), headers={"Content-Disposition": 'attachment; filename="model-comparison.json"'})

    @app.get("/api/integrations")
    def integrations():
        return {"components": [
            {"name": "AxonLLM", "version": importlib.metadata.version("axon-llm"),
             "role": "Actual model routing during recorded collection"},
            {"name": "Ostiari Guard", "version": importlib.metadata.version("ostiari"),
             "role": "Actual governance engine in the managed evaluation worker"},
            {"name": "Workbench", "version": "0.1.0",
             "role": "Local ledger, deterministic checks, comparison, and proposal"},
        ], "native_connectors": "Codex, Cursor, Claude Code and billing feed importers are not implemented in this first demo."}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web/index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app


app = create_app()
