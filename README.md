# Claude Code Codegraph Harness

An offline local codegraph gateway, dual-client adapters, evaluation runner, and
cross-platform packaging system for Claude Code and Codex.

> Status: `v0.2.0-rc.1`, public-fixture release candidate. The runtime works,
> but measured Codex graph conditions increased input tokens by 48–52%, and
> forced Claude graph use increased effective input by 58–112%. Company
> source remains blocked until enterprise Windows/macOS isolation evidence is
> approved. This release makes no token-reduction claim.

For a business-user and administrator explanation in Japanese, start with
[このハーネスの仕組み](docs/how-it-works-ja.md). The same bytes are included as
`HOW-IT-WORKS-JA.md` in every generated offline ZIP.

## What is implemented

- a company-owned Go `stdio` gateway exposing five bounded, read-only tools;
- Codebase-Memory v0.10.8 native binary support behind that gateway;
- explicit administrative index builds, immutable generations, atomic current
  pointers, repository-bound state, and per-query freshness checks;
- Claude Code Plugin/Rule and a Codex user Skill using one canonical routing policy;
- macOS and Windows installers for arm64 and x86_64 runtime bundles;
- deterministic, checksummed adapter-only and four-platform internal ZIPs;
- a public-fixture evaluation runner that records token usage, latency, bounded
  oracle results, and tool names without retaining prompts or model responses.

The gateway exposes only:

- `codegraph_status`
- `codegraph_search`
- `codegraph_neighbors`
- `codegraph_impact`
- `codegraph_architecture`

Indexing, mutation, arbitrary graph queries, source-body retrieval, URLs, and
upstream MCP tools are not model-callable.

## Runtime architecture

```text
Claude Code Plugin + Rule ----\
                               > registered local stdio gateway
Codex user Skill -------------/              |
                                              v
                                  pinned Codebase-Memory native binary
                                              |
                                              v
                              private repository-bound graph generations

administrator command -> gateway index build -> validate -> atomic activation
```

Claude Code and Codex share the exact gateway, backend, index, freshness model,
and five-tool contract. The Plugin and Skill contain routing guidance only; they
never launch an upstream backend directly.

## Current adoption decision

Graphify v0.9.48 is rejected for company source because the pinned upstream MCP
includes GitHub-connected PR tools and external LLM paths. Codebase-Memory
v0.10.8 is the conditional native backend because its production native path has
no observed external network dependency, can disable UI/watch/auto-index, and
ships for all four target OS/CPU pairs. Its npm, PyPI, Go, and upstream installer
wrappers are prohibited because they download from GitHub.

The gateway and backend were exercised on a disposable public fixture under a
macOS sandbox denying external network access. It produced 759 nodes and 1,760
edges with zero skipped, partial, or non-indexed files; search, impact tracing,
architecture, schema validation, and stale/root rejection succeeded.

The repeated Codex comparison did **not** show savings:

| Task | Baseline median input | Graph median input | Change | Quality oracle |
|---|---:|---:|---:|---:|
| one-symbol location | 52,037 | 79,176 | +52.15% | 3/3 vs 3/3 |
| caller/dependency/test trace | 134,073 | 198,427 | +48.00% | 3/3 vs 3/3 |

Claude Code also used the gateway successfully, but did **not** show savings:

| Task | Baseline median effective input | Forced graph median | Change | Quality oracle |
|---|---:|---:|---:|---:|
| one-symbol location | 54,464 | 115,250 | +111.61% | 3/3 vs 3/3 |
| caller/direct-test/default-profile trace | 112,029 | 176,515 | +57.56% | 3/3 vs 3/3 |

The Claude treatment called exactly one bounded gateway tool per run and then
verified source. An unforced graph-enabled probe chose no MCP tool, so automatic
tool selection is not established. OAuth/keychain required normal headless mode;
the exact controls and limitations are recorded in the
[Claude Code evaluation](docs/evidence/claude-v0.2.0-public-token-eval.md).

Therefore the graph is an opt-in structural-navigation capability, not an
always-on cost optimization. See also the
[Codex evaluation](docs/evidence/codex-v0.2.0-public-token-eval.md).

## No-code-egress boundary

The endpoint installers contain no downloader or package-manager invocation.
The gateway launches only hash-pinned local backend and Git executables with a
synthetic private home and a minimal environment. State is outside the source
repository. Tool results contain bounded relative paths and graph evidence, not
source bodies.

Those controls are not an enterprise sandbox. `stdio` does not prevent a child
process from opening DNS or HTTPS. Runtime installation requires an explicit
absolute `--allowed-root`/`-AllowedRoot`, and each release-candidate gateway is
compiled with the content fingerprint of the exact clean public fixture; a
label, a different checkout, an ignored extra file, or a different repository
cannot enable it. This release is still public-fixture-only. Before company-source use,
endpoint/AppSec must enforce and record process-tree network denial and
filesystem/credential isolation for the exact binaries on every supported
Windows and macOS architecture.

