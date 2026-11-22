---
name: paper-reading-annotation
description: Create PhD-level PDF highlights/comments for newly added Zotero papers or RH PDFs. Trigger when importing/syncing a paper into Zotero, adding a PDF attachment, 精读标注, 论文批注, 博士生读论文, or equivalent requests to make a paper quickly graspable through PDF annotations.
category: research
version: 0.1.0
public_suite: zotero
task_type: annotation
data_access_level: zotero-local
inputs: paper_id or PDF path, topic focus, Zotero attachment context
outputs: PDF annotations, reading notes, paperindex card signals
gates: skip low-relevance papers; preserve absolute attachment paths
artifact_schemas: paper_annotations, paperindex_card
estimated_runtime: 10-45 min
---

# Paper Reading Annotation

Use this skill whenever a paper PDF is added to Zotero/RH and should receive actionable reading highlights, not just section navigation.

## Objective

Produce PDF annotations that help a PhD student quickly grasp:

- the paper's core problem, motivation, and claims;
- theoretical innovation, algorithmic mechanism, and hidden assumptions;
- evidence strength, benchmark/baseline choices, reproducibility, and risks;
- critical assessment, cross-paper position, and RH-topic reuse value;
- the current RH paper-content primitive set (`paper_summarize`, `claim_extract`, `deep_read`, `method_taxonomy`, `baseline_identify`, `evidence_matrix`, `contradiction_detect`, `consistency_check`, `gap_detect`, `section_draft`);
- direct reuse value for the current RH topic or the user's own research.

## Workflow

1. **Resolve context**
   - Identify `paper_id`, topic, title, local `pdf_path`, and Zotero item/attachment keys when available.
   - If this is part of Zotero import/sync, run this before or immediately after attaching the PDF so the Zotero copy contains the annotations.

2. **Read before annotating**
   - Use existing RH `paper_annotations`, deep-read notes, and/or extracted PDF text.
   - If `deep_reading` exists, treat it as the primary source for algorithm walk-through, limitation analysis, reproducibility, and critical assessment.
   - For normal research papers, inspect abstract, introduction, method, experiments, limitations, and conclusion.
   - For surveys, inspect scope, taxonomy, paper-selection evidence, benchmark/resource tables, challenges, and limitations.

3. **Create an annotation plan**
   - Use `references/phd-annotation-schema.md` for categories and minimum coverage.
   - For theory/algorithm-heavy batches, also read `references/paper-content-primitives.md`.
   - For AdWorldBench / ad-simulation batches, also read:
     - Zotero collection `Research Harness / RH优化 / adworldbench-pdf-marginalia-optimization-2026-05-26`
     - `references/rh-pdf-marginalia-style.md` (repo mirror of the accepted style)
   - Pick an explicit profile in the JSON plan:
     - `zotero-content-primitives-v2` — default for Zotero re-annotation batches when the user expects theory/algorithm-level marginalia aligned to RH paper-content primitives.
     - `zotero-marginalia-batch-v1` — legacy dense profile when the user wants accepted-style marginalia but did not ask for primitive-mapped content coverage.
     - `phd-quick-grasp-v1` — fallback for one-off deep reading when there is no accepted Zotero batch style to mirror.
   - Write a JSON plan with anchor text and comments. Prefer 25–40 annotations for a full paper; 15–25 for short papers.
   - **Do not stop at an abstract-only pass.** For a genuine Zotero PDF re-annotation batch, use `zotero-content-primitives-v2` and target **exactly 19 content-dense annotations per valid PDF**.
   - Each comment must be actionable: explain why the highlighted text matters and how to use/critique it.
   - For `zotero-content-primitives-v2`:
     - every annotation must include `primitive_focus`;
     - the union of `primitive_focus` must cover the RH paper-content primitive set;
     - visible notes should emphasize theory/mechanism/evidence/judgment, not writing tips;
     - do **not** spend quota on `writing-move`, `reusable-framing`, or `surprise`.
   - Run the validator before touching the PDF:
     ```bash
     python skills/paper-reading-annotation/scripts/validate_annotation_plan.py \
       --spec /absolute/path/to/annotation_plan.json \
       --json
     ```
   - A plan is not acceptable if it:
     - falls back to 3-summary-note coverage;
     - omits the theory/evidence/assessment categories required by the selected profile;
     - lacks primitive coverage when using `zotero-content-primitives-v2`;
     - uses writing-oriented categories as a substitute for content understanding in the content-primitives profile;
     - exposes user-visible `RH原语`, `Primary primitive`, or meta-teaching language.

4. **Apply annotations**
   - If this is a re-annotation pass, first remove the previous RH-generated batch annotations:
     ```bash
     python skills/paper-reading-annotation/scripts/reset_rh_pdf_annotations.py \
       --pdf /absolute/path/to/paper.pdf \
       --in-place \
       --json
     ```
   - Run the bundled tool:
     ```bash
     python skills/paper-reading-annotation/scripts/phd_pdf_annotator.py \
       --pdf /absolute/path/to/paper.pdf \
       --spec /absolute/path/to/annotation_plan.json \
       --in-place \
       --json
     ```
   - For Zotero, apply to the actual Zotero storage PDF if known; otherwise apply before attachment so Zotero imports the annotated copy.
   - Keep backups unless the user explicitly asks not to.

5. **Verify and record**
   - Confirm applied/missing counts from the tool output.
   - Verify the actual PDF file, not just Zotero SQLite metadata:
     - expected batch profile count (e.g. 19 for `zotero-content-primitives-v2`);
     - anchors resolved to real source text;
     - forbidden-expression hits = 0.
   - If used inside RH, record a `zotero_pdf_annotation_receipt` or `paper_pdf_annotation_receipt` artifact with paper ids, paths, annotation count, and missing anchors.
   - If the PDF is already open in Zotero Reader, tell the user to close/reopen the PDF or restart Zotero to refresh embedded annotations.

## Trigger contract for Zotero import

When a future agent imports or syncs papers into Zotero, treat this as the default post-processing step unless the user opts out:

1. RH paper has a local PDF.
2. Generate the PhD annotation plan.
3. Validate the plan with `validate_annotation_plan.py`.
4. Apply annotations to the PDF that will be attached or to the attached Zotero storage PDF.
5. Verify the actual PDF annotation count after writing.
6. Attach/sync the annotated PDF and deep-read note.
7. Record the receipt.

Do not silently claim annotations were added: always verify PDF annotation counts.
