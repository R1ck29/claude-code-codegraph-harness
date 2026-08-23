# ADR 0003: One local graph runtime for Claude Code and Codex

- Status: Accepted for implementation
- Decision date: 2026-08-23

## Context

The business-user distribution path is an offline ZIP installed by command on Windows or macOS. Users may have Claude Code, Codex, or both. The endpoint must not fetch an executable from GitHub, npm, PyPI, Go registries, or an upstream installer.

## Decision

Install one OS/architecture-specific runtime per endpoint and register its `codegraph-gateway` stdio server with each installed client.

```text
Claude Code plugin + Rule ----\
                               > local stdio gateway -> pinned native backend -> local graph
Codex user Skill -------------/
```

The two clients share the same gateway executable, backend executable, repository-bound cache, freshness manifest, and security policy. Their adapters contain only client-specific installation metadata and guidance.

The canonical routing policy is stored once and rendered or verified into the Claude Code and Codex adapter formats. Global project instructions such as `AGENTS.md` are not overwritten. A Codex user/admin Skill is used instead.

## Runtime identity

The offline bundle records:

- gateway version and SHA-256;
- backend version, commit, archive SHA-256, extracted executable SHA-256, OS, and architecture;
- policy and schema hashes;
- license, notice, SBOM, and source references;
- the bundle manifest and an out-of-band release hash or signature.

The installer selects exactly one matching runtime, verifies it before and after placement, and records ownership in a receipt. Reinstall, upgrade, rollback, and uninstall preserve unowned or user-modified files.

## MCP registration

The registered command and arguments are stable across projects. A dynamic project path is not placed in a managed `serverCommand` allowlist. The installer records one explicit absolute allowed root. The gateway resolves the active Git top-level from its working directory, confirms it is contained by that canonical allowed root, rejects dirty/ignored additions, and matches actual tracked-file content to the public-fixture manifests compiled into the release binary.

For managed Claude Code deployments, IT may register the fixed gateway path in `managed-mcp.json`; the plugin then carries Skills/agents only. For self-service evaluation without managed MCP, the installer may create the user-scoped registration. These modes are mutually exclusive.

For Codex, the installer uses the supported local stdio MCP configuration. The
gateway itself exposes exactly five tools; the supplied managed-config template
also sets `enabled_tools`, `required`, and the read-only approval mode. A
production administrator may additionally pin the server identity in Codex
requirements policy.

## Security boundary

The gateway/backend process tree receives no inherited proxy, API-key,
SSH-agent, or credential environment variables. Gateway path validation limits
the requested repository and writes to its private cache, but it does not make
other same-user files invisible to a native subprocess. Enterprise OS/EDR must
enforce filesystem isolation and external DNS/TCP/UDP denial. The backend's UI,
watcher, updater, and automatic indexing are disabled.

The index is treated as source-derived confidential data. It is outside the repository, encrypted and access-controlled by the endpoint policy, never uploaded by this product, and removed according to the organization retention policy.

## Consequences

- Claude Code and Codex results are comparable because the graph and query contract are identical.
- Security review focuses on one runtime instead of two independent integrations.
- Client upgrades may require adapter/config validation but do not require rebuilding the graph backend.
- Windows and macOS runtime evidence is mandatory before company-source approval; a successful macOS test alone is insufficient.
