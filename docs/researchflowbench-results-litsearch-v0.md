# ResearchFlowBench LitSearch Results v0

Verified: 2026-06-01.

These results summarize local deterministic LitSearch runs. They use local data
and do not execute paid model/API jobs.

## Inputs

Score reports summarized:

- `.research-harness/eval_runs/rfb_optimization_round1/litsearch_full597_bm25_score_report.json`
- `.research-harness/eval_runs/rfb_optimization_round1/litsearch_full597_paper_search_local_bm25_score_report.json`
- `.research-harness/eval_runs/rfb_optimization_round2/litsearch_full597_paper_search_local_bm25_title5_score_report.json`

All three reports have `benchmark_id=litsearch`, `task_count=597`, and
`model_execution_performed=false`.

## Summary

| Runner | Kind | Tasks | Mean retrieval recall | Mean rerank quality | Hit@k rate |
|---|---|---:|---:|---:|---:|
| `bm25_retrieval` | model-free BM25 baseline | 597 | 0.5674 | 0.3338 | 0.5812 |
| `paper_search_local_bm25` | RH primitive replay | 597 | 0.5792 | 0.3564 | 0.5913 |
| `paper_search_local_bm25_title5` | RH primitive replay | 597 | 0.5842 | 0.3576 | 0.5963 |

## Phase B Smoke 2026-06-04

Before moving from Stage A mechanism hardening into real-paper evaluation, the
local LitSearch stratified50 pack was replayed as a minimal Phase B smoke.
Official LitSearch data was present under the local benchmark root and passed
`local-data-check`. The task pack contains local-only `gold.json` files, so
release validation fails as expected without `--allow-local-gold`; private
judge validation passes with that flag.

| Runner | Kind | Tasks | Mean retrieval recall | Mean rerank quality | Hit@k rate | Status |
|---|---|---:|---:|---:|---:|---|
| `lexical_retrieval` | deterministic external baseline | 50 | 0.000000 | 0.000000 | 0.000000 | PASS |
| `paper_search_local_bm25` | RH primitive replay | 50 | 0.576667 | 0.288110 | 0.620000 | PASS |

The non-regression gate comparing `paper_search_local_bm25` against
`lexical_retrieval` passed with positive deltas on all required metrics:

| Metric | Delta |
|---|---:|
| `mean_retrieval_recall` | `+0.576667` |
| `mean_rerank_quality` | `+0.288110` |
| `mean_hit_at_k` | `+0.620000` |

The candidate attribution report groups the remaining 19/50 misses under
`paper_search.recall`, `paper_search.rerank_quality`, and
`citation.candidate_generation`, with `evidence_state=real_data` and
`model_execution_performed=false`. These outputs are local evaluation evidence;
the official data rows, adapted task pack, and local gold files remain outside
commits.

## Phase B Full597 Replay 2026-06-04

The same current-code replay was then run on the local LitSearch full597
promotion pack. The local official data preflight passed, and private judge
validation passed with `--allow-local-gold`.

| Runner | Kind | Tasks | Mean retrieval recall | Mean rerank quality | Hit@k rate | Status |
|---|---|---:|---:|---:|---:|---|
| `bm25_retrieval` | model-free BM25 baseline | 597 | 0.567448 | 0.333785 | 0.581240 | PASS |
| `paper_search_local_bm25` | RH primitive replay | 597 | 0.595087 | 0.367662 | 0.608040 | PASS |

The non-regression gate comparing `paper_search_local_bm25` against
`bm25_retrieval` passed:

| Metric | Delta |
|---|---:|
| `mean_retrieval_recall` | `+0.027639` |
| `mean_rerank_quality` | `+0.033877` |
| `mean_hit_at_k` | `+0.026800` |

The attribution report groups the remaining 234/597 misses under
`paper_search.recall`, `paper_search.rerank_quality`, and
`citation.candidate_generation`, with `evidence_state=real_data`,
`blocked_score_count=0`, and `model_execution_performed=false`.

## Interpretation

The RH primitive replay is slightly above the standalone BM25 baseline on recall,
rerank quality, and Hit@k for this local LitSearch pack. These numbers are
baseline evidence for retrieval behavior, not a claim about full research-agent
quality.
