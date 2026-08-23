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
| Wrong repository is indexed | Gateway canonicalizes Git top-level, requires an explicit absolute allowed root, rejects dirty/ignored additions, and matches actual tracked-file content to a compile-time fixture allowlist |
| Uninstall leaves source-derived state | Document retention; provide explicit transactional purge; verify deletion according to internal policy |
| User self-asserts company approval | Public release has no company-source enablement path; a future internal policy must be signed and OS-managed |

Local `stdio` is a transport, not a network sandbox. A backend process must be isolated by OS, container, VM, or endpoint security controls when evaluating untrusted content.

## Blocking verification for company source

Before the first real-source run, verify all network, filesystem, and credential boundaries on both Windows and macOS. Capture process-tree and firewall/EDR evidence for startup, successful queries, invalid inputs, crashes, and update-check paths. The expected backend egress set is empty. Store the evidence internally; never add it to this public repository if it contains company identifiers.

The current Windows implementation starts the backend and then assigns it to a
Job Object. That closes ordinary descendant-cleanup failures, but it does not
prove that a compromised backend cannot create a child in the start-to-assign
interval. A future company-source build therefore needs either a launcher that
assigns the suspended process before backend work begins or an endpoint policy
that independently confines the complete process tree. Public-fixture-only use
does not remove this promotion requirement.

The current installer fixes the runtime classification to `public-fixture`.
That string is not a sensitivity detector, so the binary also rejects every
repository whose clean tracked-content manifest was not compiled into the
controlled release. This prevents self-labeling from enabling an arbitrary
checkout; it is not an OS sandbox or company-source approval. Company-source
promotion must therefore be a separately
signed, endpoint-managed internal release with an immutable allowed-root policy,
not a command-line opt-in available to business users.
