# Internal harness integration

This repository extends an existing Plugin-plus-scripted-Rules harness; it does
not replace or merge with it.

## Release status

`v0.2.0-rc.1` contains the complete gateway source and adapter/packaging logic,
but is authorized only for public fixtures. Observed Codex graph conditions
increased median input tokens by 48–52%; forced Claude graph use increased
median effective input by 58–112%. Enterprise Windows/macOS isolation
evidence is incomplete. Do not present this release as a cost-reduction feature
or point its allowed root at company source.

## Inputs owned by the internal pipeline

- immutable public tag and commit;
- four reviewed gateway build outputs;
- Codebase-Memory v0.10.8 native executables from an internal mirror;
- exact archive/executable hashes, provenance, license, SBOM, and malware result;
- completed runtime profile derived from `runtime-matrix.json.in`;
- organization-specific Rule/policy overlays kept outside this repository;
- signing credentials and the software-portal release record.

Never send internal profiles, paths, Rules, evaluation data, graphs, prompts, or
logs back to GitHub or another external service. Use an internal mirror and
one-way import when the pipeline cannot technically enforce that boundary.

## Assembly sequence

1. Verify the public tag, commit signature/policy, and public CI result.
2. Re-run Python, Go, Plugin, installer, schema, and archive tests internally.
3. Compute the exact clean public-fixture content manifest with `fixture
   fingerprint`, then build `codegraph-gateway` with `-trimpath` and
   `-ldflags "-X main.allowedFixtureManifests=CODEGRAPH_APPROVED_FIXTURES:<manifest>:END"`
   for darwin/windows
   and arm64/amd64; record every command, hash, manifest, and source commit. A
   normal source build intentionally permits no repository.
4. Stage exactly eight reviewed executables plus the pinned upstream license,
   third-party notices, and SBOM using the relative layout in
   [`packaging/README.md`](../packaging/README.md).
5. Replace every gateway token and the approved-fixture-manifest token in
   `runtime-matrix.json.in`. Confirm the profile manifest equals the linker
   allowlist in all four binaries. Do not change the backend lock without a new
   source/dynamic audit.
6. Build the internal ZIP with the explicit profile and `--vendor-dir`.
7. Validate manifest/schema/checksums, scan, sign, and test the exact bytes on
   the supported endpoint matrix.
8. Publish that exact ZIP and a signature or SHA-256 through separate trusted
   portal metadata. Archive the inputs, outputs, tests, approval, and rollback.

Example:

```text
codegraph-harness bundle \
  --version 0.2.0-rc.1-company.1 \
  --profile /approved/input/runtime-matrix.json \
  --vendor-dir /approved/input/native \
  --output /approved/output/codegraph-harness-0.2.0-rc.1-company.1.zip
```

The paths are examples only. The builder never scans the vendor directory and
never downloads a missing file.

## Existing harness ownership

- Keep `codegraph-evaluator`, `company-codegraph`, and
  `codegraph-harness.md` namespaced.
- Continue installing Rules outside the Plugin; the installer stops on an
  unowned same-name file and never overwrites a user-modified owned file.
- Do not write a global or project `AGENTS.md`; install the Codex user Skill.
- Decide centrally between exclusive `managed-mcp.json` and installer-managed
  registration. Do not operate both as competing owners.
- If managed MCP is exclusive, distribute the fixed gateway through endpoint
  management and use the ZIP only for Plugin/Rule/Skill assets.
- Never register the upstream Codebase-Memory MCP directly.

## Business-user installation

The public adapter-only bundle needs no allowed root. A runtime bundle requires
the exact compiled public fixture and its explicit absolute root:

```text
./install.sh --dry-run --allowed-root /absolute/approved/public-fixtures
./install.sh --allowed-root /absolute/approved/public-fixtures
```

```text
powershell.exe -NoProfile -File .\install.ps1 -DryRun -AllowedRoot C:\Approved\PublicFixtures
powershell.exe -NoProfile -File .\install.ps1 -AllowedRoot C:\Approved\PublicFixtures
```

The endpoint must have an organization-managed Git executable. It does not need
GitHub, npm, PyPI, Go registry, or vendor-server access. If managed Claude Code
policy blocks local marketplaces, pass `--skip-plugin`/`-SkipPlugin` and deploy
the Plugin centrally.

Verify the complete ZIP before extraction. Dry-run validates every entry and
shows the selected runtime without writing state.

## Index operation

Index builds are an IT/developer operation, not an MCP tool. Use the installed
gateway with the same allowed root, backend/config/Git paths, and hashes in the
registration receipt. Build only the clean committed public fixture whose
content manifest is compile-approved by the binary and profile. The first
successful build activates an immutable generation; later
failures leave the previous generation unchanged.

Index rebuild triggers should be explicit and managed, for example after an
approved checkout/commit transition. Do not let the model, filesystem watcher,
or upstream auto-indexer refresh the graph.

## Company-source promotion gate

The checked-in installer deliberately registers `public-fixture`. Promotion is
a new reviewed internal release, not a user flag change. Before creating it:

1. test the exact four native backend and gateway hashes;
2. enforce zero external DNS/TCP/UDP for gateway, backend, Git, and descendants;
3. make HOME/keychain/SSH agent/other repositories/credential env inaccessible;
4. mount or ACL the approved source root read-only for query operation and allow
   writes only to the private state root;
5. exercise startup, build, normal queries, invalid input, crash, stale/dirty,
   upgrade, rollback, uninstall, retention, and purge;
6. verify Windows and macOS on every supported CPU under enterprise policy;
   on Windows, prove there is no backend start-to-Job-Object-assignment escape
   window, using a suspended/gated launcher or an independently enforced EDR
   process-tree policy;
7. sign the approval policy so an endpoint user cannot self-assert approval;
8. repeat the client token/quality evaluation on representative public or
   internally approved tasks and record that it currently fails the cost gate.

If any item is missing, retain public-fixture-only behavior.
