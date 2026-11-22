---
name: rh-paper-production
description: End-to-end Research Harness paper-production workflow for academic manuscript tasks. Use when the user provides a 科研题目, research topic, target journal, 目标期刊, asks to 写论文, draft related work, design experiments, create architecture figures, plan baselines/benchmarks, build a paper pool, or produce CRediT authorship statements for p1-p8.
public_suite: paper
task_type: paper-production
data_access_level: local-files
inputs: research topic, target venue, paper mode, workspace artifacts, evidence records, figure requirements
outputs: manuscript sections, paper plan, figure tasks, evidence gates, provenance records, publication bundle readiness
gates: RH skill doctor health check, evidence/provenance gate, figure-quality gate for architecture figures, final bundle quality gate
artifact_schemas: paper_plan, evidence_record, provenance_record, figure_plan, publication_pack, gate_report
estimated_runtime: 30-180 min
---

# RH Paper Production

## Operating Contract

Require only two user inputs before starting: research topic or title, and target journal or venue. Infer reasonable defaults for article type, contribution shape, and workflow stage, then proceed.

If the project provides a paper-production workspace profile, read it before creating topic artifacts or manuscript outputs. Prefer reusable project docs such as `docs/paper-production-workspace.md` and `docs/research-bootstrap.md` over hard-coded personal paths. If no project-specific profile exists, use the generic defaults in `docs/paper-production-workspace.md`: RH remains the source of truth, local generated outputs stay under ignored workspace state, and committed files are limited to reusable protocols, sanitized examples, and public documentation.

Use Research Harness (RH) as the primary system of record for research facts, papers, claims, evidence, artifacts, provenance, and stage gates. Use Codex web search and local files as fallbacks or complements, and record provenance for every fallback result. For paper architecture figures and method visuals, route to `rh-paper-figure-generator`, which uses the RH illustration route (Grok Imagine / GPT Image / Gemini) as the primary architecture-figure path unless the user explicitly requests GPT Image 2. In Claude Code or Codex sessions, RH loading is not considered healthy until `rh skill doctor --agent claude-code --agent codex` reports the critical skills installed, or the failure is explicitly reported.

Keep long-lived rules in this skill and public docs, and keep durable topic content in RH artifacts or ignored local workspace state. Do not duplicate the workflow rules into every topic folder. Do not commit generated paper-production run outputs such as manuscript PDFs, TeX build products, status JSON, progress logs, local databases, downloaded papers, or files containing personal machine paths.

For Introduction/引言 drafting or revision, route section-specific work to `rh-ccf-a-introduction-writer` after this paper-production skill establishes topic state, writing mode, and artifact lineage. For architecture figures, method overview figures, graphical abstracts, or figure prompts, route section-specific work to `rh-paper-figure-generator`. For designing or auditing the paper's SECTION ARCHITECTURE / skeleton, INTRODUCTION arc, ABSTRACT element order, PROSE STYLE, or RESULT-FIGURE SUITE (experiment/analysis figures: chart choices, multi-panel composition, discipline style) by analogy to high-quality published exemplars from the target venue ("stand on the shoulders of giants", transferring FORM not CONTENT), route to `rh-exemplar-writing` (the Exemplar-Anchored Generation engine; `rh exemplar curate|plan|generate|figures`); result-figure suites render deterministically from recorded experiment records via `figure_suite_render` and pass `figure-quality`'s `RESULT_FIGURE_PUBLICATION_GATE` before acceptance. Before declaring a manuscript submission-ready or assembling the final bundle, run first-class final-draft polish via `rh-manuscript-polish` (`rh polish run`): a `manuscript_polish_report` with `submission_readiness` of `blocked` (any high-severity finding) or `needs_revision` (any medium) must be resolved — with `section_revise` / `citation_sanitize` / `rh-exemplar-writing` — or explicitly human-waived, before final.

## Dataset-First Topic Fit

For engineering or science topics that require model training, run a dataset-first check before literature synthesis, experiment design, or drafting goes deep.

