"""Company OIDC: authorization code + PKCE, browser-bound state, explicit accounts."""
from __future__ import annotations

import hmac
import json
import secrets
import time
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from sqlalchemy import delete, insert, select

from . import auth
from .database import Conflict, hash_secret, identities, oidc_states, sessions, sso_sessions, teams, uid, users

BINDING_COOKIE = "workbench_oidc"
CALLBACK = "/api/auth/oidc/callback"


def provision(database, actor, name, subject, role, issuer):
    name = auth.username(name)
    if role not in auth.ROLES or not issuer or not 1 <= len(subject) <= 255:
        raise ValueError("Valid issuer, subject, username and role required")
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == actor["team_id"]).with_for_update()).first()
        if db.execute(select(users.c.id).where(users.c.username == name)).first() or db.execute(
                select(identities.c.user_id).where(identities.c.issuer == issuer,
                                                   identities.c.subject == subject)).first():
            raise Conflict("Username or company identity already exists")
        identity = uid()
        db.execute(insert(users).values(id=identity, team_id=actor["team_id"], username=name,
            password_hash=auth.password_hash(secrets.token_urlsafe(48)), role=role,
            active=True, created_at=int(time.time())))
        db.execute(insert(identities).values(issuer=issuer, subject=subject, user_id=identity))
        database.audit(db, actor["team_id"], actor["username"], "user.sso_provisioned", identity)
    return {"id": identity, "username": name, "role": role}


class CompanyIdentity:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        self.client = OAuth().register("company", client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": "openid", "code_challenge_method": "S256",
                           "timeout": 10, "trust_env": False})

    async def metadata(self):
        metadata = await self.client.load_server_metadata()
        if metadata.get("issuer") != self.settings.oidc_issuer:
            raise ValueError("Identity provider issuer mismatch")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            url = urlsplit(metadata.get(key, ""))
            if url.scheme != "https" or not url.hostname or url.username or url.fragment:
                raise ValueError("Identity provider requires HTTPS endpoints")
        # Never trust a provider document to enable unsigned or symmetric ID tokens.
        metadata["id_token_signing_alg_values_supported"] = ["RS256", "ES256"]
        return metadata

    async def begin(self):
        await self.metadata()
        data = await self.client.create_authorization_url(
            self.settings.public_origin + CALLBACK,
            **({"acr_values": self.settings.oidc_required_acr} if self.settings.oidc_required_acr else {}))
        binding = secrets.token_urlsafe(32)
        data["binding_hash"] = hash_secret(binding)
        with self.database.engine.begin() as db:
            db.execute(select(teams.c.id).with_for_update()).first()
            db.execute(delete(oidc_states).where(oidc_states.c.expires_at <= int(time.time())))
            # Bound abandoned login attempts; they must not exhaust durable storage.
            from sqlalchemy import func
            if db.execute(select(func.count()).select_from(oidc_states)).scalar_one() >= 1000:
                raise Conflict("Company sign-in is busy; try again shortly")
            db.execute(insert(oidc_states).values(id=hash_secret(data["state"]),
                payload=json.dumps(data), expires_at=int(time.time()) + 600))
        return data["url"], binding

    def consume(self, state, binding):
        if not state or not binding or len(state) > 200 or len(binding) > 100:
            raise ValueError("Invalid sign-in state")
        with self.database.engine.begin() as db:
            row = db.execute(select(oidc_states).where(oidc_states.c.id == hash_secret(state),
                oidc_states.c.expires_at > int(time.time())).with_for_update()).mappings().first()
            if not row:
                raise ValueError("Sign-in expired or was already used")
            data = json.loads(row["payload"])
            if not hmac.compare_digest(data["binding_hash"], hash_secret(binding)):
                raise ValueError("Sign-in belongs to another browser")
            db.execute(delete(oidc_states).where(oidc_states.c.id == row["id"]))
            return data

    async def complete(self, state, binding, code):
        data = self.consume(state, binding)
        if not code or len(code) > 8192:
            raise ValueError("Invalid authorization code")
        await self.metadata()
        token = await self.client.fetch_access_token(code=code,
            code_verifier=data["code_verifier"], redirect_uri=self.settings.public_origin + CALLBACK)
        claims = await self.client.parse_id_token(token, nonce=data["nonce"],
            claims_options={"iss": {"essential": True, "value": self.settings.oidc_issuer}},
            leeway=30)
        if not claims or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255:
            raise ValueError("A verified company identity is required")
        amr = claims.get("amr", [])
        if not isinstance(amr, list) or any(value not in amr for value in self.settings.oidc_required_amr):
            raise ValueError("Company sign-in did not satisfy the required MFA methods")
        if self.settings.oidc_required_acr and claims.get("acr") != self.settings.oidc_required_acr:
            raise ValueError("Company sign-in did not satisfy the required assurance level")
        with self.database.engine.begin() as db:
            user = db.execute(select(users).join(identities).where(
                identities.c.issuer == self.settings.oidc_issuer,
                identities.c.subject == claims["sub"], users.c.active.is_(True))
                .with_for_update()).mappings().first()
            if not user:
                raise PermissionError("Your administrator must provision your company identity")
            raw, now = secrets.token_urlsafe(32), int(time.time())
            db.execute(insert(sessions).values(id=hash_secret(raw), user_id=user["id"],
                created_at=now, expires_at=now + self.settings.session_seconds, last_seen=now))
            db.execute(insert(sso_sessions).values(session_id=hash_secret(raw)))
            self.database.audit(db, user["team_id"], user["username"], "session.sso_created", user["id"])
        return raw
