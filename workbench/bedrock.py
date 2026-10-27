"""Opt-in boto3 Converse capture. The caller keeps prompts and responses.

Use an existing bedrock-runtime client. SDK retries are left unchanged and
reported honestly; this adapter never retries a billable application operation.
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

from pydantic import ValidationError

from .connector import Outbox, now, reserve_call
from .pilot.events import BedrockContext, BedrockUsage, BedrockUsageEvent


def _choice(value, allowed):
    return value if value in allowed else "unknown"


def _context(client, request, operation):
    if client.meta.service_model.service_name != "bedrock-runtime":
        raise ValueError("Use a boto3 bedrock-runtime client")
    if not isinstance(request.get("modelId"), str):
        raise ValueError("modelId is required")
    # Managed prompt versions own their inference configuration.
    if ":prompt/" not in request["modelId"]:
        maximum = request.get("inferenceConfig", {}).get("maxTokens")
        if type(maximum) is not int or not 1 <= maximum <= 100_000:
            raise ValueError("Set an explicit inferenceConfig.maxTokens between 1 and 100000")
    return BedrockContext(region=client.meta.region_name, operation=operation,
        service_tier=_choice(request.get("serviceTier", {}).get("type", "default"),
                             {"default", "priority", "flex", "reserved"}),
        performance=_choice(request.get("performanceConfig", {}).get("latency", "standard"),
                            {"standard", "optimized"}),
        additional_charges=bool(request.get("guardrailConfig") or request.get("additionalModelRequestFields")
                                or ":prompt/" in request["modelId"]))


def _reserve(client, outbox, request, task_id, project, stage, operation, evidence):
    pending = BedrockUsageEvent(schema_version="bedrock.usage.v1", event_id=uuid.uuid4().hex,
        task_id=task_id, project=project, stage=stage, model=request.get("modelId"),
        occurred_at=now(), status="interrupted", evidence=evidence,
        bedrock=_context(client, request, operation))
    return pending, reserve_call(outbox, pending), time.monotonic()


def _response_event(pending, response, started, *, status="success"):
    """Allowlist metadata; no headers, exception messages, trace or response text."""
    context = pending.bedrock.model_dump()
    raw = response.get("usage")
    usage, issue = None, "missing_usage"
    if isinstance(raw, dict):
        try:
            usage = BedrockUsage(input_tokens=raw["inputTokens"], output_tokens=raw["outputTokens"],
                total_tokens=raw["totalTokens"], cache_read_input_tokens=raw.get("cacheReadInputTokens", 0),
                cache_write_input_tokens=raw.get("cacheWriteInputTokens", 0))
            # A TTL breakdown without its aggregate cache-write count cannot be
            # mistaken for an uncached request when an SDK/provider changes.
            issue = "invalid_metadata" if raw.get("cacheDetails") and not usage.cache_write_input_tokens else None
        except (KeyError, TypeError, ValidationError):
            issue = "invalid_metadata"
    metadata = response.get("ResponseMetadata") or {}
    retries = metadata.get("RetryAttempts")
    context["sdk_retry_count"] = retries if type(retries) is int and 0 <= retries <= 100 else None
    latency = (response.get("metrics") or {}).get("latencyMs")
    context["provider_latency_ms"] = latency if type(latency) in {float, int} and 0 <= latency <= 86_400_000 else None
    if "serviceTier" in response:
        context["service_tier"] = _choice(response["serviceTier"].get("type"),
                                          {"default", "priority", "flex", "reserved"})
    if "performanceConfig" in response:
        context["performance"] = _choice(response["performanceConfig"].get("latency"), {"standard", "optimized"})
    context["capture_issue"] = issue if status == "success" else (
        "unfinished_stream" if status == "interrupted" else "request_failed")
    request_id = metadata.get("RequestId")
    return BedrockUsageEvent(**(pending.model_dump() | {
        "status": status, "latency_ms": min(86_400_000.0, (time.monotonic() - started) * 1000),
        "bedrock": BedrockContext(**context), "usage": usage,
        "usage_basis": "provider_reported" if usage else "unknown",
        "attempt_coverage": "single_attempt" if status == "success" and context["sdk_retry_count"] == 0
                             else "final_response_only" if status == "success" else "unknown",
        "provider_response_id": request_id if isinstance(request_id, str) and len(request_id) <= 512 else None,
    }))


def _finish(outbox, path, pending, response, started, status):
    try:
        event = _response_event(pending, response, started, status=status)
    except (ValidationError, TypeError, ValueError, AttributeError):
        # An SDK response can evolve. Preserve a visible gap, never discard the call.
        event = pending.model_copy(update={
            "status": status, "latency_ms": min(86_400_000.0, (time.monotonic() - started) * 1000),
            "bedrock": pending.bedrock.model_copy(update={"capture_issue": "invalid_metadata"})})
    outbox.put(event)
    path.unlink()


def capture_converse(client, outbox: Outbox, *, task_id, project, stage, **request):
    """Call Converse once, reserve first, enqueue metadata, return the original response."""
    pending, path, started = _reserve(client, outbox, request, task_id, project, stage, "Converse", "observed")
    try:
        response = client.converse(**request)
    except BaseException as exc:
        _finish(outbox, path, pending, {}, started, "error" if isinstance(exc, Exception) else "interrupted")
        raise
    _finish(outbox, path, pending, response, started, "success")
    return response


class CapturedStream:
    """Closeable iterator; durable finalization happens at metadata/end/close."""
    def __init__(self, response, outbox, pending, path, started):
        self.stream = response["stream"]
        self.iterator = iter(self.stream)
        self.metadata = {"ResponseMetadata": response.get("ResponseMetadata", {})}
        self.outbox, self.pending, self.path, self.started = outbox, pending, path, started
        self.finished = False
        self.saw_stop = False
        self.saw_metadata = False
        self.saw_error = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.finished:
            raise StopIteration
        try:
            item = next(self.iterator)
        except StopIteration:
            self.finish("success" if self.saw_metadata and self.saw_stop and not self.saw_error else
                        "error" if self.saw_error else "interrupted")
            raise
        except BaseException as exc:
            self.finish("error" if isinstance(exc, Exception) else "interrupted")
            raise
        if "messageStop" in item:
            self.saw_stop = True
        if "metadata" in item:
            # SDK metadata includes no response text; select only supported fields.
            self.metadata.update({key: item["metadata"][key] for key in
                ("usage", "metrics", "serviceTier", "performanceConfig") if key in item["metadata"]})
            self.saw_metadata = True
        if any(key.endswith("Exception") for key in item):
            self.saw_error = True
        return item

    def finish(self, status):
        if not self.finished:
            _finish(self.outbox, self.path, self.pending, self.metadata, self.started, status)
            self.finished = True

    def close(self):
        try:
            self.finish("success" if self.saw_metadata and self.saw_stop and not self.saw_error else
                        "error" if self.saw_error else "interrupted")
        finally:
            self.stream.close()


@contextmanager
def capture_converse_stream(client, outbox: Outbox, *, task_id, project, stage, **request):
    """Consume inside `with`; breaking early records an interrupted, unknown-cost call."""
    pending, path, started = _reserve(client, outbox, request, task_id, project, stage,
                                      "ConverseStream", "observed")
    try:
        response = client.converse_stream(**request)
        stream = CapturedStream(response, outbox, pending, path, started)
    except BaseException as exc:
        _finish(outbox, path, pending, {}, started, "error" if isinstance(exc, Exception) else "interrupted")
        raise
    try:
        yield stream
    finally:
        stream.close()
