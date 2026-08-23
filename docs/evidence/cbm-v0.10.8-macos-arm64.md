# Codebase-Memory v0.10.8 macOS arm64 runtime evidence

- Date: 2026-08-23
- Host: macOS arm64
- Data: disposable archive of this public repository; no company source or credentials
- Backend: Codebase-Memory v0.10.8, commit `46ae198fc11cda80e817acbc5f5908d7c2de7032`
- Archive SHA-256: `9bd840dfb3ec7eaef4f310382057adaa5b0e904df883104d03ffcf39836afd07`
- Executable SHA-256: `2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf`

## Isolation used

The process ran under a macOS sandbox profile that denied all network operations and then allowed only bind/outbound operations to the backend's private Unix-domain-socket directory. External network access remained denied. The test used private temporary cache, runtime, and repository directories and set:

- `auto_index=false`
- `auto_watch=false`
- `ui_enabled=false`

An initial profile that denied every network operation also denied the required Unix-domain socket and the daemon failed. This confirms that a blanket macOS `network*` rule must distinguish local IPC from external networking.

## Observed results

- index state: indexed
- graph nodes: 759
- graph edges: 1,760
- not indexed files: 0
- skipped files: 0
- partial parses: 0
- exact symbol search: `run_bundle_cli` found at `src/codegraph_harness/bundle.py`
- inbound trace: 3 callers returned for the exact qualified symbol
- architecture overview: Python, YAML, Bash, and TOML represented

Read-only project listing, symbol search, path tracing, and architecture queries all completed under the network-deny profile.

## What this evidence does not prove

- It does not test the Windows binaries.
- It does not replace enterprise EDR/firewall process-tree evidence.
- It does not prove filesystem isolation from unrelated user files.
- It does not measure Claude Code or Codex token savings; those are recorded in
  a separate client evaluation.
- It does not authorize company-source use.

The release-specific Windows/macOS security gates and repeated client evaluations remain mandatory.
