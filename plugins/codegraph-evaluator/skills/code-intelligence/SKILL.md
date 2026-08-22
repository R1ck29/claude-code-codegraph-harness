---
name: code-intelligence
description: Route structural code questions through an approved code-graph MCP when one is available, then verify consequential claims against source and tests. Use for callers, callees, dependency paths, architecture boundaries, hubs, and change-impact exploration.
argument-hint: "[structural code question]"
---

# Code intelligence routing

Treat graph output as an index derived from static analysis, not as source-of-truth.

1. Check whether an approved code-graph MCP tool is available in this session. Never claim that Graphify, Codebase-Memory, or another backend is installed merely because this skill exists.
2. For callers, callees, dependency paths, architecture boundaries, hubs, and impact candidates, prefer a bounded graph query when available.
3. For exact branches, error behavior, runtime dependency injection, reflection, generated code, configuration, and final change decisions, inspect source and tests.
4. If graph status is stale, unavailable, truncated, or does not identify its indexed revision, stop relying on it and use Read, Grep, Glob, LSP, and tests.
5. Report which conclusions came from graph structure and which were verified directly.

Read [routing guidance](references/routing.md) and [freshness requirements](references/freshness.md) before treating a graph result as evidence.

Do not promise a token reduction or quality improvement. Those are evaluation outcomes, not properties of this plugin.

Never use graph tools to access remote pull requests, create external issues, open or construct external URLs, install or update software, start a network listener, or select a cloud model. A tool's presence does not make it approved for company source.
