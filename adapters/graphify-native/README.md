# Graphify native condition

`graphify-native` means the pinned upstream Graphify package and its MCP server, without a company wrapper, Rule, or Skill.

The checked-in example uses the upstream command shapes documented for the current Python package:

- prepare: `graphify extract . --code-only`;
- stdio MCP: `python -m graphify.serve <graph.json>`.

The evaluator supplies the pinned Python environment on `PATH`. The runner never runs `pip`, downloads Graphify, or modifies Claude configuration. Upstream writes `graphify-out/` below its working repository. Therefore the runner refuses this condition unless the evaluator passes `--repo-is-disposable-copy`; never point it at the original repository. The flag is an acknowledgement, not proof that the copy or worktree is isolated.

Before use, record the exact `graphifyy` version, wheel SHA-256, Python version, platform, and resolved executable paths. Confirm the command surface against that pinned release; an upstream change is a new condition artifact, not an in-place edit to completed results.

The example disables Graphify query logging explicitly. Verify that setting against the pinned release and retain an egress/filesystem trace as evidence; configuration documentation is not runtime proof.

This condition is `public-fixture` only. Upstream documents external LLM processing for documents and media, and the MCP tool surface includes PR-related capabilities that may use GitHub. `--code-only` limits extraction but does not prove the whole subprocess tree has no egress. The runner itself has no network client and downloads nothing, but it does not create or prove OS/container/network isolation for Graphify, its Python environment, Claude, or MCP children. Raw stdout/stderr are discarded by default.

Primary references: [Graphify repository](https://github.com/Graphify-Labs/graphify) and [graphifyy on PyPI](https://pypi.org/project/graphifyy/).
