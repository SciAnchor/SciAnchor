# ResearchFlowBench AutoResearchBench Results v0

Verified: 2026-06-04.

These results summarize the local AutoResearchBench Phase B smoke work: first a
deterministic adapter/candidate-source run, then a small full RH + Codex-style
agent smoke. Official rows, generated task packs, local gold files, and
prediction artifacts remain outside commits.

## Inputs

Local evaluation evidence was written under:

```text
.research-harness/eval_runs/phase_b_real_paper_2026-06-04/autoresearchbench_smoke50/
```

The local data preflight passed for AutoResearchBench. The adapted smoke pack
contains 50 tasks with local-only gold, so release validation rejects it without
`--allow-local-gold` as expected; private judge validation passes with that
flag.

Follow-up full1000 evidence was written under:

```text
.research-harness/eval_runs/overnight_autoresearchbench_2026-06-04/
```

## Summary

| Runner | Kind | Tasks | Mean deep accuracy | Mean wide IoU | Mean wide precision | Mean wide recall | Blocked scores | Model execution | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| `stub_zero` | deterministic zero-floor baseline | 50 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | false | PASS |
| `autoresearchbench_candidate_bm25` | non-gold local pool DB BM25 | 50 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | false | PASS |

## Attribution

The failure attribution reports group all 50/50 failures under the same
real-data axes for both `stub_zero` and the local pool DB candidate BM25 run:

| RH axis | Failing tasks | Evidence state |
|---|---:|---|
| `deep_research.discovery_accuracy` | 50 | `real_data` |
| `literature.set_completion` | 50 | `real_data` |
| `retrieval.provenance_coverage` | 50 | `real_data` |

## Candidate Source Status

The `autoresearchbench_candidate_bm25` baseline now has a builder for separate
non-gold candidate sources. For this smoke, the builder read the local Research
Harness `papers` table and wrote a candidate root with:

| Source | Candidate records | Skipped records | Gold policy |
|---|---:|---:|---|
| local Research Harness pool DB | 2445 | 0 | `no_gold_labels` |

The resulting candidate BM25 score report has 50 scores, 0 blocked scores, and
per-task retrieval traces with ranked candidates. The non-regression gate
against `stub_zero` passed with zero deltas on all four AutoResearchBench public
metrics.

Passing the official plaintext benchmark root as the candidate data source is
still rejected: the runner requires a separate `candidate_manifest.json` /
candidate corpus root that declares no gold labels.

The official plaintext file was therefore not used as a retrieval corpus. This
keeps AutoResearchBench promotion separated from gold leakage: the adapter and
zero-floor scoring path are verified, and candidate BM25 can run against a real
non-gold candidate source. The current local pool DB source does not overlap the
smoke gold answers enough to improve metrics.

## Full1000 Phase B Candidate Sources

The overnight Phase B run built a local AutoResearchBench `full1000` pack
containing 600 Deep Research tasks and 400 Wide Research tasks. Gold files were
present only for local scoring. Candidate sources were built from non-gold paper
metadata and stored under:

```text
.research-harness/eval_runs/overnight_autoresearchbench_2026-06-04/
```

The official plaintext benchmark rows were not used as a retrieval corpus.

| Candidate source | Records | Records with arXiv ID | Candidate top-k | Mean deep accuracy | Mean wide IoU | Mean wide precision | Mean wide recall | Positive tasks | Gate vs zero |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| OpenAlex partial v2, builder-extracted arXiv IDs | 14,737 | 400 | 10 | 0.000000 | 0.000727 | 0.003450 | 0.000844 | 8 | PASS |
| OpenAlex partial300 v1, resumed to 300 visible tasks | 21,369 | 640 | 10 | 0.000000 | 0.000683 | 0.003833 | 0.000792 | 8 | PASS |
| Union v3 unique IDs: OpenAlex raw + RH pool DB + LitSearch corpus | 75,068 | 1,025 | 50 | 0.002000 | 0.000708 | 0.002901 | 0.000972 | 11 | PASS |

