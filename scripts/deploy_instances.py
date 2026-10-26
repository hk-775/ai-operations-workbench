"""Build and run isolated seeded/clean local deployments, preserving existing data."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-port",type=int,default=8770)
    parser.add_argument("--clean-port",type=int,default=8771)
    args = parser.parse_args()
    subprocess.run([sys.executable,"scripts/setup_instances.py","--demo-port",str(args.demo_port),
                    "--clean-port",str(args.clean_port)],check=True)
    deployments = []
    for kind in ("demo","clean"):
        path = Path(".pilot/instances") / kind
        values = dict(line.split("=",1) for line in (path/"compose.env").read_text().splitlines() if "=" in line)
        port = values["WORKBENCH_INSTANCE_PORT"]
        compose = ["docker","compose","--env-file",str(path/"compose.env"),"-f","compose.instances.yaml"]
        if kind == "demo":
            subprocess.run(compose+["build","app","db"],check=True)
        subprocess.run(compose+["up","--no-build","--wait"],check=True)
        url = f"http://127.0.0.1:{port}"
        with urlopen(url+"/api/auth/session",timeout=10) as response:
            initialized = json.load(response)["initialized"]
        if not initialized:
            subprocess.run(compose+["exec","-T","app","python","-m","workbench.pilot","init",
                "--team","Workbench recorded demo" if kind=="demo" else "My AI team",
                "--username","admin","--password-file","/run/secrets/admin_password"],check=True)
        if kind == "demo":
            subprocess.run(compose+["exec","-T","app","python","-m","workbench.pilot","seed-demo"],check=True)
        deployments.append({"instance":kind,"url":url+"/","username":"admin",
                            "password_file":str(path/"admin-password")})
    (Path(".pilot/instances")/"deployments.json").write_text(json.dumps(deployments,indent=2)+"\n")
    print(json.dumps({"deployments":deployments,"credentials":"stored only in private files"}))


if __name__ == "__main__":
    main()
