"""Issue a CVE-specific VEX for one SBOM after checking its actual proxy binary."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image]))[0]
    # Bind the evidence to an immutable local image, not a mutable tag.
    identity = image["Id"]
    bom = json.loads(args.sbom.read_text())
    properties = {p["name"]:p["value"] for p in bom["metadata"]["component"].get("properties", [])}
    assert properties.get("aquasecurity:trivy:ImageID") == identity, "SBOM/image mismatch"
    result = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only",
                             "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                             "--entrypoint", "/usr/bin/caddy", identity,
                             "--workbench-security-self-test"], capture_output=True, text=True,
                            timeout=15, check=True)
    assert result.stdout.strip() == "CVE-2026-116587: JOSE v3 RSA bounds and public-header checks passed"
    package = "pkg:golang/github.com/go-jose/go-jose/v3@v3.0.5"
    components = [c for c in bom["components"] if c.get("purl") == package]
    assert len(components) == 1, "Unexpected JOSE component; review the backport"
    serial = bom["serialNumber"].removeprefix("urn:uuid:")
    reference = f"urn:cdx:{serial}/{bom['version']}#{components[0]['bom-ref']}"
    document = {
        "bomFormat":"CycloneDX", "specVersion":"1.5", "version":1,
        "vulnerabilities":[{
            "id":"CVE-2026-116587",
            "analysis":{
                "state":"resolved", "response":["update"],
                "detail":"This image backports the RSA modulus/prime bounds and public JWK/EPK "
                         "header checks from go-jose a0111f82742fa92bceec9ede40845e73319e6230. "
                         "Docker build verifies original and patched source checksums and regression "
                         "tests; the actual scanned binary passed its regression self-test. "
                         "JOSE v3's original module version remains visible for other advisories. "
                         "Evidence applies only to this SBOM and image "+identity+".",
                "lastUpdated":datetime.now(timezone.utc).isoformat(),
            },
            "affects":[{"ref":reference}],
        }],
    }
    args.output.write_text(json.dumps(document, indent=2)+"\n")
    print("Verified proxy backport; issued VEX for one CVE, component, SBOM and image.")


if __name__ == "__main__":
    main()
