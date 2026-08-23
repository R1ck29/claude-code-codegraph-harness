# ADR 0001: Backend selection

- Status: Conditionally accepted behind the company gateway
- Decision date: 2026-08-23

## Context

Graphify and Codebase-Memory are separate implementations with different packaging, tool contracts, and published evidence. The `v0.1.1-eval` release did not contain either backend and did not measure an actual graph-enabled run.

## Decision

Use the pinned Codebase-Memory v0.10.8 native executable at commit `46ae198fc11cda80e817acbc5f5908d7c2de7032` as the initial backend behind the company-owned `codegraph-gateway`. Do not expose the upstream MCP directly.

Pinned upstream Graphify remains rejected for company-source use after static source audit identified GitHub-connected PR tools in its stdio MCP and external LLM paths. Its conditions remain public-fixture-only.

Package-manager wrappers and upstream online installers are rejected. Internal assembly may ingest only the four native archives pinned in `vendor/codebase-memory-v0.10.8.lock.json`, verify both archive and extracted executable hashes, and redistribute them with the MIT license and notices.

On the current macOS arm64 host, the exact binary was run against a disposable public fixture under an OS sandbox that denied external network access while allowing only its private Unix-domain socket. Indexing and read-only search, trace, and architecture queries succeeded. This is positive macOS evidence, not a Windows or enterprise EDR attestation.

Company-source use stays disabled until the exact release bundle passes the Windows and macOS process-tree egress, filesystem isolation, freshness, quality, token, and rollback gates. Failure of any gate retains the normal source exploration baseline.

The first repeated Codex comparison has now failed the token gate: graph use
increased median input by 48.00% to 52.15% on the two recorded task shapes while
preserving bounded oracle quality. This does not reject the backend as an
opt-in structural index, but it rejects an always-on cost-saving rollout.

## Why this backend

- It provides the multilingual parser and persistent graph that a standard-library-only implementation cannot accurately reproduce.
- The native source audit found no source/query HTTP sender in the pinned revision.
- The fixed native executable works without package-manager or upstream installer activity.
- A company gateway can reduce the upstream tool surface to bounded read-only queries while preserving backend replaceability.

## Explicit non-claims

- Passing one macOS sandbox run does not prove that every platform build has zero egress.
- The backend is not approved for company source until the release-specific enterprise gates pass.
- No token reduction is claimed. Codex currently has negative cost evidence,
  and Claude Code safe-headless measurement is incomplete.
