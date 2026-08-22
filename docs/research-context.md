# Research context and evidence boundaries

This repository was motivated by the Zenn article [「Claude Codeのコード探索を10倍効率化する — Code Graph × MCPでトークン消費を1/10に」](https://zenn.dev/nocodesolutions/articles/19f0d415af42be). The repository does not adopt its headline as a performance guarantee.

## Confirmed distinctions

- The article's hands-on implementation builds a graph with Graphify and exposes it to Claude Code through MCP.
- The approximately one-tenth token result cited by the article comes from the separate Codebase-Memory evaluation described in [its arXiv preprint](https://arxiv.org/html/2603.27277v1), not from the article's Graphify setup.
- That preprint reports results under its own repositories, question categories, model, version, and comparison workflow. It does not establish the same result for this organization's repositories or current Claude Code environment.
- Graphify's own worked comparisons use their stated baselines and are vendor evidence, not an independent measurement of normal Claude Code exploration.
- Structural graph retrieval can be useful without proving that either pinned product is safe, more accurate, faster, or cheaper in the target environment.

## Consequence for this repository

Every benefit is treated as a hypothesis. The evaluation holds the model, Claude Code version, task suite, revision, permissions, cache policy, repetitions, and scoring process constant. Metrics that Claude Code does not report are `null`, never estimated.

Security eligibility is evaluated before performance. The pinned Graphify upstream is rejected for company source after source audit found external-capable paths. The pinned Codebase-Memory native binary remains conditional and cannot be enabled for company source in this release. See [candidate egress audit](candidate-egress-audit.md).

## Evidence classes

- `Confirmed`: directly observed in pinned source, a recorded run, or an artifact/control record;
- `Vendor claim`: stated by a project or article but not independently reproduced here;
- `Inference`: a conclusion drawn from confirmed observations and labeled as such;
- `Unknown`: missing, conflicting, version-dependent, or not dynamically tested.

The internal decision record must preserve these labels and must not convert an unknown or vendor claim into an expected ROI.
