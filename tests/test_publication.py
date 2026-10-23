"""Keep the downloadable source's documentation and asset links usable."""
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

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
