# Graphify hybrid condition

`graphify-hybrid` is not an upstream Graphify baseline. It is the pinned upstream engine behind a company-owned adapter plus the proposed company Rule and Skill.

The example reserves two stable adapter entry points:

- `codegraph-graphify-prepare --repo <path> --state <path>`;
- `codegraph-graphify-mcp --repo <path> --state <path>`.

Those executables are intentionally not implemented or downloaded by the evaluation runner. Add this condition only after `graphify-native` produces a documented blocker or a separately stated routing hypothesis. The adapter must be supplied as an approved artifact and must:

- use stdio only and open no listener;
- accept explicit repository and state roots;
- perform no install, update, or Claude configuration mutation;
- expose a bounded, read-only tool contract;
- report stale or incomplete indexes instead of silently falling back;
- work with paths containing spaces on macOS and Windows.

Record the wrapper commit and artifact SHA-256 separately from the upstream Graphify version. This preserves attribution between upstream behavior and company customization.

The Claude command starts from `--bare` and adds only the repository's `codegraph-evaluator` Plugin and `codegraph-harness.md` Rule with explicit paths. The prompt is provided on stdin. This condition is `public-fixture` only for the same external-processing and PR-tool concerns as native Graphify. The runner downloads nothing and has no network client, but neither the wrapper nor its MCP subprocess is network-isolated by the runner. Raw stdout/stderr are discarded unless secure storage is explicitly requested.