- Treat the user's initial topic as adjustable within its intent. Slightly revise the topic, task framing, target variable, dataset scope, or method angle if that is necessary to make the research trainable and evidence-backed.
- Training data is mandatory for trainable engineering/science topics. Do not proceed with a training-dependent design that has no plausible training dataset.
- Prioritize open-source/public datasets absolutely. Prefer datasets with stable URLs, licenses or access terms, field descriptions, train/test protocol, and prior usage in papers or benchmarks.
- If no exact public dataset exists, search for close substitutes and propose a topic adjustment that preserves the user's core intent while matching available data.
- If no suitable public or close-substitute dataset exists, produce a concrete dataset-generation or data-collection plan before proceeding. Include source channels, fields, labels, scale, annotation strategy, quality controls, privacy/licensing assumptions, expected cost/time, and whether the resulting work should remain a proposal rather than an empirical paper until data exists.
- Do not expose `blocked`, `proposal-stage`, or equivalent status labels in the manuscript body. Preserve that status in artifact metadata and, for PDF delivery, on a standalone final boundary page only.
- Record this check in `dataset_survey` with provenance, rejected datasets, selected dataset, topic-adjustment rationale, and remaining risks.

## Paper Writing Modes

For paper-writing tasks, use the `main` result-expression mode:

1. `main` (`actual_result`)
   - Purpose: full experiment workflow, formal manuscript, experiment report, submission-facing draft, or any artifact that claims completed evidence.
   - Run or consume completed experiments before writing final empirical claims.
   - Result language must follow observed RH/local experiment artifacts exactly.
   - Baseline comparisons, tables, ablations, and conclusions must distinguish `observed`, `reported_baseline`, `planned`, and `hypothetical`.
   - Do not upgrade MSE-only wins, partial-domain wins, or expected results into full SOTA claims.


Always use the `actual_result` boundary: final submission wording, experiment summaries, current-results wording, and completed-run reporting state only completed or cited evidence.

## RH Entry Sequence

1. Discover or resume topic state:
   - Call `topic_list`.
   - If a likely topic exists, call `topic_show(name)` and `orchestrator_status(topic_id)`.
   - If a topic exists but the workflow is not active, call `orchestrator_resume(topic_id)` before writing durable outputs.
   - If no topic exists and no topic-creation tool is exposed, continue with local topic files under the workspace and mark all durable outputs `RH_PENDING_TOPIC_ID`; tell the user that RH artifact recording can start once a topic exists.
2. Record every durable output with `orchestrator_record_artifact` when a `topic_id` is available.
3. Check stage readiness with `orchestrator_gate_check` before advancing.
4. Advance only after required artifacts are present and evidence gaps are explicit.

Preferred RH tools:

- Discovery and state: `topic_list`, `topic_show`, `orchestrator_status`, `orchestrator_resume`.
- Literature: `paper_search`, `paper_ingest`, `paper_list`, `paper_summarize`, `claim_extract`, `evidence_link`, `gap_detect`, `baseline_identify`.
- Drafting and QA: `section_draft`, `consistency_check`, `provenance_summary`.
- Artifacts: `orchestrator_record_artifact`, `orchestrator_gate_check`, `orchestrator_advance`.
- Version commits: `paper_commit_version` (MCP) or
  `rh paper-production commit-version --topic <id> --tex <file> --pdf <file>
  [--quality-report <json>] [--depends-on <artifact_id>]` — one call hashes
  the files, records draft_pack + final_bundle (+ quality report) with
  lineage wired, and rejects the commit if a `--depends-on` artifact is
  superseded. Use it for every manuscript version instead of manual `shasum`
  plus separate `orchestrator_record_artifact` calls; never chain a new
  version onto a superseded draft.
- Zotero: `zotero_sync` when bibliography or PDF annotation sync is requested.

Rerunning in a topic that already has manuscript artifacts:

- Start with `rh paper-production reset-run --topic <id> --dry-run` to see
  which prior-run content artifacts are still active, then run it without
  `--dry-run` to supersede them all in one pass and invalidate the cached
  literature overview. Do not supersede artifacts one by one or edit
  `project_artifacts` with raw sqlite.
- The reset never touches decision history (`gate_decision`,
  `rollback_event`, `provenance_record`, `human_feedback_record`); those
  stay active as the audit trail.

`consistency_check` usage contract:

- Pass the actual manuscript section text in `sections`; the cached topic
  literature overview is injected separately as reference-only context.
- On a rerun, scope change, or when findings cite old drafts/synthesis that
  are no longer canonical, call it once with `refresh_context: true` (or run
  `rh topic summary-refresh <topic_id>`) instead of superseding artifacts one
  by one.
- Findings carry a `source` field: fix `manuscript` findings in the TeX;
  `literature_context` findings usually mean the cached overview is stale or
  broader than the paper — refresh the context or add a scope-boundary
  sentence, do not rewrite the manuscript to match a stale overview.
