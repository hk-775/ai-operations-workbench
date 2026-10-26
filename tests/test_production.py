"""Production behaviors: exact pagination, OIDC threats, retention, and metrics."""
import copy
import json
import secrets
import time
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import delete, func, insert, select, update

from workbench.pilot import auth
from workbench.pilot.api import create_pilot_app
from workbench.pilot.database import Database, events, facts, identities, maintenance, oidc_states, schema, users
from workbench.pilot.identity import provision
from workbench.pilot.maintenance import run_once
from test_pilot import pilot, sample, settings


def source(pilot):
    return pilot.db.create_source(pilot.team, "Production test source", "admin")


def test_paginated_totals_time_windows_and_call_pages(pilot):
    identity = source(pilot)
    pilot.db.ingest(pilot.team, identity, [sample(event_id=f"event-{n}", task_id=f"task-{n}") for n in range(125)])
    first = pilot.client.get("/api/pilot/usage?page_size=50").json()
    second = pilot.client.get("/api/pilot/usage?page_size=50&page=1").json()
    last = pilot.client.get("/api/pilot/usage?page_size=50&page=2").json()
    assert first["api_estimate_usd"] == "0.312500000"
    assert first["events"] == second["events"] == 125
    assert len(first["tasks"]) == len(second["tasks"]) == 50
    assert len(last["tasks"]) == 25 and not last["has_more"]
    assert len({t["task_id"] for p in (first,second,last) for t in p["tasks"]}) == 125
    assert pilot.client.get("/api/pilot/usage?start=2026-10-24T00:00:00Z").json()["events"] == 0
    assert pilot.client.get("/api/pilot/usage?start=2026-10-22").status_code == 422
    assert pilot.client.get("/api/pilot/usage?page_size=10000").status_code == 422
    pilot.db.ingest(pilot.team, identity, [sample(event_id=f"long-{n}", task_id="long") for n in range(125)])
    task = pilot.client.get("/api/pilot/usage?task_id=long").json()["tasks"][0]
    assert len(task["calls"]) == 100 and task["call_count"] == 125 and task["calls_has_more"]
    calls = pilot.client.get("/api/pilot/calls",params={"source_id":identity,"task_id":"long","offset":100}).json()
    assert len(calls["calls"]) == 25 and not calls["has_more"]


def test_v1_migration_preserves_recorded_accounting(pilot):
    identity = source(pilot)
    pilot.db.ingest(pilot.team, identity, [sample(),sample(event_id="unknown",model="not-priced")])
    with pilot.db.engine.begin() as db:
        before = db.execute(select(events.c.accounting).order_by(events.c.event_id)).scalars().all()
        db.execute(delete(facts))
        db.execute(update(schema).values(version=1))
    pilot.db.migrate()
    pilot.db.migrate()
    with pilot.db.engine.connect() as db:
        assert db.execute(select(events.c.accounting).order_by(events.c.event_id)).scalars().all() == before
        assert db.execute(select(func.count()).select_from(facts)).scalar_one() == 2
    assert pilot.db.usage(pilot.team)["unknown_cost_calls"] == 1
    assert pilot.db.usage(pilot.team)["api_estimate_usd"] == "0.002500000"
    with pilot.db.engine.begin() as db:
        db.execute(update(schema).values(version=999))
    with pytest.raises(RuntimeError, match="Unsupported"):
        pilot.db.migrate()


def test_retention_preview_cutoff_retry_and_evidence_preservation(pilot):
    identity = source(pilot)
    pilot.db.ingest(pilot.team, identity, [sample(occurred_at="2020-01-01T00:00:00Z"),
                                         sample(event_id="recent", occurred_at=datetime.now(timezone.utc).isoformat())])
    pilot.client.post("/api/pilot/recordings/example",json={})
    config = replace(pilot.settings, retention_days=90)
    preview = run_once(pilot.db, config, dry_run=True)
    assert preview["eligible_events"] == 1 and preview["deleted_events"] == 0
    assert pilot.db.usage(pilot.team)["events"] == 146
    actual = run_once(pilot.db, config)
    assert actual["deleted_events"] == 1
    assert pilot.db.usage(pilot.team)["events"] == 145
    from workbench.pilot.database import Conflict
    with pytest.raises(Conflict,match="retention"):
        pilot.db.ingest(pilot.team, identity,[sample(occurred_at="2020-01-01T00:00:00Z")])
    assert run_once(pilot.db, config)["deleted_events"] == 0
    with pilot.db.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(facts)).scalar_one() == 145


