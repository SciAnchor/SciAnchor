# Project Self-Evolution

Status: v1 MVP, manually triggered only.

The executable self-evolution scope is intentionally small:

1. Manual archive run: collect durable evaluation artifacts for a topic.
2. Champion registry: select the best replay-ready candidate per target.
3. Replay gate: require deterministic promotion or held-out evidence before a
   candidate becomes a champion.

The canonical exercised path is `final-bundle-quality`: scan a final bundle,
record deterministic PDF-quality evidence, replay against held-out bundles, and
archive the resulting score/gate artifacts. The loop records evidence; it does
not mutate code, prompts, workflow graphs, skills, or external resources.

## Runtime Surface

Source package: `research_harness.evolution.harness`

| Module | v1 role |
|---|---|
| `archive.py` | Candidate archive records, replay splits, champion registry packs. |
| `collectors.py` | Read-only collectors for ResearchFlowBench reports and final-bundle replay evidence. |
| `pdf_quality.py` | Deterministic TeX/PDF/log quality scan and finding triage. |
| `trajectory_gate.py` | Deterministic PDF-quality replay gate and report persistence. |
| `models.py` | Dataclasses needed by the archive, champion, and replay gate path. |

## CLI

```bash
rh self-evolution record-rfb-score-report --topic TOPIC --score-file scores.json
rh self-evolution record-rfb-gate-report --topic TOPIC --gate-file gate.json
rh self-evolution archive-from-artifacts --topic TOPIC
```

`archive-from-artifacts` creates `candidate_archive_pack` and, when a candidate
has non-incubating promotion evidence, `champion_registry_pack`.

## Promotion Rule

A candidate can become champion only when all of these are true:

- its archive record has `gate_action = "promote"`;
- its replay split is not incubating;
- it has source replay references;
- it has at least one promotion-test or held-out replay reference.

## Removed From Runtime

The following mechanisms were removed from executable source in the 2026-06-01
MVP contraction and now live only as research notes:

- automatic code mutation and candidate workspaces;
- AFlow/A-Evolve style workflow graph mutation;
- reference-library planning and broad feedback triage;
- multi-route review guidance as a self-evolution planner input;
- skill-bank lifecycle management and MUSE/SkillOpt style package promotion.

See `docs/research/self-evolution-future-work.md` for those planned mechanisms
and the gates required before any of them can return to source code.
