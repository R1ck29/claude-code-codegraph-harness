# Offline distribution

Business endpoints are not expected to reach GitHub, PyPI, npm, or vendor release servers.

The endpoint installer performs no download. After installation, the selected graph backend must also be prevented from reaching external services; an offline ZIP does not by itself prevent runtime egress.

## Public source release

The public release contains source, the vendor-neutral plugin, public Rules, schemas, tests, and a bundle builder. It does not contain Graphify environments or Codebase-Memory binaries.

## Internal assembly

An internal pipeline should:

1. fetch an immutable public tag and verify its commit;
2. obtain the approved vendor artifact from an internal mirror;
3. verify the exact hash, provenance, license, SBOM, and malware scan;
4. compute the exact clean public-fixture tracked-content fingerprint, compile
   it into every gateway, and record the same value in the install profile;
5. inject a private install profile and private Rules;
6. build the deterministic four-platform runtime ZIP and verify that each
   endpoint installs only its matching OS/CPU pair;
7. sign the scripts or enclosing package according to organization policy;
8. publish the ZIP to the internal software portal together with an out-of-band SHA-256 value or signature that is stored and delivered separately from the ZIP.

## Endpoint install

The endpoint extracts the ZIP and runs one local command:

```text
./install.sh --allowed-root /absolute/approved/public-fixtures
powershell.exe -NoProfile -File .\install.ps1 -AllowedRoot C:\Approved\PublicFixtures
```

Before extraction, the endpoint or portal must verify the ZIP itself against the separately delivered SHA-256 value or signature. The installer then verifies that mandatory extracted files are listed in the in-band `SHA256SUMS`, verifies all listed hashes, requires an explicit runtime allowed root, selects one runtime pair, checks owned collisions, installs from a local marketplace, registers the company gateway with Claude Code and Codex, writes a receipt, and rolls back partial failure. It performs no network download. The in-band checksum file detects partial tampering but cannot authenticate a completely replaced ZIP.

The public profile remains adapter-only. A runtime ZIP is assembled only in the
internal pipeline from the complete, hash-pinned four-platform matrix. The
current release registers `public-fixture`; the label is not authorization. The
gateway also requires the actual clean tracked-content manifest to match its
compile-time public-fixture allowlist and rejects ignored/untracked additions.
These checks still do not prove enterprise process isolation.

Uninstall retains derived graph state by default. Use the explicit purge option
in the original uninstall transaction when the organization's retention policy
requires deletion, and record the deletion result.

Do not use GitHub's automatically generated source ZIP as the business-user artifact. Use the workflow-generated, checksummed bundle.
