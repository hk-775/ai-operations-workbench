"""Package an allowlisted, company-neutral source release with a SHA-256 checksum."""
import hashlib
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("README.md","LICENSE","SECURITY.md","SUPPORT.md","CONTRIBUTING.md","CODE_OF_CONDUCT.md",
         "AGENTS.md","pyproject.toml","uv.lock","package.json","package-lock.json",
         "playwright.config.js","playwright.pilot.config.js","playwright.pages.config.js",
         "Dockerfile",".dockerignore",".gitignore",
         "compose.pilot.yaml","compose.production.yaml","compose.instances.yaml","compose.hosted-test.yaml")
DIRECTORIES = ("workbench","scripts","config","web","docs","tests",".github")
DATA_FILES = ("data/cases.json", "data/model-comparison.json",
              "data/coding/cases.json", "data/coding/calibration.json", "data/coding/example-recording.json", "data/coding/example-result.json",
              "data/billing-sample/README.md", "data/billing-sample/legacy-cur.csv",
              "data/billing-sample/cur-2.0.csv", "data/billing-sample/matching-usage.json",
              "data/billing-sample/expected-totals.json", "data/billing-sample/sample-check.json")


def main():
    version = tomllib.loads((ROOT/"pyproject.toml").read_text())["project"]["version"]
    name = f"ai-operations-workbench-{version}"
    output = ROOT / "artifacts/releases"
    output.mkdir(parents=True,exist_ok=True)
    paths = [ROOT/path for path in FILES]
    for directory in (*DIRECTORIES,"deploy"):
        paths.extend(p for p in (ROOT/directory).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and not p.name.endswith((".pyc",".DS_Store")))
    paths.extend(ROOT/path for path in DATA_FILES)
    archive = output / f"{name}.tar.gz"
    with tarfile.open(archive,"w:gz") as bundle:
        for path in sorted(set(paths)):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Release input must be a regular file: {path.name}")
            relative = path.relative_to(ROOT)
            if any(part in {".pilot",".state",".venv","node_modules"} for part in relative.parts):
                raise ValueError("Private runtime state must never enter a release")
            metadata = bundle.gettarinfo(str(path),arcname=str(Path(name)/relative))
            metadata.uid = metadata.gid = 0
            metadata.uname = metadata.gname = ""
            with path.open("rb") as source:
                bundle.addfile(metadata,source)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/"SHA256SUMS").write_text(f"{checksum}  {archive.name}\n")
    print(f"Prepared {archive.name} with {len(paths)} source files and SHA256SUMS; no company state included.")


if __name__ == "__main__":
    main()