- Do not loop compile→record→recheck on one finding at a time; the checker
  reports all findings in a single pass, so batch the fixes and re-record one
  artifact version per batch.

## Required Artifact Lineage

Create or update these artifact types in order. Use the same names as `artifact_type` values when recording to RH.

1. `topic_brief`
   - Include topic, target journal, article type, intended contribution, constraints, expected outputs, and open questions.
2. `dataset_survey`
   - For trainable engineering/science topics, include public dataset search queries, candidate datasets, stable URLs/DOIs, licenses or access terms, task mapping, fields, target labels, scale, quality concerns, selected dataset, rejected alternatives, topic-adjustment rationale, and fallback generation/collection plan if no suitable public dataset exists.
3. `paper_pool`
   - Include search queries, providers, filters, result metadata, tier, year, DOI/arXiv/URL, inclusion/exclusion decision, and reason.
4. `literature_map`
   - Group related work by research route, technical bottleneck, dataset/benchmark, and evaluation paradigm. Do not list papers one-by-one as the main structure.
5. `deep_read_synthesis`
   - For core papers, capture problem, method, data, metrics, results, limitations, reusable ideas, and citation-ready claims.
6. `experiment_design`
   - Include public benchmarks, metrics, baseline methods, baseline result provenance, planned ablations, and expected result tables.
7. `figure_plan`
   - Include architecture figure plan, experiment figures, result tables, ablation plots, visualization panels, ImageGen prompt, and output path.
8. `draft_pack`
   - Include manuscript outline, section drafts, citation map, unresolved evidence gaps, revision notes, and writing mode. Introduction drafts should include paragraph-role maps and claim-evidence maps from `rh-ccf-a-introduction-writer`.
9. `authorship_statement`
   - Include the final `CRediT authorship contribution statement` using author placeholders `p1` through `p8`.

When recording artifacts, include dependency artifact IDs whenever an output consumes earlier artifacts.

## Literature Rules

Default search policy:

- Use `paper_search` with `year_from=2025`, `year_to=2026`, `max_results >= 50`, and a high-tier filter.
- Use `tier_filter="ccf_b"` for CS conference-style targets.
- Use `tier_filter="cas_q2"` for journal-style targets.
- For cross-domain topics, run separate CCF-B-or-above and CAS-Q2-or-above searches, then merge and deduplicate.
- Start with `auto_ingest=false` for query calibration. Use `auto_ingest=true` only after the search query and filters are acceptable.

Screening policy:

- Prefer CCF-B or higher and Chinese Academy of Sciences Q2 or higher.
- Prefer 2025 and 2026 papers.
- If fewer than 40 usable papers remain after screening, broaden deliberately:
  - First expand to 2024.
  - Then expand to earlier foundational papers.
  - Then lower tier only if necessary.
- Every broadened paper must include a `relaxation_reason` in `paper_pool`.
- Every included paper must have DOI, arXiv ID, URL, or another stable source identifier when available.
- Before delivering a final PDF, check the manuscript bibliography count against
  the screened `paper_pool`. For RH paper-production drafts, fewer than 40 usable
  screened papers is a blocking issue unless the final standalone boundary page
  explicitly states that the literature pool is incomplete and the user has asked
  for a non-final interim draft. Do not call such a PDF a final manuscript.
- Run `PAPER_POOL_CONSISTENCY_GATE` before calling any PDF final, rerun-complete,
  advisor-ready, or CCF-A-target-ready: the manuscript bibliography, `paper_pool`,
  `figure_plan`, figure provenance, and control/handoff summary must agree on
  reference count, figure route, claim boundary, and readiness label. If any local
  artifact is stale, update it or mark the bundle `artifact_sync_blocked`.
- The manuscript reference list should normally include at least the core cited
  subset needed to support every related-work category, dataset/baseline claim,
  method lineage claim, and experiment design choice. A short hand-written
  bibliography is not acceptable when the RH paper-pool threshold has not been
  met.

Related-work policy:

- Write synthesis by category, not chronological summaries.
- Compare research routes, assumptions, benchmarks, evaluation metrics, limitations, and unsolved gaps.
- Link important claims to paper IDs or evidence IDs. Do not make unsupported novelty claims.

## Experiment Rules

Use only public benchmarks or datasets unless the user explicitly provides private data access details.

