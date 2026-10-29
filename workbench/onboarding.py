"""Connector setup guidance and private local token handling; no account auto-login."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import warnings

from sqlalchemy import func, select

from workbench.pilot.database import events, tokens
from workbench.pilot.workflows import WorkflowError


def command(*args):
    return shlex.join(str(arg) for arg in args)


def guide(database, settings, team, identity, project):
    source = database.source(team, identity)
    if source is None:
        raise KeyError(identity)
    if source["kind"] not in {"axonllm", "bedrock", "codex", "claude_code", "cursor"}:
        raise WorkflowError("Saved recordings do not need a live collector")
    with database.engine.connect() as db:
        source = dict(source)
        source["tokens"] = [dict(row) for row in db.execute(select(tokens.c.revoked, tokens.c.expires_at)
            .where(tokens.c.source_id == identity)).mappings()]
        health = database.collection_health(db, source)
        observed = db.execute(select(func.count()).select_from(events).where(
            events.c.team_id == team, events.c.source_id == identity,
            events.c.evidence == "observed")).scalar_one()
        latest = db.execute(select(func.max(events.c.received_at)).where(
            events.c.team_id == team, events.c.source_id == identity,
            events.c.evidence == "observed")).scalar_one()
    outbox, token_file = f".pilot/{identity}.outbox.db", f".pilot/{identity}.token"
    base = ["uv", "run", "--locked", "python", "-m"]
    native = [*base, "workbench.coding_tools", "--project", project, "--outbox", outbox]
    common = [
        {"title": "Save the Workbench connection token",
         "description": "Issue a token in Usage sources, then paste it into this hidden terminal prompt. It creates a new private file and never overwrites one.",
         "command": command(*base, "workbench.onboarding", "save-token", "--file", token_file)},
        {"title": "Deliver captured metadata",
         "description": "Run this in a separate terminal on the collector host. A heartbeat proves delivery is running; it does not prove full capture.",
         "command": "\n".join([
             "export WORKBENCH_INGEST_URL=" + shlex.quote(settings.public_origin + "/api/pilot/ingest"),
             "export WORKBENCH_INGEST_TOKEN_FILE=" + shlex.quote(token_file),
             command(*base, "workbench.connector", "--outbox", outbox, "deliver", "--watch")])},
    ]
    if source["kind"] == "codex":
        capture = [{"title": "Import your saved Codex invocation",
            "description": "Replace the uppercase placeholders with the original file, capture ID, invocation start time and configured model label. Preserve these values for every replay of that invocation.",
            "command": command(*native, "codex", "--input", "YOUR_SAVED_CODEX_JSONL",
                "--capture-id", "ORIGINAL_CAPTURE_ID", "--started-at", "ORIGINAL_UTC_START_TIME",
                "--model", "YOUR_CONFIGURED_MODEL")}]
        limitation = "CLI turns only. The stream does not report a monetary amount or attest the response model. Use a declared subscription allocation when you have the monthly charge."
    elif source["kind"] == "cursor":
        capture = [{"title": "Import a complete Cursor reporting window",
            "description": "Use a complete Admin API JSON export and its original bounds. The start is inclusive and the end is exclusive. Keep windows closed and non-overlapping.",
            "command": command(*native, "cursor-import", "--input", "YOUR_COMPLETE_CURSOR_EXPORT",
                               "--start", "ORIGINAL_WINDOW_START", "--before", "ORIGINAL_EXCLUSIVE_END")}]
        limitation = "Team Admin API reporting data can arrive late. An individual-account CSV is outside this connector's supported input."
    elif source["kind"] == "claude_code":
        receiver = f".pilot/{identity}.otel.token"
        capture = [
            {"title": "Import existing Claude Code telemetry",
             "description": "Use a saved OTLP/HTTP JSON logs request from your existing telemetry setup.",
             "command": command(*native, "claude-import", "--input", "YOUR_CLAUDE_OTLP_JSON")},
            {"title": "Or prepare a local receiver",
             "description": "The receiver needs a separate private token. Choose a different port if 14318 is already in use.",
             "command": command(*base, "workbench.onboarding", "receiver-token", "--file", receiver) + "\n" +
                 command(*native, "claude-listen", "--port", "14318", "--token-file", receiver)},
            {"title": "Launch your normal Claude Code session with telemetry",
             "description": "Run this only when you choose to use Claude Code. Normal provider usage can apply. Existing managed vendor settings may take precedence.",
             "command": command(*base, "workbench.onboarding", "claude-env", "--token-file", receiver,
                                "--port", "14318", "--", "claude")},
        ]
        limitation = "The receiver accepts API metadata in OTLP HTTP/JSON logs. Pricing is the tool's reported estimate when supplied; subscription allocation stays separate."
    else:
        capture = []
        limitation = "Only instrumented calls are captured. Follow the source guide in your checkout; unsupported model prices remain unknown."
    return {"source": {"id": identity, "name": source["name"], "kind": source["kind"]},
            "project": project, "outbox": outbox, "token_file": token_file,
            "steps": [
                {"name": "Source created", "state": "ready", "detail": "This source belongs to your signed-in workspace."},
                {"name": "Active connection token", "state": "needed" if health["status"] == "token_required" else "ready",
                 "detail": "Issue or rotate a token, then save it privately on the collector host."},
                {"name": "Delivery process", "state": health["status"],
                 "detail": "Check the collector heartbeat and any queued events."},
                {"name": "Observed records received", "state": "received" if observed else "waiting",
                 "detail": f"{observed} observed records received. Synthetic examples do not complete this step."},
            ], "health": health, "observed_records": observed, "last_observed_received_at": latest,
            "commands": common[:1] + capture + common[1:], "limitation": limitation,
            "application_guide": f"docs/{'BEDROCK' if source['kind'] == 'bedrock' else 'PILOT'}.md"
                if source["kind"] in {"axonllm", "bedrock"} else None,
            "note": "Run commands from the Workbench checkout on the collector host. This report contains no connection token or vendor credentials."}


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as target:
        target.write(value)


def receiver_secret(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024:
            raise ValueError("Use an owner-only regular receiver token file")
        value = stream.read().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value):
        raise ValueError("Invalid receiver token")
    return value


def claude_environment(token_file, port, inherited=None):
    if not 1024 <= port <= 65535:
        raise ValueError("Unsupported receiver port")
    secret = receiver_secret(token_file)
    environment = dict(os.environ if inherited is None else inherited)
    environment.update({
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "none", "OTEL_TRACES_EXPORTER": "none",
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/json",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"http://127.0.0.1:{port}/v1/logs",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=Bearer " + secret,
        "OTEL_LOG_USER_PROMPTS": "0", "OTEL_LOG_ASSISTANT_RESPONSES": "0",
        "OTEL_LOG_TOOL_DETAILS": "0", "OTEL_LOG_TOOL_CONTENT": "0",
    })
    environment.pop("OTEL_LOG_RAW_API_BODIES", None)
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in ("save-token", "receiver-token"):
        mode = modes.add_parser(name)
        mode.add_argument("--file", required=True, type=Path)
    launch = modes.add_parser("claude-env", help="Start a command with private local Claude telemetry settings")
    launch.add_argument("--token-file", required=True, type=Path)
    launch.add_argument("--port", type=int, default=14318)
    launch.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.mode == "claude-env":
            if not 1024 <= args.port <= 65535:
                raise ValueError("Unsupported receiver port")
            command_args = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not command_args:
                raise ValueError("Supply the command you want to launch")
            result = subprocess.run(command_args, env=claude_environment(args.token_file, args.port), check=False)
            raise SystemExit(result.returncode)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Workbench connection token (input hidden): ").strip() \
                if args.mode == "save-token" else secrets.token_urlsafe(32)
        if args.mode == "save-token" and not re.fullmatch(r"wb_ing_[A-Za-z0-9_-]{43}", value):
            raise ValueError("Invalid Workbench token")
        private_write(args.file, value)
        print("Private token file created. Keep it with this source's outbox.")
    except (OSError, ValueError, EOFError, getpass.GetPassWarning):
        parser.exit(1, "Setup could not complete. Use an interactive terminal for token entry and check the private file, permissions, port and command; existing files are preserved.\n")


if __name__ == "__main__":
    main()
