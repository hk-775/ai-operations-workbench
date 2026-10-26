"""Create two isolated local test deployments with private generated credentials."""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path


def initialize_sql(target):
    path = target / "init.sql"
    if path.exists():
        path.chmod(0o444)
        return
    password = (target / "application-password").read_text().strip()
    if not password or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in password):
        raise ValueError("Unexpected generated database password format")
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444),"w") as stream:
        stream.write(f"CREATE ROLE workbench LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;\n"
                     "CREATE DATABASE workbench OWNER workbench;\n")
    path.chmod(0o444)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-port",type=int,default=8770)
    parser.add_argument("--clean-port",type=int,default=8771)
    args = parser.parse_args()
    if args.demo_port == args.clean_port:
        parser.error("Each deployment needs a different port")
    root = Path(".pilot/instances")
    root.mkdir(parents=True,mode=0o700,exist_ok=True)
    root.chmod(0o700)
    for kind, port in (("demo",args.demo_port),("clean",args.clean_port)):
        target = root / kind
        target.mkdir(mode=0o700,exist_ok=True)
        config = target / "compose.env"
        if config.exists():
            for name in ("postgres-password","application-password"):
                (target/name).chmod(0o644)
            initialize_sql(target)
            print(f"{kind}: existing deployment configuration preserved")
            continue
        if not 1024 <= port <= 65535:
            parser.error("Choose unprivileged ports between 1024 and 65535")
        with socket.socket() as test:
            try:
                test.bind(("127.0.0.1",port))
            except OSError:
                parser.error(f"Port {port} is occupied; select another port")
        password = secrets.token_urlsafe(36)
        admin = secrets.token_urlsafe(32)
        for name,value,mode in (
            ("postgres-password",secrets.token_urlsafe(36),0o644),
            ("application-password",password,0o644),
            ("database-url",f"postgresql+psycopg://workbench:{password}@db:5432/workbench",0o600),
            ("admin-password",admin,0o600)):
            with os.fdopen(os.open(target/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode),"w") as file:
                file.write(value)
            (target/name).chmod(mode)
        with os.fdopen(os.open(config,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),"w") as file:
            file.write(f"WORKBENCH_INSTANCE={kind}\nWORKBENCH_INSTANCE_PORT={port}\n"
                       f"WORKBENCH_RUN_UID={os.getuid()}\nWORKBENCH_RUN_GID={os.getgid()}\n")
        initialize_sql(target)
        print(f"{kind}: ready to deploy on http://127.0.0.1:{port}/; administrator password stored privately")


if __name__ == "__main__":
    main()
