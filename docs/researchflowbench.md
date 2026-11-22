# ResearchFlowBench

ResearchFlowBench is the Research Harness evaluation surface for checking
whether research agents preserve provenance, keep hidden gold isolated, and
produce reproducible research-workflow artifacts.

The current implementation focuses on a public-safe synthetic Pilot-20 pack and
an external benchmark registry. It is intentionally model-free: building the
pack writes static fixture files and runs deterministic validators, but does not
run an LLM experiment.

## Boundary With Academic Research Eval

ResearchFlowBench is RH-owned runtime and regression evidence. Private/local
benchmark and performance runs are regression governance only. They do not
authorize public benchmark, leaderboard, ranking, release-grade, or public
performance claims. It is not the neutral public leaderboard surface for
open-source research libraries.

Use this split:

| Work item | Owner |
| --- | --- |
| RH primitive runners, RH + Codex/agent workspaces, temporary RH databases, provenance checks, self-evolution archive inputs, and RH-axis attribution | Research Harness |
| Public open-source-library registry, public result snapshots, neutral replay disclosure, offline scorer contract, and cross-library leaderboard pages | Academic Research Eval |
| Export/import bridges that convert RH task packs or score reports into a neutral ARE contract without running RH | ARE adapter, with RH as source format |

The allowed exchange format is file-based:

```text
task pack -> predictions.json -> score_report.json -> gate_report.json
```

Do not make ARE depend on RH runtime state such as `.research-harness/`, SQLite
databases, MCP sessions, provenance records, or local-only benchmark gold. Do
not move RH runners into ARE unless the move preserves the clean boundary
between external benchmark adapters and RH runtime internals and passes review.

If a benchmark artifact is intended for public cross-library ranking, publish it
through ARE. If it is intended to improve or regress-test RH behavior, keep it
in ResearchFlowBench and treat it as RH-owned evidence.

## Dataset contract v0

ResearchFlowBench v0 uses an explicit dataset contract so RH-owned task packs,
local external adapters, score reports, and self-evolution archive records all
carry the same minimum metadata. The machine-readable contract is exposed from
`research_harness.eval.researchflowbench.dataset_contract_v0_payload`.

### Task schema

Every v0 task must include:

| Field | Meaning |
| --- | --- |
| `schema_version` | Task envelope version, currently `researchflowbench.task.v0` for RH-owned task metadata and `researchflowbench.external_task.v0.1` for adapter-visible task inputs. |
| `benchmark_id` | Stable benchmark or dataset identifier, for example `researchflowbench.synthetic_public_pilot20_v0`, `litsearch`, or `autoresearchbench`. |
| `task_id` | Stable task identifier unique within the benchmark. |
| `split` | One of the v0 split names below. |
| `input` | Agent-visible input references or payload. Hidden gold must not appear here. |
| `expected_rh_axes` | RH capability axes the task is intended to measure. |
| `artifact_policy` | Visibility and storage rules for generated artifacts, gold, and judge files. |
| `license` | Dataset license and redistribution metadata. |
| `leakage_policy` | Gold-blind and judge-only constraints applied before execution. |
| `archive_linkage` | Minimum benchmark/task/split/axis metadata needed by candidate archive and champion registry flows. |

### Score schema

The canonical score artifact type is `researchflowbench_score_report`. A v0
score report must include:

| Field | Meaning |
| --- | --- |
| `schema_version` | Score report version, currently `researchflowbench_score_report.v0`. |
| `benchmark_id` | Benchmark identifier matching the task pack or external adapter. |
| `split` | Split scored by this report. |
| `scores` | Per-task score records. Each record must include `task_id`, `split`, `metrics`, and `rh_axis_ids`; legacy adapter score records may be normalized during archive ingestion. |
| `metrics` | Report-level metric names and aggregates when available. |
| `rh_axis_ids` | Union of RH axes measured by the report. |
| `artifact_refs` | Source artifact references or local pack references used to produce the report. |
| `model_execution_performed` | `false` for model-free builders, dry-runs, and stub baselines. |

Score reports are evidence, not code changes. They can feed
`candidate_archive_pack` and `champion_registry_pack`, but they must not trigger
automatic mutation.

### External predictions schema

Gold-blind external agents write `predictions.json` before any scorer reads
judge-only gold. The current file contract is
`researchflowbench.external_predictions.v0.1`.

Top-level fields:

| Field | Contract |
| --- | --- |
| `schema_version` | Required; must be `researchflowbench.external_predictions.v0.1`. |
| `benchmark_id` | Required non-empty string; must match the task pack benchmark when scored. |
| `runner_id` | Required non-empty string identifying the generator. |
| `model_execution_performed` | Required boolean; `false` for fake replay and deterministic fixtures. |
| `execution_limits` | Optional object; declared max iteration caps must not exceed scoring caps. |
| `predictions` | Required list of per-task prediction entries. |
| `artifact_refs` | Optional source references such as task pack or replay files. |
| `metadata` | Optional runner metadata; may include workspace, strict-JSON, and task-count fields. |

Each `predictions[]` entry must include a unique non-empty `task_id`.
AutoResearchBench entries are scored from:

```json
{
  "task_id": "autoresearchbench.example",
  "prediction": {
    "predicted_titles": ["Paper title"],
    "predicted_arxiv_ids": ["2401.00001"]
  },
  "runner_output": {
    "iterations_used": 1,
    "retrieval_iterations_used": 1
  }
}
```

