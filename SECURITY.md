# Security policy

## Supported version

Only the latest tagged release receives security fixes while the project is in evaluation status.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open a public issue containing exploit details, proprietary source, credentials, or internal environment information.

## Distribution warning

This repository does not audit or redistribute Graphify or Codebase-Memory binaries. An organization that injects third-party artifacts into an offline bundle is responsible for provenance, hash, license, malware, dependency, privacy, and platform review.

Never commit:

- internal source, prompts, benchmark answers, or results;
- internal hostnames, paths, managed settings, or private Rules;
- credentials, signing keys, certificates, or `.env` files;
- generated graphs, caches, or unreviewed executable artifacts.

## Mandatory no-egress gate

Real company code may be evaluated only after all of the following are evidenced in the target environment:

- the Claude Code model/API route is explicitly approved for company source;
- Graphify, Codebase-Memory, wrappers, parsers, and every child process are denied external network access at the OS, endpoint-security, container, or VM layer;
- DNS, proxy, telemetry, crash reporting, package resolution, and update checks are included in that denial;
- only the target repository is mounted read-only and only a dedicated, access-controlled cache/result directory is writable;
- home directories, other repositories, SSH agents, keychains, cloud credentials, and unrelated environment variables are unavailable to the backend;
- normal, failure, startup, and update-check paths were observed with firewall or equivalent network evidence and produced no unapproved egress;
- generated graphs and raw results are treated as source-equivalent data for encryption, access, retention, backup, and deletion.

A successful local test or use of `stdio` MCP is not proof of network isolation. If any item above is not proven, use only synthetic or already-public fixtures and stop before production integration.
