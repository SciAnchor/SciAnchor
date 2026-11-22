---
name: figure-quality
description: Central router for Research Harness manuscript figures. Use for any paper figure, plot, panel, schematic, architecture diagram, Nature-style figure, collision audit, or ImageGen/illustration request. Classifies the figure, then routes to the existing stack — do not install parallel plotting skills.
public_suite: paper
task_type: visual-evaluation
data_access_level: local-files
inputs: figure_plan, manuscript, final_bundle, recorded result artifacts
outputs: publication-ready figure assets, figure provenance, visual-risk report
gates: result figures must use recorded evidence; generated assets need provenance
artifact_schemas: figure_plan, final_bundle_quality_report
estimated_runtime: 20-90 min
---

# Figure Quality

Use this skill to turn RH `figure_plan` artifacts and manuscript context into publication-ready figure assets. Automated RH writing uses the RH illustration route (`figure_generate`; model `illustration` / `illustration-fake`). Session ImageGen is an interactive host tool, not the programmatic route.

This skill adopts a reference-driven quality loop for academic figures:
contract first, reference/style selection, render, critic review, bounded
refinement, then caption and provenance recording. RH remains the source of
truth for figure plans, evidence boundaries, asset paths, and recorded
provenance.

For Nature/high-impact-journal style expectations, use the adapted guidance in `references/nature-figure-adaptation.md`. The goal is not decorative image generation; each figure should act as a visual argument with a clear claim, evidence boundary, panel logic, export contract, and review-risk check.

## Stack router

One stack. Do not clone or invoke SciPilot Figure, academic-figure-skill, figures4papers, ScholarPlot-MCP, or matplotlib MCP plot servers. Those overlap this router; installing them forks the engine.

The one thing that pack states and this router did not — print geometry, type size at print size, vector master, embedded fonts — is written down in `references/academic-figure-skill-adopted.md`. It is a spec for the existing render gate, not a second pipeline. Its palette is not adopted.

| Kind | Owner |
|---|---|
| Architecture, method, protocol, graphical abstract, npj Figure 1 | RH illustration route → MCP `figure_generate` (`illustration` / `illustration-fake`) |
| Draw or redraw a draft's generative figures (fill placeholders, redraw Figure 1) from a LaTeX manuscript | `paper-arch-figure` (method text + caption → 3 candidates → model judge → swap in → Linear 子-架构图 close-out) |
| Single evidence-bound Figure Package (top-one) | MCP `figure_package` (`research_harness.visualization.figure_package_workflow`) |
| Quantitative panels from recorded results | MCP `figure_suite_plan` then `figure_suite_render` (`research_harness.visualization.experiment_figures`), using RH soft `PALETTE_POOL` (`core`/`warm`/`pathway`/`immune`/`lineage`/`tissue`/`extended`, rotated per ticket with `#222222` ink edges) and canonical sequential ramp `YlGnBu` / `YlGnBu_r` (never hand-rolled single-hue white `LinearSegmentedColormap` or hardcoded `#BC3C29/#0072B5` across all tickets) |
| Rendered PDF gates (clip, palette, text collision, grayscale) | `figure_integrity.check_figure` on every PDF until FAIL is empty |
| Whole-paper inventory | `docs/FIGURE_CONTRACT.md` (12 roles × 4 pipelines) |

Never equal-weight 2×2 dashboards. Prefer one hero panel plus supporting panels with distinct inferential roles. Never ImageGen a numeric chart. Never locally-edit a PNG after data change — rerun the script.

## Ranker skill (no trained model)

`rank_figure_candidates` selects among rendered candidates with a checklist, not a learned scorer. Taste comes from this skill, `references/nature-figure-adaptation.md`, venue profiles, and `venue_figure_grammar`. Axes:

- `story_composite` — Nature/biomed: hero + supporting panels (`schematic_led_composite` / `asymmetric_mixed_modality`). Penalize isolated 1–2 plots and equal 2×2.
- `application_scene` — clinical/patient/protocol/case correspondence (`case_exhibit`, `failure_gallery`, `study_design`).
- `venue` — recommended vs discouraged vs refused charts (pie / 3D / dual-y / rainbow).
- `logic` — distinct panel purposes; claim present.
- `richness` — panel count and caption density.
- `frontier` — mixed-modality / application-grounded composition.
- `fit` — role + claim.
- `texture` / `aesthetics` — PDF integrity; VLM aesthetics when vision is on.
- Extra keys in `figure_spec["quality_axes"]` are additive.
- `form_prior` — venue share of the planned `form_id` from `figure_knowledge` (v0 caption tree). Unclassified gets zero. Does not replace the five roles.

The fake illustration provider stays at 1 candidate. Writing still ranks with `use_vision=False`.

Chart intercepts (refuse, do not style around): pie, 3D, dual y-axis, rainbow/jet/hsv. Mean-only bars at n<10 per group must overlay raw points (`result_plot_policy.refuse_chart_kind`). Empty-effect panels (flat AUROC, empty volcano, no between-group spread) are skipped, not decorated.

