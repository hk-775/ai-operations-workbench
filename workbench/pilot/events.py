"""Versioned metadata-only usage events and server-side Decimal accounting."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from workbench.domain import ROOT, digest, money, prices, strict_json

Identifier = str


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt_tokens: int = Field(ge=0, le=100_000_000)
    completion_tokens: int = Field(ge=0, le=100_000_000)
    cached_tokens: int = Field(default=0, ge=0, le=100_000_000)
    cache_creation_tokens: int = Field(default=0, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def valid_cache(self):
        if self.cached_tokens > self.prompt_tokens:
            raise ValueError("cached tokens exceed input tokens")
        return self


class UsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["axon.usage.v1"] = "axon.usage.v1"
    event_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    task_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    project: str = Field(min_length=1, max_length=100)
    stage: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=150)
    occurred_at: str = Field(max_length=50)
    status: Literal["success", "error", "interrupted"]
    evidence: Literal["observed", "recorded", "fixture"] = "observed"
    usage_basis: Literal["provider_reported", "estimated", "unknown"] = "unknown"
    attempt_coverage: Literal["single_attempt", "final_response_only", "unknown"] = "unknown"
    usage: Usage | None = None
    latency_ms: float = Field(ge=0, le=86_400_000, allow_inf_nan=False)
    provider_response_id: str | None = Field(default=None, max_length=512)
    recording_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    case_id: str | None = Field(default=None, max_length=100)

    @field_validator("occurred_at")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if parsed.timestamp() > datetime.now(timezone.utc).timestamp() + 300:
            raise ValueError("event timestamp is in the future")
        return parsed.astimezone(timezone.utc).isoformat()

    @model_validator(mode="after")
    def usage_consistency(self):
        if self.usage_basis != "unknown" and self.usage is None:
            raise ValueError("a usage basis requires token usage")
        if self.recording_id is not None and self.evidence == "observed":
            raise ValueError("backfilled recordings must be labeled recorded or fixture")
        return self


class BedrockUsage(BaseModel):
    """Keep AWS token categories intact; do not impose OpenAI cache semantics."""
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0, le=100_000_000)
    output_tokens: int = Field(ge=0, le=100_000_000)
    total_tokens: int = Field(ge=0, le=400_000_000)
    cache_read_input_tokens: int = Field(default=0, ge=0, le=100_000_000)
    cache_write_input_tokens: int = Field(default=0, ge=0, le=100_000_000)


class BedrockContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    region: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")
    operation: Literal["Converse", "ConverseStream"]
    service_tier: Literal["default", "priority", "flex", "reserved", "unknown"] = "unknown"
    performance: Literal["standard", "optimized", "unknown"] = "unknown"
    additional_charges: bool = True
    sdk_retry_count: int | None = Field(default=None, ge=0, le=100)
    provider_latency_ms: float | None = Field(default=None, ge=0, le=86_400_000, allow_inf_nan=False)
    capture_issue: Literal["missing_usage", "invalid_metadata", "unfinished_stream", "request_failed"] | None = None


class BedrockUsageEvent(UsageEvent):
    schema_version: Literal["bedrock.usage.v1"]
    provider: Literal["bedrock"] = "bedrock"
    model: str = Field(min_length=1, max_length=2048)
    usage: BedrockUsage | None = None
    # An interrupted reservation has no measured duration.
    latency_ms: float | None = Field(default=None, ge=0, le=86_400_000, allow_inf_nan=False)
    bedrock: BedrockContext

    @model_validator(mode="after")
    def bedrock_consistency(self):
        if self.recording_id is not None or self.case_id is not None:
            raise ValueError("Bedrock usage metadata is not a support recording")
        if self.attempt_coverage == "single_attempt" and (
                self.bedrock.sdk_retry_count != 0 or self.status != "success"):
            raise ValueError("Single-attempt coverage requires a completed response with zero SDK retries")
        return self


class CodingToolUsage(BaseModel):
    """Native token categories are retained instead of repriced as API usage."""
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0, le=100_000_000)
    output_tokens: int = Field(ge=0, le=100_000_000)
    cache_read_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    cache_write_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    reasoning_output_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    input_semantics: Literal["includes_cache_read", "excludes_cache", "vendor_defined"]

    @model_validator(mode="after")
    def categories(self):
        if self.input_semantics == "includes_cache_read" and (
                self.cache_read_tokens or 0) > self.input_tokens:
            raise ValueError("Cached input exceeds total input")
        if (self.reasoning_output_tokens or 0) > self.output_tokens:
            raise ValueError("Reasoning output exceeds total output")
        return self


class CodingToolContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: Literal["codex", "cursor", "claude_code"]
    transport: Literal["codex_jsonl", "otel_logs", "cursor_admin"]
    record_kind: Literal["turn", "api_response", "api_error", "vendor_usage"]
    task_scope: Literal["turn", "prompt", "session", "event"]
    timestamp_basis: Literal["source", "capture_start"] = "source"
    model_basis: Literal["reported", "configured"] = "reported"
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    actor_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    # These are imported assertions, never independently authenticated invoices.
    reported_model_estimate_usd: str | None = Field(default=None, max_length=80)
    reported_charge_usd: str | None = Field(default=None, max_length=80)
    billing_category: Literal["included", "usage_based", "unknown"] = "unknown"

    @field_validator("reported_model_estimate_usd", "reported_charge_usd")
    @classmethod
    def amount(cls, value):
        if value is None:
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError("Invalid reported USD") from None
        if (not number.is_finite() or not 0 <= number <= 1_000_000
                or number != number.quantize(Decimal("0.000000001"))):
            raise ValueError("Reported USD must be nonnegative with at most nine decimal places")
        return money(number)


class CodingToolUsageEvent(UsageEvent):
    schema_version: Literal["coding-tool.usage.v1"] = "coding-tool.usage.v1"
    provider: Literal["codex", "cursor", "claude_code"]
    status: Literal["success", "error", "interrupted", "unknown"]
    usage_basis: Literal["tool_reported", "unknown"] = "unknown"
    usage: CodingToolUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0, le=86_400_000, allow_inf_nan=False)
    coding_tool: CodingToolContext

    @model_validator(mode="after")
    def native_contract(self):
        expected = {"codex": "codex_jsonl", "cursor": "cursor_admin", "claude_code": "otel_logs"}
        if self.provider != self.coding_tool.tool or self.coding_tool.transport != expected[self.provider]:
            raise ValueError("Coding tool and transport do not match")
        if self.recording_id is not None or self.case_id is not None or self.provider_response_id is not None:
            raise ValueError("Native tool metadata cannot impersonate support recordings")
        if self.attempt_coverage != "unknown":
            raise ValueError("Native metadata does not establish complete API attempt capture")
        if self.provider != "cursor" and self.coding_tool.reported_charge_usd is not None:
            raise ValueError("This connector does not report vendor charges")
        if self.provider == "codex" and self.coding_tool.reported_model_estimate_usd is not None:
            raise ValueError("Codex JSON output does not report monetary cost")
        context = self.coding_tool
        if self.provider == "codex" and (context.record_kind != "turn" or context.task_scope != "turn"
                or context.timestamp_basis != "capture_start" or context.model_basis != "configured"
                or self.latency_ms is not None or self.status == "unknown"):
            raise ValueError("Codex JSONL describes configured-model turns")
        if self.provider == "cursor" and (context.record_kind != "vendor_usage"
                or context.task_scope not in {"session", "event"} or self.status != "unknown"
                or self.latency_ms is not None):
            raise ValueError("Cursor usage does not attest call status or duration")
        if self.provider == "claude_code" and (context.record_kind not in {"api_response", "api_error"}
                or context.task_scope not in {"session", "prompt"}):
            raise ValueError("Unsupported Claude Code usage event")
        if self.provider != "codex" and (context.model_basis != "reported" or context.timestamp_basis != "source"):
            raise ValueError("Native usage requires source model and timestamp metadata")
        if self.usage and self.usage.input_semantics != {
                "codex": "includes_cache_read", "cursor": "vendor_defined", "claude_code": "excludes_cache"}[self.provider]:
            raise ValueError("Native token categories differ from this tool's contract")
        if context.record_kind == "api_error" and (self.status != "error" or self.usage is not None
                or context.reported_model_estimate_usd is not None):
            raise ValueError("API errors keep unknown usage and costs")
        return self


Event = UsageEvent | BedrockUsageEvent | CodingToolUsageEvent
event_adapter = TypeAdapter(Event)
SOURCE_SCHEMAS = {"axonllm": "axon.usage.v1", "bedrock": "bedrock.usage.v1",
                  **{kind: "coding-tool.usage.v1" for kind in ("codex", "cursor", "claude_code")}}


class CollectorHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    collector_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    pending_events: int = Field(ge=0, le=1_000_000_000)
    inflight_calls: int = Field(ge=0, le=1_000_000_000)
    retrying_events: int = Field(ge=0, le=1_000_000_000)
    oldest_pending_at: str | None = Field(default=None, max_length=50)

    @field_validator("oldest_pending_at")
    @classmethod
    def timestamp(cls, value):
        return None if value is None else UsageEvent.utc_timestamp(value)

    @model_validator(mode="after")
    def counts(self):
        if self.retrying_events > self.pending_events:
            raise ValueError("Retrying events exceed pending events")
        return self


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[Event] = Field(min_length=1, max_length=100)


def pricebook() -> dict:
    snapshot = prices()
    snapshot["bedrock"] = strict_json((ROOT / "config/bedrock-prices.json").read_text())
    return {"id": digest(snapshot), "snapshot": snapshot}


def account(event: UsageEvent, book: dict) -> dict:
    """Price only supported reported usage; leave uncovered units explicit."""
    if isinstance(event, CodingToolUsageEvent):
        return {
            "api_estimate_usd": None, "cost_basis": "tool_reported", "pricebook_id": book["id"],
            "unknown_reason": "Tool usage does not establish an API bill or allocated subscription cost.",
            "attempt_cost_complete": False, "invoice_usd": None, "hardware_electricity_usd": None,
            "reported_model_estimate_usd": event.coding_tool.reported_model_estimate_usd,
            "reported_charge_usd": event.coding_tool.reported_charge_usd,
        }
    amount = None
    reason = None
    rate = book["snapshot"]["models"].get(event.model)
    if event.usage is None or event.usage_basis != "provider_reported":
        reason = "Provider-reported usage is unavailable"
    elif isinstance(event, BedrockUsageEvent):
        amount, reason = bedrock_amount(event, book["snapshot"].get("bedrock", {}))
    elif event.provider != "openai" or rate is None:
        reason = "No reviewed rate for this provider/model"
    elif event.usage.cache_creation_tokens:
        reason = "Cache-creation units are not covered by this rate card"
    else:
        usage = event.usage
        amount = (Decimal(usage.prompt_tokens - usage.cached_tokens) * Decimal(rate["input"])
                   + Decimal(usage.cached_tokens) * Decimal(rate["cached_input"])
                   + Decimal(usage.completion_tokens) * Decimal(rate["output"])) / 1_000_000
    return {
        "api_estimate_usd": None if amount is None else money(amount),
        "cost_basis": "unknown" if amount is None else "estimated",
        "pricebook_id": book["id"],
        "unknown_reason": reason,
        "attempt_cost_complete": amount is not None and event.attempt_coverage == "single_attempt",
        "invoice_usd": None,
        "hardware_electricity_usd": None,
    }


def bedrock_amount(event: BedrockUsageEvent, book: dict):
    context, usage = event.bedrock, event.usage
    if event.status != "success" or context.capture_issue:
        return None, "Bedrock call metadata is incomplete"
    if context.additional_charges:
        return None, "Additional Bedrock features are outside the token rate card"
    if usage.cache_read_input_tokens or usage.cache_write_input_tokens:
        return None, "Bedrock cache pricing is not covered by this rate card"
    if usage.total_tokens != usage.input_tokens + usage.output_tokens:
        return None, "Bedrock token totals do not match the reviewed pricing contract"
    for rate in book.get("rates", []):
        if (event.model == rate["model"] and context.region == rate["region"]
                and context.service_tier == rate["service_tier"]
                and context.performance == rate["performance"]
                and rate["effective_from"] <= event.occurred_at < rate["review_expires_at"]):
            amount = (Decimal(usage.input_tokens) * Decimal(rate["input"])
                      + Decimal(usage.output_tokens) * Decimal(rate["output"])) / 1_000_000
            return amount, None
    return None, "No reviewed Bedrock rate for this model, region, tier, performance, and date"


def recording_events(recording: dict) -> list[UsageEvent]:
    """Backfill saved evidence without relabeling it as newly observed traffic."""
    identity = digest(recording)
    rows = []
    for sample in recording["samples"]:
        for stage in sample["stages"]:
            usage = stage.get("usage")
            rows.append(UsageEvent(
                event_id=f"recording:{identity}:{sample['case_id']}:{sample['model']}:{stage['name']}",
                task_id=f"{identity}:{sample['case_id']}:{sample['model']}",
                project="recorded-support", stage=stage["name"], provider="openai",
                model=sample["model"], occurred_at=recording["created_at"],
                status=stage["status"],
                evidence="fixture" if recording["mode"] == "fixture" else "recorded",
                usage_basis="provider_reported" if usage else "unknown",
                attempt_coverage="single_attempt",
                usage=None if usage is None else Usage(**{
                    key: usage.get(key, 0) for key in Usage.model_fields}),
                latency_ms=float(stage["latency_ms"]),
                provider_response_id=stage.get("provider_response_id"),
                recording_id=identity, case_id=sample["case_id"],
            ))
    return rows
