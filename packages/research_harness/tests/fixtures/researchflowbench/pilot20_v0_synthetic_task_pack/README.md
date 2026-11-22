# ResearchFlowBench Synthetic Pilot-20 v0

This RH-owned task pack is public-safe synthetic fixture data for ResearchFlowBench validator, scorer, and archive-ingestion development.

## Status

- Split: `draft_dev`
- Release readiness: `draft_not_release_grade`
- Model execution performed: `false`
- Third-party benchmark data vendored: `false`
- Gold policy: judge-only synthetic gold in `gold_bundle.json`

The pack does not make publication-grade benchmark claims. Changing release labels or public-readiness status requires human approval.

## Visibility

Agent-visible inputs are limited to each task's `prompt.md`, `input_bundle.json`, and `tool_fixtures/local_static_corpus.jsonl`. `gold_bundle.json` and `judge_bundle.json` are judge-only hidden files. Leakage canaries are present only in hidden bundles and are audited by the deterministic validators.

## Coverage

- Task count: `20` stable T01-T20 task IDs
- Expected RH axes: baseline_identification.coverage, citation.candidate_generation, deep_research.discovery_accuracy, evidence_linking.support_accuracy, final_bundle.pdf_quality, gap_detection.novelty_accuracy, governance.rollback_blocking, literature.set_completion, paper_reading.claim_quality, paper_search.recall, paper_search.rerank_quality, paper_selection.precision, retrieval.provenance_coverage, section_drafting.citation_grounding
