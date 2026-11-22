---
name: rh-exemplar-writing
description: Reference-grounded ("stand on the shoulders of giants") generation of research artifacts via the Research Harness Exemplar-Anchored Generation (EAG) engine. Use when designing or auditing a paper's SECTION ARCHITECTURE / skeleton, INTRODUCTION arc, ABSTRACT element order, PROSE STYLE, or WHOLE-PAPER FIGURE CONTRACT (all figure roles — framing, method, data, results, analysis, spatial maps, listings — chart choices, multi-panel composition, discipline style, two-phase design/reconcile) by analogy to high-quality published exemplars from the target venue. Runs TWO exemplar tracks: Track A (DOMAIN REGISTER) learns the field's canonical terminology and phrasing conventions from same-domain published papers and reuses them verbatim; Track B (FORM) learns argument structure and writing logic from architecture-similar papers of any topic. Transfers FORM and canonical vocabulary — never CONTENT (claims, data, specific wording). Complements rh-ccf-a-introduction-writer, rh-paper-figure-generator, and rh-paper-production.
public_suite: paper
task_type: exemplar-anchored-writing
data_access_level: local-files
inputs: topic id, unit type (domain_register|skeleton|intro_arc|related_work_arc|method_arc|experiment_arc|discussion_arc|paragraph_moves|abstract|style|figure_suite), this paper's content/contributions, target venue, paper_type (empirical|survey), experiment records or planned matrix (for figure suites)
outputs: exemplar_register_lexicon (Track A canonical field vocabulary with per-term paper support), exemplar_pack (quality-gated library slice), exemplar_plan (form-only skeleton/arc/suite spec), figure_suite_plan (two-phase contract + coverage + logging requirements + generative export), drafted section or rendered figure suite, anti-plagiarism + register critique / figure critique
gates: exemplar quality gate (only high-quality target-venue exemplars admitted), same-domain gate for register sources (no cross-domain fill), form-not-content overlap gate (deterministic n-gram anti-plagiarism; canonical register terms exempt), register adherence check (deterministic non-canonical-synonym flags), rendered-figure critique (deterministic + optional VLM), figure_contract advisory (missing plan / coverage gaps)
artifact_schemas: exemplar_register_lexicon, exemplar_pack, exemplar_plan, figure_suite_plan, figure_suite
estimated_runtime: 1-10 min
---

# RH Exemplar-Anchored Writing (EAG)

## Objective

Generalize the proven reference-driven figure-generation pattern — *retrieve high-quality published exemplars → transfer FORM by structural analogy → generate → critique against the exemplars → iterate*, over a **quality-gated exemplar library** — from figures to research **prose, structure, and result-figure design**. The guiding principle (from reference-driven figure retrieval) is **"structure is more important than topic"**: a same-FORM exemplar from a different topic beats a same-TOPIC exemplar with a different form.

Use this skill to design or audit a paper's **section architecture**, **introduction arc**, **abstract element order**, **prose style**, or **result-figure suite** by standing on the shoulders of the best papers in the target venue — while never copying their content.

### Two exemplar tracks (both are required for prose)

| Track | Exemplars | Selection rule | Learns | Reuse rule |
|---|---|---|---|---|
| **A · Domain register** (`unit_type=domain_register`) | Published, target-tier papers of the **same field and task** (e.g. AI peer review / review feedback) | **Domain/task match dominates**; never filled from other domains | Canonical names for the task, inputs, outputs and metrics; standard terms (kept only when ≥2 papers use them); hedges; claims the field warns against; non-canonical → canonical synonyms | Canonical terms are **reused verbatim**; the drafter must not coin a new name for a concept the field already names |
| **B · Form / writing logic** (all other unit types) | Published papers with a **similar method architecture or paper type**, any topic | **Structure dominates topic** (structure-first principle) | Abstract moves, introduction paragraph roles, how challenges are enumerated and mapped to modules, results framing, section skeleton | Transfer structure only; never wording, claims or data |

Why both: Track B alone makes the drafter invent field vocabulary, which expert reviewers read as an outsider's writing; Track A alone yields correct terms but no argument. Curate Track A first (`rh exemplar register`), then plan/generate with Track B — the register is injected into every plan/draft prompt and into the critique gate automatically.

## When to use / not use

- Use for: section-architecture design/audit, introduction-arc planning, abstract structuring, style profiling, and experiment/result figure-suite design (which charts, how panels compose, which discipline style) — grounded in top-venue exemplars.
- Do NOT use to: invent claims, copy exemplar wording/data, or make empirical results. It transfers structure/style only; evidence and claims stay this paper's own. For generative architecture/method figures, route to `rh-paper-figure-generator` (illustration route); for evidence-grounded full drafts, it delegates to `section_draft`.

## The engine (RH primitives; also `rh exemplar` CLI and MCP tools)

