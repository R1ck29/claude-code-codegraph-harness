# Internal harness integration

This repository is an extension source, not a replacement for an existing company harness.

## Inputs from the company pipeline

The internal assembly job must provide, outside this repository:

- the approved public tag and commit;
- an install profile with exact artifact hashes;
- approved backend artifacts from an internal mirror, if a backend has passed evaluation;
- any private Rules and organization-specific managed settings;
- signing and software-portal publishing credentials.

The builder reads vendor files only when they are explicitly listed in the install profile. It never discovers or downloads vendor files. Repository-owned plugin, Rule, installer, license, and installation-guide assets are included through fixed mappings in the builder.

## Recommended integration sequence

1. Verify the public tag, commit, and CI result.
2. Re-run the repository tests in the internal build environment.
3. Stage approved vendor files in a clean directory.
4. Create a private profile from `packaging/profiles/internal.example.json` and record each relative source, bundle target, and SHA-256.
5. Build the ZIP with `codegraph-harness bundle`.
6. Secret-scan and malware-scan the ZIP, then sign it or publish its SHA-256 through a channel separate from the ZIP; archive the ZIP, verification value, and manifest.
7. Exercise install, reinstall, upgrade, rollback, and uninstall on the supported Windows/macOS matrix.
8. Publish the exact tested ZIP through the internal software portal.

The assembly environment may import approved public artifacts, but it must never publish internal profiles, Rules, evaluation data, source-derived graphs, paths, or logs back to GitHub or another external service. Run internal CI from an internal mirror when the build system cannot enforce one-way artifact import.

Example assembly command:

```text
codegraph-harness bundle \
  --version 0.1.0-company.1 \
  --profile /secure-build/input/company-profile.json \
  --vendor-dir /secure-build/input/vendor \
  --output /secure-build/output/codegraph-harness-0.1.0-company.1.zip
```

The profile, vendor directory, and output paths above are examples, not prescribed company paths.

## Existing harness boundary

- Keep the public plugin name and Rule filename namespaced.
- Do not merge private Rules into this public repository.
- Treat an existing, unowned Rule collision as an installation failure.
- Decide centrally whether MCP is deployed through `managed-mcp.json` or plugin configuration. Do not enable both paths.
- If `managed-mcp.json` exists, the plugin remains Skills/Agents-only and endpoint management owns the MCP server definition.
- If managed MCP is not exclusive, allow only a fixed wrapper command. Do not place a dynamic project path in the managed `serverCommand` argument list; the wrapper must validate the session root against an OS-managed allowed-root policy.

## Business-user command

After downloading and extracting the internally approved ZIP:

```text
./install.sh --dry-run
./install.sh
```

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -DryRun
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Verify the ZIP against the software portal's separately stored SHA-256 value or signature before extraction. The installer performs no package or network download; its in-band `SHA256SUMS` is only a secondary integrity check. Enterprise policy may require a stricter PowerShell invocation or a signed package; the internal release owner must define that command.

## Production gate

Do not add a backend to the business-user bundle until the backend ADR is closed with recorded evidence for quality, security, freshness, offline operation, Windows/macOS support, and rollback. The public `v0.1.0-eval` plugin intentionally contains no MCP server.

For environments where company code cannot leave the organization, AppSec or endpoint engineering must attach firewall/EDR evidence showing that the backend and its descendants cannot reach DNS, HTTP(S), proxies, update services, or telemetry endpoints. Configuration flags alone are insufficient. If the approved Claude Code service path itself is uncertain, stop and resolve that contract before evaluating company source.