Malformed top-level files are rejected before scoring. Missing selected tasks
remain score rows with `evidence_state=blocked_missing_prediction`; invalid
per-task prediction payloads remain score rows with
`evidence_state=blocked_invalid_prediction`. This keeps file-contract failures
separate from ordinary agent-generation failures.

### Model-free baseline scoring

Build or point at a local RH-owned Pilot-20 task pack, then run the model-free
baseline scorer:

```bash
rh researchflowbench run-baseline \
  --task-pack packages/research_harness/tests/fixtures/researchflowbench/pilot20_v0_synthetic_task_pack \
  --out /tmp/researchflowbench-score-report.json
```

The command validates the task pack before scoring, performs no model calls, uses
no network access, and writes a `researchflowbench_score_report.v0` JSON file.
The default `stub_zero` baseline intentionally emits no semantic answer objects,
so its score report is useful as a reproducible floor for archive wiring and RH
axis attribution.

The first measured optimization backlog from this floor is stored in
`researchflowbench-optimization-backlog-v0.md`, with a machine-readable
companion at `researchflowbench-optimization-backlog-v0.json`. It groups
failures by RH axis and by optimization surface: retrieval, evidence linking,
citation integrity, section drafting, PDF/final bundle, and orchestrator policy.

Record that report through the self-evolution evidence path:

```bash
rh self-evolution record-rfb-score-report \
  --topic <topic-name> \
  --score-file /tmp/researchflowbench-score-report.json

rh self-evolution archive-from-artifacts --topic <topic-name>
```

`archive-from-artifacts` records `candidate_archive_pack` and
`champion_registry_pack` payloads only. It does not mutate skills, prompts, code,
benchmark definitions, or release labels.

### External primitive replay and score gates

External adapters can be replayed through real RH primitives when the official
benchmark data is available locally. For LitSearch, `paper_search_local_bm25`
imports the local corpus into a temporary RH paper pool and scores the real
`paper_search(local_only=True)` primitive. It performs no external provider
fan-out and no model calls.

Each LitSearch primitive score includes both aggregate retrieval metrics and a
per-task `retrieval_trace` with query, tool call, backend, providers, ranked
candidate ids, candidate source, and rank. This trace is optimization evidence
for `retrieval.provenance_coverage`; it must remain derived from visible query
inputs plus the local official corpus, not from hidden gold files.

```bash
rh researchflowbench run-external-primitive \
  --task-pack .research-harness/eval_runs/rfb_coverage_v1/litsearch_stratified50 \
  --data .research-harness/benchmarks/litsearch \
  --runner paper_search_local_bm25 \
  --evidence-state real_data \
  --out /tmp/litsearch-paper-search-score.json
```

Candidate score reports should be compared against the prior baseline before
they feed optimization decisions:

```bash
rh researchflowbench compare-score-reports \
  --baseline-file /tmp/litsearch-bm25-score.json \
  --candidate-file /tmp/litsearch-paper-search-score.json \
  --out /tmp/litsearch-paper-search-gate.json \
  --metric mean_retrieval_recall \
  --metric mean_rerank_quality \
  --metric mean_hit_at_k \
  --min-delta mean_retrieval_recall=0 \
  --min-delta mean_rerank_quality=0 \
  --min-delta mean_hit_at_k=0
```

The gate report is evidence for review. It must not trigger automatic mutation
or public leaderboard claims.

### Post-search Pilot-5

Search quality is now separated from post-search quality. The synthetic
Post-search Pilot-5 pack covers the downstream chain after candidates have been
retrieved:

| Task | RH axis |
| --- | --- |
| P01 paper selection | `paper_selection.precision` |
| P02 claim extraction | `paper_reading.claim_quality` |
| P03 evidence linking | `evidence_linking.support_accuracy` |
| P04 section drafting | `section_drafting.citation_grounding` |
| P05 final bundle QA | `final_bundle.pdf_quality` |

Build a local scoring pack with synthetic gold:

```bash
rh researchflowbench build-postsearch-pilot5 \
  --out .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --include-gold \
  --overwrite
```

Run the model-free floor and a deterministic visible-input baseline:

```bash
rh researchflowbench run-postsearch-baseline \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --out .research-harness/reports/postsearch_pilot5_stub_zero_score.json

rh researchflowbench run-postsearch-baseline \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --baseline deterministic_visible \
  --out .research-harness/reports/postsearch_pilot5_deterministic_visible_score.json
```

This pack is intended to make downstream failures visible before any
self-evolution step: paper selection precision, scoped claim extraction, support
label accuracy, citation grounding, and final PDF/bundle QA coverage.

The downstream contract replay runner is `postsearch_contract_scan`. It uses
deterministic visible-input contract checks for P01-P04, so it is useful for
verifying paper-selection, claim, evidence-link, and section-grounding metric
plumbing. It is not a model-quality result and does not claim semantic
generalization:

```bash
rh researchflowbench run-postsearch-primitive \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --runner postsearch_contract_scan \
  --out .research-harness/reports/postsearch_pilot5_contract_scan_score.json
```

P05 is outside this runner scope and remains covered by final-bundle runners.

The first evidence-link primitive replay runner is
`evidence_link_record_replay`. It supports only P03. The runner derives the
synthetic support label from the visible span text, calls RH's real non-LLM
`evidence_link` primitive to record each claim-to-span link, and then scores the
recorded links against local gold:

```bash
rh researchflowbench run-postsearch-primitive \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --runner evidence_link_record_replay \
  --out .research-harness/reports/postsearch_pilot5_evidence_link_record_replay_score.json
```

