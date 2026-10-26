"""Operator commands. Credentials are read from a prompt or private file."""
import argparse
import getpass
import json
import stat
from pathlib import Path

from . import auth
from .config import Settings
from .database import Conflict, Database
from .worker import EvaluationWorker
from . import maintenance as upkeep


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
    commands.add_parser("operations")
    commands.add_parser("check-production")
    commands.add_parser("seed-demo")
    maintenance = commands.add_parser("maintenance")
    maintenance.add_argument("--watch", action="store_true")
    maintenance.add_argument("--dry-run", action="store_true")
    identity = commands.add_parser("link-identity")
    identity.add_argument("--username", required=True)
    identity.add_argument("--subject", required=True)
    for name in ("init", "reset-password"):
        command = commands.add_parser(name)
        command.add_argument("--username", required=True)
        command.add_argument("--password-file", type=Path)
        if name == "init":
            command.add_argument("--team", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_url)
    if settings.production and args.command not in {"migrate", "init"}:
        database.check_schema()
    else:
        database.migrate()
    try:
        if args.command == "worker":
            EvaluationWorker(database, settings).run()
        elif args.command == "maintenance":
            if args.watch and args.dry_run:
                raise ValueError("Choose a one-time dry run or scheduled maintenance")
            if args.watch:
                upkeep.run(database, settings)
            else:
                print(json.dumps(upkeep.run_once(database, settings, dry_run=args.dry_run)))
        elif args.command == "operations":
            from .operations import snapshot
            print(json.dumps(snapshot(database, settings), indent=2))
        elif args.command == "seed-demo":
            from .demo import seed
            print(json.dumps(seed(database, settings)))
        elif args.command == "check-production":
            if not settings.production:
                raise ValueError("WORKBENCH_PRODUCTION must be true")
            settings.validate_production_app()
            print("Production configuration and schema checks passed. Verify SSO, TLS, alerts, and restore on the target host before accepting traffic.")
        elif args.command == "link-identity":
            from sqlalchemy import insert, select
            from .database import identities, users
            if not settings.oidc_issuer or not 1 <= len(args.subject) <= 255:
                raise ValueError("Configure the OIDC issuer and provide its exact subject identifier")
            with database.engine.begin() as db:
                user = db.execute(select(users).where(users.c.username == auth.username(args.username),
                    users.c.active.is_(True)).with_for_update()).mappings().first()
                if not user:
                    raise ValueError("Active local account not found")
                if db.execute(select(identities.c.user_id).where(
                    (identities.c.user_id == user["id"]) |
                    ((identities.c.issuer == settings.oidc_issuer) & (identities.c.subject == args.subject)))).first():
                    raise Conflict("Account or company identity is already linked")
                db.execute(insert(identities).values(issuer=settings.oidc_issuer,
                    subject=args.subject, user_id=user["id"]))
                database.audit(db, user["team_id"], "operator-cli", "user.sso_linked", user["id"])
            print("Company identity linked. Workbench roles still apply.")
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
