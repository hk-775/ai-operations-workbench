"""Setup reports separate token/heartbeat/capture evidence and keep secrets local."""
import json
import os
import secrets
import shlex
import stat

import pytest
from sqlalchemy import insert

from test_pilot import pilot, sample, settings
from workbench.onboarding import claude_environment, private_write, receiver_secret
from workbench.pilot.database import teams, uid
from workbench.pilot.events import CollectorHealth


def test_setup_status_never_treats_heartbeat_or_fixture_as_observed_capture(pilot):
    source = pilot.db.create_source(pilot.team, "Application", "admin")
    endpoint = f"/api/pilot/sources/{source}/setup"
    report = pilot.client.get(endpoint).json()
    assert report["steps"][1]["state"] == "needed" and report["observed_records"] == 0
    token = pilot.db.issue_token(pilot.team, source, "admin")
    # Issue-token returns a structured response; no value appears in the setup report.
    raw = token["token"]
    report = pilot.client.get(endpoint).json()
    assert raw not in json.dumps(report) and report["steps"][1]["state"] == "ready"
    pilot.db.report_collector(raw, CollectorHealth(collector_id="a" * 32,
        pending_events=0, inflight_calls=0, retrying_events=0, oldest_pending_at=None))
    report = pilot.client.get(endpoint).json()
    assert report["health"]["status"] == "connected" and report["observed_records"] == 0
    pilot.db.ingest(pilot.team, source, [sample(evidence="fixture")])
    assert pilot.client.get(endpoint).json()["observed_records"] == 0
    pilot.db.ingest(pilot.team, source, [sample(event_id="observed")])
    report = pilot.client.get(endpoint).json()
    assert report["observed_records"] == 1 and report["steps"][-1]["state"] == "received"
    assert report["health"]["status"] == "connected"
    assert raw not in pilot.client.get(endpoint + "/export").text


def test_setup_commands_quote_untrusted_project_names_and_preserve_team_scope(pilot):
    source = pilot.db.create_source(pilot.team, "Coding", "admin", kind="codex")
    project = "team'; $(touch /tmp/should-not-run)"
    report = pilot.client.get(f"/api/pilot/sources/{source}/setup", params={"project": project}).json()
    capture = next(row["command"] for row in report["commands"] if "workbench.coding_tools" in row["command"])
    args = shlex.split(capture)
    assert args[args.index("--project") + 1] == project
    assert report["token_file"].startswith(".pilot/") and "wb_ing_" not in json.dumps(report)
    other = uid()
    with pilot.db.engine.begin() as db:
        db.execute(insert(teams).values(id=other, name="Other"))
    foreign = pilot.db.create_source(other, "Foreign", "operator")
    assert pilot.client.get(f"/api/pilot/sources/{foreign}/setup").status_code == 404
    assert pilot.client.get(f"/api/pilot/sources/{foreign}/setup/export").status_code == 404


def test_private_token_helpers_refuse_overwrite_links_and_public_permissions(tmp_path):
    path = tmp_path / "private" / "receiver.token"
    secret = secrets.token_urlsafe(32)
    private_write(path, secret)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert receiver_secret(path) == secret
    with pytest.raises(FileExistsError):
        private_write(path, "replacement")
    linked = path.parent / "link"
    linked.symlink_to(path)
    with pytest.raises(OSError):
        receiver_secret(linked)
    environment = claude_environment(path, 14318, {"OTEL_LOG_RAW_API_BODIES": "1", "EXISTING_SETTING": "preserved"})
    assert environment["EXISTING_SETTING"] == "preserved"
    assert environment["OTEL_EXPORTER_OTLP_LOGS_HEADERS"] == "Authorization=Bearer " + secret
    assert environment["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] == "http://127.0.0.1:14318/v1/logs"
    assert "OTEL_LOG_RAW_API_BODIES" not in environment
    assert environment["OTEL_LOG_USER_PROMPTS"] == environment["OTEL_LOG_ASSISTANT_RESPONSES"] == "0"
    path.chmod(0o644)
    with pytest.raises(ValueError):
        receiver_secret(path)


def test_token_prompt_refuses_fallback_that_could_echo_a_secret(tmp_path, monkeypatch, capsys):
    import getpass
    import sys
    import warnings
    from workbench.onboarding import main
    path = tmp_path / "connection.token"
    monkeypatch.setattr(sys, "argv", ["onboarding", "save-token", "--file", str(path)])
    def unsafe_prompt(*_):
        warnings.warn("Echo cannot be disabled", getpass.GetPassWarning)
        pytest.fail("Token entry continued after hidden input became unavailable")
    monkeypatch.setattr(getpass, "getpass", unsafe_prompt)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1 and not path.exists()
    assert "interactive terminal" in capsys.readouterr().err
