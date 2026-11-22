# Nature Figure Adaptation for RH Figure Quality

This reference adapts Nature/high-impact-journal figure guidance for Research Harness manuscripts. Use it when a manuscript has reviewer-facing visual blockers, multi-panel figures, Nature-style expectations, or a request to improve image quality with Codex ImageGen.

Do not copy private local paths or template provenance into user-facing output. Apply the principles, not the source wording.

## Core Rule

A paper figure is a visual argument. Before generating, redrawing, or replacing an asset, define what claim the figure must defend and how each panel supports that claim. Visual polish is subordinate to scientific logic, evidence traceability, and readability at final PDF scale.

## Figure Contract

Write this contract before creating the figure asset:

- `claim`: one sentence stating the conclusion or role of the figure.
- `evidence_boundary`: `conceptual`, `planned_protocol`, `evidence_backed`, or `mixed`; state which parts are observed data.
- `panel_map`: each panel's purpose and the evidence it contributes; remove panels that do not add a distinct point.
- `archetype`: one of `quantitative_grid`, `schematic_led_composite`, `image_plate_plus_quant`, or `asymmetric_mixed_modality`.
- `asset_route`: `codex_session_imagegen`, deterministic SVG/TikZ, Python/R chart, `openai_image_api`, optional `gemini_nano_banana`, legacy `fal_legacy`, reused empirical image, or mixed route.
- `export_contract`: target dimensions, file formats, text readability, local asset path, and whether source data/statistics are required.
- `review_risks`: likely reviewer objections such as invented data, unreadable labels, missing n/statistics, over-decorated diagrams, or unclear relation to the manuscript claim.

Record the contract in the RH artifact/state update when the figure is material to publication readiness.

## Archetypes

- `quantitative_grid`: multiple metrics, methods, datasets, ablations, trends, or heatmaps. Use deterministic charting from recorded data. Export SVG/PDF/TIFF/PNG as appropriate; do not use ImageGen for numeric values.
- `schematic_led_composite`: a large mechanism, workflow, protocol, or evidence-lineage panel with smaller supporting panels. Codex session ImageGen is appropriate for the schematic portion if labels are controlled and evidence boundaries are clear; automated runs should use an explicit programmable provider such as `openai_image_api` or an explicitly configured `gemini_nano_banana` route.
- `image_plate_plus_quant`: microscopy, screenshots, frames, field images, or model-output examples plus quantitative summaries. Preserve real image integrity; do not synthesize evidence images. ImageGen may only supply non-evidentiary schematic context.
- `asymmetric_mixed_modality`: one hero panel plus charts, tables, or process panels. Use a mixed route: generated schematic for conceptual structure, deterministic plots for numbers, and real images for evidence.

Prefer one hero panel plus subordinate evidence/process panels over filling the canvas with equal-sized subplots.

Refuse pie charts, 3D charts, dual y-axes, and rainbow/jet maps. If n<10 per group, overlay raw points on any bar; do not ship a mean-only column. Skip a panel that has no signal (empty volcano, AUROC indistinguishable from chance, heatmap with no row variance) instead of decorating it.

## Route Selection

- Use Codex session ImageGen for conceptual mechanisms, protocol diagrams, pipeline overviews, evidence-flow diagrams, reviewer-blocker explanations, and planned-study visuals when the current host exposes it. Treat that as an interactive asset route, not a reproducible Python primitive.
- Use deterministic SVG/TikZ for simple boxes, arrows, timelines, and workflows when text precision is more important than rich imagery.
- Use Python/R charting for bars, trend lines, heatmaps, radar plots, scatter plots, error bars, confidence intervals, and any figure with numeric claims.
- Use original empirical images for screenshots, video frames, microscopy, or domain images; generated imagery must not masquerade as observed evidence.
- For mixed figures, create separate assets for generated schematic panels and deterministic result panels, then compose them in TeX or a reproducible script.

## Visual Standards

- Background should be white for diagrams and plots; dark backgrounds are reserved for genuine image plates where the source modality needs it.
- Use direct labels instead of legends when categories have stable positions or legends would force unnecessary eye travel.
- Use a restrained palette: one neutral family, one signal family, and one accent family. Reserve red/green mainly for directional gain/drop annotations.
- Keep labels short, large, and editable when possible. Avoid tiny text, long sentence labels, watermark-like marks, logos, dense gradients, and ornamental effects.
- Maintain consistent color semantics across panels.
- Align panels by evidence logic, not by making all panels the same size.

## Source Data and Export Readiness

Evidence-backed result figures are not ready until the underlying data and statistical meaning are clear:

- state `n`, statistical test or descriptive statistic, error-bar meaning, and source-data path when relevant;
- keep plot exports as editable SVG/PDF where practical, plus high-DPI raster for final bundles when required;
- preserve real image provenance and integrity notes for screenshots, microscopy, video frames, or model outputs;
- never ask ImageGen to create a chart from imagined data or to draw empirical images that did not exist.

For Codex ImageGen assets, preserve the generated original, copy the chosen image into the manuscript workspace, and store a small prompt/contract summary in the RH artifact payload.

## Pattern Routing

- Method comparison or ablation bars: deterministic chart, grouped bars, consistent method colors, print-safe hatching if needed.
- Multi-metric benchmark grids: wide layout, shared palette, readable axis labels, separate legend panel if the legend is large.
- Study protocol or system pipeline: ImageGen or SVG schematic, 3-7 stages, direct labels, clear arrows, no fabricated outcomes.
- Evidence lineage or claim map: schematic-led composite; emphasize source-to-claim flow and mark uncertain/planned steps.
- Trend over time: deterministic line/area chart, direct event annotations, tightened y-axis only when it does not distort interpretation.
- Heatmap or matrix: deterministic chart, readable labels/colorbar, explicit scale and source data.
- Image plate plus quantification: real image panels with scale/context when available, deterministic quant panel, separate conceptual inset only if needed.

## QA Checklist

Before accepting a repaired figure:

- The figure contract is explicit and matches the manuscript section and caption.
- Every panel has a unique evidentiary or explanatory role.
- Conceptual/planned/evidence-backed status is visible in the caption or surrounding text.
- Numeric claims come from recorded data and are not embedded in generated imagery.
- Labels remain readable at final PDF size.
- Color, label, and panel semantics are consistent across the figure.
- Local manuscript assets, source data, and generated originals can be traced.
- The compiled PDF has no placeholder boxes, broken paths, or newly introduced layout errors.
