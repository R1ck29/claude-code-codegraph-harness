# Code intelligence evaluation rule

Use an approved code-graph MCP only for structural exploration such as callers, callees, dependency paths, hubs, architecture boundaries, and impact candidates.

- A graph is derived static-analysis data, not source-of-truth.
- Verify consequential claims in current source and tests before making changes.
- If backend, version, indexed revision, dirty-state handling, or truncation status is unavailable, use normal Claude Code exploration.
- Do not infer runtime behavior for reflection, dependency injection, macros, generated code, or environment-driven configuration from a static graph alone.
- Do not claim token or quality improvements unless they were measured under the current evaluation protocol.
- Do not disable Read, Grep, Glob, LSP, or tests as a means of forcing graph use.
- Do not use a graph backend to open or construct external URLs, create issues, inspect remote pull requests, update itself, install packages, start an HTTP server, or select a cloud LLM backend.
- A backend condition that is not approved for the current data classification must not be invoked, even if its executable or MCP tools are present.