This is evidence for the evidence-link record path, not a claim that
`evidence_link` classifies support labels semantically. Tasks outside P03 are
marked `skipped_runner_scope`.

Use offline prediction-file scoring for real model or agent replays. The model
runner writes predictions first; ResearchFlowBench then scores that file against
local gold without doing model execution inside the scorer:

```json
{
  "schema_version": "researchflowbench.postsearch_predictions.v0.1",
  "runner_id": "candidate_model_replay",
  "model_execution_performed": true,
  "predictions": [
    {
      "task_id": "postsearch.P01_paper_selection_precision",
      "prediction": {"selected_paper_ids": ["P-A", "P-C"]}
    }
  ]
}
```

```bash
rh researchflowbench score-postsearch-predictions \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --predictions .research-harness/reports/candidate_model_predictions.json \
  --out .research-harness/reports/postsearch_pilot5_candidate_model_score.json
```

Missing predictions are retained as blocked scores with
`blocked_missing_prediction`, so score reports preserve all P01-P05 task slots.
Duplicate task ids in the prediction file are rejected because they make the
replay ambiguous. This entry point is the bridge to claim, evidence, gap,
section, final-bundle, and self-evolution model evaluation without mixing
candidate execution and local gold scoring.

The first real final-bundle replay runner is `final_bundle_quality_scan`. It
executes RH's deterministic PDF/LaTeX quality scanner on P05's synthetic
`paper.tex`, `paper.pdf`, and `paper.log` fixture, then scores final-bundle QA
coverage and citation integrity:

```bash
rh researchflowbench run-postsearch-primitive \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --runner final_bundle_quality_scan \
  --out .research-harness/reports/postsearch_pilot5_final_bundle_quality_scan_score.json
```

Tasks outside the runner scope are marked `skipped_runner_scope`, not failed.
This keeps single-stage replay useful while the remaining post-search runners
are added incrementally.

The generated-PDF replay runner is `publication_pack_backfill_scan`. It creates
a temporary RH topic with synthetic `evidence_pack` and `draft_pack` artifacts,
runs `publication_pack_backfill(components=["final_bundle"])`, then scans the
generated `final_bundle` with the same PDF/LaTeX quality scanner:

```bash
rh researchflowbench run-postsearch-primitive \
  --task-pack .research-harness/rfb/postsearch_pilot5/pilot5_v0 \
  --runner publication_pack_backfill_scan \
  --out .research-harness/reports/postsearch_pilot5_publication_pack_backfill_scan_score.json
```

This is the first replay that directly exercises RH's own PDF generation path.
It is still synthetic, but it closes the loop from draft/evidence artifacts to
generated final bundle to deterministic PDF quality score.

Use two gate levels for retrieval optimization:

| Gate | Dataset | Policy |
| --- | --- | --- |
| Smoke | LitSearch stratified50 | Fast local regression check; allow small sample variance with bounded `--max-regression`. |
| Promotion | LitSearch full597 | Candidate promotion evidence; require zero regression or explicit positive deltas on recall, MRR, and hit@20. |

### Split names

| Split | Use |
| --- | --- |
| `source` | Source examples used to derive or document a candidate. |
| `draft_dev` | Draft public-safe development fixtures such as current Pilot-20 synthetic tasks. |
| `mutate_dev` | Development replay examples allowed to guide proposed improvements. |
| `promotion_test` | Promotion replay examples used for candidate gate decisions. |
| `held_out` | Held-out replay examples for stronger champion evidence. |

Current Pilot-20 tasks intentionally remain `draft_dev` and
`draft_not_release_grade`. Changing release labels or public-readiness claims
requires human approval.

### Artifact types

ResearchFlowBench v0 recognizes these artifact types in the evaluation and
self-evolution flow:

| Artifact type | Purpose |
| --- | --- |
| `researchflowbench_task_pack` | Durable reference to an RH-owned or adapted local task pack. |
| `researchflowbench_score_report` | Per-task and aggregate scores for a task pack or adapter fixture. |
| `candidate_archive_pack` | Evidence records derived from score reports or replay gates. |
| `champion_registry_pack` | Best currently promotable candidates by target surface. |

### License fields

Every task pack and external adapter manifest must declare:

| Field | Meaning |
| --- | --- |
| `dataset_license` | SPDX-like license key or `noassertion` when unresolved. |
| `data_source_url` | Official source URL or local synthetic source identifier. |
| `redistribution_policy` | Whether data can be committed, referenced only, or must remain local. |
| `gold_storage_policy` | One of `public_safe_synthetic`, `reference_only`, `local_only`, or `judge_only`. |
| `third_party_data_vendored` | Must be `false` for external benchmark data in this repository. |

Stop for human approval if license or redistribution terms are ambiguous.

### Leakage policy

The v0 leakage policy is gold-blind by default:

- Agent-visible inputs must be listed in a visible input manifest.
- `gold_bundle.json` and `judge_bundle.json` are judge-only hidden files.
- Visible file hashes must be recorded before execution.
- Leakage canaries are required for RH-owned judge/gold bundles.
- Hidden gold, judge canaries, answer keys, and gold hashes must not appear in
  prompts, visible inputs, local corpora, or external adapter visible tasks.
- External search is `forbidden_in_v0` unless a future task contract explicitly
  changes the policy with human-approved scope.

### Archive and champion linkage

The minimum metadata required to link scores into the self-evolution archive is:

| Field | Meaning |
| --- | --- |
| `benchmark_id` | Benchmark or dataset that produced the score. |
| `task_id` | Task-level replay reference. |
| `split` | Replay role used for archive split assignment. |
| `rh_axis_ids` | RH capability axes measured by the score. |
| `artifact_refs` | Durable source score report or task-pack references. |

