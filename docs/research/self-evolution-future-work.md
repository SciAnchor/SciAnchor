# Self-evolution Future Work

This document keeps higher-risk self-evolution mechanisms out of the v1 runtime
contract. The current executable scope is manual signal capture, candidate /
champion artifact records, and replay gates.

## Future Mechanisms

| Mechanism | Status | Required gate before implementation |
|---|---|---|
| DGM-style automatic code mutation | planned | Sandbox, regression suite, candidate archive, human approval. |
| AFlow/A-Evolve workflow graph mutation | planned | Workflow replay tasks with component attribution and rollback. |
| OpenEvolve-style multi-candidate archive search | planned | Stable evaluator artifacts and parent-selection policy. |
| TextGrad/DSPy/GEPA prompt optimization | planned | Prompt/template replay set and leakage checks. |
| Candidate workspace materialization | planned | Isolated workspace contract, diff review, and promotion gate. |
| Reference-library planning and broad feedback triage | planned | Demonstrated replay set showing planner decisions improve promotion outcomes. |
| Multi-route review guidance as self-evolution input | planned | Clear ownership split between review gates and project-level evolution. |
| Skill-bank lifecycle management (MUSE/SkillOpt style) | planned | At least two real promoted skills with held-out replay evidence. |

## Non-goals For v1

- No automatic modification of source files.
- No automatic publication, push, merge, or external resource mutation.
- No promotion from a single topic or single source trace.
- No benchmark score without RH component/axis attribution.
