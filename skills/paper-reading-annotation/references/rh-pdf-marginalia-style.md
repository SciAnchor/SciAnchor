# RH PDF Marginalia Style (AdWorldBench baseline)

Source of truth in Zotero:

- Collection: `Research Harness / RH优化 / adworldbench-pdf-marginalia-optimization-2026-05-26`
- Note: `AdWorldBench PDF批注风格优化复现说明（文字版，2026-05-26）`
- Attachment: `rh-annotation-optimization-repro-2026-05-26.zip` (text-only reproducibility package)

Use this style when annotating papers for advertising / simulation / recommender-system topics, especially AdWorldBench batches.

## What the note should do

Each PDF highlight + popup note should:

1. Enter a concrete scenario immediately: ads, recommendation, budget, auction, feedback loop, simulation, or experiment design.
2. Explain why the highlighted text matters, what is strong, what is risky, and where the conclusion can generalize.
3. Connect the insight to AdWorldBench or the current RH topic when relevant.
4. Stay anchored to exact source text; do not annotate whole pages.

## Tone

Good:

> 这处痛点抓得比较关键。广告策略评估最麻烦的地方通常不是缺一个更复杂模型，而是日志看不到反事实、竞争者会变、预算和反馈有时序。方法是否有价值，主要取决于它是否真的压住了这个痛点。

Bad:

- `Important.`
- `RH原语: gap_detect`
- `Primary primitive: claim_extract`
- `我会…` / `学生…` / `读者…` / `给新读者…`

## Visibility rules

- You may use RH primitives internally while planning annotations.
- Do **not** expose RH labels in user-visible PDF notes:
  - no `RH原语`
  - no `Primary primitive`
  - no meta-teaching language

## Batch target used in the accepted run

- Valid PDFs: 19 (RECOSIM skipped because no valid PDF)
- Per valid PDF: 19 fine-grained source highlights + popup notes
- Total PDF notes: 361
- Forbidden-expression check: 0 hits

Treat this as the baseline for the `zotero-marginalia-batch-v1` profile:

- the batch is dense enough that a reader can understand the paper without stopping at the abstract;
- each note contains judgment, not only paraphrase;
- visible PDF notes stay domain-facing and scenario-facing, not tool-facing.

## Workflow for agents

1. Read the Zotero note in the collection above before generating a new batch plan.
2. Use `references/phd-annotation-schema.md` for category coverage.
3. Apply this style file when the topic is AdWorldBench or ad/recommender simulation work.
4. Before writing to Zotero storage PDFs, back up SQLite/PDFs and quit Zotero if modifying files directly.
5. Verify:
   - annotations anchor to real text
   - notes enter scenario + judgment
   - forbidden expressions = 0

## Comment labels still allowed

Use short Chinese labels when helpful:

- `【理论创新】`
- `【应用创新】`
- `【证据检查】`
- `【局限风险】`
- `【AdWorldBench启发】`

Do not use RH-internal labels in the visible note body.