## Decision Order

1. Inspect the manuscript TeX/PDF and latest RH `figure_plan`, `publication_pack`, `final_bundle`, and review artifacts.
2. Define a quick figure contract before generation: one-sentence claim, evidence boundary, panel map, archetype, asset route, export needs, and review risks. Load `references/nature-figure-adaptation.md` for multi-panel, Nature-style, or reviewer-facing figure work.
3. Classify existing figures:
   - `placeholder`: `\fbox`, `minipage`, ASCII arrows, text-only mockups.
   - `low_quality_raster`: blurry, low-resolution, screenshot-like, tiny labels.
   - `acceptable_asset`: readable publication graphic with clear provenance.
   - `evidence_gap`: figure is attractive but does not represent recorded evidence.
4. Architecture, method, protocol, graphical abstract, and npj Figure 1 use the RH illustration route via MCP `figure_generate` (`illustration` / `illustration-fake`). Automated RH writing uses this path, including the fake provider when no real route is on. Session ImageGen is an interactive host tool, not the programmatic route.
5. For quantitative charts, use `figure_suite_render` from recorded data (or nature-figure Python/R when the user is iterating a single script). Do not invent numbers in ImageGen or the illustration route.
6. If the illustration route is unconfigured or fails, mark `ILLUSTRATION_PROVIDER_PENDING` and then generate a deterministic SVG/TikZ/PDF diagram as an explicitly labeled `deterministic_local` fallback. Never describe that fallback as provider-generated output. Simple non-hero workflow boxes may start as deterministic local.
7. Never claim that a figure was generated if the image tool or API was unavailable.
8. Do not replace a required illustration-route architecture/method figure with a deterministic local diagram and call it provider output. Record the exact provider route, or mark pending with a missing-env diagnosis.

## Illustration Provider Policy

Use this provider order when speed and quality both matter:

1. `illustration`: first-class programmatic route via `figure_generate`
   (`illustration` / `illustration-fake`). Automated writing uses the fake
   provider when no real backend is on. Real generation runs when
   `RESEARCH_HARNESS_FIGURE_MODEL=illustration` (or the auto-runner default)
   and at least one public backend is configured; RH tries them in order:
   Grok Imagine (`GROK_API_KEY`, optional `GROK_BASE_URL`), GPT Image via an
   OpenAI-compatible endpoint (`GPT_IMAGE_API_KEY`, optional
   `GPT_IMAGE_BASE_URL`), then native Gemini (`GOOGLE_API_KEY`, optional
   `RESEARCH_HARNESS_FIGURE_GEMINI_MODEL`). Only secret-free readiness and
   provenance are recorded.
2. `deterministic_local`: use Python/R/SVG/TikZ for quantitative charts, exact
   labels, and any figure with numeric source data. For experiment/result
   analysis figures, prefer the exemplar-anchored figure contract over one-off
   plotting scripts: plan the whole-paper suite by analogy to target-venue
   exemplars via `rh-exemplar-writing` (`rh exemplar figure-plan`, EAG
   `unit_type=figure_suite`), then render deterministically with
   `figure_suite_render` (`research_harness.visualization.experiment_figures`),
   which composes multi-panel figures with discipline style profiles
   (`stem_conference` / `nature_family` / `social_humanities` / `biomed_omics`).
   A strong experiment plan should normally render multiple forms: grouped
   benchmark bars (with error bars), ablation heatmaps, radar/capability
   profiles, Pareto/efficiency scatter plots, sensitivity or convergence
   curves, and — per discipline — coefficient/forest plots (social science) or
   Kaplan-Meier / volcano / expression heatmaps (biomedical). See
   `docs/FIGURE_CONTRACT.md`. Architecture/method heroes use this route only as
   the labeled fallback after `ILLUSTRATION_PROVIDER_PENDING`.
3. `codex_session_imagegen`: interactive path when the current Codex session
   exposes an ImageGen tool. Record asset provenance. Do not route automated
   RH primitives through a session-only ImageGen tool.
4. `openai_image_api`: use the RH `figure_generate` API path with
   `gpt-image-2` when the user explicitly requires GPT Image 2 and
   `OPENAI_API_KEY` is configured.
5. `fal_legacy`: keep legacy `recraft`, `flux`, and `nano-banana` aliases only
   for environments with `FAL_KEY`.

The reference-driven loop is useful because it separates visual planning from
rendering: retrieve or name a style reference, draft the visual specification,
render one candidate, critique faithfulness/readability/aesthetics, refine only
within the evidence boundary, then record the final prompt summary and caption
constraints. Stop after a bounded number of revisions if the provider is slow.

## ImageGen Workflow

Interactive Codex/session ImageGen only. Automated RH writing and npj Figure 1 stay on the RH illustration route (`figure_generate`).

When using Codex ImageGen:

