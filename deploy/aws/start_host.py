"""Build and initialize the explicitly selected hosted acceptance environment."""
import json
import subprocess
from pathlib import Path

ROOT = Path("/opt/workbench")


def compose(label, *arguments):
    subprocess.run([
        "docker", "compose", "--env-file", ".pilot/production.env",
        "-f", "compose.production.yaml", "-f", "compose.hosted-test.yaml", *arguments,
    ], cwd=ROOT/label, check=True)


def start():
    # One build serves both identical applications and both PostgreSQL containers.
    compose("demo", "build", "app", "db", "proxy")
    for label in ("demo", "clean"):
        compose(label, "up", "-d", "--wait", "db")
        marker = ROOT/label/".pilot"/"initialized"
        if not marker.exists():
            compose(label, "run", "--rm", "app", "python", "-m", "workbench.pilot", "migrate")
            compose(label, "run", "--rm", "app", "python", "-m", "workbench.pilot", "init",
                    "--team", "Workbench recorded demo" if label == "demo" else "Workbench clean test",
                    "--username", "admin", "--password-file", "/run/secrets/hosted_admin_password")
            identity = json.loads((ROOT/label/".pilot"/"identity.json").read_text())
            compose(label, "run", "--rm", "app", "python", "-m", "workbench.pilot", "link-identity",
                    "--username", "admin", "--subject", identity["subject"])
            marker.touch(mode=0o600)
        if label == "demo":
            compose(label, "run", "--rm", "app", "python", "-m", "workbench.pilot", "seed-demo")
        compose(label, "run", "--rm", "app", "python", "-m", "workbench.pilot", "check-production")
        compose(label, "up", "-d", "--wait", "app", "worker", "maintenance")
    subprocess.run(["docker", "compose", "-f", str(ROOT/"origin"/"compose.json"), "up", "-d"],
                   check=True)
    print("Hosted test services started; external acceptance is still required.")


if __name__ == "__main__":
    start()