Champion registry entries must preserve candidate id, finding id, target kind,
RH axes, replay refs, artifact refs, metrics, and promotion strength. Promotion
requires non-incubating replay evidence; archive records from draft scores are
evaluation evidence only.

## Pilot-20 synthetic pack

Generate a fresh public-safe Pilot-20 task pack:

```bash
rh researchflowbench build-pilot20 --out /tmp/rfb-pilot20
```

Generate the pack and run the deterministic schema dry-run:

```bash
rh --json researchflowbench build-pilot20 \
  --out /tmp/rfb-pilot20 \
  --schema-dry-run-output /tmp/rfb-pilot20-dry-run
```

The JSON output reports:

| Field | Meaning |
| --- | --- |
| `task_count` | Number of generated Pilot-20 tasks |
| `validation_pass` | Result from `validate_pilot20_task_pack` |
| `preflight_pass` | Whether allowed-tool preflight checks passed |
| `leakage_pass` | Whether hidden gold / judge leakage checks passed |
| `schema_dry_run` | Optional dry-run summary when `--schema-dry-run-output` is set |

The builder refuses to overwrite a non-empty output directory unless
`--overwrite` is passed. Strict mode is enabled by default. Use `--no-strict`
only when intentionally inspecting invalid intermediate files.

Pilot-20 v0 currently contains 20 stable RH-owned synthetic tasks, T01-T20:

| Range | Coverage |
| --- | --- |
| T01-T05 | Original seed tasks for citation support, attribution abstention, partial support, stale evidence propagation, and false novelty. |
| T06-T10 | Search intent, reranking, deduplication, citation identifier integrity, and baseline-family boundaries. |
| T11-T15 | Negative evidence, cross-topic provenance, claim scope, multi-source rank conflicts, and survey facet coverage. |
| T16-T20 | Deep anchor selection, evidence-link granularity, artifact trace completeness, stale baseline rollback, and final-bundle citation integrity. |

Each task records `expected_rh_axes` in the manifest, `task.json`,
`input_bundle.json`, and `judge_bundle.json`. The current axis coverage spans
`paper_search.recall`, `paper_search.rerank_quality`,
`retrieval.provenance_coverage`, `literature.set_completion`,
`deep_research.discovery_accuracy`, and `citation.candidate_generation`.

## Generated files

The generated pack contains:

- `README.md` with operator-facing pack status, visibility, and axis coverage.
- `pilot20_manifest_draft.json` with file inventory and SHA-256 hashes.
- `goldgraph_seed_assets.jsonl` and `corrupted_evidence_cases.jsonl`.
- `schemas/` with synthetic schema fixtures.
- `tasks/T*_*/` directories with visible prompt/input files, hidden
  `gold_bundle.json`, hidden `judge_bundle.json`, and tool fixtures.

The checked-in public fixture under
`packages/research_harness/tests/fixtures/researchflowbench/pilot20_v0_synthetic_task_pack`
is reproducible from the builder. Tests compare generated output byte-for-byte
against that fixture.

## Visibility policy

ResearchFlowBench separates generator-visible inputs from judge-only data:

- Agent-visible files are listed in `tool_fixtures/visible_input_manifest.json`.
- `gold_bundle.json` and `judge_bundle.json` are hidden and judge-only.
- External search is forbidden in the current synthetic v0 pack.
- Hidden canaries are checked so gold or judge text cannot leak into visible
  inputs.
- The public synthetic pack declares `model_execution_performed=false`.

This makes the pack suitable for validator development and public CI. It is not
a release-grade benchmark claim by itself; human calibration and real held-out
tasks are still required before publication-quality evaluation claims.

## Release-readiness gate

Run the RH-owned v0 release-readiness check before treating a task pack as a
public candidate:

```bash
rh --json researchflowbench release-check \
  --task-pack packages/research_harness/tests/fixtures/researchflowbench/pilot20_v0_synthetic_task_pack \
  --schema-dry-run-output /tmp/rfb-pilot20-release-dry-run \
  --rebuild-output /tmp/rfb-pilot20-release-rebuild \
  --out /tmp/rfb-pilot20-release-readiness.json
```

The gate is read-only for the source task pack and does not change release
labels. It checks:

- no private data markers or local paper paths in the pack;
- no hidden gold, judge bundle, canary, or hash leakage in visible inputs;
- reproducible build output against the checked-in fixture;
- schema dry-run pass across deterministic validators;
- this operator documentation mentions the release path; and
- the focused ruff and pytest commands required before any public readiness
  decision.

The report includes the exact quality commands:

```bash
ruff check packages/research_harness/research_harness/eval/researchflowbench \
  packages/research_harness/research_harness/evolution/harness \
  packages/research_harness/research_harness/cli.py

pytest packages/research_harness/tests/test_researchflowbench_*.py \
  packages/research_harness/tests/test_cli.py \
  packages/research_harness/tests/test_longtask_supervisor.py -q
```

If any check fails, quarantine the pack and fix the source issue. Passing this
gate is necessary but not sufficient to mark the dataset release-grade; changing
public readiness status still requires human approval.

## External benchmark registry

List public external benchmarks that RH can calibrate against:

```bash
rh researchflowbench external-benchmarks
```

Export the registry as JSON and Markdown:

```bash
rh --json researchflowbench external-benchmarks --out /tmp/rfb-external-benchmarks
```

