# Whole-Paper Figure Contract

Research Harness plans and renders a paper's **entire figure suite** — not just
result plots — through an exemplar-anchored, two-phase contract. The design is
grounded in an empirical study of 152 A-venue papers (ML/DM/NLP conferences,
Nature-family journals, social-science, and biomedical/omics), which fixed a
**12-role × 4-pipeline × 4-style** vocabulary.

## Separation of concerns

| Layer | Owner | What it does |
|---|---|---|
| Design (v1) | `figure_suite_plan source=matrix` (EAG curate/retrieve/plan) | Plan the whole-paper figure suite by analogy to target-venue exemplars, at experiment-design time. Emits a renderable spec, a bidirectional matrix-coverage check, per-panel logging requirements, and a generative-pipeline export. |
| Reconcile (v2) | `figure_suite_plan source=records` | Diff the design spec against actual results; prune figures the data can't feed. |
| Execution | `figure_suite_render` → `research_harness.visualization.experiment_figures` | Deterministically resolve the venue/result policy and render the deterministic-pipeline figures (composed multi-panel, discipline style). |
| Acceptance | built-in critique + `figure-quality`'s `RESULT_FIGURE_PUBLICATION_GATE` | Deterministic sanity checks, optional VLM review, publication gate. |

Generative figures (framing/method/etc.) route to `figure_generate` /
`rh-paper-figure-generator`; listings route to LaTeX; spatial maps wrap
externally-produced GIS assets.

## Roles, pipelines, style profiles

**12 roles → 4 pipelines:**

- **generative** (route to figure_generate, illustration route): `framing` (Fig 1
  motivation), `method` (architecture/pipeline), `study_design`
  (protocol/CONSORT/flowchart), `theory` (causal DAG, state diagram, proof),
  `survey_meta` (PRISMA, taxonomy tree, field-trend).
- **deterministic** (render from records): `data` (dataset stats/distribution),
  `results` (benchmark/ablation/curves), `results_sensitivity`
  (hyperparameter/scale sweeps), `analysis` (t-SNE/UMAP/attention/SHAP/error/
  calibration), `qualitative` (prediction-vs-truth showcase).
- **latex**: `listing` (prompt/code/transcript blocks).
- **external_asset**: `spatial_map` (study-area/choropleth/GWR maps — wrapped,
  never fabricated).

**Chart kinds (deterministic):** `grouped_bar`, `heatmap`, `radar`,
`pareto_scatter`, `sensitivity_line`, `line` (with confidence band + categorical
x), `scatter`, `box`, `violin`, `bar`, `forest`, `hist`, `stacked_bar`,
`km_survival` (step curves + censoring ticks), `volcano` (log2FC vs -log10p
thresholds), `image` (external asset into a panel), `qualitative_grid` (case
image grid, skips missing assets). Error bars are automatic when records carry
`std` / `lo,hi` / repeated seeds. Pie, 3D, and dual-y encodings are refused.
A panel whose records are missing is skipped and recorded in provenance. A
recorded null or empty effect (flat bars, empty volcano, ROC Youden < 0.15,
zero heatmap variance) is retained and annotated in provenance; it is not
hidden because the visual signal is weak. Mean-only bars at n<10 per group
overlay raw points.

**4 style profiles:** `stem_conference`, `nature_family`, `social_humanities`,
`biomed_omics` (survival/expression/omics conventions, NEJM-clinical palette).

**paper_type knob:** `empirical` (default) or `survey` (pre-weights PRISMA +
taxonomy + field-trend + meta-comparison tables).

## Deterministic result-plot policy

Style profiles control typography, palette, and sizing. A separate immutable
policy selects the evidence grammar from the caller override, topic/spec
metadata, and available record fields. Resolution order is:

1. a valid explicit `style_profile` argument;
2. deterministic `target_venue`, `discipline`, `article_type`/`paper_type`, and
   record-schema signals;
3. a valid style profile already stored in the suite spec;
4. a warned `stem_conference` compatibility fallback.

The five v1 policies are `stem_computing_v1`,
`nature_multidisciplinary_v1`, `biomed_clinical_v1`, `biomed_omics_v1`, and
`social_behavioral_v1`. They reuse the four public style profiles while ranking
appropriate charts and declaring evidence metadata such as uncertainty,
sample-size, replicate, effect-size, and reproduction semantics. Planning reads
the topic's target venue and domain when available, injects the deterministic
recommended/discouraged chart grammar before suite design, then stores the
resolved style and flattened `result_plot_policy` in the spec. Rendering
resolves the same policy again from the spec and records it in suite- and
figure-level provenance. Unknown signals are never presented as a recognized
venue: the fallback and warning remain visible in that provenance.