The union source improves Deep Research coverage and wide recall, while the
OpenAlex-only source remains cleaner for wide IoU and precision. A source-local
top-k sweep showed `k=10` dominates the default `k=20` for OpenAlex partial v2,
and `k=50` dominates the default `k=20` for the union source. Cross-source
comparison is a tradeoff rather than a strict dominance result.

The follow-on OpenAlex resume extended the metadata fetch from 197 completed
visible tasks / 14,737 records to 300 completed visible tasks / 21,369 records
without provider errors. This increased OpenAlex-only wide source coverage from
27 to 35 tasks and arXiv-bearing records from 400 to 640, but the larger corpus
introduced enough ranking noise that `k=10` slightly regressed wide IoU and
recall versus OpenAlex partial v2. A partial300 top-k sweep found `k=50` raises
wide recall to 0.000994, but wide IoU falls to 0.000489 and precision to
0.001044. The result reinforces that corpus growth alone is not sufficient
without better query/ranking.

The union v3 candidate source was rebuilt after the coverage diagnostic exposed
59 duplicate `paper_id` collisions in union v2. The builder now assigns stable
unique IDs to duplicate paper IDs so the BM25 index no longer overwrites earlier
records. The v3 correctness fix preserves the same positive-task count and
slightly changes wide precision/IoU.

A local coverage diagnostic, using gold only for aggregate analysis and emitting
no gold details, found that union v3 contains substantially more answer-title
coverage than OpenAlex-only, but most covered candidates still do not rank into
the scored candidate set:

| Candidate source | Deep covered tasks | Deep top-hit tasks | Wide covered tasks | Wide top-hit tasks | Covered but not top |
|---|---:|---:|---:|---:|---:|
| OpenAlex partial v2, k=10 | 0 | 0 | 27 | 15 | 12 |
| OpenAlex partial300 v1, k=10 | 0 | 0 | 35 | 17 | 18 |
| OpenAlex partial300 v1, k=50 | 0 | 0 | 35 | 22 | 13 |
| Union v3 unique IDs, k=50 | 30 | 2 | 76 | 44 | 60 |

The next bottleneck is therefore ranking/query formulation, not only corpus
size. A keyword/RRF query-fusion experiment over union v2 increased wide recall
slightly but regressed deep accuracy, wide IoU, and wide precision while adding
substantial runtime cost, so it was not promoted into the baseline runner.

A follow-on reranking diagnostic over the union v3 BM25 top-50 traces compared
`bm25_order`, `title_token_overlap`, `title_overlap_bm25_blend`, and
`arxiv_first_bm25` at selection sizes 1/5/10/20/50. The diagnostic emits only
aggregate metrics and no gold labels. Simple title-overlap reranking did not
recover Deep Research matches; `arxiv_first_bm25@10` reproduced the union v3
top-50 wide metrics with a smaller selected set but did not improve them. The
result supports keeping reranking work in diagnostics until a stronger
query-expansion or learned/semantic ranker candidate is available.

An additional source-retrieval diagnostic extended the same script to reload
the non-gold union v3 candidate corpus and run fresh query-variant RRF and
IDF-based query-reduction searches. These source-retrieval strategies are
reported separately from trace-only rerankers because they search the full
candidate source rather than only reordering the recorded BM25 top-50 traces.
They reused the existing AutoResearchBench public-query variant builder and the
shared local BM25 index, but still did not produce a promotion-worthy lift on
full1000:
`query_variant_rrf_field_blend@50` reached wide recall `0.000981` and wide
precision `0.003020`, but deep accuracy remained `0.000000` and wide IoU
`0.000706` stayed below `bm25_order@50` (`0.000708`). The IDF variants were
weaker (`idf_query_rrf_bm25@50` wide IoU `0.000595`, wide recall `0.000841`).
The local environment did not already include `torch`, `transformers`,
`sentence_transformers`, or `FlagEmbedding`, so learned reranking was left as a
separate optional experiment rather than added as a default dependency.

