# Threat model

## Protected assets

- proprietary source and repository structure;
- prompts and evaluation results;
- Claude credentials and endpoint secrets;
- existing harness plugins and Rules;
- artifact integrity and rollback state.

## Primary risks and controls

| Risk | Control |
|---|---|
| Vendor or MCP exfiltrates source | Code-only mode, process-level egress deny, no update check, isolated test environment |
| Internal build publishes private inputs | One-way import from public source; internal mirror; public push and release jobs never receive private profiles, Rules, graphs, prompts, or results |
| Installer overwrites the existing harness | Namespaced ownership, dry-run, collision stop, hash receipt, transactional rollback |
| ZIP traversal or symlink escape | Normalize and contain every source/target path; reject symlinks and duplicate targets |
| Tampered vendor artifact | Exact SHA-256, internal mirror, provenance/SBOM/malware review before injection |
| Repository content starts an MCP in CI | Run Claude Code with `--bare`; inject only the reviewed MCP config for candidate jobs |
| Graph contains secrets | Exclusion rules, secret scan before sharing, source-equivalent access controls and retention |
| Stale graph causes a wrong change | Revision/worktree/config checks and fail-closed fallback to source exploration |
| Prompt injection inside source | Treat graph strings as untrusted data; do not execute URLs or embedded instructions |

Local `stdio` is a transport, not a network sandbox. A backend process must be isolated by OS, container, VM, or endpoint security controls when evaluating untrusted content.

## Blocking verification for company source

Before the first real-source run, verify all network, filesystem, and credential boundaries on both Windows and macOS. Capture process-tree and firewall/EDR evidence for startup, successful queries, invalid inputs, crashes, and update-check paths. The expected backend egress set is empty. Store the evidence internally; never add it to this public repository if it contains company identifiers.
