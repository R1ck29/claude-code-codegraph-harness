# Codebase-Memory hybrid condition

`codebase-memory-hybrid` is the pinned upstream Codebase-Memory engine behind a company-owned adapter plus the proposed company Rule and Skill. It is evaluated separately from `codebase-memory-native`.

The example reserves two stable adapter entry points:

- `codegraph-cbm-prepare --repo <path> --state <path>`;
- `codegraph-cbm-mcp --repo <path> --state <path>`.

The evaluation runner does not provide or download those executables. Introduce them only for a pre-registered hypothesis or a concrete native-backend gap. The adapter must:

- run as a local stdio process with no UI or network listener;
- constrain access to the explicit repository root;
- use the explicit state directory rather than a shared user cache;
- disable autonomous install, update, config mutation, and watchers unless a watcher is the declared variable under test;
- return explicit stale, truncated, and unsupported-language states;
- behave consistently on macOS and Windows, including paths containing spaces.

Record the wrapper commit and SHA-256 independently from the upstream binary version and SHA-256. Do not attribute wrapper or Rule behavior to the upstream project.

The Claude command starts from `--bare` and adds only the repository's `codegraph-evaluator` Plugin and `codegraph-harness.md` Rule with explicit paths. The prompt is provided on stdin. This condition remains `public-fixture` only until the native binary and wrapper receive source and egress approval. The runner never downloads a vendor and has no network client, but it does not create or prove OS/container/network isolation and cannot guarantee MCP-grandchild credential visibility. Raw stdout/stderr are discarded by default.