1. Build one prompt per figure from the RH `figure_plan`, manuscript section, caption, and evidence boundary.
2. Encode the figure contract in the prompt:
   - visual claim and panel role;
   - whether the figure is conceptual, planned, or evidence-backed;
   - requested archetype such as `schematic-led composite` or `asymmetric mixed-modality`;
   - required labels and forbidden labels.
3. Use academic-diagram prompts:
   - white background;
   - crisp vector-like layout;
   - short English labels, usually 2-4 words;
   - no tiny text, watermarks, logos, decorative gradients, or photorealistic effects;
   - restrained palette: neutral family, signal family, and at most one accent;
   - clear arrows, grouping, and hierarchy.
4. Prefer one hero panel plus subordinate evidence/process panels instead of equal-weight clutter when the figure has multiple concepts.
5. Generate wide landscape assets for paper diagrams unless the figure plan clearly needs another aspect ratio.
6. Copy generated files from the Codex generated-images directory into the relevant manuscript workspace; keep the original generated file in place.
7. Update the TeX to use `\includegraphics` for the new asset, preserving the evidence boundary in the caption.
8. Recompile or run the available PDF quality checks.
9. Record a durable RH state update or artifact that includes source figure plan id, generated asset path, prompt summary, figure contract, and any remaining visual limitations.

## Evidence Rules

- Do not turn expected/planned results into observed results.
- Label planned-study diagrams as design or protocol figures, not empirical findings.
- For result figures, use only recorded numbers, tables, or artifacts.
- If generated text in the image is wrong or unreadable, regenerate or replace labels locally; do not ship unreadable labels.
- Prefer diagrams that explain system flow, study protocol, evidence lineage, or review blockers over decorative illustrations.
- Treat statistics, sample size, error definitions, source-data traceability, and image-integrity notes as part of figure readiness for evidence-backed result figures.

## Quality Gate

For a core architecture or method figure in an A-class/CCF-A/high-impact manuscript, a single generated candidate is not enough unless it passes a strict critic review. Generate multiple candidates or run a bounded refinement pass when the first output has typo risk, weak hierarchy, unreadable labels, or does not express the paper's mechanism. Any visible typo, misspelled module label, malformed arrow label, watermark, unreadable small text, or stray explanatory paragraph embedded in the image is a blocking issue.

Run `CCFA_FIGURE_REVIEW_GATE` before accepting an architecture/method figure as CCF-A-target-ready. Provider completion is only an asset-generation event, not a quality decision. The review artifact must score or explicitly judge: contribution clarity, mechanism completeness, information density, label readability at PDF scale, evidence/claim boundary, route provenance, caption fit, absence of stray text blocks, and whether refinement is required. If provenance still says `provider_output_not_human_reviewed`, `quality_not_independently_evaluated`, or no critic findings were recorded for a core figure, mark the figure `review_pending` rather than publication-ready.

Run `RESULT_FIGURE_PUBLICATION_GATE` before accepting quantitative result figures in a CCF-A/high-impact manuscript. Judge whether the figure looks like a publication-quality scientific chart rather than a default script output: typography, panel alignment, spacing, color palette, line width, marker choice, legend placement, axis labeling, unit/direction clarity, uncertainty display, source-data traceability, and consistency across all result figures. Prefer domain-specific scientific-figure templates or reusable RH plotting utilities over one-off Python defaults.

Before calling a figure repaired, verify:

- every manuscript figure is either an acceptable asset or intentionally text/table-based;
- placeholder `\fbox` diagrams have been replaced or explicitly justified;
- labels are readable at final PDF scale;
- captions state whether the figure is conceptual, planned, or evidence-backed;
- image paths are local to the manuscript workspace or RH output bundle;
- result plots have source data or an explicit statement that they are conceptual/planned rather than empirical;
- illustration-required architecture figures have a real provider provenance
  route (`grok_imagine`, `gpt_image`, `gemini_native`, or another real
  provider route); `deterministic_local` is not acceptable for such figures;
- compilation has no new LaTeX errors, undefined citations, or high-severity overfull boxes.

## Boundaries

- Codex CLI supports attaching images as input; it does not provide a stable local `codex image-generate` command for RH Python code to call.
- The session ImageGen tool is an agent capability, not a reproducible RH primitive. Use RH artifacts to record what was generated and why.
- Do not route automated RH primitives through a session-only ImageGen tool.
- For automated non-interactive runs, use a programmable provider such as OpenAI Image API or deterministic SVG/TikZ; do not rely on hidden session-only tools.
- Do not import Nature plotting-backend gates blindly. When this skill uses Codex ImageGen, Python/R selection is not required; backend selection only matters for deterministic charts generated from data.
- Do not import external figure-tool runtime code or temporary gateway
  configuration into RH. Port only stable workflow ideas and provider-policy
  contracts.
- Do not mutate `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `FAL_KEY`, relay/gateway
  settings, or gateway/base-url configuration from this skill.

## References

- `references/nature-figure-adaptation.md` — load for Nature-style figure contracts, archetypes, source-data/export expectations, QA checks, and chart-pattern routing.