The public repository and release never contain company source, prompts,
results, internal paths, managed policy, signing keys, generated graphs, or
third-party native binaries.

## Public adapter-only ZIP

The public release is intentionally small and contains adapters, installers,
contracts, and documentation only:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
codegraph-harness bundle \
  --version 0.2.0-rc.1 \
  --profile packaging/profiles/public.json \
  --output dist/codegraph-harness-0.2.0-rc.1.zip
```

Installing this ZIP does not enable a graph runtime.

## Internal runtime ZIP

The internal artifact pipeline builds the gateway for four targets and stages
the four exact Codebase-Memory executables from its approved mirror. It then
replaces the gateway metadata tokens in
[`runtime-matrix.json.in`](packaging/profiles/runtime-matrix.json.in) and runs:

```text
codegraph-harness bundle \
  --version COMPANY_RELEASE_VERSION \
  --profile /approved/input/runtime-matrix.json \
  --vendor-dir /approved/input/native \
  --output /approved/output/codegraph-harness-COMPANY_RELEASE_VERSION.zip
```

The builder reads only explicitly enumerated regular files, verifies every
SHA-256, rejects symlinks/traversal/collisions, and emits a deterministic ZIP,
runtime manifest, bundle manifest, and `SHA256SUMS`. The current four-platform
test ZIP is 172 MB compressed and 1.1 GB extracted; an endpoint installs only
its matching gateway/backend pair.

Business endpoints need no GitHub, npm, PyPI, Go registry, or vendor server.
They do need the organization-managed Git executable recorded at installation.

## Endpoint commands

For an adapter-only public ZIP:

```text
./install.sh --dry-run
./install.sh

powershell.exe -NoProfile -File .\install.ps1 -DryRun
powershell.exe -NoProfile -File .\install.ps1
```

For a runtime ZIP, an administrator must scope it to the exact public-fixture
checkout compiled into that gateway binary:

```text
./install.sh --dry-run --allowed-root /absolute/approved/public-fixtures
./install.sh --allowed-root /absolute/approved/public-fixtures

powershell.exe -NoProfile -File .\install.ps1 -DryRun -AllowedRoot C:\Approved\PublicFixtures
powershell.exe -NoProfile -File .\install.ps1 -AllowedRoot C:\Approved\PublicFixtures
```

At assembly time, the bundle builder verifies that every gateway's embedded
fixture allowlist matches the runtime profile. At the endpoint, the installer
verifies every extracted entry against `SHA256SUMS`, selects the local OS/CPU pair,
installs the Claude Rule and Codex Skill without overwriting unowned files,
optionally installs the local Claude marketplace Plugin, registers the same
gateway with both installed clients, and writes a hash receipt. Partial failures
roll back.

Uninstall preserves derived graph state by default to avoid silent data loss.
Use `--purge-graph-state` or `-PurgeGraphState` in the original uninstall command
when policy requires deletion.

Verify the complete ZIP against a signature or SHA-256 obtained separately from
the ZIP before extraction. In-band `SHA256SUMS` detects partial replacement but
is not a trust root for a fully replaced archive.

## Evaluation runner

The checked-in runner accepts public fixtures only and rejects `company-source`
before reading condition JSON or starting a process. It supports Claude and
Codex baseline/gateway conditions plus the legacy candidate comparison IDs. Raw
stdout/stderr is hashed but not stored unless explicitly requested.

See [Evaluation protocol](docs/evaluation-protocol.md). A condition file is
executable configuration and must be treated as trusted code.

## Verification

Local verification currently includes 85+ Python tests, Black, mypy strict, Go
unit/vet/race checks, four-target Go cross-builds, Claude Plugin strict
validation, checksum/archive tests, and a real macOS arm64
install→index→MCP query→uninstall run. Windows executables are cross-built and
the PowerShell flow runs in GitHub Actions; native Windows Codebase-Memory and
enterprise EDR evidence remain release gates for company source.

## Further reading

- [Architecture](docs/architecture.md)
- [Internal harness integration](docs/internal-integration.md)
- [Offline distribution](docs/offline-distribution.md)
- [Threat model](docs/threat-model.md)
- [Backend selection ADR](docs/adr/0001-backend-selection.md)
- [Wrapper ADR](docs/adr/0002-upstream-vs-wrapper.md)
- [Dual-client ADR](docs/adr/0003-dual-client-runtime.md)
- [Candidate egress audit](docs/candidate-egress-audit.md)
- [Runtime evidence](docs/evidence/cbm-v0.10.8-macos-arm64.md)

## License

Repository-owned code is Apache-2.0. Codebase-Memory remains MIT-licensed and
is redistributed only by an internally reviewed bundle with its notices.
