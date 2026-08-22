Claude Code Codegraph Harness - Offline Bundle

For a plain-language Japanese explanation, read HOW-IT-WORKS-JA.md in this folder.

This bundle installs a vendor-neutral evaluation plugin and public Rule.
It does not select or download a code-graph backend.

macOS:
  ./install.sh --dry-run
  ./install.sh

Windows PowerShell:
  powershell.exe -NoProfile -File .\install.ps1 -DryRun
  powershell.exe -NoProfile -File .\install.ps1

Uninstall:
  ./uninstall.sh
  powershell.exe -NoProfile -File .\uninstall.ps1

The installer uses the local marketplace inside this extracted bundle. It
does not require GitHub, Git, PyPI, npm, or a vendor release server. If your
organization blocks local marketplaces through managed policy, ask the
Claude Code administrator to distribute the plugin through the approved
managed mechanism instead.

Before extraction, verify the ZIP against a SHA-256 value or signature obtained
separately from the ZIP through your organization's software portal. The
SHA256SUMS file protects individual extracted files from accidental or partial
tampering, but it is inside the ZIP and is not a trust root for a replaced ZIP.