For grouped result bars, policies use hatch plus color category encoding.
Nature, biomedical, and social-science policies also overlay deterministic raw
replicate points when repeated values or a replicate identifier are available;
summary statistics continue to use every eligible record. The visual overlay is
bounded to 500 points per panel. When more points are available, the renderer
selects evenly across stable method/dataset/record order and records
`raw_points`, `raw_points_available`, and
`replicate_visibility=overlaid_sampled`; smaller overlays remain complete.
Panel provenance also records whether uncertainty came from repeated-sample
standard deviation, an explicit standard deviation, or an explicit interval.
This does not infer biological-versus-technical replicate meaning: callers must
still supply and document that semantic distinction.

This policy is used only by the recorded-data renderer. It does not route,
generate, or assess illustration-route architecture, method, protocol, or other
generative figures.

## Two-phase flow (RH stages `init→build→analyze→propose→experiment→write`)

```
propose/experiment (design defined)
  │  figure_suite_plan source=matrix
  │     ground on planned inventory (explicit matrix, or goal_pool /
  │     experiment_result)
  ▼
  v1 spec ─┬─ matrix_coverage: unfeedable panels / experiments with no figure
           └─ logging_requirements: what each panel needs recorded (fields +
              granularity, e.g. per-seed values for error bars, per-epoch curves)
  ▼
experiment (run; log per the requirements)
  ▼
write: figure_suite_plan source=records → v2 (prune unfeedable figures)
  ├─ deterministic figures → figure_suite_render → RESULT_FIGURE_PUBLICATION_GATE
  ├─ generative figures    → figure_generate / rh-paper-figure-generator
  ├─ listings              → LaTeX (lstlisting/tcolorbox)
  └─ spatial maps          → external GIS asset wrapped via image panel
```

Design can begin before any result exists: the **planned inventory** is
synthesized from the topic's `goal_pool` (dataset × metric × baseline) plus the
`baseline_matrix` methods, or an explicit matrix JSON. Dream-mode papers ground
on declared `expected_proposed_results` targets, tagged `mode: planned`. The
inventory always carries `mode: planned|observed` so the planner knows whether
the numbers are final.

## Form-not-content, by construction

The plan carries **no data** — only roles, chart kinds, composition,
`record_filter` bindings, labels, and a style profile. Every rendered number
comes from the caller's records. Panels without matching records are **skipped
and reported** (`provenance.limitations`), never invented. Generative figures
carry title/purpose only. This is the same "stand on the shoulders of giants"
discipline as the prose EAG path, but for figures the guarantee is structural
rather than an n-gram gate.

## Usage

```bash
# Design phase (v1): plan the suite + get the logging checklist
rh exemplar figure-plan --topic 12 --target "$(cat contributions.md)" \
    --from-matrix experiment_matrix.json --paper-type empirical

# ...run experiments, logging what the requirements asked for...

# Reconcile (v2): prune against real results
rh exemplar figure-plan --topic 12 --reuse-plan --records results.json

# Render the deterministic figures (design+render in one shot, or offline)
rh exemplar figures --topic 12 --records results.json \
    --target "..." --output-dir 06-writing/figures/ --vision --formats png,pdf
rh exemplar figures --topic 12 --records results.json \
    --spec suite_spec.json --output-dir 06-writing/figures/   # offline, no LLM
```

Records are plain dicts (`{"figure_type": "benchmark", "dataset": ..., "method":
..., "metric": ..., "value": ...}`; repeated results may include
`replicate_id`, `replicate`, `seed`, `run_id`, `sample_id`, or `subject_id`;
generic kinds use `x`/`y`, `group`/`value`, `time`/`value`,
`log2fc`/`neg_log10_p`, or `path` for asset grids). Artifacts:
`exemplar_pack_figure_suite`, `exemplar_plan_figure_suite`, `figure_suite_plan`
(v1/v2 with coverage + logging requirements), and `figure_suite` (rendered
paths + provenance + critique), with lineage between them.

The flow is exposed as public MCP tools (`exemplar_curate`, `exemplar_retrieve`,
`exemplar_plan`, `figure_suite_plan`, `figure_suite_render`). The
`figure_contract` advisory nudges when a topic reaches experiment/write stage
with results but no plan, or when the plan reports coverage gaps.
