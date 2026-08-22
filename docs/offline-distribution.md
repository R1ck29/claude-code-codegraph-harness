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
4. inject a private install profile and private Rules;
5. build separate tested artifacts for the approved OS and CPU inventory;
6. sign the scripts or enclosing package according to organization policy;
7. publish the ZIP to the internal software portal together with an out-of-band SHA-256 value or signature that is stored and delivered separately from the ZIP.

## Endpoint install

The endpoint extracts the ZIP and runs one local command:

```text
./install.sh
powershell.exe -NoProfile -File .\install.ps1
```

Before extraction, the endpoint or portal must verify the ZIP itself against the separately delivered SHA-256 value or signature. The installer then verifies that mandatory extracted files are listed in the in-band `SHA256SUMS`, verifies their hashes, shows a plan, backs up owned collisions, installs from a local marketplace, writes a receipt, and rolls back partial failure. It performs no network download. The in-band checksum file detects partial tampering but cannot authenticate a completely replaced ZIP.

Do not use GitHub's automatically generated source ZIP as the business-user artifact. Use the workflow-generated, checksummed bundle.
