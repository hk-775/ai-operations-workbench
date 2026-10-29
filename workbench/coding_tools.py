"""Metadata-only Codex JSONL, Claude Code OTLP, and Cursor Admin API connectors.

Native payloads can contain private content. Only explicitly selected metadata
enters the durable outbox; raw documents, emails, errors and API keys never do.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys

import httpx

from .connector import Outbox
from .domain import digest, money
from .pilot.events import CodingToolContext, CodingToolUsage, CodingToolUsageEvent, UsageEvent

MAX_INPUT = 8_000_000
CURSOR_URL = "https://api.cursor.com/teams/filtered-usage-events"
TOOLS = ("codex", "cursor", "claude_code")


class NativeInputError(ValueError):
    """A safe diagnostic that never embeds the untrusted input."""


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise NativeInputError("Invalid numeric metadata")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise NativeInputError("Invalid numeric metadata") from None
    if not result.is_finite():
        raise NativeInputError("Nonfinite numeric metadata")
    return result


def integer(value, maximum=100_000_000):
    result = number(value)
    if result != result.to_integral_value() or not 0 <= result <= maximum:
        raise NativeInputError("Invalid integer metadata")
    return int(result)


def text(value, maximum=200):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise NativeInputError("Missing or invalid identifier metadata")
    return value


def document(value: bytes):
    if len(value) > MAX_INPUT:
        raise NativeInputError("Native input exceeds the supported size")
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise NativeInputError("Duplicate JSON fields")
            result[key] = item
        return result
    try:
        return json.loads(value, parse_float=Decimal, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              NativeInputError("Nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise NativeInputError("Invalid native JSON") from None


def usd(value, divisor=1):
    result = number(value) / divisor
    if not 0 <= result <= 1_000_000 or result != result.quantize(Decimal("0.000000001")):
        raise NativeInputError("Unsupported monetary precision or amount")
    return money(result)


class NativeOutbox:
    def __init__(self, path, tool, project, *, evidence="observed"):
        if tool not in TOOLS:
            raise NativeInputError("Unsupported coding tool")
        if evidence not in {"observed", "fixture"}:
            raise NativeInputError("Unsupported native evidence mode")
        self.outbox, self.tool, self.project = Outbox(Path(path)), tool, text(project, 100)
        self.evidence = evidence
        with self.outbox.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS native_binding
                       (singleton INTEGER PRIMARY KEY, tool TEXT NOT NULL, project TEXT NOT NULL,
                        evidence TEXT NOT NULL, pseudonym_key TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS native_windows
                       (start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                        fingerprint TEXT NOT NULL, PRIMARY KEY(start_ms,end_ms))""")
            previous = db.execute("SELECT tool,project,evidence FROM native_binding WHERE singleton=1").fetchone()
            if previous and (previous["tool"], previous["project"], previous["evidence"]) != (tool, project, evidence):
                raise NativeInputError("Use a separate outbox for another tool, project or evidence mode")
            if not previous:
                if db.execute("SELECT 1 FROM outbox LIMIT 1").fetchone():
                    raise NativeInputError("Use an empty outbox for a new native connector")
                db.execute("INSERT INTO native_binding VALUES (1,?,?,?,?)",
                           (tool, project, evidence, secrets.token_hex(32)))
            self.key = db.execute("SELECT pseudonym_key FROM native_binding WHERE singleton=1").fetchone()[0]

    def opaque(self, *parts):
        # Stable per-outbox pseudonyms, including for Cursor's userEmail.
        value = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
        return hmac.new(self.key.encode(), value, hashlib.sha256).hexdigest()

    def event(self, *, identity, task, timestamp, model, status, context, usage=None, latency=None):
        return CodingToolUsageEvent(event_id=self.opaque("event", *identity),
            task_id=self.opaque("task", *task), project=self.project,
            stage=context.record_kind, provider=self.tool, model=text(model, 150),
            occurred_at=timestamp, status=status, usage=usage, evidence=self.evidence,
            usage_basis="tool_reported" if usage is not None else "unknown",
            attempt_coverage="unknown", latency_ms=latency, coding_tool=context)

    def save(self, events, *, window=None):
        """An entire OTLP batch / Cursor window commits or none of it does."""
        rows = [(event.event_id, digest(event.model_dump()), json.dumps(event.model_dump()))
                for event in events]
        fingerprint = digest(sorted((identity, hash_) for identity, hash_, _ in rows))
        with self.outbox.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if window:
                start, end = window
                overlaps = db.execute("""SELECT * FROM native_windows
                    WHERE start_ms<=? AND end_ms>=?""", (end, start)).fetchall()
                for prior in overlaps:
                    if (prior["start_ms"], prior["end_ms"], prior["fingerprint"]) != (
                            start, end, fingerprint):
                        raise NativeInputError(
                            "Cursor window overlaps or changed; review it instead of double-counting")
            added = 0
            for identity, hash_, payload in rows:
                previous = db.execute("SELECT fingerprint FROM outbox WHERE id=?", (identity,)).fetchone()
                if previous and previous["fingerprint"] != hash_:
                    raise NativeInputError("Native event changed; existing evidence was preserved")
                if not previous:
                    db.execute("INSERT INTO outbox(id,fingerprint,payload) VALUES(?,?,?)",
                               (identity, hash_, payload))
                    added += 1
            if window:
                db.execute("INSERT OR IGNORE INTO native_windows VALUES(?,?,?)", (*window, fingerprint))
        return {"added": added, "duplicates": len(rows) - added}