The registry stores adapter metadata only. It points to official repositories
and datasets, records licensing and publication-readiness status, and avoids
vendoring third-party benchmark data or hidden gold into this repository.

The registry also exports a machine-readable metric map:

- `metric_map.rh_axes` defines RH capability axes such as
  `paper_search.recall`, `paper_search.rerank_quality`, and
  `retrieval.provenance_coverage`.
- Each benchmark record includes `metric_mappings`, which maps public benchmark
  metrics to those RH axes and declares the adapter contract that generated the
  tasks.

This keeps every external benchmark explicit about what part of RH it measures.

The same payload includes `local_data_registry`, and the local-only view is
available directly:

```bash
rh --json researchflowbench local-data-registry
```

The local registry tracks only implemented adapters whose licenses are already
clear enough for local evaluation. It records:

| Field | Meaning |
| --- | --- |
| `official_source_url` | Canonical upstream dataset or repository URL. |
| `expected_local_path` | Recommended local path, rooted at `RESEARCH_HARNESS_BENCHMARK_DATA` or `.research-harness/benchmarks`. |
| `license_key` | SPDX-like license key from the official source. |
| `redistribution_policy` | Whether official data, generated tasks, and gold can be committed. |
| `adapter_id` | ResearchFlowBench adapter contract that consumes the local data. |
| `supported_metrics` | Metrics the adapter can score or report. |
| `gold_label_policy` | `local_only` for current P0 external adapters: gold may exist in a local official export but must not be committed. |

Current P0 local data contracts:

| Benchmark | Expected local path | Gold labels |
| --- | --- | --- |
| AutoResearchBench | `${RESEARCH_HARNESS_BENCHMARK_DATA}/autoresearchbench/input_data/AutoResearchBench.jsonl` | `local_only` |
| LitSearch | `${RESEARCH_HARNESS_BENCHMARK_DATA}/litsearch` | `local_only` |

Current P0 adapter candidates are:

| Benchmark | Fit for RH |
| --- | --- |
| AutoResearchBench | Literature discovery and set-completion calibration |
| LitSearch | Low-cost paper search and retrieval quality calibration |

Expansion candidates for local leaderboard preparation:

| Priority | Benchmark | Fit for RH | Current status |
| --- | --- | --- |
| P1 | SAGE | Larger-corpus scientific literature retrieval and deep-research candidate generation | adapter planned; license/schema review required |
| P1 | PaperArena | Tool-augmented scientific literature reasoning, evidence synthesis, and citation-grounded answers | adapter planned; license/runtime review required |
| P2 | DeepResearch Bench | Citation-rich deep-research report quality and leaderboard comparison | leaderboard harness planned; judge/submission review required |
| P2 | DeepResearch Bench II | Rubric-level deep-research report recall, analysis, and presentation | leaderboard harness planned; license/judge review required |
| P2 | ScienceAgentBench | Scientific task execution, code generation, execution score, cost | heavy harness; isolated runtime required |
| P2 | CORE-Bench | Paper artifact navigation and computational reproducibility | heavy harness; Docker/HAL harness recommended |
| P2 | PaperBench | Long-horizon paper replication and artifact-linked reporting | heavy harness; API/GPU costs likely |
| P3 | MLR-Bench | Idea, proposal, experiment, and paper-writing lifecycle | long-horizon harness planned |
| P3 | AIRS-Bench | Frontier ML research lifecycle and normalized score/Elo | license review; non-commercial restrictions |

License-limited, unreviewed, or heavy harnesses are tracked as P1/P2 candidates
until their runtime and licensing constraints are suitable for public RH claims.

## Operator runbook

Use this sequence when preparing local external benchmark evidence or refreshing
RH-owned Pilot-20 evidence. The flow is intentionally local-only: do not upload,
publish, push, run paid model/API jobs, vendor third-party benchmark rows, or
enable automatic mutation.

### 1. Inspect local data contracts

Start by checking what each adapter expects and where official data should live:

```bash
rh --json researchflowbench local-data-registry
rh --json researchflowbench local-data-check --benchmark-id litsearch
rh --json researchflowbench external-benchmarks --out /tmp/rfb-external-benchmarks
```

Use `RESEARCH_HARNESS_BENCHMARK_DATA` for local official data when possible:

```bash
export RESEARCH_HARNESS_BENCHMARK_DATA="$PWD/.research-harness/benchmarks"
mkdir -p "$RESEARCH_HARNESS_BENCHMARK_DATA"
```

The registry is metadata only. It is safe to commit registry documentation, but
not official external dataset rows, decrypted benchmark files, generated
external task packs, or external gold files.

`local-data-check` is the preflight gate before any real-data adapter run. A
`blocked` result means RH must not adapt, score, record, or archive that
external benchmark yet. The JSON output names the expected root, every required
file, and the missing paths so operators can fix the local official export
without guessing.

### 2. Download official external data locally

Download external benchmarks from their official upstream sources into the
local benchmark data root. Stop if an upstream license, redistribution policy,
or gold-label storage rule is unclear.

LitSearch local export:

```bash
mkdir -p "$RESEARCH_HARNESS_BENCHMARK_DATA/litsearch/query"
mkdir -p "$RESEARCH_HARNESS_BENCHMARK_DATA/litsearch/corpus_clean"
python - <<'PY'
from datasets import load_dataset
from pathlib import Path
import os

root = Path(os.environ["RESEARCH_HARNESS_BENCHMARK_DATA"]) / "litsearch"
load_dataset("princeton-nlp/LitSearch", "query", split="full").to_json(
    str(root / "query" / "queries.jsonl")
)
load_dataset("princeton-nlp/LitSearch", "corpus_clean", split="full").to_json(
    str(root / "corpus_clean" / "corpus.jsonl")
)
PY
```

