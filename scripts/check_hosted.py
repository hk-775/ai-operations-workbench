"""Verify the anonymous HTTPS boundary without logging cookies or OIDC state."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx


def check(origin, *, transport=None):
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Supply an HTTPS origin without path, query, or fragment")
    origin = origin.rstrip("/")
    checks = {}
    with httpx.Client(base_url=origin, timeout=25, follow_redirects=False,
                      transport=transport) as client:
        for path, expected in (("/", 200), ("/health/live", 200), ("/health/ready", 200),
                               ("/metrics", 401), ("/api/pilot/usage", 401),
                               ("/api/pilot/operations", 401)):
            response = client.get(path)
            checks[path] = response.status_code == expected
            if path == "/":
                checks["hsts"] = "max-age=" in response.headers.get("strict-transport-security", "")
            if path == "/health/ready":
                checks["ready_payload"] = response.status_code == 200 and response.json().get("status") == "ready"
        response = client.get("/api/auth/session")
        session = response.json() if response.status_code == 200 else {}
        checks["anonymous_session"] = session.get("user", False) is None
        checks["sso_only"] = session.get("login_methods") == {"local": False, "company": True}
        checks["explicit_test_profile"] = session.get("deployment") == "hosted_test"
        checks["session_uncached"] = "Hit" not in response.headers.get("x-cache", "")
        response = client.post("/api/auth/login", headers={"Origin": origin},
                               json={"username": "boundary-check", "password": "deliberately-invalid"})
        checks["local_login_disabled"] = response.status_code == 403
        response = client.get("/api/auth/oidc/start")
        location = urlsplit(response.headers.get("location", ""))
        query = parse_qs(location.query)
        checks["oidc_redirect_https"] = response.status_code == 302 and location.scheme == "https"
        checks["oidc_code_pkce"] = (query.get("response_type") == ["code"]
            and query.get("code_challenge_method") == ["S256"]
            and len(query.get("code_challenge", [""])[0]) == 43)
        checks["exact_callback"] = query.get("redirect_uri") == [origin+"/api/auth/oidc/callback"]
        cookie = response.headers.get("set-cookie", "").lower()
        checks["protected_oidc_cookie"] = all(x in cookie for x in ("secure", "httponly", "samesite=lax"))
    return {"origin": origin, "checked_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(checks.values()), "checks": checks,
            "scope": "Anonymous HTTPS boundary only. Actual SSO and backup/alert proofs are separate."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check(args.origin)
    text = json.dumps(report, indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text)
    raise SystemExit(0 if report["passed"] else 1)