For engineering/science topics that require training, do not finalize `experiment_design` until `dataset_survey` identifies a viable training dataset, a topic-adjusted public dataset route, or an explicit dataset-generation/collection plan. If only a generation/collection plan exists, mark empirical claims as `blocked` or `proposal-stage` in metadata until data is actually available, and put that boundary only on the standalone final PDF page.

Baseline rules:

- Baseline methods must be real published systems, leaderboard entries, or reproducible public reports.
- Baseline numbers must come from original papers, benchmark leaderboards, official reports, or clearly cited reproduction sources.
- Never invent baseline performance.
- If a baseline value is unavailable, mark it `missing_public_result` and explain how it would be obtained.

Proposed-method result rules:

- It is acceptable to draft ideal but reasonable expected values for the user's proposed method.
- Idealized values must be constrained by real baseline values, dataset scale and noise, metric sensitivity, the method's expected mechanism, comparable gains in related papers, and the target venue's credibility expectations.
- Mark every such value as `expected`, `planned`, or `hypothetical_until_validated`.
- Do not present expected values as completed experiments.
- In `main` mode, remove idealized wording and report only validated results, planned work, and limitations with explicit status labels.

The `experiment_design` artifact must separate:

- `observed_baseline_results`
- `expected_proposed_results`
- `planned_ablation_results`
- `validation_needed`

## Method Revision Patterns

When strengthening a manuscript method section from a reference paper, transfer structure only, not claims or prose. Useful structure to extract:

- Formal problem definition before the proposed method.
- Method overview with component-level data flow.
- Module input/output/design-motivation table.
- Algorithm 1 for the end-to-end training/inference workflow.
- Algorithm 2 for the most important preprocessing, prior construction, or representation step.
- Explicit training/inference separation, validation selection, leakage controls, loss function, and complexity analysis.

The final method text must describe the research method itself, not the agent's reasoning process. Remove process phrases such as "compared with the first draft," "the boss decision version," "our current idea," or "this is just a feature concat improvement" unless they are part of a non-manuscript revision note.

## Figures And Manuscript

Default English manuscript layout is single-column: `\documentclass[11pt]{article}` with `\usepackage[margin=1in]{geometry}` (the RH `arxiv` template in `latex_compiler.py`). Do not hand-write `twocolumn` document options or `\twocolumn[` blocks. Use a two-column layout only when the user explicitly requests it or the declared target venue's official template is two-column (e.g., AAAI/ICML via the RH venue templates); record that trigger in the run notes. When converting an existing two-column draft to single column, also demote `figure*`/`table*` floats, remove `\resizebox{\columnwidth}` stretch wrappers so small tables keep natural size, and cap single-plot figures near `0.6\textwidth`.

For npj Figure 1 / overview / architecture hero figures, use the RH illustration route via MCP `figure_generate` (`illustration` / `illustration-fake`), same as other architecture diagrams through `rh-paper-figure-generator` and the `figure-quality` router. The primary path is RH `figure_generate(model="illustration")`, with route provenance from the actual backend: `grok_imagine`, `gpt_image`, or `gemini_native`, tried in that order among those configured. When the user explicitly requires GPT Image 2 or a direct GPT Image model call, the route must expose or guarantee `gpt-image-2`; do not substitute a model-opaque built-in generator. Prefer the provider route over hand-drawn SVG/HTML/Mermaid/TikZ/scripts when the provider is available. Record the illustration prompt, provider route, generation date, style fingerprint, intended caption, claim boundary, and output path in `figure_plan`. If the illustration route is required but unconfigured or fails (HTTP error, no image asset), mark `ILLUSTRATION_PROVIDER_PENDING` AND generate a deterministic local architecture figure (TikZ/SVG/script-rendered), record its route honestly as `deterministic_local` fallback (never describe it as provider output), and include it in the PDF so the manuscript is never delivered without an architecture figure. Replace the local fallback with the provider output once the provider recovers. Shipping a figure-less final bundle is a write-gate blocker (`figure_fallback_policy` / `manuscript_visual_completeness`).

The manuscript must include a `CRediT authorship contribution statement` section after the conclusion and before references or appendices. Use placeholders `p1` through `p8`.

Default CRediT template:

```text
CRediT authorship contribution statement

p1: Conceptualization, Methodology, Writing - original draft.
p2: Methodology, Software, Validation.
p3: Data curation, Investigation, Formal analysis.
p4: Resources, Benchmark curation, Visualization.
p5: Writing - review & editing, Validation.
p6: Supervision, Project administration.
p7: Funding acquisition, Resources.
p8: Supervision, Writing - review & editing.
```

