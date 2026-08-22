# Architecture

## Boundaries

The public repository owns the comparison protocol, a platform-neutral Claude Code plugin, public Rules, schemas, installer source, and deterministic bundle assembly.

The internal assembly pipeline owns private Rules, real organization paths, managed settings, signing material, evaluation tasks and results, and approved vendor artifacts.

The endpoint installer owns only namespaced files recorded in its receipt. It must not regenerate or overwrite the existing harness.

## Components

```text
task suite -> evaluation runner -> Claude Code condition -> raw local result
                                  | baseline
                                  | Graphify native profile
                                  | Codebase-Memory native profile
                                  | Graphify hybrid profile
                                  ` Codebase-Memory hybrid profile

public source + install profile + optional approved vendor directory
                         -> deterministic bundle builder
                         -> offline ZIP
                         -> transactional endpoint install
```

## MCP deployment modes

The evaluation runner injects candidate MCP configuration into an isolated run. Production integration is deliberately undecided.

- If an organization deploys `managed-mcp.json`, plugin-provided MCP servers are suppressed. The plugin contains skills and agents only; IT owns the fixed server entry.
- Without exclusive managed MCP, an OS-specific plugin may launch a separately installed wrapper from a fixed absolute path. The managed allowlist must match the invariant command exactly.

Project `.mcp.json` is not part of the endpoint distribution design.

## Ownership

The extension may create or update only:

- the `codegraph-evaluator` plugin installed from the `codegraph-harness` local marketplace;
- `codegraph-harness.md` under the configured Rules directory;
- its own versioned data directory;
- its own receipt and backups.

An unowned collision is a hard stop. Uninstall removes only paths whose previous and installed hashes are recorded in the receipt.