def test_monitoring_is_protected_and_contains_no_request_secrets(pilot, caplog):
    config = replace(pilot.settings,metrics_token=secrets.token_urlsafe(32))
    app = create_pilot_app(config)
    marker = "do-not-log-this-user-input"
    with TestClient(app,base_url=config.public_origin) as client:
        assert client.get("/metrics").status_code == 401
        assert client.get("/api/pilot/operations").status_code == 401
        response = client.post("/api/auth/login",json={"username":marker,"password":marker})
        assert len(response.headers["x-request-id"]) == 32
        metrics = client.get("/metrics",headers={"Authorization":"Bearer "+config.metrics_token})
        assert metrics.status_code == 200 and "workbench_http_requests_total" in metrics.text
        assert marker not in metrics.text and config.metrics_token not in metrics.text
    assert marker not in caplog.text and config.metrics_token not in caplog.text
    health = pilot.client.get("/api/pilot/operations").json()
    assert health["status"] == "attention" and health["alerts"][0]["severity"] == "critical"


@pytest.fixture
def oidc(pilot):
    config = replace(pilot.settings, public_origin="https://workbench.example",
        oidc_issuer="https://identity.example", oidc_client_id="workbench-client",
        oidc_client_secret=secrets.token_urlsafe(32), oidc_required_amr=("mfa",), local_login=False)
    with pilot.db.engine.connect() as db:
        actor = dict(db.execute(select(users).where(users.c.username=="admin")).mappings().one())
    provision(pilot.db,actor,"employee","employee-subject","viewer",config.oidc_issuer)
    app = create_pilot_app(config)
    company = app.state.company_identity
    key = RSAKey.generate_key(2048, parameters={"kid":"test-signing-key"})
    state = {"changes":{},"nonce":None,"token_requests":0}

    def provider(request):
        path = request.url.path
        if path.endswith("openid-configuration"):
            return httpx.Response(200,json={"issuer":config.oidc_issuer,
                "authorization_endpoint":config.oidc_issuer+"/authorize",
                "token_endpoint":config.oidc_issuer+"/token","jwks_uri":config.oidc_issuer+"/keys",
                "id_token_signing_alg_values_supported":["RS256"]})
        if path == "/keys":
            return httpx.Response(200,json={"keys":[key.as_dict(private=False)]})
        assert path == "/token"
        values = parse_qs(request.content.decode())
        assert values["code_verifier"] and values["redirect_uri"] == [config.public_origin+"/api/auth/oidc/callback"]
        state["token_requests"] += 1
        claims = {"iss":config.oidc_issuer,"sub":"employee-subject","aud":config.oidc_client_id,
                  "iat":int(time.time()),"exp":int(time.time())+300,"nonce":state["nonce"],"amr":["mfa"]}
        claims.update(state["changes"])
        encoded = jwt.encode({"alg":"RS256","kid":"test-signing-key"},claims,key)
        return httpx.Response(200,json={"access_token":"opaque-test-access","token_type":"Bearer",
                                       "id_token":encoded})
    company.client.client_kwargs["transport"] = httpx.MockTransport(provider)
    with TestClient(app,base_url=config.public_origin,follow_redirects=False) as client:
        def start():
            response = client.get("/api/auth/oidc/start")
            assert response.status_code == 302
            params = parse_qs(urlsplit(response.headers["location"]).query)
            assert params["code_challenge_method"] == ["S256"] and params["code_challenge"]
            state["nonce"] = params["nonce"][0]
            return params["state"][0]
        yield client, app, state, start


def test_company_sso_mfa_session_roles_and_replayed_callback(oidc):
    client, app, state, start = oidc
    assert client.post("/api/auth/login",json={"username":"admin","password":"ignored"}).status_code == 403
    identity = start()
    response = client.get("/api/auth/oidc/callback",params={"state":identity,"code":"one-use-code"})
    assert response.headers["location"] == "/"
    assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    current = client.get("/api/auth/session").json()
    assert current["user"]["username"] == "employee" and current["user"]["role"] == "viewer"
    assert auth.principal(app.state.database,client.cookies.get(auth.COOKIE),
                          replace(app.state.settings,production=True))["username"] == "employee"
    assert client.get("/api/pilot/operations").status_code == 403
    assert client.get("/api/auth/oidc/callback",params={"state":identity,"code":"again"}).headers["location"] == "/?signin=failed"
    assert state["token_requests"] == 1


@pytest.mark.parametrize("changes", [
    {"nonce":"wrong"}, {"iss":"https://other.example"}, {"aud":"other-client"},
    {"exp":1}, {"amr":["pwd"]}, {"sub":"unprovisioned-subject"},
])
def test_oidc_rejects_invalid_claims_or_unprovisioned_identity(oidc,changes):
    client, app, state, start = oidc
    state["changes"] = changes
    identity = start()
    response = client.get("/api/auth/oidc/callback",params={"state":identity,"code":"rejected"})
    assert response.headers["location"] == "/?signin=failed"
    assert client.get("/api/auth/session").json()["user"] is None


def test_oidc_callback_must_return_to_originating_browser(oidc):
    client, app, state, start = oidc
    identity = start()
    with TestClient(app,base_url="https://workbench.example",follow_redirects=False) as outsider:
        response = outsider.get("/api/auth/oidc/callback",params={"state":identity,"code":"stolen-state"})
        assert response.headers["location"] == "/?signin=failed"
    assert state["token_requests"] == 0
    assert client.get("/api/auth/oidc/callback",params={"state":identity,"code":"legitimate"}).headers["location"] == "/"


