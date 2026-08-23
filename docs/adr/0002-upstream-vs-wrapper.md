# ADR 0002: Upstream, wrapper, or fork

- Status: Company gateway selected; upstream backend remains unmodified
- Decision date: 2026-08-23

## Decision

Place a company-owned local stdio MCP gateway in front of the exact upstream native backend. Keep the parser and graph implementation unmodified. The gateway is the only MCP surface registered with Claude Code and Codex.

The gateway exists because the upstream analysis profile is still broader than the company contract: it includes arbitrary graph queries, source snippets, project listing, change detection, and index diagnostics. Client-side allowlists are defense in depth; they do not make an exposed upstream tool safe.

The gateway exposes only:

- `codegraph_status`
- `codegraph_search`
- `codegraph_neighbors`
- `codegraph_impact`
- `codegraph_architecture`

It rejects arbitrary projects, absolute paths, arbitrary graph languages, indexing, mutation, source-body retrieval, URLs, and unbounded responses. It also owns freshness checks and normalizes all output into a backend-independent schema.

Index creation is a separate human/administrator command, never a model-callable MCP tool. The backend runs with UI, watcher, auto-index, updater, and online installation paths disabled.

## Fork policy

A fork is not approved for v1. Open a fork decision only if a reproducible parser or graph-construction defect cannot be fixed by configuration, gateway translation, or an accepted upstream change. A fork requires its own provenance, security audit, patch ledger, and multi-platform build process.

## Fallback

If the backend or gateway is unavailable, stale, truncated, outside the approved root, or fails a security/quality/token gate, both clients must use their normal source, grep, and language-server exploration. Graph failure must never block ordinary code work.
