# ResearchFlowBench Optimization Backlog v0

Date: 2026-06-02
Status: downstream-prioritized optimization backlog; evaluation evidence only.
Source score report: `/tmp/rh-rfb-downstream-2026-06-02/pilot20_deterministic_visible_score.json` generated with `.venv/bin/python -m research_harness.cli researchflowbench run-baseline`.
Benchmark: `researchflowbench.synthetic_public_pilot20_v0`
Baseline: `deterministic_visible`
Split: `draft_dev`

This backlog is derived from the model-free Pilot-20 visible-contract baseline.
The baseline validated 20 tasks, performed no model or network execution, and
emitted only deterministic visible object stubs. It proves archive wiring and
axis attribution, not semantic task quality:

| Metric | Value |
| --- | ---: |
| Tasks scored | 20 |
| Mean outcome score | 0.0 |
| Mean process score | 0.0 |
| Mean combined score | 0.0 |
| Mean expected object coverage | 0.164762 |

## Operator priority overlay

Operator feedback from real usage on 2026-06-02 says retrieval and paper
deep-reading are already performing reasonably well. For optimization planning,
use retrieval metrics as health checks and infrastructure dependencies, not as
the main quality target.

The practical downstream priority order is:

1. Claim extraction quality and evidence-link support accuracy.
2. Citation grounding, unsupported-citation blocking, and stale-evidence
   rollback before drafting.
3. Gap detection, baseline identification, proposal quality, and direction
   ranking.
4. Section drafting, final-bundle integrity, and self-evolution decisions based
   on evaluation results.

The Pilot-20 task axes were remapped on 2026-06-02 so downstream tasks now
attribute failures to claim, evidence, gap, baseline, drafting, final-bundle,
and governance axes instead of overloading `retrieval.provenance_coverage`.

Because `deterministic_visible` intentionally emits no semantic answers, every
failed task is treated as a capability gap only when the task explicitly
declares the corresponding `expected_rh_axes`. This makes the backlog
axis-bound rather than based on subjective final PDF inspection.

## Failure groups by RH axis

| RH axis | Failed tasks | Primary backlog category | Secondary categories |
| --- | ---: | --- | --- |
| `citation.candidate_generation` | 8 | citation integrity | evidence linking, section drafting, governance |
| `governance.rollback_blocking` | 8 | governance | citation integrity, section drafting, baseline freshness |
| `evidence_linking.support_accuracy` | 6 | evidence linking | claim extraction, citation integrity |
| `retrieval.provenance_coverage` | 5 | retrieval health check | governance, paper selection |
| `baseline_identification.coverage` | 4 | baseline identification | gap detection, proposal quality |
| `gap_detection.novelty_accuracy` | 4 | gap detection | baseline identification, proposal quality |
| `section_drafting.citation_grounding` | 4 | section drafting | evidence linking, citation integrity |
| `literature.set_completion` | 3 | retrieval health check | paper selection, gap detection |
| `paper_reading.claim_quality` | 3 | claim extraction | evidence linking, section drafting |
| `paper_search.recall` | 3 | retrieval health check | citation candidate generation |
| `paper_search.rerank_quality` | 2 | retrieval | orchestrator policy |
| `deep_research.discovery_accuracy` | 2 | retrieval | evidence linking |
| `final_bundle.pdf_quality` | 1 | PDF/final bundle | section drafting, citation integrity |
| `paper_selection.precision` | 1 | paper selection | literature mapping |

## Implementation progress

Progress recorded on 2026-06-03:

- `RFB-OPT-P0-001`: added a typed `EvidenceLink` contract with
  `support_status`, `evidence_span`, and `citation_candidate`; the
  `evidence_link` primitive schema and local backend accept the new fields
  while preserving legacy `claim_id/source_type/source_id/strength/notes`
  calls.
- `RFB-OPT-P0-001`: Post-search Pilot-5 P03 now records typed evidence-link
  replay output and scores `typed_contract_coverage` alongside support-label
  accuracy and span match.
- `RFB-OPT-P0-002`: write-stage gates now block active `evidence_links` or
  `evidence_pack` artifacts containing `support_status=unsupported` or
  `support_status=contradicts`.
