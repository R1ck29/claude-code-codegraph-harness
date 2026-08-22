# Routing guidance

| Question type | First tool | Required verification |
|---|---|---|
| Callers, callees, dependency paths, hubs, architecture boundaries | Approved graph MCP, if available | Open consequential source locations before proposing a change |
| Exact control flow, exception behavior, validation, text literals | Read, Grep, or LSP | Relevant tests |
| Reflection, runtime DI, macros, generated code, environment-driven behavior | Source, configuration, and execution | Tests or a reproducible run |
| Stale, truncated, failed, or unversioned graph | Standard Claude Code exploration | Normal verification workflow |

Use bounded queries. Avoid arbitrary graph-query languages and unbounded depth during evaluation. Preserve the same task, model, permissions, and cache policy across comparison conditions.
