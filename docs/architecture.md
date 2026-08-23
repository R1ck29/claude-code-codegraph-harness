# Architecture

## Product boundary

The public repository owns the gateway source, client adapters, public Rule,
evaluation runner, schemas, installer source, and deterministic bundle builder.
It never contains native vendor executables or internal data.

The internal assembly pipeline owns the exact native artifacts, generated
gateway binaries, company signing material, malware/SBOM evidence, managed
allowed roots, private Rules, and enterprise acceptance records.

## Runtime

```text
Claude Code Plugin/Rule ----\
                            > local stdio codegraph-gateway -> pinned CBM -> graph
Codex user Skill ----------/

administrator -> gateway index build -> isolated generation -> validate -> current
```

The client adapters do not contain MCP server declarations. The installer or
managed endpoint policy registers one fixed gateway executable and invariant
arguments. Both clients share the same five read-only tools, backend, state, and
freshness contract.

## Gateway boundary

The gateway:

- canonicalizes the Git top-level and contains it within an explicit absolute
  allowed root;
- recomputes a clean tracked-file content manifest, rejects ignored/untracked
  additions, and requires that manifest in a compile-time fixture allowlist;
- pins its backend, routing policy, and managed Git identities by SHA-256;
- starts Codebase-Memory with a synthetic private home and a minimal environment;
- disables UI, watch, and automatic indexing;
- exposes only status, search, neighbors, impact, and architecture;
- rejects mutation, indexing over MCP, arbitrary query languages, absolute
  paths, source bodies, URLs, oversized results, and unsupported arguments;
- revalidates commit, dirty state, generation, backend, gateway, and config on
  every query;
- returns only a bounded backend-independent JSON contract.

Index state is stored outside the repository under a repository-identity hash.
Builds use an exclusive lock and immutable generation directory. A generation
becomes current only after the backend reports complete node/edge/file counts
with no skipped, partial, or non-indexed files.

## Deployment modes

The endpoint must choose one control owner.

- With exclusive `managed-mcp.json`, endpoint management defines the gateway;
  the Plugin remains Skill/Agent-only.
- Without exclusive managed MCP, the offline installer registers the fixed
  separately installed gateway for Claude Code and Codex.

Project `.mcp.json` is never part of the distribution. Runtime installation
requires an explicit allowed root; `.` is not registered. For this release the
classification is fixed to `public-fixture`; the label is not authorization.
The release binary additionally permits only content manifests compiled by the
controlled build, and an ordinary source build permits none.

## Client routing

The canonical routing policy is [`clients/routing-policy.json`](../clients/routing-policy.json).
Generated Claude and Codex guidance uses graph tools only for structural
discovery, then verifies consequential claims in source and tests. Normal query
responses carry their own freshness result; `codegraph_status` is diagnostic,
not a mandatory preflight.

If the graph is unavailable, stale, dirty, or truncated, both clients fall back
to normal source, search, LSP, and tests. Graph failure never blocks ordinary
coding work.

## Packaging

The public profile produces an adapter-only ZIP. The internal runtime profile
must enumerate exactly one gateway and one backend for each of macOS/Windows ×
arm64/x86_64. Every entry carries version, commit, license, executable flag, and
SHA-256. The runtime manifest also records the compile-time public-fixture
fingerprints. The endpoint verifies the entire archive inventory and installs
only its matching pair; release review must match those fingerprints to all
four build commands.

Install ownership covers namespaced runtime files, the Claude Rule/Plugin, the
Codex Skill, MCP registrations, and a receipt. Unowned or user-modified
collisions stop or are preserved. Derived graph state is retained by default
and can be explicitly purged during uninstall.

## Security limit

The gateway narrows application behavior but does not create an OS sandbox for
its native subprocess. Company-source enablement requires enterprise-enforced
network and filesystem isolation for the whole process tree on every supported
platform. The public-fixture macOS sandbox result is evidence of compatibility,
not production authorization.
