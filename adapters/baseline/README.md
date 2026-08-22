# Baseline condition

`baseline` runs Claude Code with an explicitly materialized empty MCP configuration. It does not install, start, or download a code-graph backend.

The example invokes Claude Code with `--bare`, `--no-session-persistence`, `--mcp-config`, and `--strict-mcp-config`. The task prompt is sent on stdin, not in argv. Before recording results, the evaluator must verify the pinned Claude Code build actually isolates other MCP sources in the target environment. A passing process exit code alone does not prove isolation.

Use the same Claude Code version, model, permission policy, repository revision, task suite, seed, and repetition count as every candidate condition.

`company-source` is disabled in the current release, even if a security evidence ID is supplied. No immutable approved Claude command identity or routing policy has been published for this runner, so condition JSON cannot opt into company-source execution. The CLI evidence option is reserved for a future reviewed contract. The runner has no network client, but the Claude subprocess can communicate using its configured route. Raw stdout and stderr are discarded by default; explicit storage requires an output directory outside the repository and harness and still depends on company endpoint controls.

The child environment excludes `HOME`, `USERPROFILE`, `APPDATA`, and `LOCALAPPDATA`, and condition JSON cannot provide or inherit them. Explicit environment keys also cannot override the runner's minimum OS environment or overlap either phase's inherited-name list, with comparisons performed case-insensitively. Approved Claude authentication must use an OS-managed route that does not expose user-profile directories to the Claude or MCP subprocess tree.

Primary reference: [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference).
