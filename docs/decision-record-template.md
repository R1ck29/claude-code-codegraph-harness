# Backend decision record template

Copy this file into the internal decision system. Do not commit company results or identifiers to the public repository.

## Evaluation identity

- Decision owner:
- Reviewers: Engineering / AppSec / Privacy / Endpoint / Legal:
- Public harness tag and commit:
- Claude Code version, model, effort, and approved service route:
- Task-suite hash:
- Conditions-config hash:
- Repository-set identifier or internal evidence link:
- Seed and repetitions:
- macOS versions/architectures tested:
- Windows versions/architectures tested:

## Pre-registered gates

Record every threshold before viewing comparative results. Use `Not measured` when evidence is absent; do not estimate.

| Gate | Threshold | Baseline | Graphify native | Codebase-Memory native | Graphify hybrid | Codebase-Memory hybrid |
|---|---:|---:|---:|---:|---:|---:|
| Blind answer correctness |  |  |  |  |  |  |
| Blind answer completeness |  |  |  |  |  |  |
| Change-task test pass rate |  |  |  |  |  |  |
| Input tokens |  |  |  |  |  |  |
| Output tokens |  |  |  |  |  |  |
| Cache creation/read tokens |  |  |  |  |  |  |
| Wall time |  |  |  |  |  |  |
| Index build time and size |  |  |  |  |  |  |
| Stale-index rejection | Pass/Fail |  |  |  |  |  |
| Truncation made explicit | Pass/Fail |  |  |  |  |  |
| macOS install/rollback | Pass/Fail |  |  |  |  |  |
| Windows install/rollback | Pass/Fail |  |  |  |  |  |
| Offline installation | Pass/Fail |  |  |  |  |  |
| Backend egress is zero | Pass/Fail |  |  |  |  |  |
| Filesystem/credential isolation | Pass/Fail |  |  |  |  |  |
| License/provenance/SBOM review | Pass/Fail |  |  |  |  |  |

No-egress, filesystem isolation, provenance, and rollback are blocking controls. Do not trade them for token or quality gains.

## Evidence classification

For every material statement, label it:

- `Confirmed`: directly supported by a recorded run, artifact hash, source inspection, or control evidence;
- `Vendor claim`: stated by upstream but not independently reproduced;
- `Inference`: a reasoned interpretation of confirmed observations;
- `Unknown`: absent, conflicting, or inconclusive evidence.

## Native versus customization finding

- Native blocker reproduced:
- Evidence artifact/hash:
- Is configuration sufficient? Yes / No / Unknown
- If not, can a thin wrapper correct only the boundary gap? Yes / No / Unknown
- Wrapper regression result:
- Is a fork technically necessary? Yes / No / Unknown
- Upstream issue/change request:
- Long-term owner:

## Decision

Select exactly one:

- adopt one pinned upstream candidate unchanged;
- adopt one pinned upstream candidate behind a thin wrapper;
- approve a minimal maintained fork with patch ledger;
- select neither and retain baseline exploration;
- defer because required evidence is unknown.

Decision rationale:

Unresolved evidence:

Expiry/re-review date:

Rollback trigger and owner:
