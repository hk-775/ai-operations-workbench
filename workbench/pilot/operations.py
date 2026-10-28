"""Operational health without prompts, token values, or high-cardinality labels."""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import and_, func, select
from starlette.datastructures import MutableHeaders

from .database import events, facts, jobs, maintenance, sources, workers

log = logging.getLogger("workbench.operations")


def snapshot(database, settings, team=None):
    now = int(time.time())
    since = datetime.fromtimestamp(now - 86400, timezone.utc).isoformat()
    with database.engine.connect() as db:
        heartbeat = db.execute(select(func.max(workers.c.heartbeat_at))).scalar_one()
        job_filter = [jobs.c.team_id == team] if team else []
        counts = dict(db.execute(select(jobs.c.status, func.count()).where(*job_filter)
                                 .group_by(jobs.c.status)).all())
        oldest = db.execute(select(func.min(jobs.c.created_at)).where(
            *job_filter, jobs.c.status == "queued")).scalar_one()
        failed = db.execute(select(func.count()).select_from(jobs).where(
            *job_filter, jobs.c.status == "failed", jobs.c.finished_at >= now - 86400)).scalar_one()
        where = [events.c.evidence == "observed", events.c.occurred_at >= since]
        if team:
            where.append(events.c.team_id == team)
        joined = events.join(facts, and_(events.c.source_id == facts.c.source_id,
                                        events.c.event_id == facts.c.event_id))
        captured = db.execute(select(func.count()).select_from(joined).where(*where)).scalar_one()
        unknown = db.execute(select(func.count()).select_from(joined).where(
            *where, facts.c.api_nanodollars.is_(None))).scalar_one()
        latest = db.execute(select(func.max(events.c.received_at)).where(
            *([events.c.team_id == team] if team else []), events.c.evidence == "observed")).scalar_one()
        upkeep = db.execute(select(maintenance).where(maintenance.c.id == "last_run")).mappings().first()
        teams = [team] if team else db.execute(select(sources.c.team_id).distinct()).scalars().all()
    connections = [source for identity in teams for source in database.list_sources(identity)
                   if source["kind"] != "recording"]
    stale_sources = sum(s["collection"]["stale_collectors"] > 0 for s in connections)
    backlog_sources = sum(bool(s["collection"]["pending_events"]) for s in connections)
    worker_age = None if heartbeat is None else max(0, now - heartbeat)
    maintenance_age = None if not upkeep else max(0, now - upkeep["updated_at"])
    result = {"worker_healthy": worker_age is not None and worker_age < 45,
              "worker_heartbeat_age_seconds": worker_age,
              "jobs": counts, "failed_jobs_24h": failed,
              "oldest_queued_seconds": 0 if oldest is None else max(0, now - oldest),
              "observed_calls_24h": captured, "unknown_cost_calls_24h": unknown,
              "last_observed_received_at": latest, "retention_days": settings.retention_days,
              "evidence_retention_days": settings.evidence_retention_days,
              "audit_retention_days": settings.audit_retention_days,
              "maintenance_age_seconds": maintenance_age,
              "maintenance": json.loads(upkeep["payload"]) if upkeep else None}
    result["collection"] = {"application_sources": len(connections),
        "stale_sources": stale_sources, "backlog_sources": backlog_sources,
        "unmonitored_sources": sum(s["collection"]["status"] == "unmonitored" for s in connections)}
    result["stale_usage_sources"] = stale_sources
    result["backlog_usage_sources"] = backlog_sources
    alerts = []
    if not result["worker_healthy"]:
        alerts.append({"severity": "critical", "message": "Evaluation worker is unavailable."})
    if result["oldest_queued_seconds"] > 300:
        alerts.append({"severity": "warning", "message": "An evaluation has waited more than five minutes."})
    if failed:
        alerts.append({"severity": "warning", "message": f"{failed} evaluations failed in the last 24 hours."})
    if captured and unknown / captured > .05:
        alerts.append({"severity": "warning", "message": "More than 5% of observed calls have unknown costs."})
    if stale_sources:
        alerts.append({"severity": "warning", "message": f"{stale_sources} usage sources have stopped reporting collector health. Check Usage sources."})
    if backlog_sources:
        alerts.append({"severity": "warning", "message": f"{backlog_sources} usage sources last reported undelivered events. Check Usage sources."})
    if settings.retention_days and (maintenance_age is None or maintenance_age > 7200):
        alerts.append({"severity": "critical", "message": "Scheduled maintenance has not completed in two hours."})
    result["alerts"] = alerts
    result["status"] = "attention" if alerts else "healthy"
    return result


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter("workbench_http_requests_total", "HTTP responses",
                                ["method", "route", "status"], registry=self.registry)
        self.duration = Histogram("workbench_http_duration_seconds", "HTTP request duration",
                                  ["route"], buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 15),
                                  registry=self.registry)
        names = ("worker_healthy", "oldest_queued_seconds", "failed_jobs_24h",
                 "observed_calls_24h", "unknown_cost_calls_24h", "maintenance_age_seconds",
                 "stale_usage_sources", "backlog_usage_sources")
        self.gauges = {name: Gauge(f"workbench_{name}", name.replace("_", " "),
                                  registry=self.registry) for name in names}

    def render(self, state):
        for name, gauge in self.gauges.items():
            value = state[name]
            gauge.set(-1 if value is None else value)
        return generate_latest(self.registry)


class Instrumentation:
    def __init__(self, app, metrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        identity, started, status = uuid.uuid4().hex, time.monotonic(), 500

        async def response(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = identity
            await send(message)

        try:
            await self.app(scope, receive, response)
        finally:
            duration = time.monotonic() - started
            route = getattr(scope.get("route"), "path", "/unmatched")
            method = scope["method"] if scope["method"] in {"GET", "POST", "HEAD", "OPTIONS"} else "OTHER"
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.duration.labels(route).observe(duration)
            # Deliberately omit URL parameters, headers, payloads, and exception messages.
            log.info(json.dumps({"event": "http_request", "request_id": identity,
                "method": method, "route": route, "status": status, "duration_ms": round(duration * 1000, 2)}))