- `RFB-OPT-P0-002`: failed citation checks now persist replayable
  `citation_verification`, `review_issue`, and `gate_decision` objects for
  unsupported/contradictory evidence links, hallucinated citations, and
  cross-topic citation references; Post-search Pilot-5 P03 now scores
  `citation_governance_replay_coverage`. A deterministic local PDF demo was
  generated at `.tmp/rfb-opt-p0-002-demo/rfb-opt-p0-002-citation-governance.pdf`.

## Prioritized backlog

### P0

1. **RFB-OPT-P0-001 - Preserve evidence links from claim to citation to span**
   - RH axes: `paper_reading.claim_quality`, `evidence_linking.support_accuracy`, `citation.candidate_generation`
   - Category: evidence linking
   - Failed tasks: T01, T03, T04, T11, T13, T17
   - Finding: Downstream tasks require scoped `claim`, exact `evidence_span`, and support-aware `citation_link` objects.
   - Optimization target: add a typed evidence-link contract that records claim scope, supporting span, contradiction or partial-support status, and the citation candidate that justifies the link.
   - Gate: replay on current `draft_dev` tasks first; do not promote without held-out or promotion-test examples.

2. **RFB-OPT-P0-002 - Block hallucinated or unsupported citations before drafting**
   - RH axes: `citation.candidate_generation`, `section_drafting.citation_grounding`, `governance.rollback_blocking`
   - Category: citation integrity
   - Failed tasks: T01, T02, T04, T09, T12, T13, T18, T19, T20
   - Finding: Citation-heavy tasks require identifier validation, support status, cross-topic guards, and block/rollback evidence before unsupported claims reach drafts.
   - Optimization target: make citation verification statuses first-class replay objects and require failed citation checks to create `review_issue` and `gate_decision` records.
   - Gate: citation changes must keep gold/judge bundles hidden and must not add external search to the v0 synthetic pack.

3. **RFB-OPT-P0-003 - Calibrate gap, baseline, and direction quality**
   - RH axes: `gap_detection.novelty_accuracy`, `baseline_identification.coverage`, `proposal.direction_quality`
   - Category: gap/baseline/proposal quality
   - Failed tasks: T05, T10, T15, T19
   - Finding: Real usage shows the weaker part is not finding papers but deciding whether prior work already closes the claimed gap and whether a proposed direction remains defensible.
   - Optimization target: score baseline family coverage, stale-baseline invalidation, false-novelty detection, and direction ranking from explicit evidence.
   - Gate: do not tune proposal prompts from retrieval-only scores; require downstream score reports first.

### P1

4. **RFB-OPT-P1-004 - Add section-draft safeguards for stale or overreaching evidence**
   - RH axes: `section_drafting.citation_grounding`, `evidence_linking.support_accuracy`, `governance.rollback_blocking`
   - Category: section drafting
   - Failed tasks: T01, T04, T13, T20
   - Finding: Section-producing tasks expect the system to avoid stale propagation, claim scope overreach, and final citation drift before bundle assembly.
   - Optimization target: make `section_draft` output carry evidence-link IDs, citation verification state, and rollback/block decisions when support is partial or stale.

5. **RFB-OPT-P1-005 - Add final-bundle citation integrity replay checks**
   - RH axes: `final_bundle.pdf_quality`, `section_drafting.citation_grounding`, `citation.candidate_generation`
   - Category: PDF/final bundle
   - Failed tasks: T20
   - Finding: Pilot-20 now distinguishes final-bundle failures from upstream citation and section-drafting failures.
   - Optimization target: add a final-bundle replay check that verifies every final citation resolves to a visible evidence link and no stale or hallucinated identifiers survive export.
   - Gate: do not change public dataset readiness or release labels without human approval.

6. **RFB-OPT-P1-006 - Turn gate, rollback, and abstention behavior into policy evidence**
   - RH axes: `governance.rollback_blocking`
   - Category: orchestrator policy
   - Failed tasks: T02, T04, T05, T09, T12, T18, T19, T20
   - Finding: Several failures require the correct behavior to abstain, block, rollback, or mark cross-topic provenance invalid, not simply produce an answer.
   - Optimization target: ensure orchestrator gates emit `gate_decision`, `rollback_event`, `review_issue`, and `artifact_ref` objects with reason codes tied to RH axes.

