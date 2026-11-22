---
name: rh-paper-figure-generator
description: Generate Research Harness paper figures and architecture diagrams with the RH illustration route (Grok Imagine / GPT Image / Gemini) as the primary architecture-figure provider. Use when creating, revising, or planning academic architecture figures, method overview figures, pipeline diagrams, mechanism diagrams, graphical abstracts, advisor/boss paper figures, CCF-A style method visuals, figure prompts, figure plans, or figure style variants. Enforces RH evidence boundaries, topic-specific mechanism profiles, figure_plan provenance, publication-quality gates, and cross-paper visual diversity.
public_suite: paper
task_type: figure-generation
data_access_level: local-files
inputs: research topic, paper mode, target venue, figure role, mechanism profile, claim boundaries, output path
outputs: figure_plan, provider route, generated figure, caption, provenance, quality-gate notes
gates: figure_contract before provider call, illustration backend readiness, figure-quality review before publication-ready acceptance
artifact_schemas: figure_plan, figure_contract, provenance_record, figure_quality_report
estimated_runtime: 5-30 min
---

# RH Paper Figure Generator

## Objective

Create manuscript-ready academic architecture figures through the RH illustration route, using whichever public image backend is configured (Grok Imagine, GPT Image via an OpenAI-compatible endpoint, or native Gemini). The output is a polished bitmap figure for advisor review or paper drafting, with recorded prompt, caption, evidence boundaries, provider route, and style fingerprint.

Do not default to SVG, HTML, Mermaid, TikZ, or script-drawn vector diagrams. Use those only for post-generation annotation notes, downstream redrawing, or when the user explicitly asks for code-native/vector output.

Quantitative result charts (bars, forests, volcanoes, heatmaps, KM, ROC) are out of scope. Hand those to `figure-quality` → `figure_suite_render`. Do not send a numeric panel to the illustration route.

## Primary Generation Rule

For architecture diagrams and method figures:

1. Before generation, create or update a `figure_contract`/`figure_plan` with communicative intent, visual hierarchy, allowed labels, forbidden labels, typography/readability constraints, evidence boundary, and review failure modes. Do not send an ad-hoc hand-written prompt directly to the provider for a core paper architecture figure.
2. Use RH `figure_generate(model="illustration")` for architecture and method figures when the illustration route is required or expected by the workflow. `figure_generate` now runs an **RH-native `reference_style_selection`** step before the provider call: it curates the topic's own schematic/architecture figures into visual-STYLE exemplars (EAG `unit_type=figure`, native — not the pb_refs stub), retrieves by structure-over-topic, and plans a FORM-only style anchor (layout archetype, palette, geometry, composition) that is injected into the prompt and recorded in figure provenance as `reference_style_selection: {executed: true, reference_paper_ids: [...], conditioning: ...}`. This transfers VISUAL FORM from well-composed published figures, never their method/components. Best-effort: disable with `RESEARCH_HARNESS_FIGURE_STYLE_REF=0`; unavailable exemplars or LLM degrade to unanchored generation (`executed: false`). Grow the anchor pool by ingesting target-venue papers with figures. This is separate from the provider's own quality-loop contract (whose `reference_style_selection` is metadata-only with zero executed rounds).

   **Two conditioning modes.** By default the reference is a *text style anchor* (`conditioning: text_anchor`) injected into the prompt. When `RESEARCH_HARNESS_FIGURE_REF_IMAGES=1` (opt-in, needs a vision backend), RH also VLM-gates the retrieved exemplars' schematic figures and attaches them to the provider request as reference images; provenance records `conditioning: image` and `reference_image_count`. The current public backends render text-to-image, so attached reference images are recorded but not yet consumed by the render call. This degrades to the text anchor when no vision backend or no extractable reference figures are available.
3. The illustration route tries the configured public backends in order: `grok_imagine` when `GROK_API_KEY` is set, `gpt_image` when `GPT_IMAGE_API_KEY` is set, then `gemini_native` when `GOOGLE_API_KEY` is set.
4. Record the exact provider route in `figure_plan` and figure provenance. Do not describe a deterministic local diagram, SVG, TikZ, Mermaid, or script-rendered graphic as provider output.
4. If the illustration route is required but no backend is configured or the provider call fails, produce a complete `figure_plan`, mark `ILLUSTRATION_PROVIDER_PENDING`, list the missing backend keys, and then generate a deterministic local diagram as an explicitly labeled fallback (route `deterministic_local`, never described as provider output) so the manuscript still ships with a real architecture figure. A provider failure must never result in a figure-less final PDF; the write gate blocks `figure_plan` records that report a failed provider with no figure asset.
5. If the user explicitly requires GPT Image 2, `gpt-image-2`, "direct", or "must call the model", use the local imagegen CLI/API path with `--model gpt-image-2`. This is a hard route requirement.
6. Do not satisfy an explicit GPT Image 2 requirement with a model-opaque built-in image tool, even if it can generate a visually similar bitmap.
7. If the user later explicitly authorizes built-in prompt-mode image generation despite missing local API key/model controls, use the built-in `image_gen` tool and record the route as `USER_AUTHORIZED_BUILTIN_IMAGEGEN_PROMPT_MODE`.