- `exemplar_curate` — build a quality-gated exemplar library slice from the topic's papers (extract each paper's abstracted FORM for one `unit_type`; keep only high-quality, target-venue exemplars). Records an `exemplar_pack` artifact. For `result_figure_suite` the evidence is the paper's **figure captions** (extracted from the pool PDF) plus, when `RH_EAG_FIGURE_VISION=1` and a vision backend is configured, VLM analyses of the paper's actual result figures.
- `exemplar_curate unit_type=domain_register` — **Track A**: extracts each same-field paper's canonical vocabulary (abstract + introduction prose); sources come only from the topic's own (same-domain) papers or explicit `paper_ids`, never from the global cross-domain fill. `build_register_lexicon(units, min_support=2)` aggregates the per-paper registers into one lexicon: a term is kept when ≥`min_support` papers use it (capped by pack size), synonyms are majority-voted and never flag a term the field itself uses canonically. Recorded as an `exemplar_register_lexicon` artifact.
- `exemplar_retrieve` — rank Track-B exemplars by **structure > topic**; return top-k.
- `exemplar_plan` — produce a **FORM-only** plan (skeleton / intro move-map / figure-suite spec) for THIS paper by analogy; never reuses exemplar wording. With `register_lexicon`, the plan is bound to the field's canonical vocabulary. Records an `exemplar_plan` artifact.
- `exemplar_generate` — plan → draft → **anti-plagiarism + register critique** → revise loop for prose. Uses RH `section_draft` (evidence-grounded) when the topic is drafting-ready (active PAPER_PLAN); else a self-contained drafter. With `register_lexicon`, the revise loop also restores canonical terms the draft replaced.
- `exemplar_critique` — the **form-not-content gate** for prose: deterministic n-gram overlap of a draft against source exemplars; fails on excess verbatim reuse. With `register_lexicon`: canonical terms are masked before counting (standard vocabulary is not plagiarism), `conformance.register` lists canonical terms used and non-canonical synonyms found, and `strict_register=True` (default) fails the gate on a synonym violation.
- `figure_suite_plan` — the **whole-paper figure-contract brain** (two-phase). `source=matrix` (design, v1): grounds on a planned inventory (explicit matrix, or the topic's goal_pool / experiment_result), curates `figure_suite` exemplars, and plans the paper's figure suite by analogy — returning a renderable spec, a bidirectional **matrix-coverage** check (panels without data / experiments without a panel), per-panel **logging requirements** for the run phase, and a **generative-pipeline export** for `figure_generate`. `source=records` (reconcile, v2): diffs a prior design spec against actual records, pruning unfeedable figures.
- `figure_suite_render` — the **deterministic execution layer**: renders the planned spec from recorded experiment records via `research_harness.visualization` (seaborn/matplotlib), composing multi-panel figures with per-discipline style profiles. No LLM renders anything; panels without matching records are skipped and reported in provenance, never invented.

## Whole-paper figure contract (all paper figures, not only results)

The empirical study of 152 A-venue papers established a **12-role** contract across **four execution pipelines** and **four discipline style profiles**, planned in **two phases**.

**Roles → pipeline:** `framing` / `method` / `study_design` / `theory` (incl. causal DAG) / `survey_meta` (PRISMA, taxonomy) → **generative** (route to `rh-paper-figure-generator`); `data` / `results` / `results_sensitivity` / `analysis` / `qualitative` → **deterministic** (render from records); `listing` (prompt/code/transcript) → **latex**; `spatial_map` (study-area/choropleth/GWR maps) → **external_asset** (wrap a supplied figure — never fabricate a map).

**Chart kinds (deterministic):** `grouped_bar | heatmap | radar | pareto_scatter | sensitivity_line | line | scatter | box | violin | bar | forest | hist | stacked_bar | km_survival | volcano | image | qualitative_grid`. Error bars are automatic when records carry `std` / `lo,hi` / repeated seeds; `line` supports confidence bands and categorical x.

**Style profiles:** `stem_conference` (dense colorblind-safe conference), `nature_family` (compact multi-panel, bold lowercase letters, NPG palette), `social_humanities` (serif, muted, coefficient/forest conventions), `biomed_omics` (survival/volcano/expression conventions, NEJM-clinical palette, uppercase bold letters).

**paper_type knob:** `empirical` (default) or `survey` (pre-weights PRISMA + taxonomy + field-trend + meta-comparison figures).

**Two phases:**
1. **Design (experiment-design time, v1)** — `figure_suite_plan source=matrix` plans the suite before results exist, doubling as a **check on the experiment matrix** (panels with no experiment, experiments with no panel) and emitting a **logging-requirements** checklist so the run phase records exactly what each panel needs (e.g. per-seed values for error bars, per-epoch for curves).
2. **Reconcile + render (write time, v2)** — `figure_suite_plan source=records` prunes figures the real results can't feed; `figure_suite_render` draws the survivors; generative/latex/external figures route to their own pipelines.

**Acceptance** — built-in critique (deterministic sanity checks + optional VLM readability/composition review), then `figure-quality`'s `RESULT_FIGURE_PUBLICATION_GATE`.

Evidence rules: records may be observed logs or reported baselines — `claim_boundary` is recorded in provenance; the renderer never invents numbers (form-not-content by construction, since the spec carries no data).

## CLI

```
rh exemplar doctor
# Track A — domain register first (same-field published papers; canonical vocabulary)
rh exemplar register    --topic <id> [--paper-ids 12,15,...] [--max-papers 12] [--min-support 2] [--min-tier 85] [--json]
# Track B — form / writing logic (architecture-similar papers, any topic)
rh exemplar curate      --topic <id> --unit-type intro_arc|related_work_arc|method_arc|experiment_arc|discussion_arc|paragraph_moves|skeleton|abstract|style|figure_suite|domain_register [--min-quality 7] [--max-papers 6]
rh exemplar plan        --topic <id> --unit-type <t> --target "<this paper's content>" [--reuse-pack] [--register/--no-register]
rh exemplar generate    --topic <id> --unit-type <t> --target "<...>" [--section introduction] [--backend auto|self|section_draft] [--reuse-pack] [--register/--no-register]
# figure contract — design phase (v1): plan the suite + get logging requirements
rh exemplar figure-plan --topic <id> --target "<...>" [--from-matrix matrix.json | --records results.json] [--paper-type empirical|survey] [--style-profile ...]
# figure contract — reconcile phase (v2): prune against real results
rh exemplar figure-plan --topic <id> --reuse-plan --records results.json
# render a spec (design+render in one shot, or offline with --spec)
rh exemplar figures     --topic <id> --records results.json --target "<...>" --output-dir 06-writing/figures/ [--vision] [--style-profile ...] [--formats png,pdf] [--claim-boundary ...]
rh exemplar figures     --topic <id> --records results.json --spec suite_spec.json --output-dir ... (offline: render an existing spec, no LLM)
```

`register` records an `exemplar_pack_domain_register` artifact plus the aggregated `exemplar_register_lexicon`; `plan` and `generate` load the latest lexicon automatically (`--no-register` opts out). `curate` records an `exemplar_pack_<unit_type>` artifact; `plan --reuse-pack` reuses the latest pack. `figure-plan` records a `figure_suite_plan` artifact (v1 or v2); `figures` records a `figure_suite` artifact with lineage. `--spec` skips design entirely (no LLM). The `figure_contract` advisory nudges when a topic reaches experiment/write stage with results but no plan, or when the plan reports coverage gaps.

## Discipline (mandatory): transfer FORM and canonical vocabulary, never CONTENT

The plan/generate steps receive only **form abstractions** (structure schemas, move-maps, style parameters, chart/composition vocabularies) — never verbatim exemplar text/data. For prose, the `exemplar_critique` overlap gate enforces this; for figures, the deterministic renderer enforces it by construction (structure/style is not copyrightable; specific expression and data are). Every generated prose draft must pass the gate; every rendered figure must trace to caller records.

The one deliberate exception is the **domain register** (Track A). Field-standard names — of the task, its inputs and outputs, metrics, and established concepts — are shared vocabulary, not any paper's expression; they must be reused exactly as the field writes them, and the drafting model must not invent alternatives. The register never carries claims, results, system names or dataset names, and a term is canonical only when several published papers of the field use it. When no register is recorded for a topic, say so and curate one before drafting prose for expert readers.

## Agent-pattern mapping (Anthropic "Building Effective Agents")

Routing = `exemplar_retrieve`; prompt-chaining = curate → retrieve → plan; evaluator-optimizer = `exemplar_generate` ↔ `exemplar_critique` (prose) and `figure_suite_render` ↔ figure critique (figures); orchestrator-workers = `rh-paper-production` delegates to this skill. Deterministic checks (the overlap gate, the renderer, the figure sanity checks) use code, not an LLM (simplicity). Every step records an inspectable artifact naming the chosen exemplars and the form transferred (transparency).

## Integration

Invoke after `rh-paper-production` establishes topic state + paper pool. For Track A, make sure the pool holds at least 6–10 published, target-tier papers of the **same field and task** (ingest them with `paper_search`/acquisition if missing) and run `rh exemplar register` before any prose step. For Track B, source exemplars from the topic's retrieved (OA / target-venue) papers — ingesting PDFs matters for `result_figure_suite` because captions are the curation evidence; grow the pool with `paper_search`/acquisition when target-venue exemplars are missing. Architecture figures stay with `rh-paper-figure-generator`; deep introduction paragraph-role/claim-evidence maps stay with `rh-ccf-a-introduction-writer`; publication acceptance of rendered result figures runs through `figure-quality`'s `RESULT_FIGURE_PUBLICATION_GATE` — this skill supplies the exemplar-derived FORM those consume.
