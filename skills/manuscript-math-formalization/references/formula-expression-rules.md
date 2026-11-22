# Formula Expression Rules

## Reviewer Standard

If a reader would pronounce the expression as a variable, formula, condition,
mapping, tensor/matrix operation, set relation, probability, loss, algorithm
state, or rule pattern, it must be rendered as math. More generally, when
formula rendering gives the expression better stability, clearer hierarchy, or
more professional reviewer-facing appearance than body text, prefer formula
rendering.

This applies equally in Chinese and English prose:

- Chinese: `给定 X_{t-L+1:t} 预测 y_{t+h}`
- English: `given X_{t-L+1:t}, predict y_{t+h}`

Both require the symbolic spans to be math objects, even when the surrounding
sentence remains ordinary text.

## Convert

Convert the full expression, not only known sub-symbols. The audit must look for
new formulas that are not in the project symbol table.

| Plain prose smell | Preferred math intent |
| --- | --- |
| `QKT/√d` | inline prose: one math object rendered as `QK^T/\sqrt{d}` with a slash, not a stacked fraction |
| `softmax(QKT/√d+br)` | `softmax(QK^T/\sqrt{d}+b_r)` |
| `Yt∈RL×1` | `Y_t \in \mathbb{R}^{L\times 1}` |
| `Itrain(τ)∪Ival(τ)` | `I_{train}(τ)\cup I_{val}(τ)` |
| `rt = Norm(Concatβ φβ(St))` | `r_t=\mathrm{Norm}(\mathrm{Concat}_β φ_β(S_t))` |
| `P10/P50/P90` | `P_{10}/P_{50}/P_{90}` |
| `O(nm)` | `O(nm)` as a math object |
| `O(d·Ntoken)` | `O(d\cdot N_{token})` |
| `month=Aug → search hotel high → demand rise` | a math/rule object if used as a rule example |

## Scan Beyond Variable Lists

Do not rely only on a project-specific symbol table. Also scan for:

- operators: `=`, `<`, `>`, `≤`, `≥`, `∈`, `∪`, `∩`, `→`, `⊑`, `|`;
- math typography hints: `_`, `^`, `{}`, `:`, `/`, `√`, Greek letters;
- function calls: `softmax(...)`, `log(...)`, `max(...)`, `min(...)`,
  `Norm(...)`, `Concat(...)`, `CrossAttn(...)`;
- matrix/tensor notation: capital-letter products with transpose suffixes,
  e.g. `QKT`, `QK^T`, `XTX`;
- dimensions and sets: `R^d`, `RL×p`, `{low, high}`;
- complexity notation: `O(...)`, `Θ(...)`, `Ω(...)`, including full-width
  Chinese parentheses;
- local complexity variables introduced in prose, such as `n`, `m`, `e`,
  `lmax`, `K`, `d`, and `Ntoken`;
- rule/table examples with arrows or assignments.

## Inline Versus Display

- Inline prose: prefer compact linear math (`QK^T/√d`, `P_{10}/P_{50}/P_{90}`)
  so line height remains stable.
- Display equations: use built-up fractions and larger structures when the
  equation is centered or set apart from prose.
- DOCX implementation: both choices must still be real Word math objects. The
  decision is about visual layout, not whether to use math markup.

## Double-Column Layout Planning

In double-column papers, formula conversion must be planned against the column
width. A formally correct math object can still fail reviewer-facing polish if it
is forced into a half-column and Word breaks it into sparse continuation lines.

Before patching long formulas, classify them:

- short inline symbol or condition: keep inline and compact;
- short display equation: keep as one display line;
- long display equation: introduce named intermediate quantities and split at
  semantic boundaries;
- repeated set/count/sum expression: define a short symbol first, then give the
  expanded definition separately if needed;
- table-cell condition or audit field: keep short, or render as code/field text
  instead of wide display math;
- central equation that cannot be made compact: place it in a planned
  single-column/full-width equation island rather than leaving it to random
  half-column wrapping.

Acceptable multi-line formulas are planned blocks: definitions, objective terms,
or named components. Unacceptable multi-line formulas are accidental overflow
fragments where each line contains only a tail such as `/D_tau`, `+g_3...`, or
the second half of an argument list.

## Exemptions

Do not convert these unless they are part of an equation:

- dataset and task IDs;
- algorithm/model names;
- bibliographic metadata;
- English prose words containing short variable-like substrings;
- appendix code-field keys used as literal field names.

When unsure, classify by role:

- explanatory prose term -> text;
- symbolic placeholder or condition -> math;
- machine field key -> code/text;
- field key in a formal condition -> code-style condition or math object.

## Multi-Pass Gate

1. Extract plain text outside existing math.
2. Flag high-risk expressions.
3. Patch full expressions first.
4. Re-extract plain text and rescan.
5. Manually review false positives and document exemptions.
6. Stop only when all high-risk findings are fixed or explicitly exempted.