AutoResearchBench local export:

```bash
git clone https://github.com/CherYou/AutoResearchBench.git \
  "$RESEARCH_HARNESS_BENCHMARK_DATA/autoresearchbench"
cd "$RESEARCH_HARNESS_BENCHMARK_DATA/autoresearchbench"
curl -L -o input_data/AutoResearchBench.jsonl.obf.json \
  https://huggingface.co/datasets/Lk123/AutoResearchBench/resolve/main/AutoResearchBench.jsonl.obf.json
python3 decrypt_benchmark.py \
  --input-file input_data/AutoResearchBench.jsonl.obf.json \
  --output-file input_data/AutoResearchBench.jsonl
```

These commands are examples for a human/operator environment. Do not run them in
CI unless the environment is explicitly allowed to download external data.

### 3. Adapt local data into RH task packs

Convert only from local official exports:

```bash
rh researchflowbench adapt-litsearch \
  --data "$RESEARCH_HARNESS_BENCHMARK_DATA/litsearch" \
  --out /tmp/rfb-litsearch

rh researchflowbench validate-external-pack \
  --task-pack /tmp/rfb-litsearch

rh researchflowbench run-external-baseline \
  --task-pack /tmp/rfb-litsearch \
  --data "$RESEARCH_HARNESS_BENCHMARK_DATA/litsearch" \
  --baseline lexical_retrieval \
  --evidence-state real_data \
  --out /tmp/rfb-litsearch-score-report.json

rh researchflowbench attribute-score-report \
  --score-file /tmp/rfb-litsearch-score-report.json \
  --out /tmp/rfb-litsearch-failure-attribution.json \
  --evidence-state real_data

rh researchflowbench adapt-autoresearchbench \
  --data "$RESEARCH_HARNESS_BENCHMARK_DATA/autoresearchbench/input_data/AutoResearchBench.jsonl" \
  --out /tmp/rfb-autoresearchbench

rh researchflowbench validate-external-pack \
  --task-pack /tmp/rfb-autoresearchbench

rh researchflowbench run-external-baseline \
  --task-pack /tmp/rfb-autoresearchbench \
  --out /tmp/rfb-autoresearchbench-score-report.json

rh researchflowbench attribute-score-report \
  --score-file /tmp/rfb-autoresearchbench-score-report.json \
  --out /tmp/rfb-autoresearchbench-failure-attribution.json \
  --evidence-state real_data
```

Use `--limit` for smoke tests. Use `--include-gold` only for local judge
development, and keep those generated gold files outside commits. If an adapter
cannot prove hidden gold isolation, quarantine the adapted pack instead of
using it as optimization evidence.
`validate-external-pack` is the required local check between adaptation and
scoring. It verifies the adapter manifest, external task contract fields,
benchmark/adapter identity, RH axis metadata, no visible gold, and no declared
third-party data vendoring.

`run-external-baseline` is model-free and deterministic. The default
`stub_zero` mode emits a `researchflowbench_score_report.v0` without model or
network execution. For LitSearch, `--baseline lexical_retrieval` builds a local
title/abstract term-frequency index, while `--baseline bm25_retrieval` uses BM25
with document-frequency IDF and document-length normalization. Both require
`--data $RESEARCH_HARNESS_BENCHMARK_DATA/litsearch` and score retrieval
recall/reranking without paid model/API jobs. If an external pack has no local
`gold.json` files, scores are marked `blocked_missing_local_gold` instead of
being treated as valid benchmark evidence.

For AutoResearchBench, `--baseline autoresearchbench_candidate_bm25` is the
first nonzero-capable deterministic baseline, but it requires `--data` to point
to a separate non-gold candidate-source root, not the official plaintext
benchmark file. The candidate-source root must contain:

```text
candidate_manifest.json
candidate_corpus.jsonl
```

`candidate_manifest.json` must declare:

```json
{
  "schema_version": "researchflowbench.autoresearchbench_candidate_source.v0.1",
  "benchmark_id": "autoresearchbench",
  "records_file": "candidate_corpus.jsonl",
  "gold_label_policy": "no_gold_labels",
  "contains_official_answers": false
}
```

Candidate corpus records may contain paper metadata such as `paper_id`, `title`,
`abstract`, `arxiv_id`, `doi`, and `url`. The builder normalizes explicit
`arxiv_id` / `arxiv` fields and conservatively extracts arXiv IDs from DOI, URL,
paper ID, or generic ID fields only when those fields contain an `arxiv` marker.
It does not infer arXiv IDs from arbitrary DOI numeric substrings. Candidate
records must not contain `answer`, `answers`, `answer_titles`,
`answer_arxiv_ids`, `gold_titles`, or `gold_paper_ids`. Passing the official
decrypted `AutoResearchBench.jsonl` as a candidate source is intentionally
rejected because it contains benchmark answers.

If multiple input records normalize to the same `paper_id`, the builder keeps
the first ID unchanged and assigns stable hash-suffixed IDs to later collisions.
The manifest records `duplicate_paper_id_count` so candidate-source construction
issues are visible instead of silently collapsing records in the BM25 index.

Build a candidate-source root from separate paper metadata before scoring. For a
generic provider export:

```bash
rh researchflowbench build-autoresearchbench-candidate-source \
  --metadata-jsonl /path/to/non_gold_paper_metadata.jsonl \
  --out /tmp/rfb-autoresearchbench-candidate-source
```

