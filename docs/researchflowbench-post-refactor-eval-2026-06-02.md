# ResearchFlowBench Post-refactor Eval 2026-06-02

Verified: 2026-06-02 on `main`.

This report summarizes local post-refactor smoke and regression checks after the
workflow package split stabilization. Generated task packs, local gold, and
third-party benchmark data remain local-only under:

```text
.research-harness/eval_runs/post_refactor_2026-06-02/
```

## Scope

The run covered three evaluation surfaces:

- RH-owned synthetic benchmarks: Pilot-20 and Post-search Pilot-5.
- Public benchmark smoke checks: LitSearch stratified50 and AutoResearchBench
  smoke50.
- Public benchmark promotion check: LitSearch full597.
- Evaluation-driven self-optimization readiness: score attribution, retrieval
  non-regression gate, and release-readiness checks.
- Offline candidate replay scoring: external post-search prediction files can be
  scored against local gold without executing models inside the scorer.
- Downstream system-test addendum: claim extraction, evidence mapping, gap
  verification, section drafting, citation governance, publication pack,
  orchestrator rollback, and project self-evolution contracts.

All runs were deterministic and model-free. No paid model/API execution was
performed.

## Summary

| Surface | Runner | Tasks | Key metrics | Status |
|---|---|---:|---|---|
| Post-search Pilot-5 | `deterministic_visible` | 5 | mean combined `0.80` | PASS |
| Post-search Pilot-5 | `postsearch_contract_scan` | 5 | supported mean combined `1.00`; all-task mean combined `0.80` | PASS |
| Post-search Pilot-5 | `evidence_link_record_replay` | 5 | supported mean combined `1.00`; all-task mean combined `0.20` | PASS |
| Post-search Pilot-5 | `final_bundle_quality_scan` | 5 | mean combined `0.10` | PASS |
| Post-search Pilot-5 | `publication_pack_backfill_scan` | 5 | mean combined `0.20` | PASS |
| LitSearch smoke50 | `bm25_retrieval` | 50 | recall `0.536667`, rerank `0.24942`, hit@k `0.58` | PASS |
| LitSearch smoke50 | `paper_search_local_bm25` | 50 | recall `0.576667`, rerank `0.28811`, hit@k `0.62` | PASS |
| LitSearch full597 | `bm25_retrieval` | 597 | recall `0.567448`, rerank `0.333785`, hit@k `0.58124` | PASS |
| LitSearch full597 | `paper_search_local_bm25` | 597 | recall `0.595087`, rerank `0.367662`, hit@k `0.60804` | PASS |
| AutoResearchBench smoke50 | `stub_zero` | 50 | deep/wide metrics `0.0` | PASS |
| Pilot-20 | `stub_zero` | 20 | mean combined `0.0`, object coverage `0.0` | PASS |
| Pilot-20 | `deterministic_visible` | 20 | mean combined `0.0`, object coverage `0.164762` | PASS |

The LitSearch non-regression gate passed with positive deltas for the RH
primitive replay on smoke50:

| Metric | Delta |
|---|---:|
| `mean_retrieval_recall` | `+0.04` |
| `mean_rerank_quality` | `+0.03869` |
| `mean_hit_at_k` | `+0.04` |

The LitSearch full597 promotion gate also passed:

| Metric | Delta |
|---|---:|
| `mean_retrieval_recall` | `+0.027639` |
| `mean_rerank_quality` | `+0.033877` |
| `mean_hit_at_k` | `+0.0268` |

Pilot-20 release-readiness also passed: 6 checks, 0 failed checks.

## Self-optimization Applied

The full597 replay now emits per-task
`researchflowbench.external_retrieval_trace.v0.1` records. Each trace preserves
the visible query, `paper_search` call mode, retrieval backend, providers,
ranked candidate ids, candidate source, and rank. This directly addresses the
retrieval health-check backlog item for external primitive replay evidence
without changing scoring, prompts, model behavior, or benchmark gold.

## Attribution

Both Pilot-20 floor and visible-contract baselines still fail the semantic
outcome axes. The visible-contract baseline only confirms that the harness can
emit expected object stubs; it does not satisfy outcome or process scoring.

| RH axis | Failing tasks |
|---|---:|
| `citation.candidate_generation` | 8 |
| `governance.rollback_blocking` | 8 |
| `evidence_linking.support_accuracy` | 6 |
| `retrieval.provenance_coverage` | 5 |
| `baseline_identification.coverage` | 4 |
| `gap_detection.novelty_accuracy` | 4 |
| `section_drafting.citation_grounding` | 4 |
| `literature.set_completion` | 3 |
| `paper_reading.claim_quality` | 3 |
| `paper_search.recall` | 3 |
| `paper_search.rerank_quality` | 2 |
| `deep_research.discovery_accuracy` | 2 |
| `final_bundle.pdf_quality` | 1 |
| `paper_selection.precision` | 1 |

