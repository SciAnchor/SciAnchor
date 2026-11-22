# Engineering section contract

Section jobs for an engineering or CS method paper. Use this when drafting or
revising Abstract, Introduction, Related Work, Problem Formulation, Method,
Experiments, Results, Discussion, Limitations, and Conclusion. Medical IMRaD
and humanities skeletons do not use this contract.

Source: a section-by-section reconstruction brief for computational papers
(2026-09-26). The brief's repeated instruction is to read 3–5 recent papers
in the same task and copy their section shape, not their sentences. In this
workflow that comparison is the exemplar plan already bound to the topic.
Do not launch a second literature search to imitate it.

Do not invent experiments, modules, robustness, generalization, human studies,
or deployment. Do not raise a claim past the evidence already in the paper.

## Abstract

One paragraph, about 150–200 words, or the venue cap if it is tighter.
Order: problem and gap, modelling idea, evaluation, strongest result, what
that result does and does not support.

- Spend roughly a fifth on the problem, a quarter on the method, a third on
  the result, and the rest on scope.
- Name the modelling idea, not the module list, the loss, or the optimizer.
- Keep one core number, its interval if one was computed, and at most one
  supporting finding.
- Do not open with a sentence that would fit any paper in the field.

## Introduction

Continuous argument: why the task matters, what current methods miss, the
method idea, then the contribution. A contribution list is optional. Use one
only when each item names a different claim and points at the section or
table that carries it. Do not also list limitations in the introduction.

- Three open problems is the upper bound, and only when the paper actually
  answers three. One or two is enough for a short paper.
- Do not open with a field-generic sentence, and do not announce the section
  structure ("the rest of this paper is organized as follows") unless the
  venue profile requires it.

## Related Work

Group prior work by modelling idea, not by paper. Two to four groups. A group
earns a subsection only when it has its own idea, representative papers, and
a boundary relative to this task.

Each group: what the line does, what it got right, and what it leaves outside
this prediction unit. Then stop. Do not add a positioning paragraph that
repeats the contributions, and do not describe this paper's modules.

- Drop a citation that does not support the grouping. Grouping quality beats
  citation count.
- A paper with a different dataset, label, unit, or metric can be discussed.
  It is not a baseline, and the text must not say this method beats it.
- State a limitation of prior work as a scope ("is typically evaluated at",
  "does not model"), not as a failure, unless the paper reports that failure.

## Problem Formulation

Independent section only when the task has a defined unit, input, output,
and target. Otherwise fold those sentences into the method overview.

Answer only what the problem is: unit, input, model output, target. Usually
two to four paragraphs and one to three equations, under a page.

Leave out architecture, latent states, how labels or references are built,
splits, metrics, and baselines. Those belong in Method or Experiments.
Do not open with "as described in the introduction".

## Method

Answer how the defined task is solved. Open with an overview a reader can
retell, then one subsection per component.

- Give the most space to the component that is actually new. A borrowed
  backbone gets why it is used here, what it takes in, what it emits, and
  how it connects. Do not re-derive its standard equations.
- A formula sits inside the sentence that says what it is for. Do not write
  "is defined as follows" before every equation.
- Do not present the method as a list of modules. Say why the split exists
  and why the interaction happens where it does.
- Keep trainable prediction separate from reference or label construction,
  so a reader does not think an external score is an input feature.
- Training objective, if there is one, states the primary loss, any auxiliary
  term, and the weights that are actually used. Do not fill in an optimizer
  or a hyperparameter the paper does not report.
- Move splits, seeds, and metrics to Experiments.

## Experiments and Results

Setup states data, split, metric, and protocol once. Results state what
happened. Do not restate the task definition, and do not interpret why.

- Lead each result paragraph with the finding, then the number, then which
  comparison supports it.
- A same-task baseline, a sanity or chance control, and an external reference
  are different things. Label them. Only the same-task baseline supports a
  performance claim.
- An ablation claims a component effect only when that component was actually
  removed or replaced. If it was not, say the comparison is missing. Do not
  write the ablation as if it ran.
- Sensitivity, subgroup, qualitative, and failure analyses are optional and
  sit below the main comparison. Discussion, not Results, says why a result
  matters and where the evidence stops.
- A number appears in the prose or in the table, not copied into both and
  then into the caption.

## Discussion

Why the result matters, how to read it, and where the evidence stops.
About three to five paragraphs. Do not repeat the results table.

1. The main finding and at most one number, then what it means for the question.
2. Which design choice plausibly produced that behaviour. "Consistent with"
   is not a causal proof.
3. What this adds relative to the related-work groups. Do not restate the
   contribution list.
4. The strongest claim the evidence supports, and the stronger claim that
   still needs another experiment.

Prefer "suggests", "indicates", and "is consistent with" over "proves" and
"demonstrates" when the study is empirical.

## Limitations

What the current evidence cannot establish, and why. Not a list of things
the authors wish they had done. About two to four paragraphs.

Prefer three groups when they apply: measurement or proxy limits, data or
external-validity limits, and comparison or missing-ablation limits. Each
item names the limit, what interpretation it blocks, and the specific check
that would resolve it.

Do not write an item that withdraws the paper's actual result.

## Conclusion

One short paragraph, about 100–180 words. Problem, method idea, main
evidence, meaning, and the single next check. At most one metric. Do not
repeat the discussion, the module list, or the sensitivity numbers.

## Full-draft pass

After the sections exist, read the draft once for these and fix them in
place:

- A sentence that only defends the paper against a criticism the text never
  states.
- A sentence that announces what the next sentence will do.
- A one-sentence paragraph whose only job is to introduce a formula, a
  figure, or the next subsection.
- A figure or table caption that repeats the paragraph above it.
- The same motivation written again in a later section.
