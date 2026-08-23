# Third-party notices

This repository can assemble, but does not commit, the Codebase-Memory native executable listed below. Runtime bundles that include it must also include its license, upstream third-party notices, SBOM, exact artifact identity, and the organization redistribution approval.

## Codebase-Memory

- Project: Codebase-Memory MCP
- Repository: https://github.com/DeusData/codebase-memory-mcp
- Version: 0.10.8
- Commit: `46ae198fc11cda80e817acbc5f5908d7c2de7032`
- License observed at the pinned commit: MIT
- License copy in this repository: `vendor/licenses/codebase-memory-MIT.txt`
- Artifact lock: `vendor/codebase-memory-v0.10.8.lock.json`

The upstream native archives also contain `THIRD_PARTY_NOTICES.md`. Internal assembly must extract and preserve that exact file; this repository does not replace it.

## Graphify

Graphify v0.9.48 is referenced only as a rejected research/evaluation candidate. It is not included in the completed runtime and must not be added to a company-source bundle without a new candidate and security review.

License observations are not a completed legal review. Re-verify the exact release, transitive notices, provenance, vulnerabilities, and redistribution approval before every internal release.
