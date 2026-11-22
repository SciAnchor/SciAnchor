# ResearchFlowBench Post-search Pilot-5 Results v0

Verified: 2026-06-02.

These are local deterministic baselines promoted into public docs. They are not
leaderboard claims and they do not use paid model execution.

## Inputs

Task pack:

```text
.research-harness/rfb/postsearch_pilot5/pilot5_v0
```

Score reports summarized:

- `.research-harness/reports/postsearch_pilot5_stub_zero_score.json`
- `.research-harness/reports/postsearch_pilot5_deterministic_visible_score.json`
- `.research-harness/reports/postsearch_pilot5_contract_scan_score.json`
- `.research-harness/reports/postsearch_pilot5_evidence_link_record_replay_score.json`
- `.research-harness/reports/postsearch_pilot5_final_bundle_quality_scan_score.json`
- `.research-harness/reports/postsearch_pilot5_publication_pack_backfill_scan_score.json`

The scorer also supports externally generated prediction files through
`score-postsearch-predictions`. Those files are not part of this deterministic
baseline table unless a specific candidate model/agent replay is being reported.

## Summary

| Runner | Kind | Tasks | Model execution | Mean combined score | Notes |
|---|---:|---:|---:|---:|---|
| `stub_zero` | model-free postsearch stub | 5 | false | 0.00 | Floor baseline. |
| `deterministic_visible` | model-free postsearch stub | 5 | false | 0.80 | Visible-input deterministic baseline. |
| `postsearch_contract_scan` | deterministic postsearch contract scan | 5 | false | 1.00 on supported tasks | P01-P04 scored; P05 skipped by runner scope. |
| `evidence_link_record_replay` | real RH evidence-link record replay | 5 | false | 1.00 on supported task | P03 scored; P01/P02/P04/P05 skipped by runner scope. |
| `final_bundle_quality_scan` | real RH postsearch primitive | 5 | false | 0.50 on supported task | P01-P04 skipped by runner scope; P05 scored. |
| `publication_pack_backfill_scan` | real RH postsearch primitive | 5 | false | 1.00 on supported task | P01-P04 skipped by runner scope; P05 scored. |

## Per-task Scores

| Task | Axis | Stub-zero | Deterministic visible | Contract scan | Evidence-link replay | Final-bundle quality scan | Publication-pack backfill scan |
|---|---|---:|---:|---:|---:|---:|---:|
| P01 paper selection | `paper_selection.precision` | 0.00 | 0.75 | 1.00 | skipped | skipped | skipped |
| P02 claim extraction | `paper_reading.claim_quality` | 0.00 | 0.50 | 1.00 | skipped | skipped | skipped |
| P03 evidence linking | `evidence_linking.support_accuracy` | 0.00 | 0.75 | 1.00 | 1.00 | skipped | skipped |
| P04 section drafting | `section_drafting.citation_grounding` | 0.00 | 1.00 | 1.00 | skipped | skipped | skipped |
| P05 final bundle QA | `final_bundle.pdf_quality` | 0.00 | 1.00 | skipped | skipped | 0.50 | 1.00 |

## Interpretation

The result establishes a deterministic floor and a nonzero visible-input
baseline for the downstream post-search chain. `postsearch_contract_scan`
exercises the P01-P04 metric contracts with deterministic visible-input checks;
it is a plumbing and governance signal, not a semantic model-quality result.
`evidence_link_record_replay` calls the real RH `evidence_link` primitive for
P03, but its support labels are still derived from the visible synthetic spans,
so it proves record-path replay rather than semantic support classification. The
two final-bundle primitive replays cover only the final-bundle task, so they are
evidence for the PDF / publication-pack closure path rather than an end-to-end
post-search agent score.

Real candidate runs should write a
`researchflowbench.postsearch_predictions.v0.1` prediction file and then score it
offline with `score-postsearch-predictions`. This keeps model/agent execution
separate from local gold scoring while preserving blocked entries for any
missing P01-P05 predictions.
