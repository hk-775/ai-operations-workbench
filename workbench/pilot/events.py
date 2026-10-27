"""Versioned metadata-only usage events and server-side Decimal accounting."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
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


Event = UsageEvent | BedrockUsageEvent
event_adapter = TypeAdapter(Event)


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
