# Publication Pack

`publication_pack` is RH's contract-first bridge from long-running research state to publication-facing outputs.

It borrows the strongest pattern from specialized academic-output skill bundles: define the package, source obligations, and QA checks **before** polishing prose, figures, slides, or reviewer responses.

## What it is

A `publication_pack` is a write-stage orchestrator artifact that inventories the latest evidence-bearing artifacts for a topic:

- required manuscript sections (`draft_pack`);
- required claims/evidence (`evidence_pack` or compatible claim artifacts);
- optional citation/integrity reports;
- optional figure plans, data availability statements, reviewer responses, slide outlines, final bundles, and process summaries.

The pack is reviewable because it stores both:

1. the components that are present and their artifact IDs;
2. the components and checks still missing before submission-facing use;
3. deterministic `next_actions` that tell an agent which artifact/tool to run next.

## Generate one

Via MCP/primitive:

```text
publication_pack_generate(topic_id=<id>, target_profile="high-impact-general", record_artifact=true)
```

Via HTTP API:

```text
POST /api/topics/<topic_id>/publication-pack
{"target_profile": "high-impact-general", "record_artifact": true}
```

Via local CLI convenience command:

```text
rh publication-pack generate --topic "<topic-name>" --record-artifact
```

Add `--json` for the full machine-readable contract:

```text
rh --json publication-pack generate --topic "<topic-name>" --target-profile high-impact-general --record-artifact
```

The primitive is deterministic and does not call an LLM. It records the package as an artifact only when `record_artifact=true`.

The auto-runner also backfills this artifact at the end of the `write` stage
after `draft_pack`, `final_bundle`, and `process_summary` are recorded. A
write-stage draft alone is not considered sufficient for pre-execution skipping
until `publication_pack` exists.

## Required fields

The artifact schema requires:

- `components`
- `contract`
- `source_artifacts`

Most payloads also include `qa_checks`, `next_actions`, `ready_for_review`,
and `submission_ready`. `next_actions` is intentionally deterministic so an
agent can resume from the pack without reinterpreting prose.

The contract requires every generated claim to stay traceable to at least one of:

- `paper_id`
- `claim_id`
- `artifact_id`

## Readiness semantics

`ready_for_review=true` only means the required manuscript/evidence components are present. It does **not** mean the work is submission-ready.

`submission_ready=true` is stricter: required components must be present and the pack's QA checks must pass, including citation/integrity evidence, a figure contract, a final bundle, and a process/provenance summary.

Before submission-facing use, run or record:

- public `consistency_check` output or a final citation/integrity report artifact;
- adversarial/scholarly review where appropriate;
- provenance review;
- figure/data/reviewer-response artifacts if the venue needs them.