def codex_events(lines, native, *, capture_id, started_at, model):
    """Stream documented `codex exec --json` turn records; discard every item body.

    The invocation's capture ID and start time must be retained for replays.
    A turn's tokens are not represented as a single API request.
    """
    text(capture_id)
    timestamp = UsageEvent.utc_timestamp(started_at)
    text(model, 150)
    session, turn, active, total_bytes = None, 0, False, 0
    def event(status, tokens=None):
        usage = None
        if tokens is not None:
            usage = CodingToolUsage(
                input_tokens=integer(tokens["input_tokens"]),
                output_tokens=integer(tokens["output_tokens"]),
                cache_read_tokens=integer(tokens["cached_input_tokens"])
                    if "cached_input_tokens" in tokens else None,
                reasoning_output_tokens=integer(tokens["reasoning_output_tokens"])
                    if "reasoning_output_tokens" in tokens else None,
                input_semantics="includes_cache_read")
        context = CodingToolContext(tool="codex", transport="codex_jsonl", record_kind="turn",
            task_scope="turn", session_id=native.opaque("session", session),
            timestamp_basis="capture_start", model_basis="configured")
        return native.event(identity=(capture_id, turn), task=(session, capture_id, turn),
            timestamp=timestamp, model=model, status=status, context=context, usage=usage)
    for line in lines:
        total_bytes += len(line)
        if total_bytes > 64_000_000 or len(line) > MAX_INPUT:
            raise NativeInputError("Codex capture exceeds the supported size")
        if not line.strip():
            continue
        item = document(line)
        if not isinstance(item, dict):
            raise NativeInputError("Invalid Codex event")
        kind = item.get("type")
        if kind == "thread.started":
            if session is not None:
                raise NativeInputError("One capture must contain one Codex invocation")
            session = text(item.get("thread_id"))
        elif kind == "turn.started":
            if session is None or active:
                raise NativeInputError("Invalid Codex turn ordering")
            turn += 1
            active = True
        elif kind in {"turn.completed", "turn.failed"}:
            if not active:
                raise NativeInputError("Codex terminal event has no matching turn")
            yield event("success" if kind == "turn.completed" else "error",
                        item.get("usage") if kind == "turn.completed" else None)
            active = False
        # item.*, error details, prompts and responses are deliberately not retained.
    if active:
        yield event("interrupted")
    if not session or not turn:
        raise NativeInputError("No documented Codex turns were found")


