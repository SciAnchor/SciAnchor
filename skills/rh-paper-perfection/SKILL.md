---
name: rh-paper-perfection
description: End-to-end "perfect paper" pipeline for a Research Harness research direction — drive experiments to ceiling (EAG-anchored to how top venues validate & present), then EAG-mode chapter-by-chapter writing with adversarial review after EVERY chapter and a final whole-paper adversarial review. Trigger on phrases like "rh-paper-perfection", "完美论文流程", "把这个方向做完整并写成论文", "experiment-to-ceiling then write", "把工作做完整", or when a direction has a solid experimental core and the user wants it taken to a publication-ready manuscript with maximal rigor. Orchestrates rh-exemplar-writing (EAG), rh-manuscript-polish (adversarial review), rh-paper-figure-generator, and the panorama library.
public_suite: research
task_type: workflow
data_access_level: local
inputs: direction/topic id, experimental results ledger, target venue (default ICLR main), panorama library, exemplar papers
outputs: ceiling-completed experiments, EAG-anchored chapter drafts, per-chapter adversarial-review verdicts, whole-paper review verdict, publication-ready manuscript
gates: no chapter advances until its adversarial review passes; no writing starts until experiments hit ceiling; every claim bound to a real experiment; exemplars transfer FORM never CONTENT
artifact_schemas: experiment_ledger, exemplar_map, chapter_draft, adversarial_review, submission_readiness
estimated_runtime: multi-session
---

# rh-paper-perfection — 完美论文流水线

One command to take a Research-Harness direction with a solid experimental core
all the way to a publication-ready manuscript, at maximal rigor, without
re-specifying the process each time. Codifies the loop:

**experiment-to-ceiling (EAG-anchored) → EAG chapter writing → per-chapter
adversarial review → whole-paper adversarial review.**

Use everything available: the panorama library, the LLM tunnel (`source
~/.config/research-harness/private.env`; PKU compute, never GPU 3), and the
existing skills `rh-exemplar-writing` (EAG), `rh-manuscript-polish` (adversarial
review), `rh-paper-figure-generator`.

## Phase 0 — Bind to a topic (once)
- Ensure an RH topic exists for the direction (`rh topic init` / reuse). Store
  the experiment ledger under `experiments/<slug>/RESULTS.md` and the direction
  file under `docs/innovation-kb/directions/`. All state lives in RH — the user
  should never need to re-paste context.

## Phase 1 — Experiments to CEILING (EAG-anchored)
1. **Find exemplars first (EAG).** Pull 3-6 top-venue papers *of the same shape*
   (e.g. for a negative-result/eval paper: rigorous LLM-eval / test-time-scaling
   / benchmark-critique papers) from the panorama library + web. For each,
   extract HOW they validate: which baselines/ablations, sample sizes + CIs,
   robustness axes (multi-model/seed/dataset), what a mechanism analysis looks
   like, and HOW they present (table/figure conventions, the "money" plot).
   Write an `exemplar_map` (form only, never copy content/claims).
2. **Gap-list against the exemplars.** List every validation the exemplars do
   that our ledger lacks (scale, CIs, multi-model, mechanism, positive method,
   contrast). That list IS the experiment backlog.
3. **Run to ceiling.** Execute the backlog (parallel LLM harness where possible)
   until: robustness holds across ≥2 models, CIs are reported, the mechanism is
   quantified, and either a positive method exists or the negative result is
   airtight. Update `RESULTS.md` after each run; absorb any new papers
   encountered into the panorama library.
4. **Ceiling gate:** stop only when a fresh skeptic pass finds no experiment a
   reviewer would demand that we haven't run (or can't run and have justified).

## Phase 2 — EAG chapter-by-chapter writing (+ review after EACH)
Order: abstract → introduction → related work → problem/setup → method/experimental
design → results → analysis/mechanism → discussion/limitations → conclusion.
For EACH chapter:
1. **EAG draft** via `rh-exemplar-writing`: anchor the chapter's FORM
   (architecture, arc, element order, prose style, figure/table contract) to the
   exemplars; bind every sentence to a real result/citation.
2. **Adversarial review** via `rh-manuscript-polish` (multi-angle: novelty /
   methodology-stats / domain / editorial): produce a prioritized-findings
   verdict `{ready | needs_revision | blocked}`.
3. **Revise until the chapter review passes.** Do NOT advance to the next
   chapter with an open blocker. Record each verdict.

## Phase 3 — Whole-paper adversarial review
After the last chapter, run a full-manuscript adversarial review (the 4-axis
ICLR panel: novelty / methodology / significance / rigor, web-enabled to catch
same-quarter pre-emptors, per `project-novelty-certification`) + `rh-manuscript-
polish`. Address every blocker; iterate until submission-readiness = ready.

## Iron rules
- **State lives in RH**, not in prompts. Re-invoking this skill on the topic
  resumes from the ledger — the user never re-explains.
- **Experiments before writing**; **review after every chapter**; **whole-paper
  review last**. No skipping.
- **EAG transfers FORM, never CONTENT.** Every claim traces to a real experiment.
- Target = ICLR main unless told otherwise; be honest about the ceiling.
- Use the panorama library as the evidence/exemplar source and keep enriching it
  with papers encountered along the way.
