# JOSE v3 security backport

CVE-2026-116587 was reported against both JOSE v3 and v4. The build upgrades v4
to 4.1.6. Caddy's Smallstep dependency still uses unsupported v3.0.5, for which
the upstream advisory lists no patched release.

The patch adapts the RSA modulus and prime bounds and private-parameter rejection
in public JWK/EPK headers from upstream commit
`a0111f82742fa92bceec9ede40845e73319e6230`. The existing v3 API is retained.
The code is derived from go-jose under its Apache-2.0 license; the vendored module
retains that license. The build verifies the two upstream file hashes before
patching and their expected hashes afterward. It refuses mismatched source.

The modulus limit is 4096 bits, matching the upstream fix. RSA prime sizes and
their product are checked before expensive private-key validation. JWS/JWE
public headers reject private key parameters before parsing them. Explicit,
trusted private JWK imports remain supported. Build tests cover malformed keys,
public header rejection, valid RSA imports, signing and verification.

The final binary exposes `--workbench-security-self-test`. CI runs that binary
without network access before generating a CycloneDX VEX document bound to the
scanned image ID and unique SBOM. Only this CVE on this v3 component is marked
resolved. The original module version remains in the binary, so other findings
remain visible. CI retains the SBOM, VEX and scanner report for review.

Remove the patch and VEX generation when Caddy's dependency graph supports a
maintained, fixed JOSE version throughout; rerun the full image scan and proxy
tests. Never reuse the generated VEX against another SBOM or an older image.

Upstream evidence:

- https://github.com/go-jose/go-jose/security/advisories/GHSA-mgcc-cww5-fp2q
- https://github.com/go-jose/go-jose/commit/a0111f82742fa92bceec9ede40845e73319e6230
- https://github.com/go-jose/go-jose/releases/tag/v4.1.6