For illustration-route execution, configure one of `GROK_API_KEY`, `GPT_IMAGE_API_KEY`, or `GOOGLE_API_KEY`, then call `figure_generate(model="illustration")`. For explicit GPT Image 2 execution, follow the system `imagegen` skill and use `gpt-image-2`, `quality=high`, with a landscape size such as `2048x1152` or `3840x2160` when dense labels are needed.

## RH Inputs

Before writing the prompt, collect or infer:

- paper mode: `actual_result`;
- target venue/style level;
- method name and one-sentence thesis;
- key components and data flow;
- claim boundaries: observed, planned, target, or hypothetical;
- figure role: architecture overview, pipeline, mechanism detail, graphical abstract, or ablation/evaluation map;
- topic mechanism profile: paper-specific visual thesis, technical tension, state variables, alignment/control targets, result effect, and interpretability surface;
- citation/related-work anchors if the figure compares method families;
- output path under the project, normally `06-writing/figures/`.

Topic-specific mechanisms belong in RH artifacts, project files, or the current `figure_plan`, not in this reusable skill. If no topic profile exists, create one before prompting the figure. Keep target-result boundaries in metadata or figure notes, not as in-figure disclaimers.

## Figure Plan Contract

Every figure task must produce or update a `figure_plan` containing:

- `figure_id`
- `mode`
- `figure_role`
- `main_message`
- `topic_mechanism_profile`
- `components`
- `flow`
- `style_fingerprint`
- `illustration_prompt`
- `provider_route`
- `gpt_image_2_prompt` if GPT Image 2 is explicitly requested
- `caption`
- `claim_boundaries`
- `output_path`
- `generation_status`
- `revision_notes`

If RH artifact tools are unavailable, save the plan under the workspace and mark `RH_SYNC_PENDING`.

## Visual Diversity Gate

Do not reuse the same academic diagram style across papers. Before generation, choose a style fingerprint and record it.

Style fingerprint fields:

- `layout_archetype`: left-to-right pipeline, radial hub, layered stack, cyclic loop, swimlane, matrix grid, hourglass, control-plane overlay, split-screen comparison, or timeline-to-forecast.
- `palette_strategy`: restrained monochrome plus accent, warm editorial, cool technical, earth/science palette, grayscale with semantic highlights, print-safe CMYK-like, high-contrast dark, or domain-specific palette.
- `geometry_language`: rounded modules, sharp technical blocks, thin-line blueprint, layered translucent slabs, node-link graph, tabular lanes, annotated cards, or instrument-panel labels.
- `depth_model`: flat vector-like, subtle paper cutout, isometric, layered glass-free depth, or schematic blueprint.
- `typography_mood`: compact conference figure, clean journal figure, editorial graphical abstract, or dense systems diagram.

Hard rules:

- Do not default to blue-purple gradients.
- Do not use the same `layout_archetype + palette_strategy + geometry_language` as the previous figure unless the user asks for a consistent figure series.
- Do not make decorative orbs, generic AI networks, glowing brains, or stock sci-fi backgrounds.
- Do not use nested cards as the default structure.
- Use semantic color: each color must correspond to a component family, stage, or evidence status.

## Topic Mechanism Profile

Before generating a paper-specific figure, write or load a topic mechanism profile. This is where paper-specific names and mechanisms belong.

Profile fields:

- `research_object`: what the method operates on.
- `technical_tension`: the concrete failure mode or bottleneck the paper solves.
- `central_process`: how raw evidence becomes a controllable model state or decision.
- `state_variables`: dynamic quantities, memories, gates, uncertainty estimates, control signals, or representations.
- `alignment_or_control_targets`: what must be aligned, constrained, calibrated, routed, or optimized.
- `result_effect`: what changes in the output and how the figure should make that visible.
- `interpretability_surface`: attribution, audit, explanation, verification, or human-readable trace.
- `visual_priority`: what must visually dominate the figure.
- `forbidden_generic_fallback`: generic layouts or symbols that would erase the paper's contribution.

Do not hard-code a topic profile into this skill. A forecasting paper, graph-learning paper, database paper, security paper, or robotics paper should all reuse the same mechanism gate with different profiles.

## Contribution Mechanism Gate

Before prompting an architecture or method figure, define the figure's mechanism spine. Reject prompts that would produce only a title plus boxes.

Required fields:

- `visual_thesis`: what one technical idea the reader should remember.
- `scenario_tension`: what problem the method solves in this specific task, such as event timing, stale evidence, leakage, drift, or forecast-origin safety.
- `mechanism_spine`: the ordered internal logic, not just module names.
- `dynamic_state`: what changes over time and how updates/retractions are represented.
- `alignment_target`: what is being aligned, calibrated, or constrained.
- `interpretability_endpoint`: how the figure shows why the final forecast is explainable or auditable.

For CCF-A-style method figures:

- Make the layout regular, spacious, and grand, but information-dense enough to show real architecture complexity.
- Use 4-6 structured zones and at least three visual mechanism layers: evidence/event processing, state update/alignment, model/fusion/correction, plus output/audit when relevant.
- Let visuals carry the technical story: timelines, memory ledgers, state machines, gates, distribution curves, rolling windows, alignment bridges, attribution ribbons, audit panels, and feedback loops should explain the method even if the caption is removed.
- Text should name components, not replace the diagram's content. Avoid prompt designs where labels are the main evidence of complexity.
- Reject a draft if the contribution could be summarized as a simple left-to-right pipeline after removing the title.

## Publication Figure Baseline

Adopt these reusable basics from strong public figure-generation workflows:

- Classify the figure first: mechanism diagram, system architecture, pipeline, workflow, comparison, evaluation plot, ablation plot, or multi-panel hybrid.
- Use AI image generation for conceptual/mechanism diagrams; use deterministic plotting code for numeric result figures when exact data or axes matter.
- Set a document-type quality threshold before iterating: advisor sketch, internal draft, camera-ready paper, slide adaptation, or editable handoff.
- Check publication basics: readable typography at final size, no overlap, consistent fonts, semantic colors, colorblind-safe contrast, clean margins, and appropriate raster/vector export path.
- Scan for micro-defects that survive a casual look but fail review (observed in the 2026-07-02 EventGraph final): crowded or overlapping legends, truncated or abbreviated tick labels ("entertain."), rotated annotations that are illegible at print size, and axis units missing from any panel. Fix these before accepting the figure; for deterministic plots, regenerate with adjusted layout rather than post-editing the image.
- Iterate only on failed quality gates. Prefer one targeted regeneration/change over repeated full rewrites.
- For complex figures, separate visual content from caption content. Use labels for names and states; use the caption for long explanations.

## Provider Prompt Structure

Use a compact structured prompt:

```text
Use case: scientific-educational / infographic-diagram
Asset type: academic paper architecture figure
Canvas: landscape, clean whitespace, paper-ready, no watermark
Main message: <one sentence>
Figure title text: "<short exact title>"
Layout archetype: <chosen archetype>
Visual style fingerprint: <palette, geometry, depth, typography>
Mechanism spine:
- <scenario tension>
- <dynamic update>
- <alignment/calibration>
- <interpretability/audit endpoint>
Components:
1. <component label>: <visual role and contents>
2. ...
Flow:
- <arrows and dependencies>
Visual evidence:
- <what non-text visual objects must show>
Evidence/status encoding:
- <observed/planned/target if relevant>
Text constraints:
- Use only the exact labels listed.
- Keep labels short, crisp, and readable.
- Do not invent extra labels or paragraphs.
Avoid:
- generic neural-network decoration, stock AI imagery, decorative gradients, illegible tiny text, extra icons, watermark, logo
```

Because generated diagrams can distort dense text, keep in-image text short. Prefer 5-9 major labels and avoid long sentences. Put detailed explanations in the caption or manuscript, not inside the image.

## Quality Gates

Before delivering:

- The figure has one memorable message.
- The architecture is not a module dump.
- The core contribution is visible as a mechanism, not only as labeled boxes.
- The scenario tension, dynamic update, alignment target, and interpretability endpoint are visible.
- Data flow is readable from left to right, top to bottom, or by the chosen archetype.
- Labels are short and exact.
- The figure distinguishes data, event knowledge, model, calibration, and evaluation.
- The figure's content remains technically meaningful if the title is removed.
- Visual style is distinct from prior RH paper figures.
- No unsupported result claim appears inside the figure.
- The caption states the claim boundary if needed.
- The output path and prompt are recorded.

## Output Contract

When creating a figure, return:

1. `RH 优化目标` if responding to a user critique or durable figure requirement.
2. `Figure Plan`
3. `Style Fingerprint`
4. `Illustration Prompt` and `Provider Route`; include `GPT Image 2 Prompt` only
   when GPT Image 2 is explicitly requested.
5. `Caption`
6. `Generation Status`
7. `Next Revision Options`

If generation succeeds, include the saved image path and provider route. If
the illustration route is required but unavailable, mark `ILLUSTRATION_PROVIDER_PENDING`
instead of substituting a local diagram. If an explicit GPT Image 2 route cannot
run because `OPENAI_API_KEY`, dependencies, network, or API access are
unavailable, mark `IMAGEGEN_PENDING_DIRECT_GPT_IMAGE_2`, state that no
model-opaque substitute was used, and provide the exact `gpt-image-2`
command/prompt to run.
