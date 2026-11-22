# RH Paper-Content Primitive Coverage for PDF Marginalia

Use this file when the user wants PDF notes that directly support the current RH paper-understanding workflow rather than only quick reading.

## Current paper-content primitive set

These are the RH primitives that a dense PDF marginalia batch should materially support:

1. `paper_summarize`
2. `claim_extract`
3. `deep_read`
4. `method_taxonomy`
5. `baseline_identify`
6. `evidence_matrix`
7. `contradiction_detect`
8. `consistency_check`
9. `gap_detect`
10. `section_draft`

## What each primitive needs from visible PDF notes

| Primitive | Visible note should surface |
| --- | --- |
| `paper_summarize` | problem, motivation, core-claim |
| `claim_extract` | what is being claimed, under which assumption, backed by what evidence |
| `deep_read` | algorithm step, hidden assumption, reproducibility risk, critical assessment |
| `method_taxonomy` | method family, abstraction boundary, what is genuinely new |
| `baseline_identify` | who the paper compares against, and whether the comparison is fair |
| `evidence_matrix` | which sentence/table/figure supports which claim, and what it does **not** prove |
| `contradiction_detect` | where the paper conflicts with prior intuitions, baselines, or neighboring routes |
| `consistency_check` | whether claims, settings, and evidence hang together without scope inflation |
| `gap_detect` | limitations, blind spots, weakly tested assumptions, missing comparisons |
| `section_draft` | theory/mechanism/evidence phrasing reusable for later synthesis |

## Recommended category → primitive mapping

| Annotation category | Typical `primitive_focus` |
| --- | --- |
| `problem` | `paper_summarize`, `claim_extract` |
| `motivation` | `paper_summarize`, `section_draft` |
| `core-claim` | `claim_extract`, `evidence_matrix` |
| `concept-boundary` | `method_taxonomy`, `consistency_check` |
| `method-taxonomy` | `deep_read`, `method_taxonomy` |
| `theoretical-innovation` | `deep_read`, `method_taxonomy` |
| `algorithm-step` | `deep_read`, `section_draft` |
| `hidden-assumption` | `claim_extract`, `gap_detect` |
| `evidence` | `claim_extract`, `evidence_matrix` |
| `baseline` | `baseline_identify`, `evidence_matrix` |
| `reproducibility` | `deep_read`, `consistency_check` |
| `critical-assessment` | `deep_read`, `contradiction_detect` |
| `limitation-risk` | `deep_read`, `gap_detect` |
| `cross-paper-link` | `deep_read`, `contradiction_detect` |
| `rh-mapping` | `gap_detect`, `section_draft` |
| `follow-up` | `gap_detect`, `section_draft` |

## Editorial rule

The visible PDF note should still read like a domain judgment, not like an internal tooling label.

Good:

> 【算法步骤】真正关键的是先把连续序列压成可被基础模型消费的离散接口；如果这一步丢了幅值与周期信息，后面的 LLM 能力再强也补不回来。

Bad:

> RH原语: deep_read
> Primary primitive: claim_extract