def cursor_events(payload, native, *, start_ms, end_ms):
    if not 0 <= start_ms <= end_ms < int(datetime.now(timezone.utc).timestamp() * 1000):
        raise NativeInputError("Use a completed Cursor reporting window")
    if not isinstance(payload, dict) or not isinstance(payload.get("usageEvents"), list):
        raise NativeInputError("Expected Cursor Admin API usageEvents")
    items = payload["usageEvents"]
    if len(items) > 20_000:
        raise NativeInputError("Cursor window exceeds 20,000 events")
    period = payload.get("period", {})
    if (integer(period.get("startDate"), 10**15), integer(period.get("endDate"), 10**15)) != (
            start_ms, end_ms):
        raise NativeInputError("Cursor response period differs from the requested window")
    count = integer(payload.get("totalUsageEventsCount"), 20_000)
    if count != len(items):
        raise NativeInputError("Cursor snapshot is incomplete; include all pages")
    grouped = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            raise NativeInputError("Invalid Cursor event")
        stamp = integer(item.get("timestamp"), 10**15)
        if not start_ms <= stamp <= end_ms:
            raise NativeInputError("Cursor event is outside the requested period")
        model = text(item.get("model"), 150)
        actor = native.opaque("actor", text(item.get("serviceAccountId") or item.get("userEmail"), 320))
        session = item.get("conversationId") or item.get("cloudAgentId")
        if session is not None:
            session = native.opaque("session", text(session))
        usage, token = None, item.get("tokenUsage")
        if token is not None:
            if not isinstance(token, dict):
                raise NativeInputError("Invalid Cursor token metadata")
            usage = CodingToolUsage(input_tokens=integer(token["inputTokens"]),
                output_tokens=integer(token["outputTokens"]),
                cache_read_tokens=integer(token["cacheReadTokens"]) if "cacheReadTokens" in token else None,
                cache_write_tokens=integer(token["cacheWriteTokens"]) if "cacheWriteTokens" in token else None,
                input_semantics="vendor_defined")
        category = text(item.get("kind"), 100)
        billing = "included" if category.lower().startswith("included") else (
            "usage_based" if category.lower() == "usage-based" else "unknown")
        context = CodingToolContext(tool="cursor", transport="cursor_admin", record_kind="vendor_usage",
            task_scope="session" if session else "event", session_id=session, actor_id=actor,
            billing_category=billing,
            reported_model_estimate_usd=usd(token["totalCents"], 100)
                if token is not None and "totalCents" in token else None,
            reported_charge_usd=usd(item["chargedCents"], 100) if "chargedCents" in item else None)
        identity = (actor, stamp, model, session, billing)
        grouped[identity].append((context, usage))
    events = []
    for identity, values in grouped.items():
        # Preserve multiplicity: two identical vendor rows are not one row.
        values.sort(key=lambda v: digest([v[0].model_dump(), v[1].model_dump() if v[1] else None]))
        for occurrence, (context, usage) in enumerate(values):
            actor, stamp, model, session, _ = identity
            events.append(native.event(identity=(*identity, occurrence),
                task=(actor, session) if session else (*identity, occurrence),
                timestamp=datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat(),
                model=model, status="unknown", context=context, usage=usage))
    return events


def cursor_fetch(api_key, start_ms, end_ms, *, client=None):
    """Bounded, explicitly requested reads; no inference calls or credential redirects."""
    if not isinstance(api_key, str) or not 10 <= len(api_key) <= 4096 or any(
            character in api_key for character in "\r\n"):
        raise NativeInputError("Read a Cursor Admin API key from a private file")
    if not 0 <= start_ms <= end_ms or end_ms - start_ms >= 31 * 86_400_000:
        raise NativeInputError("Choose a Cursor window of at most 31 days")
    if end_ms >= int(datetime.now(timezone.utc).timestamp() * 1000):
        raise NativeInputError("Use a completed Cursor reporting window")
    from .connector import _borrow
    context = httpx.Client(timeout=30, follow_redirects=False, trust_env=False) if client is None else _borrow(client)
    combined, expected = [], None
    with context as transport:
        for page in range(1, 21):
            try:
                with transport.stream("POST", CURSOR_URL, auth=(api_key, ""), follow_redirects=False,
                        json={"startDate": start_ms, "endDate": end_ms, "page": page, "pageSize": 1000}) as response:
                    if response.status_code != 200:
                        raise NativeInputError("Cursor Admin API rejected the read; no window was imported")
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65_536):
                        if len(data) + len(chunk) > MAX_INPUT:
                            raise NativeInputError("Cursor page exceeds the supported size")
                        data.extend(chunk)
                    payload = document(bytes(data))
            except httpx.HTTPError:
                raise NativeInputError("Cursor Admin API is unavailable; no window was imported") from None
            if not isinstance(payload, dict) or not isinstance(payload.get("usageEvents"), list):
                raise NativeInputError("Invalid Cursor page")
            pagination = payload.get("pagination", {})
            count = integer(payload.get("totalUsageEventsCount"), 20_000)
            if expected is None:
                expected = count
            if count != expected or integer(pagination.get("currentPage"), 20) != page:
                raise NativeInputError("Cursor pagination changed during the read")
            if len(payload["usageEvents"]) > 1000:
                raise NativeInputError("Cursor page exceeds the requested size")
            period = payload.get("period", {})
            if (period.get("startDate"), period.get("endDate")) != (start_ms, end_ms):
                raise NativeInputError("Cursor page returned another reporting period")
            combined.extend(payload["usageEvents"])
            following = pagination.get("hasNextPage")
            if not isinstance(following, bool):
                raise NativeInputError("Cursor pagination is incomplete")
            if not following:
                if len(combined) != expected:
                    raise NativeInputError("Cursor snapshot was incomplete")
                return {"usageEvents": combined, "totalUsageEventsCount": expected,
                        "period": {"startDate": start_ms, "endDate": end_ms}}
    raise NativeInputError("Cursor window needs more than 20 pages; split the reporting window")