7. **RFB-OPT-P1-007 - Keep retrieval and provenance as downstream health checks**
   - RH axes: `paper_search.recall`, `paper_search.rerank_quality`, `retrieval.provenance_coverage`, `literature.set_completion`, `paper_selection.precision`, `deep_research.discovery_accuracy`
   - Category: retrieval health check
   - Failed tasks: T06, T07, T08, T12, T14, T16, T18
   - Finding: Retrieval and deep-reading remain important dependencies, but operator feedback says they are not the main quality bottleneck.
   - Optimization target: monitor these axes for regressions while prioritizing downstream semantic quality.

### P2

8. **RFB-OPT-P2-008 - Separate infrastructure floor failures from semantic model failures**
   - RH axes: all Pilot-20 axes
   - Category: orchestrator policy
   - Failed tasks: T01-T20
   - Finding: The current baseline is a deliberate visible-contract floor, so it proves archive wiring and axis attribution but not model behavior.
   - Optimization target: keep `stub_zero` as the reproducible floor and add a deterministic visible-contract baseline plus later human-approved model baselines for comparison.

9. **RFB-OPT-P2-009 - Add archive queries for axis and category regressions**
   - RH axes: all Pilot-20 axes
   - Category: orchestrator policy
   - Failed tasks: T01-T20
   - Finding: Score reports can be archived, but operators still need a direct way to ask which RH axis and optimization category regressed across replay runs.
   - Optimization target: expose an archive summary that groups `researchflowbench_score_report` records by benchmark, split, RH axis, backlog category, task, and candidate id.

## Task-to-category map

| Task | RH axes | Backlog categories |
| --- | --- | --- |
| T01 | `citation.candidate_generation`, `evidence_linking.support_accuracy`, `section_drafting.citation_grounding` | evidence linking, citation integrity, section drafting |
| T02 | `paper_search.recall`, `citation.candidate_generation`, `governance.rollback_blocking` | retrieval health check, citation integrity, governance |
| T03 | `paper_reading.claim_quality`, `evidence_linking.support_accuracy`, `citation.candidate_generation` | claim extraction, evidence linking, citation integrity |
| T04 | `evidence_linking.support_accuracy`, `section_drafting.citation_grounding`, `governance.rollback_blocking` | evidence linking, section drafting, governance |
| T05 | `gap_detection.novelty_accuracy`, `baseline_identification.coverage`, `governance.rollback_blocking` | gap detection, baseline identification, governance |
| T06 | `paper_search.recall`, `literature.set_completion` | retrieval |
| T07 | `paper_search.rerank_quality`, `retrieval.provenance_coverage` | retrieval, orchestrator policy |
| T08 | `literature.set_completion`, `paper_selection.precision`, `retrieval.provenance_coverage` | retrieval health check, paper selection |
| T09 | `citation.candidate_generation`, `governance.rollback_blocking` | citation integrity, governance |
| T10 | `baseline_identification.coverage`, `gap_detection.novelty_accuracy`, `deep_research.discovery_accuracy` | baseline identification, gap detection, retrieval health check |
| T11 | `paper_reading.claim_quality`, `evidence_linking.support_accuracy`, `citation.candidate_generation` | claim extraction, evidence linking, citation integrity |
| T12 | `retrieval.provenance_coverage`, `citation.candidate_generation`, `governance.rollback_blocking` | retrieval health check, citation integrity, governance |
| T13 | `paper_reading.claim_quality`, `evidence_linking.support_accuracy`, `section_drafting.citation_grounding` | claim extraction, evidence linking, section drafting |
| T14 | `paper_search.rerank_quality`, `retrieval.provenance_coverage` | retrieval, orchestrator policy |
| T15 | `gap_detection.novelty_accuracy`, `baseline_identification.coverage`, `literature.set_completion` | gap detection, baseline identification, retrieval health check |
| T16 | `deep_research.discovery_accuracy`, `paper_search.recall` | retrieval, evidence linking |
| T17 | `evidence_linking.support_accuracy`, `citation.candidate_generation` | evidence linking, citation integrity |
| T18 | `retrieval.provenance_coverage`, `governance.rollback_blocking` | retrieval health check, governance |
| T19 | `baseline_identification.coverage`, `gap_detection.novelty_accuracy`, `governance.rollback_blocking` | baseline identification, gap detection, governance |
| T20 | `section_drafting.citation_grounding`, `final_bundle.pdf_quality`, `citation.candidate_generation`, `governance.rollback_blocking` | citation integrity, section drafting, PDF/final bundle, governance |

Machine-readable companion: `docs/researchflowbench-optimization-backlog-v0.json`.
