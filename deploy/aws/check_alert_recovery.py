"""Bounded worker outage for the hosted TEST only; always attempts worker recovery."""
import argparse
import json
from pathlib import Path
import signal
import time
import urllib.error
import urllib.request

from host_operations import compose


def response(origin, path):
    try:
        with urllib.request.urlopen(origin+path, timeout=5) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as error:
        return error.code, {}


def run(root, duration):
    config = json.loads((root/"operations.json").read_text())
    origin = config["origins"]["demo"]
    status, session = response(origin, "/api/auth/session")
    if status != 200 or session.get("deployment") != "hosted_test":
        raise RuntimeError("Outage checks require the explicit hosted test profile")
    if response(origin, "/health/ready")[0] != 200:
        raise RuntimeError("Begin with a healthy test deployment")
    directory = root/"acceptance"
    directory.mkdir(mode=0o700, exist_ok=True)
    resume = directory/"resume-worker"
    resume.unlink(missing_ok=True)
    report = {"instance": "demo", "started_at": time.time(),
              "unready_observed": False, "recovered": False}

    def save():
        path = directory/"outage.json"
        path.write_text(json.dumps(report, indent=2))
        path.chmod(0o600)

    def interrupted(*_):
        raise SystemExit("Interrupted; restarting the test worker")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        compose(root, "demo", "stop", "worker")
        report["stopped_at"] = time.time()
        save()
        deadline = time.monotonic()+duration
        while time.monotonic() < deadline:
            code, _ = response(origin, "/health/ready")
            if code == 503 and not report["unready_observed"]:
                report["unready_observed"] = True
                report["unready_at"] = time.time()
                save()
            if resume.exists():
                break
            time.sleep(2)
    finally:
        compose(root, "demo", "start", "worker")
        report["restarted_at"] = time.time()
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            try:
                if response(origin, "/health/ready")[0] == 200:
                    report["recovered"] = True
                    report["recovered_at"] = time.time()
                    break
            except Exception:
                pass
            time.sleep(2)
        save()
    print(json.dumps(report))
    if not report["unready_observed"] or not report["recovered"]:
        raise RuntimeError("Worker outage/recovery acceptance failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/workbench"))
    parser.add_argument("--duration-seconds", type=int, default=360)
    args = parser.parse_args()
    if not 120 <= args.duration_seconds <= 420:
        parser.error("Choose a bounded outage of 120–420 seconds")
    run(args.root, args.duration_seconds)
