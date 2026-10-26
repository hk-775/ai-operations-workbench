"""Configure the two isolated hosted tests from a private runtime bootstrap file.

Run as the unprivileged workbench host user. Never print the bootstrap contents.
The source tree must already be copied to /opt/workbench/demo and /opt/workbench/clean.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess


def private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        raise RuntimeError("Refusing to replace existing private configuration: "+str(path))
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        stream.write(text)


def configure(root, config):
    if os.getuid() == 0:
        raise RuntimeError("Run as the unprivileged workbench host user")
    for label, port in (("demo", 8770), ("clean", 8771)):
        app = root / label
        subprocess.run(["python3", "scripts/setup_pilot.py"], cwd=app, check=True)
        data = config[label]
        state = app / ".pilot"
        private(state/"oidc_client_secret", data["client_secret"])
        private(state/"metrics_token", secrets.token_urlsafe(48))
        private(state/"admin_password", secrets.token_urlsafe(48))
        values = {
            "WORKBENCH_DOMAIN": data["domain"],
            "WORKBENCH_PILOT_PORT": str(port),
            "WORKBENCH_OIDC_ISSUER": config["issuer"],
            "WORKBENCH_OIDC_CLIENT_ID": data["client_id"],
            "WORKBENCH_OIDC_REQUIRED_AMR": "",
            "WORKBENCH_OIDC_REQUIRED_ACR": "",
            "WORKBENCH_RETENTION_DAYS": "30",
            "WORKBENCH_EVIDENCE_RETENTION_DAYS": "365",
            "WORKBENCH_AUDIT_RETENTION_DAYS": "365",
            "WORKBENCH_HOSTED_PROJECT": "workbench-hosted-"+label,
        }
        if any(any(c in v for c in "\r\n'$") for v in values.values()):
            raise RuntimeError("Invalid bootstrap metadata")
        private(state/"production.env", (state/"compose.env").read_text()+"\n"+
                "\n".join(k+"='"+v+"'" for k, v in values.items())+"\n")
        # Identity subjects are opaque provider IDs, not email-based auto-linking.
        private(state/"identity.json", json.dumps({"subject": data["subject"], "username": "admin"}))

    origin = root/"origin"
    origin.mkdir(mode=0o700, exist_ok=True)
    caddy = """{
    admin off
    auto_https off
}
:80 {
    request_body {
        max_size 8MB
    }
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        X-Frame-Options DENY
    }
"""
    for label, port in (("demo", 8770), ("clean", 8771)):
        caddy += f"""    @{label} host {config[label]["domain"]}
    handle @{label} {{
        reverse_proxy 127.0.0.1:{port} {{
            header_up Host {config[label]["domain"]}
        }}
    }}
"""
    caddy += "    handle {\n        respond 404\n    }\n}\n"
    private(origin/"Caddyfile", caddy)
    private(origin/"compose.json", json.dumps({
        "name": "workbench-hosted-origin",
        "services": {"origin": {
            "image": "ai-operations-workbench-proxy:0.2.0",
            "network_mode": "host", "restart": "unless-stopped",
            "volumes": [str(origin/"Caddyfile")+":/etc/caddy/Caddyfile:ro"],
            "security_opt": ["no-new-privileges:true"], "mem_limit": "256m",
        }},
    }, indent=2))
    private(root/"operations.json", json.dumps({
        "deployment": config["deployment"], "region": config["region"],
        "bucket": config["bucket"],
        "origins": {label: "https://"+config[label]["domain"] for label in ("demo", "clean")},
    }, indent=2))
    print("Prepared isolated hosted test configuration; password-only SSO is explicit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/workbench"))
    parser.add_argument("--bootstrap", type=Path, required=True)
    args = parser.parse_args()
    configure(args.root, json.loads(args.bootstrap.read_text()))