Adjust roles to match the actual project if the user gives author responsibilities.

## CCF-A Target Manuscript Quality Gates

Run these reusable gates before calling any computer-science manuscript `advisor-ready`, `CCF-A-target-ready`, or `rerun-complete`. They are generic RH quality controls, not topic-specific fixes.

### TITLE_ABSTRACT_CONTRIBUTION_GATE

- Title must foreground the method name when one exists, the technical mechanism, and the task boundary. Avoid generic titles that only name the application area.
- Abstract must synthesize the method at a professional level: problem abstraction, core mechanism, validation protocol, concrete result pattern, and significance. Avoid pipeline-only summaries.
- Contributions must state theoretical or formulation novelty, technical mechanism novelty, evaluation/protocol novelty, and concrete metric gains.

### NUMERIC_CONSISTENCY_GATE

- Check every reported number against the manuscript tables, figures, captions, and prose.
- Verify metric direction before describing gains: lower-is-better metrics need reductions; higher-is-better metrics need increases.
- Convert absolute and relative improvements correctly, and do not mix normalized anchors with source-paper units unless the conversion is explicitly recorded.
- If accuracy, recall, F1, precision, error, latency, or normalized score appear together, check that the relationships are arithmetically and conceptually possible.

### RELATED_WORK_SYNTHESIS_GATE

- Related work must be organized by research route, technical bottleneck, dataset/protocol family, or evaluation paradigm, not by chronological paper list.
- Each route should include a synthesis claim, representative strong papers discussed in more depth, shared limitations, and the specific gap addressed by the current method.
- Avoid one-sentence-per-paper narration. If many citations are needed, group secondary citations after a route-level claim.
- Important novelty claims must connect to evidence records or paper IDs.

### RESULT_EVIDENCE_DENSITY_GATE

- A CCF-A target result section should normally include multiple evidence surfaces: protocol-specific main results, source-metric reconciliation, ablations, leakage or mechanism diagnostics, sensitivity/robustness, efficiency, perceptual or human evaluation when relevant, and failure/qualitative analysis when safe.
- Prefer wide, readable, information-rich tables over many cramped mini tables. Table columns must separate dataset/protocol, metric unit/direction, baseline source, proposed-method value, and validation status when those concepts differ.
- Do not use a single mixed leaderboard when baselines report incompatible datasets, units, or perceptual protocols. Split tables by protocol.
- Figures and tables should show enough experimental breadth that the result section reads as a serious validation plan or evidence report, not a small demo.

### ANTI_DEFENSIVE_WRITING_GATE

- Preserve necessary scope, evidence, ethics, safety, legal, and methodological limits, but remove unnecessary defensive writing from the main argumentative path.
- Do not scatter repeated phrases such as "does not claim," "not intended," "should not be interpreted," "before submission-facing use," or similar caveats through abstracts, introductions, contributions, results topic sentences, or conclusions.
- Do not put venue-target or planning meta-language in the manuscript body: phrases such as "CCF-A target," "target evidence pattern," "target validation protocol," "advisor draft," "dream mode," "submission-facing," "idealized result," and "validation target" belong in RH metadata, handoff notes, or the standalone boundary note, not in the paper's scientific argument.
- Convert defensive or appeasing phrasing into positive scope: state what the paper studies, proves, compares, or contributes. Put unavoidable evidence-boundary caveats in RH metadata or the limitations section.
- Limitations should be concise and calibrated. Do not volunteer excessive reviewer attack surfaces; explain scope and deployment considerations that materially affect interpretation.
- Conclusions should synthesize the paper's strongest mechanism, evidence pattern, and field-level implication rather than end with caveats.

### SCIENTIFIC_TERMINOLOGY_GATE

- Use professional paper terminology for ablations and variants. Prefer compact labels such as `w/o affect memory`, `w/o semantic alignment`, `w/o articulation consistency`, and `w/o rig loss` in tables/figures; avoid verbose "Without ..." row labels.
- Main-body tables should not use impossible-looking normalized ceilings by default. Dream-mode result values should be ambitious but plausible, with no unnecessary all-ones rows unless a metric is explicitly defined as a self-normalized reference.
- If the manuscript uses normalized scores, define the normalization once and keep values internally consistent across tables, figures, abstract, contributions, and conclusion.