A follow-up diagnostic added two guardrails before further query experiments:
the rerank script now emits a candidate-source compatibility summary comparing
the score report's recorded `data_root`, trace baseline/schema versions, and
trace candidate IDs against the supplied candidate source; and it accepts a
`--strategy` filter and `--task-id` filter so expensive source-retrieval
experiments can be scoped instead of always rerunning every strategy over every
task. The diagnostic output also now separates broad `strategy_kind` from the
more precise
`strategy_dependency_kind`, so source-augmented trace rerankers are not confused
with pure trace-only rerankers or fresh source retrieval. The compatibility
check validates known trace schema fields, treats missing legacy trace metadata
as unknown rather than incompatible, and scopes trace checks to the selected
task subset. It passed on the union v3 score report/source pair used above.

An IDF-window variant was then tested as a cheaper no-model attempt to preserve
contiguous high-IDF clue spans from the visible question. On the existing
stratified100 task pack, using the union v3 full1000 score report and candidate
source, neither `idf_window_rrf_bm25` nor `idf_window_rrf_field_blend` produced
positive tasks at selection 10 or 50. `query_variant_rrf_field_blend@50` remained
the only source-retrieval query strategy with a positive stratified100 signal
(one wide positive task; wide IoU `0.000500`, wide precision `0.001667`, wide
recall `0.000667`). The IDF-window strategy was also slow enough on full1000
that it should remain a diagnostic-only branch and should not be promoted without
a stronger early-pruning design. A refreshed full1000 IDF-window run found only
two wide positive tasks and no Deep Research positives; `idf_window_rrf_bm25@50`
had wide IoU `0.000111`, precision `0.000174`, and recall `0.000278`, all below
`bm25_order@50`. The diagnostic now uses a per-run cache for exact repeated BM25
variant searches shared by plain and field-blended source-retrieval strategies,
but runtime should still be treated as exploratory rather than a runner-ready
cost profile: the refreshed full1000 keyword/IDF diagnostic took about 4:46
locally, and the full1000 IDF-window subset took about 5:05 locally.

## Full RH + Codex Agent Smoke

The previous candidate-source diagnostics tested only local BM25-style retrieval
and reranking. A follow-up implementation now exercises the intended full
workflow by splitting agent generation from judge scoring:

1. `run-external-agent` prepares a temporary gold-blind task workspace from
   `input.json` only, copies the non-gold candidate-source manifest/corpus into
   that workspace, and invokes Codex with strict JSON output.
2. `score-external-predictions` reads local `gold.json` only after the prediction
   file exists and scores the written predictions.

The guardrails are intentionally narrow: visible AutoResearchBench input rejects
answer/gold fields, candidate sources must pass the existing no-gold manifest
validation, duplicate prediction task IDs are rejected, task subsets can be
selected with repeated `--task-id`, and both agent and retrieval iterations are
capped at 5. Real smoke runs used `gpt-5.3-codex-spark` with
`--reasoning-effort low`; the global Codex default was `xhigh`, which made
single-task runs too slow for practical smoke testing.

Two full1000 Wide Research tasks produced local/private diagnostic evidence
that the full agent path records selected-sample behavior that differs from
model-free BM25. The committed repository does not publish task-level gold
counts, matched answer identifiers, per-task intersections, or selected-sample
score rows; those remain in local score artifacts only. This keeps the public
doc useful as a boundary note without exposing gold-derived evidence.

Deep Research tasks did not yet produce a reliable smoke signal. Task
`autoresearchbench.301` timed out at 300 seconds, and earlier deep attempts under
the default high-effort Codex configuration also ran too long. Deep tasks need a
different prompt/retrieval strategy or longer per-task timeout before they are
representative of the full agent workflow.

The run also corrected an enrichment mistake from the exploratory pass: arXiv
IDs are now extracted only from explicit arXiv fields or DOI/URL/paper IDs that
contain an `arxiv` marker. Broad numeric extraction from ordinary DOI strings
created false positives and is not used for reported v2 results.

## Interpretation

AutoResearchBench is currently useful as a real-data adapter, validation, and
candidate-source contract check. The full1000 Phase B run now provides local
model-free retrieval diagnostics from real non-gold candidate sources, and the
full-agent smoke records private selected-sample diagnostic differences. The
absolute model-free scores remain very small, and the agent evidence is still a
tiny selected sample. The next step is a broader low-effort wide-task agent
sweep plus a better deep-task prompt/retrieval design before treating
AutoResearchBench as strong promotion evidence.