For a local Research Harness paper pool:

```bash
rh researchflowbench build-autoresearchbench-candidate-source \
  --paper-db .research-harness/pool.db \
  --out /tmp/rfb-autoresearchbench-candidate-source
```

`attribute-score-report` groups failures by RH metric axis for backlog and
self-evolution triage. The attribution report is evidence only:
`automatic_mutation_enabled` remains `false`, and fixture-only evidence must not
be upgraded into a real-data claim.

For RH-owned synthetic evidence, rebuild Pilot-20 instead of downloading data:

```bash
rh --json researchflowbench build-pilot20 \
  --out /tmp/rfb-pilot20 \
  --schema-dry-run-output /tmp/rfb-pilot20-dry-run
```

### 4. Run baseline scoring

Run the deterministic model-free baseline on RH-owned Pilot-20:

```bash
rh researchflowbench run-baseline \
  --task-pack /tmp/rfb-pilot20 \
  --out /tmp/rfb-pilot20-score-report.json
```

External adapters can produce adapter-native fixture score reports through their
adapter APIs and tests. Before recording any external score report, verify that
it uses the `researchflowbench_score_report.v0` shape or can be normalized by
`rh self-evolution record-rfb-score-report`, and that each score preserves
`benchmark_id`, `task_id`, `split`, metrics, RH axis attribution, and artifact
references.

### 5. Record score reports as evidence

Create or choose a local RH topic for self-evolution evidence, then record the
score report:

```bash
rh topic init "researchflowbench-v0-evidence"

rh self-evolution record-rfb-score-report \
  --topic "researchflowbench-v0-evidence" \
  --score-file /tmp/rfb-pilot20-score-report.json
```

For legacy or adapter-native score lists, pass `--benchmark-id` and `--split`
when the file does not include them:

```bash
rh self-evolution record-rfb-score-report \
  --topic "researchflowbench-v0-evidence" \
  --score-file /tmp/litsearch-fixture-score-report.json \
  --benchmark-id litsearch \
  --split mutate_dev
```

For external score reports produced by `run-external-baseline`, record only
after checking the attribution evidence state. `blocked_missing_local_gold` and
`fixture_only` reports can be archived for pipeline QA and backlog rehearsal,
but they cannot support public real-data performance claims.

The recorded artifact type is `researchflowbench_score_report`. Recording a
score report is evidence ingestion only; it does not modify benchmark claims,
skills, prompts, code, or release labels.

### 6. Assemble archive packs

After recording one or more score reports, assemble archive evidence:

```bash
rh self-evolution archive-from-artifacts \
  --topic "researchflowbench-v0-evidence"
```

This writes `candidate_archive_pack` and `champion_registry_pack` artifacts from
the recorded score reports. The payloads must preserve benchmark id, task id,
split role, metrics, RH axes, replay refs, and source artifact refs. The command
reports `mutation_performed: false`; if that ever changes, stop and quarantine
the run.

### 7. Decide what can be optimized next

Use recorded score evidence to update optimization backlog items, not to mutate
the system automatically.

| Evidence state | Allowed next action |
| --- | --- |
| RH-owned `draft_dev` Pilot-20 stub/baseline failures | Add or refine backlog entries tied to measured RH axes. |
| External P0 fixture scores with clear license and local-only data handling | Add backlog evidence for the mapped RH axis; keep external data local. |
| Non-incubating `promotion_test` or `held_out` replay evidence | Propose a human-reviewed candidate promotion decision. |
| Ambiguous license, leaked gold, missing task ids, missing RH axes, or invalid schema | Mark the evidence quarantined and fix the source issue first. |
| Any change to benchmark claim boundaries, release labels, public readiness, code, skills, or prompts | Stop for human approval before making the change. |

Allowed optimization targets are the surfaces identified by measured failures:
retrieval, evidence linking, citation integrity, section drafting, final
bundle/PDF quality, and orchestrator policy. Do not optimize based only on
subjective PDF inspection or undocumented anecdotes.

## LitSearch adapter

LitSearch is the first implemented external adapter. It consumes a local export
from the official `princeton-nlp/LitSearch` dataset and writes RH retrieval
tasks without committing third-party benchmark data to this repository.

Prepare the official dataset locally:

```bash
python - <<'PY'
from datasets import load_dataset

load_dataset("princeton-nlp/LitSearch", "query", split="full").to_json(
    "/tmp/litsearch/query/queries.jsonl"
)
load_dataset("princeton-nlp/LitSearch", "corpus_clean", split="full").to_json(
    "/tmp/litsearch/corpus_clean/corpus.jsonl"
)
PY
```

Convert it to RH-formatted tasks:

```bash
rh researchflowbench adapt-litsearch --data /tmp/litsearch --out /tmp/rfb-litsearch
```

For local judge development only, `--include-gold` writes separate gold files.
Do not commit generated LitSearch task packs or gold files.

The adapter contract is `researchflowbench.adapters.litsearch.v0.1`.
It maps LitSearch `retrieval_recall` to `paper_search.recall` and
`citation.candidate_generation`, and maps `rerank_quality` to
`paper_search.rerank_quality`.

## AutoResearchBench adapter

AutoResearchBench is the second implemented external adapter and the first P0
adapter for deeper research-agent discovery behavior. It consumes the local
plaintext JSONL produced by the official decrypt step and writes RH tasks for
both benchmark task families:

- Deep Research: maps `deep_accuracy` to
  `deep_research.discovery_accuracy` and `retrieval.provenance_coverage`.
