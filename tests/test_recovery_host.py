import importlib.util
import io
from pathlib import Path
import tarfile

import pytest


spec = importlib.util.spec_from_file_location(
    "recovery_host", Path(__file__).resolve().parents[1]/"deploy/aws/recovery_host.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def archive(path, entries):
    with tarfile.open(path, "w:gz") as output:
        for name, kind in entries:
            member = tarfile.TarInfo(name)
            if kind == "link":
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                output.addfile(member)
            else:
                data = b"safe test content"
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))


@pytest.mark.parametrize("entries", [
    [("../escaped", "file")], [("/absolute", "file")],
    [("link", "link")], [("duplicate", "file"), ("duplicate", "file")],
])
def test_restore_rejects_unsafe_archive_before_writing(tmp_path, entries):
    source = tmp_path/"inputs.tar.gz"
    archive(source, entries)
    target = tmp_path/"restore"
    with pytest.raises(ValueError):
        recovery.extract(source, target)
    assert not target.exists()


def test_verified_source_extraction_preserves_existing_files(tmp_path):
    source = tmp_path/"source.tar.gz"
    archive(source, [("release/config/settings.json", "file")])
    target = tmp_path/"restore"
    recovery.extract(source, target, strip_root=True)
    installed = target/"config/settings.json"
    assert installed.read_bytes() == b"safe test content"
    installed.write_text("preserve this installation")
    with pytest.raises(ValueError, match="overwrites"):
        recovery.extract(source, target, strip_root=True)
    assert installed.read_text() == "preserve this installation"
