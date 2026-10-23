"""Opaque revocable sessions and least-privilege roles for one pilot team."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from .database import (Conflict, Database, hash_secret, login_failures,
                       sessions, teams, uid, users)

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
dummy_hash = hasher.hash(secrets.token_urlsafe(32))
COOKIE = "workbench_session"
ROLES = {"admin", "analyst", "viewer"}


def username(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,79}", value):
        raise ValueError("Username must be 3–80 letters, digits, dots, hyphens, or underscores")
    return value


def password_hash(password: str) -> str:
    if not 14 <= len(password) <= 128:
        raise ValueError("Use a password of 14–128 characters")
    return hasher.hash(password)


def csrf_token(session: str) -> str:
    return hmac.new(session.encode(), b"workbench-csrf-v1", hashlib.sha256).hexdigest()


def authenticate(database: Database, name: str, password: str, ip: str, settings):
    name, now = username(name), int(time.time())
    name_hash, ip_hash = hash_secret(name), hash_secret(ip)
    with database.engine.begin() as db:
        # The single team's login gate is serialized, including failed attempts.
        team = db.execute(select(teams).with_for_update()).mappings().first()
        if not team:
            return None
        db.execute(delete(login_failures).where(login_failures.c.created_at < now - 86400))
        query = select(func.count()).select_from(login_failures).where(
            login_failures.c.created_at >= now - 900)
        by_name = db.execute(query.where(login_failures.c.username_hash == name_hash)).scalar_one()
        by_ip = db.execute(query.where(login_failures.c.ip_hash == ip_hash)).scalar_one()
        if by_name >= 10 or by_ip >= 50:
            raise Conflict("Too many sign-in attempts; try again in 15 minutes")
        user = db.execute(select(users).where(users.c.username == name,
            users.c.team_id == team["id"])).mappings().first()
        encoded = user["password_hash"] if user else dummy_hash
        try:
            valid = hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or not user or not user["active"]:
            db.execute(insert(login_failures).values(id=uid(), username_hash=name_hash,
                ip_hash=ip_hash, created_at=now))
            return None
        if hasher.check_needs_rehash(encoded):
            db.execute(update(users).where(users.c.id == user["id"]).values(
                password_hash=hasher.hash(password)))
        db.execute(delete(login_failures).where(login_failures.c.username_hash == name_hash))
        db.execute(delete(sessions).where(or_(sessions.c.expires_at <= now,
                                              sessions.c.last_seen <= now - settings.idle_seconds)))
        token = secrets.token_urlsafe(32)
        db.execute(insert(sessions).values(id=hash_secret(token), user_id=user["id"],
            created_at=now, expires_at=now + settings.session_seconds, last_seen=now))
        database.audit(db, team["id"], name, "session.created", user["id"])
        return token


def principal(database: Database, token: str | None, settings):
    if not token or len(token) > 100:
        return None
    now = int(time.time())
    with database.engine.begin() as db:
        row = db.execute(select(users.c.id, users.c.team_id, users.c.username, users.c.role,
            teams.c.name.label("team_name"), sessions.c.last_seen).select_from(
                sessions.join(users).join(teams)).where(
            sessions.c.id == hash_secret(token), sessions.c.expires_at > now,
            sessions.c.last_seen > now - settings.idle_seconds, users.c.active.is_(True))).mappings().first()
        if not row:
            return None
        if row["last_seen"] < now - 60:
            db.execute(update(sessions).where(sessions.c.id == hash_secret(token)).values(last_seen=now))
        return {key: row[key] for key in ("id", "team_id", "username", "role", "team_name")}


def logout(database, token, actor):
    with database.engine.begin() as db:
        db.execute(delete(sessions).where(sessions.c.id == hash_secret(token)))
        database.audit(db, actor["team_id"], actor["username"], "session.revoked", actor["id"])


def create_user(database, actor, name, password, role):
    name, encoded = username(name), password_hash(password)
    if role not in ROLES:
        raise ValueError("Invalid team role")
    identity = uid()
    try:
        with database.engine.begin() as db:
            db.execute(insert(users).values(id=identity, team_id=actor["team_id"], username=name,
                password_hash=encoded, role=role, active=True, created_at=int(time.time())))
            database.audit(db, actor["team_id"], actor["username"], "user.created", identity)
    except IntegrityError as exc:
        raise Conflict("Username is already in use") from exc
    return {"id": identity, "username": name, "role": role}


def disable_user(database, actor, user_id):
    with database.engine.begin() as db:
        db.execute(select(teams.c.id).where(teams.c.id == actor["team_id"]).with_for_update()).first()
        user = db.execute(select(users).where(users.c.id == user_id,
            users.c.team_id == actor["team_id"])).mappings().first()
        if not user:
            raise KeyError("User not found")
        admins = db.execute(select(func.count()).select_from(users).where(
            users.c.team_id == actor["team_id"], users.c.role == "admin",
            users.c.active.is_(True))).scalar_one()
        if user["active"] and user["role"] == "admin" and admins <= 1:
            raise Conflict("The team must retain an active administrator")
        db.execute(update(users).where(users.c.id == user_id).values(active=False))
        db.execute(delete(sessions).where(sessions.c.user_id == user_id))
        database.audit(db, actor["team_id"], actor["username"], "user.disabled", user_id)


def reset_password(database, name, password):
    name, encoded = username(name), password_hash(password)
    with database.engine.begin() as db:
        user = db.execute(select(users).where(users.c.username == name)).mappings().first()
        if not user:
            raise KeyError("User not found")
        db.execute(update(users).where(users.c.id == user["id"]).values(password_hash=encoded))
        db.execute(delete(sessions).where(sessions.c.user_id == user["id"]))
        database.audit(db, user["team_id"], "operator-cli", "user.password_reset", user["id"])
