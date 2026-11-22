---
name: publication-pack
version: 0.1.0
description: Assemble an evidence-bound publication package from Research Harness artifacts. Trigger on phrases like "publication-pack", "/publication-pack", "投稿材料包", "submission pack", "publication package", "把这个 topic 整理成投稿包", or equivalent requests to turn a topic's evidence, draft sections, figures, citation checks, response letters, and provenance into one reviewable package.
public_suite: paper
task_type: packaging
data_access_level: local
inputs: topic_id, draft_pack, evidence_pack, SKELETON_SOURCE_INTEGRITY_PROFILE, PRESUBMISSION_SEVERITY_GATE_PROFILE, REBUTTAL_READINESS_GATE_PROFILE, optional PAPER_PACKAGE, REBUTTAL_PACKAGE, final_bundle and QA artifacts
outputs: publication_pack artifact, PAPER_PACKAGE, REBUTTAL_PACKAGE readiness diagnostics, missing component list, source integrity blockers, review/rebuttal gate blockers
gates: required components must exist before ready_for_review is true; source_trace, citation_integrity, bib_doi_verification, required_section_groups, and source artifacts must pass before submission readiness; PRESUBMISSION_SEVERITY_GATE_PROFILE must have zero CRITICAL findings and a passing integrity_gate; REBUTTAL_READINESS_GATE_PROFILE must pass provenance gate, commitment gate, and coverage gate before response readiness
artifact_schemas: publication_pack, PAPER_PACKAGE, REBUTTAL_PACKAGE, SKELETON_SOURCE_INTEGRITY_PROFILE, PRESUBMISSION_SEVERITY_GATE_PROFILE, REBUTTAL_READINESS_GATE_PROFILE, ISSUE_BOARD, REVISION_PLAN, run_trace
estimated_runtime: 5-15 min
---

# Publication Pack

Use this skill when the user wants to turn an RH topic into a reviewable publication/output package rather than another free-form draft.

## Core stance

A publication pack is a **contract-first artifact**. It does not invent missing science, citations, figures, or reviewer responses. It inventories what RH already has, records what is missing, and creates a package that downstream writing, figure, slide, and response workflows can safely fill.

## RH research delivery protocol

Use RH as the evidence and state source of truth. The protocol has no external runtime dependency.
Treat `PAPER_PACKAGE` and `REBUTTAL_PACKAGE` as RH artifact
conventions assembled from recorded evidence, drafts, reviews, and provenance.
Do not package chat-only outputs as publication-ready deliverables.

## Required first move

1. Identify the topic (`topic_id` or topic name).
2. Inspect existing artifacts if needed (`orchestrator_status`, `orchestrator_artifacts`, or equivalent surface).
3. Call `publication_pack_generate(topic_id=<id>, record_artifact=true)` when the MCP primitive is available.
4. For local demo or CLI-only contexts, use `rh publication-pack generate --topic "<topic-name>" --record-artifact`.
5. If the primitive is unavailable, manually create the same payload shape described in `references/contract.md`, then record it with `orchestrator_record_artifact(..., artifact_type="publication_pack", stage="write")`.

## Components

Required:

- `manuscript_sections` — usually the latest `draft_pack`.
- `evidence_pack` — claims, evidence links, and source-paper support.

Optional but recommended before submission:

- `SKELETON_SOURCE_INTEGRITY_PROFILE` — required_section_groups, non-stub
  section bodies, source_trace, Claims-Evidence Matrix coverage, source
  artifacts, `citation_integrity`, `bib_doi_verification`, figure/table
  references, and dangling citations blockers.
- `citation_integrity` — public `consistency_check` output or final integrity report.
- `figure_plan` — contract-first figure plan before plotting.
- `figure-quality` — use Codex ImageGen or deterministic diagrams when figures are placeholders, blurry, or weak visual evidence.
- `data_availability` — repository/identifier/FAIR statement.
- `reviewer_response` — response-to-review or rebuttal draft.
- `slides_outline` — presentation/journal-club handoff.
- `final_bundle` — assembled TeX/PDF/export bundle.
- `process_summary` — provenance and execution summary.

## Workflow

1. **Inventory** — generate the publication pack and list present/missing components.
2. **Gate** — if required components are missing, stop and tell the user which RH stage to run next.
3. **QA** — run or request `SKELETON_SOURCE_INTEGRITY_PROFILE`, citation sanitization, integrity checks, adversarial review, and provenance review before submission-facing use.
4. **Fill gaps** — create missing optional artifacts only from recorded evidence.
5. **Finalize** — update or supersede the `publication_pack` artifact after filling gaps.

If the pack has figure/table quality blockers, trigger `figure-quality` before claiming visual readiness. A figure plan alone is not enough when the manuscript still contains placeholder `\fbox`/`minipage` diagrams or unreadable raster assets.

If source integrity blockers remain, do not mark `PAPER_PACKAGE` or
`publication_pack.ready_for_review` as true. Missing required_section_groups,
stale source artifacts, broken source_trace, unverified BibTeX/DOI metadata, or
dangling citations route back to writing, evidence repair, or paper verification
instead of packaging.

Before submission-facing packaging, require
`PRESUBMISSION_SEVERITY_GATE_PROFILE`. The profile must classify review findings
as `CRITICAL`, `MAJOR`, or `MINOR`; any `CRITICAL` count or failed
`integrity_gate` blocks `PAPER_PACKAGE` readiness even when the PDF compiles.

Before response packaging, require `REBUTTAL_READINESS_GATE_PROFILE` with
`ISSUE_BOARD`, response letter, `REVISION_PLAN`, response evidence, revision
deltas, and camera-ready replay metadata. The provenance gate, commitment gate,
and coverage gate must pass: factual response sentences need sources, promised
edits must appear in the revision plan with no orphan commitments, and every
reviewer concern must end answered, deferred intentionally, or needs user
input.

## Output style

Report:

- pack artifact ID;
- readiness (`ready_for_review` true/false);
- present components with artifact IDs;
- missing required components;
- missing optional components;
- next recommended RH primitive/skill calls.

Never present the pack as submission-ready merely because it exists. Submission-readiness requires the QA checks to pass.