def test_production_configuration_fails_closed(settings):
    config = replace(settings,production=True,public_origin="https://workbench.example")
    with pytest.raises(ValueError,match="OIDC"):
        config.validate_production_app()
    config = replace(config,oidc_issuer="https://identity.example",oidc_client_id="app",
                     oidc_client_secret=secrets.token_urlsafe(32),local_login=False)
    with pytest.raises(ValueError,match="MFA"):
        config.validate_production_app()
    config = replace(config,oidc_required_amr=("mfa",),metrics_token=secrets.token_urlsafe(32),
                     retention_days=90,evidence_retention_days=365,audit_retention_days=730)
    config.validate_production_app()


def test_hosted_single_factor_exception_keeps_other_production_requirements(settings):
    config = replace(settings, production=True, hosted_test=True,
                     public_origin="https://workbench.example",
                     oidc_issuer="https://identity.example", oidc_client_id="app",
                     oidc_client_secret=secrets.token_urlsafe(32), local_login=False,
                     metrics_token=secrets.token_urlsafe(32), retention_days=30,
                     evidence_retention_days=365, audit_retention_days=365)
    config.validate_production_app()
    for changes, message in [
        ({"hosted_test": False}, "MFA"),
        ({"local_login": True}, "OIDC"),
        ({"oidc_issuer": "", "oidc_client_secret": "", "oidc_client_id": ""}, "OIDC"),
        ({"metrics_token": ""}, "metrics"),
        ({"retention_days": 0}, "retention"),
        ({"evidence_retention_days": 0}, "retention"),
        ({"audit_retention_days": 0}, "retention"),
    ]:
        with pytest.raises(ValueError, match=message):
            replace(config, **changes).validate_production_app()


def test_existing_local_sessions_cannot_bypass_production_sso(pilot):
    raw = pilot.client.cookies.get(auth.COOKIE)
    config = replace(pilot.settings,production=True,public_origin="https://workbench.example")
    assert auth.principal(pilot.db,raw,config) is None


def test_cookie_namespaces_keep_parallel_local_deployments_signed_in(pilot):
    demo = create_pilot_app(replace(pilot.settings,cookie_namespace="demo"))
    clean = create_pilot_app(replace(pilot.settings,cookie_namespace="clean"))
    with TestClient(demo,base_url=pilot.settings.public_origin) as a, TestClient(clean,base_url=pilot.settings.public_origin) as b:
        body = {"username":"admin","password":pilot.password}
        signed_a = a.post("/api/auth/login",json=body).json()
        b.cookies.update(a.cookies)
        assert b.get("/api/auth/session").json()["user"] is None
        b.post("/api/auth/login",json=body)
        a.cookies.update(b.cookies)
        assert a.get("/api/auth/session").json()["user"]["username"] == "admin"
        a.post("/api/auth/logout",json={},headers={"X-Workbench-CSRF":signed_a["csrf"]})
        assert b.get("/api/auth/session").json()["user"]["username"] == "admin"


def test_seeded_demo_is_idempotent_and_refuses_company_data(pilot):
    from workbench.pilot.demo import seed
    result = seed(pilot.db,pilot.settings)
    assert result["recorded_calls"] == 144 and result["paid_calls_made"] == 0
    assert seed(pilot.db,pilot.settings) == result
    assert pilot.db.usage(pilot.team)["events"] == 144
    assert pilot.db.list_proposals(pilot.team)[0]["status"] == "no_eligible_model"
    with pilot.db.engine.begin() as db:
        db.execute(delete(maintenance).where(maintenance.c.id=="demo_seed"))
    from workbench.pilot.database import Conflict
    with pytest.raises(Conflict,match="empty"):
        seed(pilot.db,pilot.settings)


def test_evidence_retention_keeps_active_jobs_then_removes_expired_graph(pilot):
    from workbench.pilot.database import recordings, jobs, proposals
    imported = pilot.client.post("/api/pilot/recordings/example",json={}).json()
    queued = pilot.db.enqueue(pilot.team,imported["recording_id"],"admin")
    with pilot.db.engine.begin() as db:
        db.execute(update(recordings).values(created_at=1))
    config = replace(pilot.settings,evidence_retention_days=365,audit_retention_days=730)
    assert run_once(pilot.db,config)["deleted_recordings"] == 0
    pilot.db.cancel(pilot.team,queued["id"],"admin")
    assert run_once(pilot.db,config,dry_run=True)["eligible_recordings"] == 1
    assert run_once(pilot.db,config)["deleted_recordings"] == 1
    assert pilot.db.usage(pilot.team)["events"] == 0
    assert pilot.db.list_jobs(pilot.team) == []
    assert pilot.db.list_proposals(pilot.team) == []
