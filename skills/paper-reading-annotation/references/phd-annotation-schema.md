# PhD PDF Annotation Schema

Use this schema to create annotation plans for `scripts/phd_pdf_annotator.py`.

## JSON shape

```json
{
  "paper_id": 123,
  "title": "Paper title",
  "profile": "phd-quick-grasp-v1",
  "annotations": [
    {
      "anchor": "exact text fragment from the PDF",
      "page": 1,
      "category": "core-claim",
      "subject": "核心主张",
      "comment": "【核心主张】这里是作者真正希望读者相信的句子；后面需要检查实验/论证是否支撑。",
      "priority": 5,
      "primitive_focus": ["claim_extract", "evidence_matrix"]
    }
  ]
}
```

`page` is optional and 1-based; include it whenever possible to reduce false matches.
`primitive_focus` is optional for light profiles, but required for `zotero-content-primitives-v2`.

## Recommended profiles

### `zotero-content-primitives-v2`

Use this when the user wants Zotero-ready PDF marginalia that directly supports RH paper-content primitives rather than only fast reading.

- Target exactly **19** annotations per valid PDF.
- Exact category split:
  - `problem` × 1
  - `motivation` × 2
  - `core-claim` × 1
  - `concept-boundary` × 1
  - `method-taxonomy` × 2
  - `theoretical-innovation` × 1
  - `algorithm-step` × 1
  - `hidden-assumption` × 1
  - `evidence` × 2
  - `baseline` × 1
  - `reproducibility` × 1
  - `critical-assessment` × 1
  - `limitation-risk` × 1
  - `cross-paper-link` × 1
  - `rh-mapping` × 1
  - `follow-up` × 1
- Every annotation must include `primitive_focus`.
- The union of `primitive_focus` across the plan must cover:
  - `paper_summarize`
  - `claim_extract`
  - `deep_read`
  - `method_taxonomy`
  - `baseline_identify`
  - `evidence_matrix`
  - `contradiction_detect`
  - `consistency_check`
  - `gap_detect`
  - `section_draft`
- Visible comments should explain mechanism, assumption, evidence boundary, or critique; do **not** spend quota on `writing-move`, `reusable-framing`, or `surprise`.

### `zotero-marginalia-batch-v1`

Legacy dense Zotero profile when the user explicitly wants accepted-style marginalia rather than a light summary pass.

- Target exactly **19** fine-grained annotations per valid PDF.
- Minimum category coverage:
  - `problem`
  - `motivation`
  - `core-claim`
  - `method-taxonomy`
  - `evidence`
  - `baseline`
  - `limitation-risk`
  - `writing-move`
  - `rh-mapping`
  - `follow-up`
- User-visible comments must:
  - start with a short Chinese label such as `【问题定义】` or `【证据检查】`;
  - avoid `RH原语`, `Primary primitive`, and meta-teaching expressions like `我会`, `学生`, `读者`, `给新读者`;
  - explain why the source text matters, what is strong/risky, and how it connects to the current topic.

### `phd-quick-grasp-v1`

Fallback profile for one-off full-paper reading when no batch-specific Zotero style is required.

- Prefer **25–40** annotations for a full paper; **15–25** for a short paper.
- Never degrade to a 3-note abstract-only pass when the user asked for PDF annotation.

## Required categories

For a full paper, cover at least these categories:

1. `problem` — What problem is defined?
2. `motivation` — Why does the problem matter?
3. `core-claim` — What does the paper want the reader to believe?
4. `theoretical-innovation` — New concept, taxonomy, abstraction, mechanism, formalization, or evaluation lens.
5. `application-innovation` — New task setting, domain transfer, system usage, deployment path, or practice implication.
6. `concept-boundary` — Definitions and distinctions that shape the paper's scope.
7. `method-taxonomy` — Method, framework, taxonomy, pipeline, or algorithmic skeleton.
8. `algorithm-step` — A specific interface conversion, loss term, or data-flow step that determines whether the method can work.
9. `hidden-assumption` — Condition the method/taxonomy depends on but may not foreground.
10. `evidence` — Dataset, benchmark, case study, human evaluation, or survey protocol strength.
11. `baseline` — Baseline/comparison coverage or missing comparison.
12. `reproducibility` — Training/evaluation protocol transparency, code/data availability, or replication risk.
13. `critical-assessment` — A judgment about why the method may or may not really work.
14. `limitation-risk` — Explicit or implicit limitations, threats, safety/ethics/reproducibility issues.
15. `writing-move` — Notable writing structure, framing, figure/table design, or argument sequencing.
16. `surprise` — A surprising insight, framing choice, or unexpected implication.
17. `reusable-framing` — Sentence/structure useful for introduction, related work, or survey writing.
18. `cross-paper-link` — Relationship to another paper in the pool (competes, extends, contradicts, applies).
19. `rh-mapping` — How this maps to the current RH topic, workflow, artifact, gate, or evaluation design.
20. `follow-up` — Question or next citation-tracing/search action.

## Comment style

Use short Chinese comments with an explicit label:

- `【理论创新】...`
- `【应用创新】...`
- `【写作思路】...`
- `【惊喜点】...`
- `【证据检查】...`
- `【RH映射】...`

Bad comment: `Important.`

Good comment: `【理论创新】这不是实验贡献，而是把 agent 系统拆成可编码的四个维度；可直接改造成综述 taxonomy。`

Forbidden visible phrases:

- `RH原语`
- `Primary primitive`
- `我会`
- `学生`
- `给新读者`
- `新读者`
- `让读者`
- `给读者`
- `对读者`
- `作为读者`

## Density guidance

- Abstract/title: 2–4 annotations.
- Introduction: 6–10 annotations.
- Method/taxonomy: 8–14 annotations.
- Experiments/evidence/resources: 4–8 annotations.
- Limitations/challenges/conclusion: 4–8 annotations.
- Avoid highlighting whole pages; anchor exact sentences or short paragraphs.

For `zotero-marginalia-batch-v1`, a good 19-note split is:

- Abstract/title: 2–3
- Introduction/background: 4–5
- Method/taxonomy: 6–7
- Experiments/evidence: 3–4
- Limitations/conclusion/follow-up: 2–3

For `zotero-content-primitives-v2`, a good 19-note split is:

- Problem / motivation / core-claim: 4
- Concept boundary / mechanism / algorithm steps: 6
- Evidence / baseline / reproducibility / assessment: 5
- Limitation / cross-paper / RH mapping / follow-up: 4

`writing-move`, `reusable-framing`, and `surprise` belong in an optional second pass, not the primary 19-note quota.
