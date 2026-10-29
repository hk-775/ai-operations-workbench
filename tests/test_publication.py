"""Keep the downloadable source's documentation and asset links usable."""
import re
import importlib.util
import tarfile
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_local_links_and_editable_architecture():
    documents = [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md")]
    for document in documents:
        for link in re.findall(r"!?\[[^\]]*\]\(([^)\s]+)\)", document.read_text()):
            parsed = urlsplit(link)
            if parsed.scheme or not parsed.path:
                continue
            target = (document.parent / unquote(parsed.path)).resolve()
            assert target.is_relative_to(ROOT), (document.name, link)
            assert target.is_file(), (document.name, link)
    diagram = ElementTree.parse(ROOT / "docs/architecture/workbench.drawio")
    assert diagram.getroot().tag == "mxfile"
    assert len(diagram.findall(".//mxCell[@vertex='1']")) >= 6
    hosted = ElementTree.parse(ROOT / "docs/architecture/aws-hosted-test.drawio")
    assert hosted.getroot().tag == "mxfile"
    assert (ROOT / "docs/architecture/aws-hosted-test.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    acceptance = ElementTree.parse(ROOT / "docs/architecture/aws-acceptance.drawio")
    assert len(acceptance.findall(".//mxCell[@vertex='1']")) == 9
    assert (ROOT / "docs/architecture/aws-acceptance.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_downloaded_source_includes_hosted_deployment_and_excludes_private_state(tmp_path):
    spec = importlib.util.spec_from_file_location("package_release", ROOT / "scripts/package_release.py")
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    # Build from a deliberately contaminated miniature checkout. Packaging must
    # use its explicit inputs, not sweep runtime secrets into the download.
    for name in package.FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    for name in (*package.DATA_FILES,
                 "deploy/aws/configure_host.py", "deploy/aws/hosted-test.json",
                 "deploy/aws/hosted.guard", "docs/architecture/aws-hosted-test.drawio",
                 "docs/architecture/aws-hosted-test.png", "web/architecture.html",
                 "deploy/aws/billing-export.json", "deploy/aws/recovery-drill.json",
                 "deploy/aws/recovery_host.py", "docs/architecture/aws-acceptance.drawio",
                 "docs/architecture/aws-acceptance.png",
                 "web/architecture.css", "web/architecture.js"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    for name in (".pilot/hosted/logins.json", "deploy/.pilot/bootstrap.json",
                 ".state/private.db", ".env", "docs/__pycache__/private.pyc"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_TEST_SENTINEL")
    package.ROOT = tmp_path
    with pytest.raises(ValueError, match="Private runtime state"):
        package.main()
    (tmp_path / "deploy/.pilot/bootstrap.json").unlink()
    package.main()
    archive = next((tmp_path / "artifacts/releases").glob("*.tar.gz"))
    with tarfile.open(archive) as bundle:
        paths = {Path(item.name).relative_to(Path(item.name).parts[0]).as_posix()
                 for item in bundle.getmembers()}
        assert "compose.hosted-test.yaml" in paths
        assert "deploy/aws/configure_host.py" in paths
        assert "docs/architecture/aws-hosted-test.drawio" in paths
        assert "docs/architecture/aws-hosted-test.png" in paths
        assert {"deploy/aws/billing-export.json", "deploy/aws/recovery-drill.json",
                "deploy/aws/recovery_host.py", "docs/architecture/aws-acceptance.drawio",
                "docs/architecture/aws-acceptance.png"} <= paths
        assert {"web/architecture.html", "web/architecture.css", "web/architecture.js"} <= paths
        assert set(package.DATA_FILES) <= paths
        assert not any({".pilot", ".state", "__pycache__"} & set(Path(path).parts)
                       or path == ".env" for path in paths)


def test_public_build_excludes_application_and_private_files_and_verifies_media(tmp_path):
    spec = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts/build_pages.py")
    pages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pages)
    for directory in ("web", "docs/demo", "docs/architecture"):
        shutil.copytree(ROOT/directory, tmp_path/directory)
    for name in ("LICENSE", "pyproject.toml"):
        shutil.copyfile(ROOT/name, tmp_path/name)
    for name in ("web/media/private.json", "web/.env", "web/.pilot/logins.json",
                 "web/media/narration/private.mp3"):
        target = tmp_path/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_TEST_SENTINEL")
    pages.ROOT = tmp_path
    pages.main()
    output = tmp_path/"artifacts/pages/ai-operations-workbench"
    paths = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    assert {"index.html", "demo.html", "architecture.html", "media/workbench-demo.mp4",
            "architecture/aws-hosted-test.drawio", "architecture/aws-hosted-test.png",
            "architecture/aws-acceptance.drawio", "architecture/aws-acceptance.png"} <= paths
    assert not {"pilot.html", "pilot.js", "app.js", "media/private.json", ".env",
                ".pilot/logins.json", "media/narration/private.mp3"} & paths
    assert not any(b"PRIVATE_TEST_SENTINEL" in p.read_bytes() for p in output.rglob("*") if p.is_file())
    assert "connect-src &#x27;none&#x27;" in (output/"index.html").read_text()
    assert (tmp_path/"web/demo.html").read_bytes() == (ROOT/"web/demo.html").read_bytes()
    # A damaged or replaced media file must not silently become the public demo.
    (tmp_path/"web/media/workbench-demo.mp3").write_bytes(b"damaged media")
    with pytest.raises(ValueError, match="checksum mismatch"):
        pages.main()