def read_secret(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise NativeInputError("Use an owner-only regular credential file")
    if path.stat().st_size > 4096:
        raise NativeInputError("Credential file exceeds the supported size")
    return path.read_text().strip()


def milliseconds(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise NativeInputError("Use a timezone-qualified reporting boundary")
    return int(stamp.timestamp() * 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--fixture", action="store_true", help="Label authored test data explicitly")
    commands = parser.add_subparsers(dest="command", required=True)
    codex = commands.add_parser("codex", help="Read documented codex exec --json output")
    codex.add_argument("--input", default="-")
    codex.add_argument("--capture-id", required=True)
    codex.add_argument("--started-at", required=True)
    codex.add_argument("--model", required=True, help="Configured model label; not an attested response model")
    claude = commands.add_parser("claude-import", help="Import an OTLP/HTTP JSON logs export")
    claude.add_argument("--input", type=Path, required=True)
    serve = commands.add_parser("claude-listen", help="Receive Claude Code OTLP JSON on loopback")
    serve.add_argument("--port", type=int, default=14318)
    serve.add_argument("--token-file", type=Path, required=True)
    for name in ("cursor-import", "cursor-fetch"):
        cursor = commands.add_parser(name)
        cursor.add_argument("--start", required=True, help="Inclusive UTC boundary")
        cursor.add_argument("--before", required=True, help="Exclusive UTC boundary")
        if name == "cursor-import":
            cursor.add_argument("--input", type=Path, required=True)
        else:
            cursor.add_argument("--api-key-file", type=Path, required=True)
    args = parser.parse_args()
    tool = "claude_code" if args.command.startswith("claude") else (
        "cursor" if args.command.startswith("cursor") else "codex")
    try:
        native = NativeOutbox(args.outbox, tool, args.project,
                             evidence="fixture" if args.fixture else "observed")
        if tool == "codex":
            stream = sys.stdin.buffer if args.input == "-" else Path(args.input).open("rb")
            added = duplicate = 0
            try:
                for event in codex_events(stream, native, capture_id=args.capture_id,
                        started_at=args.started_at, model=args.model):
                    report = native.save([event])
                    added += report["added"]; duplicate += report["duplicates"]
            finally:
                if args.input != "-":
                    stream.close()
            report = {"added": added, "duplicates": duplicate}
        elif tool == "claude_code":
            from .coding_tools_otel import claude_events, serve
            if args.command == "claude-listen":
                serve(native, args.token_file, args.port)
                return
            with args.input.open("rb") as stream:
                payload = document(stream.read(MAX_INPUT + 1))
            report = native.save(claude_events(payload, native))
        else:
            start, end = milliseconds(args.start), milliseconds(args.before) - 1
            if not 0 <= start <= end or end - start >= 31 * 86_400_000:
                raise NativeInputError("Choose a completed window of at most 31 days")
            if args.command == "cursor-fetch":
                payload = cursor_fetch(read_secret(args.api_key_file), start, end)
            else:
                with args.input.open("rb") as stream:
                    payload = document(stream.read(MAX_INPUT + 1))
            report = native.save(cursor_events(payload, native, start_ms=start, end_ms=end),
                                 window=(start, end))
        print(json.dumps({"tool": tool, **report, "pending": native.outbox.pending(),
                          "model_calls_made": 0}))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, InvalidOperation):
        parser.exit(1, "Native collection stopped. Check format, bounds and private configuration. "
                    "Existing outbox evidence was preserved; completed streamed turns may already be queued.\n")


if __name__ == "__main__":
    main()
