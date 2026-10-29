"""Authenticated loopback OTLP/HTTP JSON intake for Claude Code usage events."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hmac
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .coding_tools import MAX_INPUT, NativeInputError, document, integer, number, read_secret, text, usd
from .pilot.events import CodingToolContext, CodingToolUsage, UsageEvent

FIELDS = {
    "event.name", "event.timestamp", "event.sequence", "model", "session.id", "prompt.id",
    "request_id", "client_request_id", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_creation_tokens", "cost_usd", "cost_usd_micros", "duration_ms",
}


def attributes(items):
    if not isinstance(items, list) or len(items) > 256:
        raise NativeInputError("Unsupported OTLP attributes")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise NativeInputError("Invalid OTLP attribute")
        key = item.get("key")
        if key not in FIELDS:
            continue
        if key in result:
            raise NativeInputError("Duplicate usage attribute")
        value = item.get("value", {})
        if not isinstance(value, dict) or len(value) != 1:
            raise NativeInputError("Invalid OTLP scalar")
        kind, scalar = next(iter(value.items()))
        if kind not in {"stringValue", "intValue", "doubleValue", "boolValue"}:
            raise NativeInputError("Expected scalar usage metadata")
        result[key] = scalar
    return result


def source_time(record, values):
    if values.get("event.timestamp"):
        return UsageEvent.utc_timestamp(text(values["event.timestamp"], 50))
    nanoseconds = integer(record.get("timeUnixNano"), 10**22)
    if not nanoseconds:
        raise NativeInputError("A source timestamp is required")
    return UsageEvent.utc_timestamp(datetime.fromtimestamp(
        nanoseconds / 1_000_000_000, timezone.utc).isoformat())


def claude_events(payload, native):
    if not isinstance(payload, dict) or not isinstance(payload.get("resourceLogs"), list):
        raise NativeInputError("Expected an OTLP JSON logs request")
    output, count = [], 0
    for resource in payload["resourceLogs"]:
        common = attributes(resource.get("resource", {}).get("attributes", []))
        scopes = resource.get("scopeLogs", [])
        if not isinstance(scopes, list):
            raise NativeInputError("Invalid OTLP scopeLogs")
        for scope in scopes:
            records = scope.get("logRecords", [])
            if not isinstance(records, list):
                raise NativeInputError("Invalid OTLP logRecords")
            for record in records:
                count += 1
                if count > 1000 or not isinstance(record, dict):
                    raise NativeInputError("OTLP batch exceeds 1,000 records")
                values = common | attributes(record.get("attributes", []))
                body = record.get("body", {})
                name = values.get("event.name") or record.get("eventName") or (
                    body.get("stringValue") if isinstance(body, dict) else None)
                if name not in {"api_request", "api_error", "claude_code.api_request", "claude_code.api_error"}:
                    continue
                kind = "api_error" if name.endswith("api_error") else "api_response"
                session = text(values.get("session.id"))
                stamp = source_time(record, values)
                sequence = values.get("event.sequence")
                request = values.get("request_id") or values.get("client_request_id")
                if sequence is None and request is None:
                    raise NativeInputError("OTLP usage needs a request ID or event sequence")
                if sequence is not None:
                    sequence = integer(sequence, 10**15)
                if request is not None:
                    request = text(request, 512)
                prompt = values.get("prompt.id")
                if prompt is not None:
                    prompt = text(prompt)
                usage = None
                if kind == "api_response" and "input_tokens" in values and "output_tokens" in values:
                    usage = CodingToolUsage(
                        input_tokens=integer(values["input_tokens"]),
                        output_tokens=integer(values["output_tokens"]),
                        cache_read_tokens=integer(values["cache_read_tokens"])
                            if "cache_read_tokens" in values else None,
                        cache_write_tokens=integer(values["cache_creation_tokens"])
                            if "cache_creation_tokens" in values else None,
                        input_semantics="excludes_cache")
                estimate = None
                if kind == "api_response":
                    if "cost_usd_micros" in values:
                        estimate = usd(integer(values["cost_usd_micros"], 10**12), 1_000_000)
                        if "cost_usd" in values and abs(number(values["cost_usd"]) - Decimal(estimate)) > Decimal("0.000001"):
                            raise NativeInputError("Conflicting tool cost metadata")
                    elif "cost_usd" in values:
                        estimate = usd(values["cost_usd"])
                context = CodingToolContext(tool="claude_code", transport="otel_logs",
                    record_kind=kind, task_scope="prompt" if prompt else "session",
                    session_id=native.opaque("session", session), reported_model_estimate_usd=estimate)
                # Original source timestamp and sequence survive exporter retries.
                identity = (session, kind, stamp, str(record.get("timeUnixNano", "")), sequence, request)
                output.append(native.event(identity=identity, task=(session, prompt),
                    timestamp=stamp, model=values.get("model"), status="error" if kind == "api_error" else "success",
                    context=context, usage=usage,
                    latency=float(number(values["duration_ms"])) if "duration_ms" in values else None))
    return output


def receiver(native, token):
    if not isinstance(token, str) or len(token) < 32 or len(token) > 4096 or not token.isascii():
        raise NativeInputError("A private ASCII telemetry token of at least 32 characters is required")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health():
        return {"status": "ready"}

    @app.post("/v1/logs")
    async def logs(request: Request):
        authorization = request.headers.get("authorization", "")
        if request.headers.get("origin") or not authorization.isascii() or not hmac.compare_digest(
                authorization, "Bearer " + token):
            raise HTTPException(401, "Valid local telemetry token required")
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPException(415, "Configure OTLP HTTP/JSON")
        if request.headers.get("content-encoding", "identity") != "identity":
            raise HTTPException(415, "Compressed telemetry is not supported")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_INPUT:
                raise HTTPException(413, "OTLP request exceeds the supported size")
        try:
            events = claude_events(document(bytes(data)), native)
            native.save(events)
        except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
            raise HTTPException(422, "Invalid usage metadata; batch was not queued") from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, "Outbox unavailable; retry telemetry delivery") from None
        return JSONResponse({})

    return app


def serve(native, token_file, port):
    if native.tool != "claude_code" or not 1024 <= port <= 65535:
        raise NativeInputError("Invalid local Claude Code receiver configuration")
    import uvicorn
    uvicorn.run(receiver(native, read_secret(token_file)), host="127.0.0.1", port=port,
                access_log=False, log_level="warning", server_header=False,
                timeout_keep_alive=5, limit_concurrency=8, h11_max_incomplete_event_size=16_384)
