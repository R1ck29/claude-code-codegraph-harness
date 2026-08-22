# Candidate egress audit

Audit date: 2026-08-22. This is a static source audit of the exact commits in `candidates/registry.json`. No company source or credential was used. Static inspection cannot prove the behavior of release binaries, operating systems, or transitive dependencies; the internal dynamic gate remains mandatory.

## Decision summary

| Candidate | Exact source | Company-source status | Reason |
|---|---|---|---|
| Graphify | `v0.9.48`, `b2cd36267456c166788c95be6e68574064a92a42` | Rejected | Upstream stdio MCP exposes PR tools that can invoke authenticated `gh` and reach GitHub; non-code-only paths can send documents to external LLM providers |
| Codebase-Memory | `v0.10.8`, `46ae198fc11cda80e817acbc5f5908d7c2de7032` | Conditional, not approved | Native stdio/index/daemon source has no identified HTTP uploader, but online installers/wrappers download from GitHub, UI and watcher defaults require hardening, and release-binary egress is not dynamically proven |

Graphify remains available only as a public-fixture comparison condition. A future fork would be a new candidate requiring a new audit; this repository does not treat a wrapper as making the audited upstream server eligible for company source.

## Graphify findings

Confirmed:

- `--code-only` removes document, paper, and image inputs from semantic extraction and normally avoids backend auto-detection. Combining it with `--dedup-llm` still requires an LLM. [Pinned CLI logic](https://github.com/Graphify-Labs/graphify/blob/b2cd36267456c166788c95be6e68574064a92a42/graphify/cli.py#L3217-L3341)
- The standard stdio MCP registers `list_prs`, `get_pr_impact`, and `triage_prs`. [Pinned server registration](https://github.com/Graphify-Labs/graphify/blob/b2cd36267456c166788c95be6e68574064a92a42/graphify/serve.py#L1663-L1708)
- Those tools execute `gh`, which can call GitHub using the workstation's authentication. [Pinned subprocess path](https://github.com/Graphify-Labs/graphify/blob/b2cd36267456c166788c95be6e68574064a92a42/graphify/prs.py#L139-L240)
- Cloud LLM backends are automatically selected from provider environment variables outside the strict code-only path. [Pinned backend detection](https://github.com/Graphify-Labs/graphify/blob/b2cd36267456c166788c95be6e68574064a92a42/graphify/llm.py#L3058-L3088)
- HTTP transport and external data integrations exist as selectable features. The default MCP transport is stdio, but the capability remains present. [Pinned transport branch](https://github.com/Graphify-Labs/graphify/blob/b2cd36267456c166788c95be6e68574064a92a42/graphify/serve.py#L2333-L2377)
- Query logging is local rather than telemetry, but optional settings can persist questions, paths, and responses. [Pinned query logger](https://github.com/Graphify-Labs/graphify/blob/b2cd36267456c166788c95be6e68574064a92a42/graphify/querylog.py#L16-L43)

Unresolved:

- Graphify imports its LLM module even in code-only CLI execution. When optional `tiktoken` is present, initialization may require dependency data not already cached. The Graphify source alone is insufficient to prove whether a given locked environment performs network access. This uncertainty reinforces rejection; it is not presented as confirmed egress.

## Codebase-Memory findings

Confirmed:

- Production native daemon code has removed the prior GitHub update provider; stdio MCP and indexing source contain no identified HTTP uploader. [Pinned daemon decision](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/src/daemon/application.c#L66-L78)
- `auto_index` defaults false, while `auto_watch` defaults true and can start local `git` child processes. [Pinned MCP defaults](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/src/mcp/mcp.c#L11494-L11643)
- A release with an embedded UI can enable its loopback UI when no config exists. The listener binds to `127.0.0.1`, but UI is unnecessary for the harness and must be disabled. [Pinned UI default](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/src/ui/config.c#L111-L130), [pinned bind](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/src/ui/httpd.c#L219-L270)
- The UI can construct a GitHub issue URL containing project/path context after explicit user interaction. It is not automatic transmission, but it violates the intended workflow and is another reason to disable UI. [Pinned issue-link construction](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/src/ui/http_server.c#L123-L147)
- npm, PyPI, Go wrappers, and upstream shell/PowerShell installers download a native binary from GitHub. They are excluded from internal distribution. [Pinned npm installer](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/pkg/npm/install.js#L517-L543), [pinned PyPI wrapper](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/pkg/pypi/src/codebase_memory_mcp/_cli.py#L1159-L1190), [pinned Go wrapper](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/pkg/go/cmd/codebase-memory-mcp/main.go#L362-L479), [pinned shell installer](https://github.com/DeusData/codebase-memory-mcp/blob/46ae198fc11cda80e817acbc5f5908d7c2de7032/install.sh#L19-L79)

Not confirmed:

- Static review found no native telemetry, crash uploader, or source/query HTTP sender. This is not equivalent to dynamic proof for the compiled release and its child processes.

## Mandatory Codebase-Memory gate

Only an exact native binary obtained and verified by the internal artifact pipeline may proceed. Do not use the upstream installer or npm/PyPI/Go wrappers. Before indexing company source:

1. verify version, commit association, platform/architecture, SHA-256, provenance, license, SBOM, and malware/SCA results;
2. create a dedicated cache and set `ui_enabled=false`, `auto_index=false`, and `auto_watch=false` before the MCP session;
3. restrict the allowed repository root and use an isolated writable cache;
4. provide a minimal trusted `PATH`, block repository/global Git configuration that can alter execution, and remove unrelated credentials from the environment;
5. deny external DNS/TCP/UDP for the binary and its process descendants at the OS/EDR layer;
6. dynamically exercise startup, index, every exposed tool, invalid input, daemon lifecycle, update command, and shutdown on Windows and macOS;
7. require zero external DNS/TCP/UDP and zero non-loopback listeners; store the evidence internally and repeat for every version.

Until this gate passes, the status remains `conditional-static-audit-only`.
