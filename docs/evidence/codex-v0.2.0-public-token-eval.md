# Codex public-fixture token evaluation

- Date: 2026-08-23
- Host: macOS arm64
- Data: disposable public-repository fixture; no company source or credentials
- Fixture commit: `ef6e7b9ef9279e84a07db0714373cabb3d168fff`
- Fixture tree: `44d6356c8d03b4fd8849831d0cd989733d21afe7`
- Codex CLI: `0.146.1`
- Model: `gpt-5.6-sol`, explicitly observed in the local Codex configuration
- Gateway executable SHA-256: `c2835417eae023d2ad78d525753e732222770b7358479348122112df4e2c08d6`
- Routing policy SHA-256: `d967756b7db7b6ab6d84b298a03adb0857cf4690e7172627d123f0c19d54bb60`
- Backend: Codebase-Memory v0.10.8 native executable
- Backend executable SHA-256: `2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf`
- Repetitions: 3 per condition and task
- Seed: `20260823`
- Raw response storage: disabled; only hashes, usage, bounded tool-call names, and oracle counts were retained

## Results

| Task | Condition | Correct / total | Median input | Median cached input | Median output | Median latency | Observed graph calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Locate one symbol definition | baseline | 3 / 3 | 52,037 | 50,688 | 120 | 30,578 ms | 0 |
| Locate one symbol definition | graph gateway | 3 / 3 | 79,176 | 67,840 | 144 | 36,727 ms | 3 searches across 3 runs |
| Trace caller, dependency, and direct test | baseline | 3 / 3 | 134,073 | 127,744 | 571 | 49,380 ms | 0 |
| Trace caller, dependency, and direct test | graph gateway | 3 / 3 | 198,427 | 177,408 | 691 | 60,492 ms | 2 calls observed in 1 run; telemetry unavailable in 2 runs |

The simple graph condition used 52.15% more median input tokens than baseline. The
structural graph condition used 48.00% more. Output tokens and median latency also
increased. Both conditions passed every bounded substring oracle, so this test did
not observe a quality regression, but it did not meet the predeclared 20% median
input-token reduction threshold.

## Decision

This evidence rejects an always-on or cost-saving claim for the tested Codex
configuration. The gateway remains useful as an opt-in, local structural-navigation
capability, but it must not be marketed or enabled organization-wide as a token
reduction feature. A future adoption decision requires broader repositories and
task suites, a pinned client/model configuration recorded by the runner, and a
fresh repeated comparison.

## Limits

- The two task shapes and one public fixture are not representative of every codebase.
- The default Codex tool context itself has a token cost; this evaluation measures the
  complete client condition rather than backend response size in isolation.
- Tool-call telemetry was fail-closed as unavailable in two structural graph runs;
  it was not interpreted as zero calls.
- This is not Windows evidence and does not authorize company-source use.
- Claude Code was not measured in this result.
