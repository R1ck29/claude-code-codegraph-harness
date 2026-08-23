# Claude Code public-fixture graph evaluation

- Date: 2026-08-23
- Host: macOS arm64
- Data: disposable public-repository fixture; no company source. The Claude client used the current user's OAuth/keychain authentication.
- Fixture commit: `ef6e7b9ef9279e84a07db0714373cabb3d168fff`
- Fixture file-manifest SHA-256: `0478f324963efd28844b0a01d092a69bf33e972a047fab247b4e4c2ae6eb7a52`
- Claude Code: `2.1.239`
- Main model: `claude-sonnet-5`, effort `low`; the client also reported an auxiliary `claude-haiku-4-5` model
- Gateway executable SHA-256: `9ea44fad40ce46adff933ee2990f3312cd50d88ed4791c21c1d21c1cd3cdc3ca`
- Routing policy SHA-256: `d967756b7db7b6ab6d84b298a03adb0857cf4690e7172627d123f0c19d54bb60`
- Backend: Codebase-Memory v0.10.8 native executable
- Backend executable SHA-256: `2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf`
- Repetitions: 3 per task and treatment
- Raw response storage: disabled; only response hashes, usage, bounded MCP tool names, and oracle outcomes were retained

## Authentication and isolation

The installed client was authenticated with Claude OAuth/keychain. Claude Code
`--bare` does not read OAuth/keychain credentials, so it could not be used on
this host without a separate API key or approved `apiKeyHelper`. The evaluation
instead used the normal headless client with all of the following explicit
controls:

- `--setting-sources ''`;
- `--strict-mcp-config` with a temporary baseline or gateway-only file;
- `--no-session-persistence`;
- `--permission-mode dontAsk`;
- only `Read`, `Grep`, `Glob`, and, for the treatment, the five gateway tools;
- no Bash, edit, web, or upstream backend tool;
- the compile-time approved clean public fixture only.

This is useful public-fixture evidence, not a company-source security approval.
The process still used the real user authentication environment and was not an
enterprise filesystem/network sandbox. The fixture contained no credential,
and the harness did not put an OAuth token in MCP configuration, but this test
does not prove that the gateway process was unable to access same-user secrets.

## Comparison design

An unforced graph-enabled probe selected zero MCP tools. The measured treatment
therefore explicitly required exactly one bounded graph call, followed by source
verification. This prevents an enabled-but-unused MCP context from being
misreported as graph use. The baseline used the same answer oracle without a
graph tool. Claude Code exposes no seed control, so no seed claim is made.

“Effective input” below is `input_tokens + cache_creation_input_tokens +
cache_read_input_tokens`, calculated from the client result. It is not the same
field as the Codex input metric and must not be compared across clients.

| Task | Treatment | Median effective input | Median output | Median elapsed | Correct | Observed graph calls |
|---|---:|---:|---:|---:|---:|---:|
| Locate `run_bundle_cli` | baseline | 54,464 | 126 | 6 s | 3/3 | 0 |
| Locate `run_bundle_cli` | one forced search | 115,250 | 322 | 17 s | 3/3 | 3 searches / 3 runs |
| Caller, direct test, default profile | baseline | 112,029 | 498 | 11 s | 3/3 | 0 |
| Caller, direct test, default profile | one forced impact query | 176,515 | 1,029 | 24 s | 3/3 | 3 impact calls / 3 runs |

The forced graph treatment increased median effective input by 111.61% for the
location task and 57.56% for the structural task. Every bounded answer oracle
passed, but the predeclared 20% reduction threshold failed.

## Decision

This result rejects a Claude Code token-reduction claim for the tested fixture,
model, and routing. It confirms that Claude Code can launch and use the same
local gateway as Codex, and that the gateway returns usable bounded evidence.
The feature remains opt-in structural navigation. It must not be enabled
automatically or marketed as a cost-saving feature.

## Limits

- Two small tasks and one public fixture do not represent company repositories.
- Requiring one graph call measures the cost of actual use, but it changes the
  treatment instruction by design.
- The unforced probe selected no graph tool, so automatic tool-selection quality
  is not established.
- Claude Code did not expose a reproducible seed.
- This is macOS-only evidence and does not authorize company-source use.
