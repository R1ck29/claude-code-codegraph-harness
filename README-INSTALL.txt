Claude Code + Codex Codegraph Harness - Offline Bundle

Read HOW-IT-WORKS-JA.md first for a plain-language explanation, security
boundaries, and current evaluation results.

VERIFY BEFORE EXTRACTION

Verify this complete ZIP against a SHA-256 value or signature obtained from a
separate trusted location in your organization's software portal. SHA256SUMS is
inside the ZIP; it detects damaged or partially replaced extracted files but is
not a trust root for a fully replaced ZIP.

BUNDLE TYPES

1. Adapter-only public bundle
   Installs the Claude Code Plugin/Rule and Codex Skill. It has no native graph
   runtime and does not enable codegraph tools.

2. Internally assembled runtime bundle
   Contains four hash-pinned runtime pairs for macOS/Windows and arm64/x86_64.
   The installer copies only the current endpoint's pair. This release candidate
   is public-fixture-only and requires the exact clean fixture whose content
   fingerprint was compiled into the included gateway, plus its absolute root.

MACOS

Adapter only:
  ./install.sh --dry-run
  ./install.sh

Runtime, scoped to approved public fixtures:
  ./install.sh --dry-run --allowed-root /absolute/approved/public-fixtures
  ./install.sh --allowed-root /absolute/approved/public-fixtures

WINDOWS POWERSHELL

Adapter only:
  powershell.exe -NoProfile -File .\install.ps1 -DryRun
  powershell.exe -NoProfile -File .\install.ps1

Runtime, scoped to approved public fixtures:
  powershell.exe -NoProfile -File .\install.ps1 -DryRun -AllowedRoot C:\Approved\PublicFixtures
  powershell.exe -NoProfile -File .\install.ps1 -AllowedRoot C:\Approved\PublicFixtures

UNINSTALL

Default uninstall preserves local derived graph state:
  ./uninstall.sh
  powershell.exe -NoProfile -File .\uninstall.ps1

Delete the derived graph state in the same transaction when policy requires it:
  ./uninstall.sh --purge-graph-state
  powershell.exe -NoProfile -File .\uninstall.ps1 -PurgeGraphState

WHAT THE INSTALLER DOES

- verifies every extracted checksummed file before creating state;
- never downloads from GitHub, package registries, or vendor servers;
- selects one OS/architecture runtime pair if present;
- requires an existing managed Git executable for runtime installation;
- refuses missing, broad, relative, or changed allowed roots;
- cannot index or serve a checkout whose clean tracked-content fingerprint is
  absent from the gateway binary's compile-time fixture allowlist;
- stops on unowned Rule, Skill, runtime, or MCP registration collisions;
- registers the company-owned gateway, never the upstream backend, with both
  installed clients;
- rolls back files and registrations created by a failed installation.

The local marketplace may be blocked by managed Claude Code policy. In that
case, use --skip-plugin/-SkipPlugin and have the Claude Code administrator
distribute the Plugin through the approved managed mechanism.

DO NOT USE COMPANY SOURCE YET

The current runtime registration is explicitly public-fixture-only, and the
binary allows only the clean fixture fingerprints fixed by the release build.
A local
stdio connection and an offline installer do not prove that every native child
process is unable to use DNS or HTTPS. Company-source approval requires the
exact internal ZIP to pass Windows and macOS enterprise process-tree network,
filesystem, credential, retention, and rollback gates. Do not point
--allowed-root/-AllowedRoot at a company repository before that approval.

The measured Codex graph conditions did not reduce tokens on the current public
fixture. Treat the graph as optional structural navigation, not a cost-saving
guarantee.
