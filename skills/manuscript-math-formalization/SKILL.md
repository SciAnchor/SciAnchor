---
name: manuscript-math-formalization
description: Formalize mathematical notation in Research Harness manuscripts. Use when reviewer/advisor feedback says prose symbols look unprofessional, when a Chinese or English manuscript/DOCX/LaTeX draft contains inline variables, equations, dimensions, matrix products, fractions, square roots, Greek symbols, indexed sets, rule expressions, or algorithm notation written as plain text, or when paper-writing/section-drafting/publication-pack needs a strict math-notation QA pass.
public_suite: paper
task_type: writing
data_access_level: local-files
inputs: manuscript DOCX/LaTeX artifact, reviewer/advisor feedback, formula-expression-rules reference, docx_math_audit findings
outputs: manuscript with formalized math objects (m:oMath / LaTeX math), math-notation audit findings, structure-preserving paragraph patches
gates: never patch inside existing math objects; preserve DOCX structure (sectPr, w:cols, styles, headers/footers, relationships); convert only function-mathematical expressions; keep method/dataset/acronym names and audit-field keys as text unless inside a formal equation
artifact_schemas: math_notation_audit, draft_section
estimated_runtime: 15-45 min
---

# Manuscript Math Formalization

Use this skill as a sub-skill for manuscript polish after the scientific text is
stable. The goal is reviewer-facing professionalism: any expression that is
mathematical in function must be rendered as a real math object (`m:oMath` in
DOCX, `$...$`/`\(...\)` in LaTeX), not as ordinary body text.

Apply the broad reviewer rule: if formula rendering would make a prose
expression more stable, less ambiguous, or more professional, render it as
math. Do not limit conversion to a known symbol table. This includes compact
operations such as `QKT/√d`, formal rule examples, function calls, dimensions,
set relations, inequalities, indexed identifiers, and any expression whose
visual correctness depends on superscript/subscript/fraction/root layout.

For running prose, prefer compact linear math when a built-up expression would
disturb line spacing: use a single formula object like `QK^T/√d` rather than a
stacked fraction. Reserve vertical built-up fractions for displayed equations,
centered formula lines, or places where the equation is intentionally separated
from body text.

For double-column manuscripts, formula formalization must include layout
planning, not only conversion. Do not force a long formula into a half-column and
let Word break it into sparse orphan lines. Classify each expression by role:
short inline symbol, compact display equation, semantic multi-line equation,
single-column/full-width equation island, table/code field, or appendix detail.
When a formula is too wide for a half-column, introduce intermediate symbols,
name repeated subexpressions, or move the full expression into a planned display
block. Multi-line display formulas should break at semantic boundaries such as
definitions, objective terms, or named components, not at arbitrary visual
overflow points.

This skill supports Chinese and English manuscripts. Do not infer that English
method names, dataset names, acronym names, or audit-field keys are math merely
because they contain capital letters or underscores.

## Workflow

1. Preserve the current artifact as the base.
   - For DOCX, patch OOXML locally and keep section, column, style, image,
     field, header/footer, and relationship parts unchanged.
   - Do not regenerate the whole manuscript from an older builder unless the
     user explicitly asks.
2. Load `references/formula-expression-rules.md` before auditing a new
   manuscript family or when the reviewer feedback is strict.
3. Run the audit script on the latest artifact:

```bash
python skills/manuscript-math-formalization/scripts/docx_math_audit.py manuscript.docx --format text
python skills/manuscript-math-formalization/scripts/docx_math_audit.py manuscript.docx --format json --fail-on-high
```

4. Patch high-severity findings first, then medium-severity findings that occur
   in formal method, problem definition, algorithm, table, proposition, or
   appendix protocol text.
5. Run a formula layout pass for double-column or narrow table contexts:
   - identify display formulas and table-cell formulas wider than the column;
   - replace accidental continuation lines with planned formula blocks;
   - prefer short named quantities over raw long sets/sums in half-column text;
   - keep equation numbering attached to the main semantic equation.
6. Re-run the audit after each patch batch. Continue until high-severity
   findings are gone and remaining medium/low findings are either intentional
   code identifiers, dataset names, method names, reference entries, or other
   documented exemptions.
7. Verify structure:
   - DOCX parses as XML.
   - `w:sectPr` count and `w:cols` layout match the base document.
   - no comments/tracked changes were introduced unless requested.
   - render with LibreOffice if available; if not, run structural checks and a
     Quick Look/WPS preview fallback.

## Must-Convert Patterns

Treat these as math even when embedded in Chinese or English prose:

- indexed sequences and windows: `y1:T`, `z_{t-L+1:t}`, `X_t`,
  `I_train(τ)`;
- dimensions and spaces: `Y_t ∈ R^{L×1}`, `h_y ∈ R^d`;
- functions and mappings: `fθ(X)`, `CrossAttn(q_y,[k_z,k_r],[v_z,v_r])`;
- matrix products, transposes, fractions, roots: `QK^T/√d`,
  `softmax((QK^T)/sqrt(d)+b_r)`;
- Greek and rule notation: `α→β`, `α⊑S_t`, `π∈R_β`;
- loss, probability, quantile, and inequality expressions:
  `MSE(ŷ,y)`, `P10/P50/P90`, `max(I_train∪I_val)<min(I_test)`;
- complexity notation and its local symbols: `O(nm)`, `O(d·N_token)`,
  `O(d)`, and variables introduced in the same sentence such as `n`, `m`,
  `e`, `l_max`, `K`, `d`, `N_token`;
- rule examples that act as formal patterns in tables:
  `month=Aug → search hotel high → demand rise`.

## Exemptions

Keep these as text unless they appear inside a formal equation or rule:

- dataset IDs and benchmark names: `HK-MO2018-HK`, `Macau2018-global`;
- method/model names and acronyms: `ERX-TDF`, `PatchTST`, `iTransformer`;
- prose module names: `LayerNorm`, `dropout`, `pinball loss`;
- raw audit-field keys in appendix tables: `selected_exog_count`,
  `train_end_idx`, `leakage_ok`.

If an audit-field key is compared or assigned in reviewer-facing prose, either
typeset the whole statement as code-style text or convert the whole comparison
to a math object. Do not mix half-formula and half-text fragments.

## DOCX Patching Rules

- Prefer paragraph-local OOXML edits over rebuilding the document.
- Never patch inside existing `m:oMath`; only patch ordinary `w:t` text.
- If Word split a phrase across runs, rebuild only that paragraph's runs while
  preserving `w:pPr` and the first run's text style.
- Match full expressions before short variables. For example, convert
  `QKT/√d` as one expression before converting `Q`, `K`, `T`, or `d`.
- For inline DOCX math, prefer slash-style fractions inside one `m:oMath`
  object when vertical `m:f` fractions make the line visually jump.
- After patching, inspect representative paragraphs by extracting both plain
  text and math text so punctuation still reads correctly.

## Resources

- `references/formula-expression-rules.md` — reviewer-facing conversion rules,
  bilingual examples, and exemption policy.
- `scripts/docx_math_audit.py` — DOCX plain-text scanner that reports likely
  unformalized math expressions outside existing Word math objects.
