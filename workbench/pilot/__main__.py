"""Operator commands. Credentials are read from a prompt or private file."""
import argparse
import getpass
import stat
from pathlib import Path

from . import auth
from .config import Settings
from .database import Conflict, Database
from .worker import EvaluationWorker


def read_password(path):
    if path:
        if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("Password file must be private (chmod 600)")
        return path.read_text().rstrip("\r\n")
    first = getpass.getpass("Password (14–128 characters): ")
    if first != getpass.getpass("Confirm password: "):
        raise ValueError("Passwords do not match")
    return first


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser("worker")
    for name in ("init", "reset-password"):
        command = commands.add_parser(name)
        command.add_argument("--username", required=True)
        command.add_argument("--password-file", type=Path)
        if name == "init":
            command.add_argument("--team", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_url)
    database.migrate()
    try:
        if args.command == "worker":
            EvaluationWorker(database, settings).run()
        elif args.command == "init":
            if not 1 <= len(args.team.strip()) <= 100:
                raise ValueError("Team name must be 1–100 characters")
            database.initialize(args.team.strip(), auth.username(args.username),
                                auth.password_hash(read_password(args.password_file)))
            print("Team initialized. Sign in using the administrator credentials you chose.")
        elif args.command == "reset-password":
            auth.reset_password(database, args.username, read_password(args.password_file))
            print("Password reset; existing sessions revoked.")
        else:
            print("Database schema is current.")
    except (Conflict, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
