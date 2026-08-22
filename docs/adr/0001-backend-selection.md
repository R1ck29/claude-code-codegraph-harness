# ADR 0001: Backend selection

- Status: Evaluation narrowed; no production backend selected
- Decision date: 2026-08-22 (security eligibility only)

## Context

Graphify and Codebase-Memory are separate implementations with different packaging, tool contracts, and published evidence. The repository does not yet have organization-specific quality, security, or operability results.

## Decision

No backend is selected in `v0.1.1-eval`.

Pinned upstream Graphify is rejected for company-source use after static source audit identified GitHub-connected PR tools in its stdio MCP and external LLM paths. Its conditions remain public-fixture-only.

Pinned Codebase-Memory native binary remains a conditional candidate. Package-manager wrappers and upstream online installers are rejected. The current runner blocks company-source candidate execution; a reviewed future release may enable it only after the exact internal binary passes the dynamic isolation and zero-egress gate in `docs/candidate-egress-audit.md`.

Evaluate the baseline and security-eligible conditions under the protocol in `docs/evaluation-protocol.md`. Graphify may be measured only with public fixtures for article/research comparison; it cannot win the company-source selection. Record approved thresholds and internal result artifact IDs before selecting Codebase-Memory or retaining the baseline.

## Allowed outcomes

- adopt upstream unchanged;
- adopt upstream through a thin wrapper;
- maintain a minimal public fork;
- adopt neither and retain baseline exploration.
