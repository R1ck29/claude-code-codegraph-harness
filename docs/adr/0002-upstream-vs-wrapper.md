# ADR 0002: Upstream, wrapper, or fork

- Status: Open
- Decision date: Not set

## Decision order

1. Prefer an exact upstream artifact with automatic configuration disabled.
2. Add a thin wrapper only for a measured boundary gap: root containment, freshness, response bounds, stable tool schema, telemetry, or platform launch differences.
3. Fork only when the defect is inside parsing or graph construction and cannot be corrected by configuration, wrapper, or an accepted upstream change.
4. If no option passes, retain baseline Claude Code.

## Required evidence for a wrapper

- the native candidate passed core quality evaluation;
- the native gap has a reproducible test;
- the wrapper fixes that test without materially reducing the measured benefit;
- wrapper ownership and compatibility testing are assigned.

## Required evidence for a fork

- the wrapper path is technically insufficient;
- an upstream issue or change request exists where appropriate;
- the patch ledger, rebase procedure, build provenance, and supported platform owners are approved.

## Current candidate application

- Graphify upstream is rejected for company source. This repository does not approve a wrapper or fork as a substitute; either would be a new candidate with a new source and dynamic security audit.
- Codebase-Memory may be evaluated only as an internally verified native binary with online wrappers/installers excluded and runtime hardening applied. A wrapper decision remains open until native quality and dynamic security gates pass.