The Pilot-20 task axes now distinguish downstream quality from retrieval health
checks. The attribution report also preserves the operator-provided evidence
state in axis summaries. For this run, Pilot-20 axis summaries consistently
report `synthetic_public`.

## Downstream System Test Addendum

Additional local system tests were run after the architecture refactor to focus
on the downstream capabilities that remain weaker in operator use. Retrieval and
deep-reading are treated as health checks here, not as the primary optimization
target.

| Surface | Tests | Result |
|---|---:|---|
| Backend stability pre-merge e2e chains | 3 | PASS |
| Semantic governance rollback/contract/trace/B5 normalization | 14 | PASS |
| Orchestrator, publication pack, writing, section loop, adversarial review | 216 | PASS |
| Claim, evidence map, gap, direction ranking, review readiness, citation sanitizer | 164 | PASS |
| ResearchFlowBench adapter, contract, validation, output guardrails, release readiness | 103 | PASS |

Interpretation of this addendum is deliberately conservative:

- The refactor did not break deterministic contracts for downstream orchestration
  and governance.
- The current tests prove wiring, rollback, citation blocking, and output-shape
  expectations; they do not prove open-ended model quality on real downstream
  research tasks.
- The next benchmark work should therefore measure claim quality, evidence-link
  support accuracy, gap/baseline/proposal quality, citation grounding, final
  bundle integrity, and self-evolution decisions before tuning prompts or model
  routing.

## Interpretation

The architecture refactor is stable enough to resume benchmark-driven work:
Post-search checks pass, Pilot-20 can be rebuilt and release-checked, and
LitSearch retrieval replay is non-regressive versus the local BM25 baseline on
both smoke50 and full597 promotion checks. Operator experience indicates that
retrieval and paper deep-reading are already comparatively strong, so these
retrieval checks should remain health checks rather than the main optimization
axis.

The added `postsearch_contract_scan` runner now separates P01-P04 downstream
contract coverage from P05 final-bundle replay. It proves deterministic metric
plumbing for paper selection, claim extraction, evidence linking, and citation
grounding, but it remains synthetic and should not be treated as real semantic
model quality.

The added `evidence_link_record_replay` runner now exercises the real RH
`evidence_link` non-LLM primitive on P03. Its support labels still come from a
deterministic visible-span scan, so it proves claim-to-span link recording and
reporting rather than semantic support classification.

The added `score-postsearch-predictions` entry point is the bridge from these
synthetic contract checks to real candidate model/agent replay. A runner writes
a `researchflowbench.postsearch_predictions.v0.1` file, then the scorer compares
P01-P05 predictions to local gold and marks missing tasks as blocked. This keeps
candidate execution separate from gold scoring and makes downstream optimization
auditable.

The next optimization target should be the downstream portion of the P0/P1
backlog in `docs/researchflowbench-optimization-backlog-v0.md`: preserve
evidence links, block hallucinated or unsupported citations before drafting,
add section-draft safeguards, make rollback/blocking policy evidence explicit,
and evaluate final-bundle/self-evolution behavior.

AutoResearchBench is currently useful as an adapter and zero-floor smoke check,
and it now has a deterministic candidate-source BM25 baseline contract. The
official local plaintext file contains answers, so using those answers as a
retrieval corpus would leak gold and is rejected. Promotion beyond zero-floor
smoke still requires a real non-gold candidate source, not a synthetic fixture.

## Verification

Focused regression checks:

```text
.venv/bin/pytest packages/research_harness/tests/test_researchflowbench_external_benchmarks.py -q
41 passed

.venv/bin/pytest packages/research_harness/tests/test_researchflowbench_external_benchmarks.py \
  packages/research_harness/tests/test_researchflowbench_contract.py \
  packages/research_harness/tests/test_researchflowbench_task_pack_validation.py \
  packages/research_harness/tests/test_researchflowbench_output_shape_guardrails.py \
  packages/research_harness/tests/test_researchflowbench_release_readiness.py \
  packages/research_harness/tests/test_researchflowbench_preflight_leakage_retrieval_cost.py \
  packages/research_harness/tests/test_researchflowbench_builder.py \
  packages/research_harness/tests/test_researchflowbench_er01_execution_repro.py \
  packages/research_harness/tests/test_researchflowbench_diagnostic_runner_debug.py -q
111 passed

scripts/codex-check.sh --full
1901 passed, 14 skipped, 5 warnings
```

The attribution fix was replayed against the local Pilot-20 score reports, and
the LitSearch full597 primitive replay was regenerated with retrieval traces
before writing this summary.
