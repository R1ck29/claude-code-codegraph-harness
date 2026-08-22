# Codebase-Memory native condition

`codebase-memory-native` means the pinned upstream `codebase-memory-mcp` binary, without a company wrapper, Rule, or Skill.

The example uses upstream's documented direct CLI and MCP interfaces. Under a dedicated `CBM_CACHE_DIR`, it first sets `auto_index=false`, `auto_watch=false`, and `ui_enabled=false`, then indexes explicitly:

- prepare: `codebase-memory-mcp cli index_repository --repo-path <absolute path>`;
- stdio MCP: `codebase-memory-mcp` with no arguments.

The evaluator supplies an approved, fixed-hash native binary on `PATH`. Do not use the npm wrapper, PyPI wrapper, official installer, updater, `install` command, or package manager in this condition: those distribution paths can download from GitHub or mutate agent configuration. The runner calls none of them and has no network client.

The example scopes the allowed repository and cache through `CBM_ALLOWED_ROOT` and `CBM_CACHE_DIR`. Verify both variables against the exact pinned release and confirm by filesystem and egress observation. Record the binary version, SHA-256, platform, architecture, and whether the binary signature or provenance was independently verified.

This condition remains `public-fixture` only until source and egress audit approval. The runner minimizes inherited environment variables and removes its temporary state after evaluation, but it does not create or prove OS/container/network isolation, and it cannot guarantee what MCP grandchildren inherit. Raw stdout/stderr are discarded by default.

Primary reference: [Codebase-Memory repository](https://github.com/DeusData/codebase-memory-mcp).