- Wide Research: maps `wide_iou` to `literature.set_completion` and
  `retrieval.provenance_coverage`.

Prepare the official data locally with the upstream repository's documented
flow:

```bash
git clone https://github.com/CherYou/AutoResearchBench.git
cd AutoResearchBench
curl -L -o input_data/AutoResearchBench.jsonl.obf.json \
  https://huggingface.co/datasets/Lk123/AutoResearchBench/resolve/main/AutoResearchBench.jsonl.obf.json
python3 decrypt_benchmark.py \
  --input-file input_data/AutoResearchBench.jsonl.obf.json \
  --output-file input_data/AutoResearchBench.jsonl
```

Convert the local plaintext export to RH-formatted tasks:

```bash
rh researchflowbench adapt-autoresearchbench \
  --data /path/to/AutoResearchBench/input_data/AutoResearchBench.jsonl \
  --out /tmp/rfb-autoresearchbench
```

For local judge development only, `--include-gold` writes separate gold files.
Do not commit decrypted AutoResearchBench data, generated task packs, or gold
files.

To run a deterministic nonzero-capable replay, build or provide a separate
candidate source that does not include official answers:

```bash
rh researchflowbench build-autoresearchbench-candidate-source \
  --metadata-jsonl /path/to/non_gold_paper_metadata.jsonl \
  --out /tmp/rfb-autoresearchbench-candidate-source

rh researchflowbench run-external-baseline \
  --task-pack /tmp/rfb-autoresearchbench \
  --baseline autoresearchbench_candidate_bm25 \
  --data /tmp/rfb-autoresearchbench-candidate-source \
  --evidence-state real_data \
  --candidate-top-k 20 \
  --out /tmp/rfb-autoresearchbench-candidate-bm25-score-report.json
```

This baseline uses the visible question to retrieve from `candidate_corpus.jsonl`
and then scores predicted titles for Deep Research tasks and predicted arXiv IDs
for Wide Research tasks. `--candidate-top-k` controls how many retrieved
candidates are converted into predictions; it defaults to 20 and is ignored by
other external baselines. Larger candidate sources may need a larger top-k to
trade precision for recall, so top-k sweeps should be reported alongside source
provenance. The baseline remains model-free and deterministic; promotion claims
require a real non-gold candidate source, not a synthetic fixture.

To evaluate the intended RH + Codex-style agent workflow, keep generation and
judging separate. First run the gold-blind agent from adapter `input.json` files
only:

```bash
rh researchflowbench run-external-agent \
  --task-pack /tmp/rfb-autoresearchbench \
  --candidate-source /tmp/rfb-autoresearchbench-candidate-source \
  --max-agent-iterations 5 \
  --max-retrieval-iterations 5 \
  --task-timeout-sec 1800 \
  --reasoning-effort medium \
  --predictions-out /tmp/rfb-autoresearchbench-agent-predictions.json
```

Then score the written predictions against local judge-only `gold.json` files:

```bash
rh researchflowbench score-external-predictions \
  --task-pack /tmp/rfb-autoresearchbench \
  --predictions /tmp/rfb-autoresearchbench-agent-predictions.json \
  --task-id autoresearchbench.60 \
  --evidence-state real_data \
  --out /tmp/rfb-autoresearchbench-agent-score-report.json
```

`run-external-agent` creates a temporary per-task workspace containing only the
visible `input.json` and an optional non-gold candidate-source manifest/corpus
copy. It rejects
iteration caps above 5 and validates the candidate-source manifest with the same
no-answer checks as `autoresearchbench_candidate_bm25`.
`score-external-predictions` is the only stage that reads local `gold.json`;
missing predictions are blocked as `blocked_missing_prediction`, and invalid
prediction objects are blocked as `blocked_invalid_prediction`.
Use repeated `--task-id` options for smoke subsets; omit `--task-id` only when
the prediction file covers the whole task pack.

When local gold is available for judge development, use the aggregate diagnostic
script to separate candidate-source coverage from top-k ranking failures without
printing answer details:

```bash
python scripts/diagnose_autoresearchbench_candidate_coverage.py \
  --task-pack /tmp/rfb-autoresearchbench \
  --candidate-source /tmp/rfb-autoresearchbench-candidate-source \
  --score-file /tmp/rfb-autoresearchbench-candidate-bm25-score-report.json \
  --out /tmp/rfb-autoresearchbench-candidate-coverage.json
```

The diagnostic emits counts only and sets `gold_detail_emitted: false`.

The adapter contract is `researchflowbench.adapters.autoresearchbench.v0.1`.

## Planned external adapters

SAGE and PaperArena are tracked in the external benchmark registry as P1
coverage expansions:

- SAGE should extend LitSearch-style retrieval from small realistic queries to
  larger-corpus scientific retrieval and deep-research candidate generation.
- PaperArena should extend retrieval into tool-augmented scientific literature
  reasoning, grounded answer synthesis, and tool trace quality.

Both remain `adapter_planned`; do not use them for RH performance claims until
their data schemas, licenses, judge requirements, and local-only data handling
are reviewed and an adapter produces validated `researchflowbench_score_report`
artifacts.

## Local verification

Run the focused ResearchFlowBench checks:

```bash
pytest packages/research_harness/tests/test_researchflowbench_*.py -q
```

Run the top-level CLI regression with the ResearchFlowBench tests:

```bash
pytest packages/research_harness/tests/test_cli.py \
  packages/research_harness/tests/test_researchflowbench_*.py -q
```
