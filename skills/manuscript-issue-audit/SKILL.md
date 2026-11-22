---
name: manuscript-issue-audit
version: 0.1.0
description: Guided multi-pass audit of a delivered clean LaTeX/PDF manuscript to find remaining problems before submission. Trigger on "检查稿件问题", "manuscript issue audit", "审稿自查", "挑毛病", "看看这篇还有什么问题", or when a user has a finished LaTeX package and wants a structured defect hunt.
public_suite: paper
task_type: review
data_access_level: local
inputs: latex zip or directory and/or PDF; optional target venue, DOI pair, prior feedback
outputs: prioritized issue board (blocker/major/minor/note), evidence snippets, optional re-audit checklist
gates: do not invent experimental results; flag missing evidence rather than fabricating fixes; separate form issues from science issues
artifact_schemas: manuscript_issue_board
estimated_runtime: 15-45 min
---

# Manuscript Issue Audit

Use when a clean LaTeX/PDF manuscript package is ready. Goal: **find problems the user can still see** and structure them.

This skill is a **workflow for the agent + human**, not a silent auto-rejector.

## Inputs (accept any subset)

1. `latex_dir` / `latex.zip` / `main.pdf`
2. Optional: `target_journal`, `code_doi`, `data_doi`
3. Optional: author notes / known worries

## Hard rules

- **No fabricated science.** If a claim lacks support in the package, open an issue `evidence-gap`, do not invent numbers.
- **Separate lanes:** science/statistics vs narrative logic vs formatting/LaTeX vs ethics/availability vs figures.
- **Every issue needs an anchor:** section, paragraph quote, figure/table id, or file:line in TeX.
- Prefer **reproducible checks** first (compile, refs, counters), then judgment passes.

## Workflow (run in order; skip only with reason)

### 0. Intake & inventory

1. Unpack zip to a working directory.
2. List TeX roots, bib, figures, tables, SI.
3. Record: page count (if PDF), figure count, table count, bib entry count.
4. Confirm package is **latex-only** (no code/data dumps). If code/data leaked into the zip, file a **blocker** `package-hygiene`.

### 1. Deterministic mechanical pass (must run)

Run whatever is available locally; record failures as issues:

| Check | What to flag |
|---|---|
| LaTeX compile (tectonic/latexmk) | undefined cite/ref, missing figures, fatal errors |
| Overfull/underfull boxes | layout major if > few pt on many pages |
| Bibliography | uncited entries, missing keys, DOI broken format |
| Cross-refs | `??`, duplicate labels |
| Counter continuity | Figure/Table/Section numbering jumps |
| Encoding | mojibake, missing CJK fonts if Chinese venue |
| Confidential residue | paths like `/Users/`, API keys, `dream`, `TODO`, `lorem` |

Produce issue stubs with `lane=mechanical`.

### 2. Availability & ethics pass

Read Data Availability, Code Availability, Ethics/IRB, Competing interests, Author contributions.

- DOIs present and match ticket (`code_doi`/`data_doi`) if provided
- Register consistency (upon-request vs open DOI) per venue norms
- Ethics: vague OK only if protocol requires vague; flag fake approval numbers
- CRediT present and role-plausible
- Corresponding author email plausible (not `example.com` unless placeholder policy)

`lane=compliance`.

### 3. Figure/table audit

For each float:

1. Caption standalone? units? sample size?
2. Referenced in text before/near appearance?
3. Raster readability (blur, tiny fonts) — if weak, suggest `figure-quality`
4. Panel labels consistent; colorblind-safe if claimed
5. Table notes vs main text contradiction

`lane=visual`.

### 4. Narrative & logic pass (multi-angle)

Do **four short adversarial reads** (separate notes, then merge):

1. **Skeptical reviewer** — what would reject this in 1st round?
2. **Domain peer** — terminology, prior-art gaps, overclaim vs related work
3. **Statistician** — identification, multiple testing, missing baselines, leakage
4. **Copy editor** — abstract↔body mismatch, tense/register, undefined acronyms

For each finding: claim → evidence in manuscript → why it fails → fix hint (not a rewrite unless asked).

`lane=science` or `lane=narrative`.

### 5. Venue fit pass

Using `target_journal` (or infer from template):

- Section order expectations (CS CCF-A order vs journal IMRAD)
- Length/figure limits if known
- Reference style
- Required statements (impact, limitations, data)

`lane=venue`.

### 6. Consistency matrix

Build a mini Claims–Evidence table (10–20 core claims):

| Claim (quote) | Where stated | Support (fig/table/eq/ref) | Status ok/weak/missing |

Any `missing` → blocker/major.

### 7. Synthesize issue board

Deduplicate and rank:

```text
BLOCKER — submission-stopping
MAJOR   — likely reviewer complaint
MINOR   — polish
NOTE    — optional nicety
```

Output format (markdown):

```markdown
# Manuscript issue board — <title>
Package: <path> · Venue: <journal> · Audit date: <ISO>

## Summary
- blockers: N · majors: N · minors: N · notes: N
- top risk: ...

## Issues
### B1. <title>
- lane: science|mechanical|...
- anchor: §3.2 / Fig.1 / main.tex:120
- evidence: "..."
- why it matters: ...
- suggested fix: ...
- ticket_feedback_payload:
  severity: blocker
  location: Figure 1
  body: |

## Residual uncertainty
- what the auditor could not verify (no PDF / no domain expertise / ...)
```

### 8. Human-guided deepening (interactive)

Ask the user **only high-value questions**, as choices when possible:

1. Which claim is load-bearing for acceptance?
2. Any known weak baseline or missing ablation?
3. Venue non-negotiables (page cap, blinded, data policy)?

### 9. Optional re-audit checklist

After fixes, re-run section 1 + any lanes that changed; mark issues resolved/regressed.

## Companion tools (call when relevant)

| Symptom | Tool/skill |
|---|---|
| Placeholder/blurry figures | `figure-quality` |
| Logic/terminology sprawl | `manuscript-logic-gate` |
| Math notation amateurish | `manuscript-math-formalization` |
| Final polish verdict | `rh-manuscript-polish` / `manuscript_polish` MCP |
| PDF compile/layout only | `final-bundle-quality` |

## Anti-patterns

- One-shot “LGTM” without mechanical compile attempt when TeX present
- Rewriting the whole paper instead of an issue board
- Mixing internal jargon (e.g. dream-mode terms) into user-facing feedback
- Filing style nits as blockers

## Done criteria

- Issue board delivered with counts and anchors
- User told the single highest-risk defect
- If ticket-linked: feedback posted or explicitly declined
- Clear next action list (fix TeX / redo fig / gather citation / accept residual risk)
