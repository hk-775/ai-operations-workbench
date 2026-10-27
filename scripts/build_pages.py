"""Build the canonical, API-free demo and architecture for GitHub Pages."""
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://hk-775.github.io/ai-operations-workbench/"
WEB_FILES = (
    "demo.html", "demo.css", "demo.js", "demo-manifest.js",
    "architecture.html", "architecture.css", "architecture.js", "architecture-narration.js",
)
DIAGRAMS = (
    "workbench.drawio", "workbench.svg", "workbench.png",
    "aws-hosted-test.drawio", "aws-hosted-test.png",
)
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "media-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'"
)


def copy_file(relative, output, destination=None, digest=None):
    source = ROOT / relative
    if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError(f"Public asset must be an in-project regular file: {relative}")
    data = source.read_bytes()
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"Public media checksum mismatch: {relative}")
    target = output / (destination or Path(relative).relative_to("web"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def public_html(html, canonical):
    # Keep the real frontend. Add publication metadata and a browser-enforced
    # network boundary only to the static build, never to the authenticated app.
    metadata = (
        f'<meta http-equiv="Content-Security-Policy" content="{escape(CSP, quote=True)}">\n'
        '<meta name="referrer" content="strict-origin-when-cross-origin">\n'
        f'<link rel="canonical" href="{SITE}{canonical}">\n'
        '<meta property="og:title" content="AI Operations Workbench">\n'
        '<meta property="og:description" content="Follow the cost. Prove the model choice. Watch the demo and explore the narrated architecture.">\n'
        f'<meta property="og:url" content="{SITE}{canonical}">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:image" content="{SITE}media/workbench-demo-poster.png">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
    )
    return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  '+metadata, 1)


def main():
    output = ROOT / "artifacts/pages/ai-operations-workbench"
    if output.is_symlink():
        raise ValueError("Public output must not be a symlink")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for filename in WEB_FILES:
        copy_file("web/"+filename, output)
    media = json.loads((ROOT/"docs/demo/manifest.json").read_text())["files"]
    for filename, entry in media.items():
        if not re.fullmatch(r"workbench-demo[\w.-]*", filename):
            raise ValueError("Unexpected public media filename")
        copy_file("web/media/"+filename, output, digest=entry["sha256"])
    clips = json.loads((ROOT/"docs/demo/audio-provenance.json").read_text())["clips"]
    for clip in clips:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", clip["id"]):
            raise ValueError("Unexpected narration identifier")
        copy_file("web/media/narration/"+clip["id"]+".mp3", output, digest=clip["audio_sha256"])
    for filename in DIAGRAMS:
        copy_file("docs/architecture/"+filename, output, "architecture/"+filename)
    copy_file("LICENSE", output, "LICENSE.txt")

    demo = public_html((output/"demo.html").read_text(), "")
    (output/"demo.html").write_text(demo)
    (output/"index.html").write_text(demo)
    architecture = public_html((output/"architecture.html").read_text(), "architecture.html")
    downloads = """<section class="scope-note" aria-label="Download architecture diagrams">
      <h2>Keep the architecture.</h2>
      <p>Static companions and editable sources for the narrated views:
      <a href="architecture/aws-hosted-test.png" download>AWS diagram (PNG)</a> ·
      <a href="architecture/aws-hosted-test.drawio" download>AWS source (draw.io)</a> ·
      <a href="architecture/workbench.svg" download>Original local workflow (SVG)</a> ·
      <a href="architecture/workbench.drawio" download>Local workflow source (draw.io)</a>.
      The AWS diagram describes the single-host acceptance test; it is not a high-availability claim.</p>
    </section>"""
    architecture = architecture.replace("<!-- public-architecture-downloads -->", downloads, 1)
    (output/"architecture.html").write_text(architecture)
    (output/".nojekyll").touch()
    (output/"robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}sitemap.xml\n")
    (output/"sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{SITE}</loc></url><url><loc>{SITE}architecture.html</loc></url></urlset>\n"
    )
    version = tomllib.loads((ROOT/"pyproject.toml").read_text())["project"]["version"]
    files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob("*")) if p.is_file()}
    (output/"site-manifest.json").write_text(json.dumps({
        "version": version, "source": "canonical web/demo.html and web/architecture.html",
        "network": "static assets only; connect-src 'none'", "files": files,
    }, indent=2)+"\n")
    print(f"Built public Workbench {version}: {len(files)+1} files; no app API or credentials.")


if __name__ == "__main__":
    main()
