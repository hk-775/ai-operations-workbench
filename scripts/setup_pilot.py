"""Generate local-only database secrets; existing credentials are preserved."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if os.getuid() == 0:
    raise SystemExit("Run pilot setup as an unprivileged host user, not root.")
directory = root / ".pilot"
directory.mkdir(mode=0o700, exist_ok=True)
directory.chmod(0o700)
password_path = directory / "postgres_password"
if password_path.exists():
    password = password_path.read_text().strip()
else:
    password = secrets.token_urlsafe(40)
    descriptor = os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(password)
url_path = directory / "database_url"
if not url_path.exists():
    descriptor = os.open(url_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(f"postgresql+psycopg://workbench:{password}@db:5432/workbench")
admin_path = directory / "postgres_admin_password"
if not admin_path.exists():
    descriptor = os.open(admin_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(secrets.token_urlsafe(40))
init_path = directory / "init.sql"
if not init_path.exists():
    # Generated URL-safe secrets contain no SQL delimiters. This is only read on
    # first initialization of the dedicated database volume.
    if not all(c.isalnum() or c in "-_" for c in password):
        raise SystemExit("Unexpected database password format; preserve existing credentials and inspect setup.")
    init_path.write_text(
        f"CREATE ROLE workbench LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;\n"
        "CREATE DATABASE workbench OWNER workbench;\n")
# The directory is mode 700. Only these individual files are mounted into the
# database container, whose postgres user must read them after dropping root.
init_path.chmod(0o444)
admin_path.chmod(0o444)
# Compose bind-mount secrets keep host ownership. Run app/worker as this host UID
# so mode-600 secrets remain readable without exposing them to other host users.
environment = directory / "compose.env"
if not environment.exists():
    environment.write_text(f"WORKBENCH_RUN_UID={os.getuid()}\nWORKBENCH_RUN_GID={os.getgid()}\n")
environment.chmod(0o600)
password_path.chmod(0o600)
url_path.chmod(0o600)
print("Pilot database credentials ready in .pilot/ (private directory, gitignored).")
print("Start: docker compose --env-file .pilot/compose.env -f compose.pilot.yaml up --build -d")
print("Then initialize the administrator with the interactive init command in docs/PILOT.md.")
