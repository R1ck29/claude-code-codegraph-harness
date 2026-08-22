# Evaluation protocol

## Conditions

The initial protocol supports:

1. `baseline`: current Claude Code exploration without a graph MCP;
2. `graphify-native`: a pinned Graphify environment and its native MCP;
3. `codebase-memory-native`: a pinned Codebase-Memory binary and native MCP;
4. `graphify-hybrid`: Graphify plus routing and normal exploration fallback;
5. `codebase-memory-hybrid`: Codebase-Memory plus routing and normal exploration fallback.

Every condition in the current release, including `baseline`, is restricted to public fixtures, and the runner rejects company-source before loading or executing a condition. JSON and a security evidence identifier cannot override this hard gate. Graphify is rejected for company source at the pinned version. Codebase-Memory may be enabled only by a reviewed future harness release after the exact native binary passes the dynamic gate in `candidate-egress-audit.md`.

Wrapper and fork conditions are added only after a native candidate produces a documented blocker.

## Controls

Hold constant:

- Claude Code version;
- model and effort;
- prompt and task order policy;
- permission mode and allowed tools;
- cache state;
- repository revision and dirty state;
- timeout and repetition count.

Randomize task order with a recorded seed. Store the condition configuration hash, task hash, backend version, artifact hash, platform, and timestamps with every result.

## Measurements

- input, output, cache creation, and cache read tokens when reported;
- total cost when reported;
- tool calls and fallback behavior when available;
- wall time and process result;
- answer correctness and completeness from a separate blind scoring step;
- test pass and regression status for change tasks;
- index build time, size, memory, and errors;
- stale, truncation, crash, and recovery events.

An unavailable metric is `null`. Never estimate it and present the estimate as telemetry.

## Privacy

The summary contains hashes, not prompt text, repository paths, or source output. When raw stdout/stderr storage is explicitly enabled, the selected result directory must be new, access-controlled, and outside both the evaluated repository and this public harness.

The runner does not store raw stdout/stderr unless `--store-raw-artifacts` is explicitly set. `company-source` is disabled in this release because no immutable approved command identity and route have been published. The security evidence CLI option is reserved for a future reviewed contract and does not enable execution. These controls do not create OS isolation.

Condition JSON is executable configuration: it supplies process commands and MCP definitions. Before any future release enables `company-source`, each condition must use an embedded immutable template or a signature/hash-pinned policy loaded only from an administrator-controlled location. A user-provided conditions file and evidence label are not approval.

The runner has no network client, but configured commands can have network access. Before using real company code, record evidence that the approved Claude Code route is the only permitted external data path and that graph backend processes and descendants have enforced DNS/network denial. Tests on public fixtures do not satisfy this gate.

Run untrusted repositories and pull requests only inside an isolated container or VM with the target tree mounted read-only, a dedicated writable cache, no home/keychain/SSH/credential visibility, and network denied. Headless Claude Code jobs must use `--bare` or another verified policy that excludes repository-provided MCP configuration.

## Decision gate

Thresholds are set before results are viewed. The repository does not provide arbitrary company thresholds. A backend may be adopted unchanged only if it passes quality, security, offline-distribution, platform, freshness, and rollback requirements. A wrapper is justified only by a concrete native-backend gap. A fork requires an approved long-term owner.

No-egress evidence is a blocking requirement, not a scored trade-off. A candidate that improves quality or token use but cannot satisfy it is rejected.
