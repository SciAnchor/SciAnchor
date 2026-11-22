---
name: provenance-review
description: Review Research Harness execution history, recorded artifacts, and process quality. Trigger on phrases like "provenance-review", "/provenance-review", "溯源审查", "回顾执行历史", or equivalent requests to inspect what was done, what was recorded, and what is missing.
public_suite: review
task_type: audit
data_access_level: local
inputs: topic_id, provenance window, artifacts, stage history, delivery protocol artifacts, SKELETON_SOURCE_INTEGRITY_PROFILE, PRESUBMISSION_SEVERITY_GATE_PROFILE, REBUTTAL_READINESS_GATE_PROFILE
outputs: process audit, missing records, stale artifacts, protocol artifact risk list, source integrity risk list, review/rebuttal provenance blockers
gates: separate recorded facts from inference; flag unrecorded outputs, unrecorded protocol deliverables, broken source_trace, stale source artifacts, citation_integrity gaps, bib_doi_verification gaps, dangling citations, failed integrity_gate, CRITICAL presubmission findings, missing ISSUE_BOARD, missing REVISION_PLAN, and failed provenance gate, commitment gate, or coverage gate
artifact_schemas: provenance_review_report, RESEARCH_BRIEF, EXPERIMENT_PLAN, PAPER_PLAN, SKELETON_SOURCE_INTEGRITY_PROFILE, PRESUBMISSION_SEVERITY_GATE_PROFILE, PAPER_PACKAGE, REBUTTAL_PACKAGE, REBUTTAL_READINESS_GATE_PROFILE, ISSUE_BOARD, REVISION_PLAN
estimated_runtime: 5-20 min
---

# Provenance Review

Use this skill for audit-style review of Research Harness work.

## RH research delivery protocol

Use RH as the evidence and state source of truth. The protocol has no external runtime dependency.
For the research delivery protocol, verify that brief, proposal,
experiment, review, paper, audit, and rebuttal deliverables were recorded as RH
artifacts, linked to the correct topic/stage, and backed by provenance. Treat
chat-only deliverables as missing until recorded as RH artifacts.

For paper-package review, require `SKELETON_SOURCE_INTEGRITY_PROFILE` evidence.
The review must check that required_section_groups are present, `source_trace`
links every manuscript claim to the Claims-Evidence Matrix and source
artifacts, `citation_integrity` has no dangling citations, and
`bib_doi_verification` records verified BibTeX/DOI or primary metadata state.
Treat a package without this profile as provenance-risky even when prose exists.

For presubmission review, require `PRESUBMISSION_SEVERITY_GATE_PROFILE`. Verify
that `CRITICAL`, `MAJOR`, and `MINOR` findings were assigned by the declared
taxonomy, that `integrity_gate` passed, and that any CRITICAL count is treated
as a submission blocker.

For rebuttal review, require `REBUTTAL_READINESS_GATE_PROFILE` before response
readiness claims. Confirm `ISSUE_BOARD`, response letter, `REVISION_PLAN`,
response evidence, and revision deltas are recorded. The provenance gate must
source factual response sentences, the commitment gate must prevent orphan
promised edits, and the coverage gate must resolve every reviewer concern as
answered, deferred intentionally, or needs user input.

## Workflow

1. Identify the project, topic, or time window under review.
2. Inspect recorded artifacts and execution history when available.
3. Check whether important outputs were ingested, recorded, and linked.
4. Check skeleton/source/citation integrity evidence before submission-facing claims.
5. Report missing provenance, weak spots, and recommended cleanup actions.
