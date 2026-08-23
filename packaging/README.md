# Offline runtime assembly

The business-user ZIP is a single deterministic artifact containing four
runtime variants:

- `macos-arm64`
- `macos-x86_64`
- `windows-arm64`
- `windows-x86_64`

The endpoint installer verifies every file in `SHA256SUMS`, detects its own
platform and architecture, and copies only the matching gateway/backend pair.
It never downloads a missing component and never runs an upstream installer or
package manager.

`profiles/runtime-matrix.json.in` is an assembly input template, not an endpoint
configuration. Replace every `__GATEWAY_*__` token from the four gateway build
outputs and replace `__APPROVED_FIXTURE_MANIFEST_SHA256__` with the fingerprint
of the exact clean public fixture. Do not replace the pinned Codebase-Memory fields unless a separately
reviewed backend version is approved. All `source` values are relative to the
explicit `--vendor-dir`; URLs, absolute paths, traversal, and symlinks are
rejected by the bundle builder.

Compute the fingerprint with an unprivileged source build and the managed Git
path/hash, then compile the same value into every distributed gateway:

```text
codegraph-gateway fixture fingerprint \
  --root APPROVED_PUBLIC_FIXTURE \
  --allowed-root APPROVED_PUBLIC_FIXTURE \
  --state-dir EXTERNAL_TEMP_STATE \
  --git-binary MANAGED_GIT_ABSOLUTE_PATH \
  --git-sha256 MANAGED_GIT_SHA256

go build -trimpath \
  -ldflags "-X main.allowedFixtureManifests=CODEGRAPH_APPROVED_FIXTURES:APPROVED_FIXTURE_MANIFEST_SHA256:END" \
  ./cmd/codegraph-gateway
```

A gateway built without this linker value cannot index or serve any repository.
The runtime profile records the same allowlist in `approved_fixture_manifests`.
The builder scans every gateway for the stable embedded release record and
refuses a mismatch, then records the executable hash. Computing a fingerprint
does not enable it.

Build after staging exactly the eight native executables plus the pinned
Codebase-Memory `LICENSE`, normalized Unix-line-ending
`THIRD_PARTY_NOTICES.md`, and release `sbom.json` at the three `legal/` paths in
the template. The builder verifies all eleven files before emitting the ZIP:

```text
codegraph-harness bundle build \
  --profile packaging/profiles/runtime-matrix.json \
  --vendor-dir APPROVED_STAGING_DIRECTORY \
  --version RELEASE_VERSION \
  --output codegraph-harness-RELEASE_VERSION-offline.zip
```

The checked-in `.json.in` file deliberately cannot be used as a release profile
until the gateway build hashes and commit have been substituted and reviewed.
Native backend bytes, generated gateway executables, upstream notices, and SBOM
must not be committed to this repository.