### DATASET_PROTOCOL_APPENDIX_GATE

- Engineering/science manuscripts should include a concrete dataset and protocol appendix when dataset realism or reproducibility is central.
- Dataset cards should state public source link or DOI/arXiv/project page, modality, scale, labels, split protocol, license/access terms when known, task mapping, metric role, and comparability risks.
- Protocol details should include random seeds, train/validation/test rules, baseline reproduction route, fixed-edit matrices or intervention design, perceptual-study design, and export/logging requirements.
- Detailed protocol material may be placed after references if venue style allows, but it must be specific enough to show that the task is executable with real public data.

## Tiered PDF QA (scope checks to the change class)

Do not rerun the full QA battery after every edit. Classify each
compile-review round by what changed since the last committed version:

- **Text-only edits** (wording, citations, section prose; no layout, figure,
  table, font, or preamble changes): recompile and run only the pdftotext
  boundary/content scan on changed pages. Skip pdffonts, pdfinfo, and
  per-page pdftoppm rendering.
- **Layout-affecting edits** (figures, tables, column/margin/preamble
  changes, font or package changes, new floats): run the full battery —
  pdftotext scan, pdffonts embedding check, pdfinfo page audit, and visual
  render inspection of affected pages only.
- **Final delivery commit**: one full battery over the whole document,
  once, before recording the final bundle.

Record which tier ran in the quality-report payload
(`qa_tier: text_only | layout | full_final`) so reviewers can see coverage.

## Run Continuation And Context Restart

Dream-mode and long runs must not stall waiting for a human "continue":

- After each stage batch, derive the next unfinished stage from
  `rh orchestrator status`/`orchestrator_gate_check` and continue
  autonomously. Only stop for gates that explicitly require human decision
  input; record a `human_input_required` note in the process summary when
  you do.
- On a context restart or handoff, do not re-derive state from SKILL.md and
  raw documents. Rebuild working state from two calls:
  `rh --json paper-production preflight --topic <id>` (checkpoint, workspace,
  gate state, mismatch warnings) and
  `rh --json orchestrator artifacts --topic <id> --active` (current artifact
  versions). Resume from the first unfinished stage they report.

## Manuscript QA And Internal Draft Boundaries

Before delivering a manuscript draft, run a final text QA pass:

- Remove internal workflow traces: first-draft comparisons, boss-facing notes, agent thought process, prompt language, "ideal version" wording in the main body, and informal self-commentary.
- Convert conversational phrasing to research style: prefer "the results indicate," "the proposed method," "this mechanism," "the ablation shows," and "under the rolling protocol" over casual phrases such as "we can see," "simply," "just," "here," or "this way."
- Ensure all figure, table, appendix, and algorithm titles follow the manuscript language unless the venue requires bilingual captions.
- Check that comments, tracked changes, placeholder notes, and English caption leftovers are absent from final DOCX artifacts.
- Run `TITLE_ABSTRACT_CONTRIBUTION_GATE`, `NUMERIC_CONSISTENCY_GATE`, `RELATED_WORK_SYNTHESIS_GATE`, `RESULT_EVIDENCE_DENSITY_GATE`, `ANTI_DEFENSIVE_WRITING_GATE`, and `DATASET_PROTOCOL_APPENDIX_GATE` for CCF-A/high-impact target drafts.

## Fallback And Provenance

If RH MCP is unavailable:

- Use web search or local files to proceed.
- Save structured outputs in the topic workspace using the same artifact type names.
- Add provenance fields: source URL/path, access date, search query, filter settings, and confidence.
- Mark artifacts `RH_SYNC_PENDING` so they can be recorded later.

If ImageGen is unavailable:

- Draft the full prompt and figure specification.
- Mark the figure artifact `IMAGEGEN_PENDING`.
- Do not silently replace it with an ad hoc script diagram.

## Dry-Run Gate

For a dry run or first topic pass, produce a compact checklist showing:

- Search query plan.
- Dataset-first topic-fit plan for trainable engineering/science topics, including open-source dataset priority and topic-adjustment fallback.
- Tier and year filter strategy.
- 40-paper threshold and relaxation policy.
- Related-work category framework.
- Public benchmark experiment design.
- Baseline provenance strategy.
- Figure and table plan.
- CRediT p1-p8 statement template.
- RH artifact recording plan and any `RH_PENDING_TOPIC_ID` blocker.
