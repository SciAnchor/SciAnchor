---
name: manuscript-logic-gate
description: "Manuscript-level writing gate for Research Harness. Use before paper-writing or section-drafting when a draft, topic, abstract, introduction, or advisor feedback indicates unclear core claim, concept sprawl, weak paragraph intent, undefined terminology, or promises that are not realized later in the manuscript."
public_suite: paper
task_type: writing-gate
data_access_level: local
inputs: topic_id, target venue, paper type, advisor feedback, draft text, evidence artifacts, experiment/result artifacts
outputs: CORE_CLAIM_CONTRACT, ARGUMENT_TREE, TERM_REGISTRY, PROMISE_REALIZATION_MATRIX, PARAGRAPH_INTENT_TREE, READER_CONFUSION_TRACE, CENTRAL_THREAD_AUDIT, ENUMERATION_DISCIPLINE_GATE, TITLE_ABSTRACT_RESULT_ALIGNMENT, TERM_SURFACE_SEMANTICS_AUDIT, PARAGRAPH_MICRO_PLAN, REVIEWER_PERSUASION_PREFLIGHT, MATERIAL_TO_ARGUMENT_GATE, manuscript_logic_gate_report
gates: block abstract/introduction/section drafting until the core claim, argument tree, terminology, promises, paragraph intents, reader path, central thread, title-abstract-result alignment, and material-to-argument mapping pass
artifact_schemas: CORE_CLAIM_CONTRACT, ARGUMENT_TREE, TERM_REGISTRY, PROMISE_REALIZATION_MATRIX, PARAGRAPH_INTENT_TREE, READER_CONFUSION_TRACE, CENTRAL_THREAD_AUDIT, ENUMERATION_DISCIPLINE_GATE, TITLE_ABSTRACT_RESULT_ALIGNMENT, TERM_SURFACE_SEMANTICS_AUDIT, PARAGRAPH_MICRO_PLAN, REVIEWER_PERSUASION_PREFLIGHT, MATERIAL_TO_ARGUMENT_GATE, manuscript_logic_gate_report, PAPER_PLAN
estimated_runtime: 10-30 min
---

# Manuscript Logic Gate

写正文前的论文逻辑门控。它不润色、不扩写、不替代
`paper-writing`；它决定当前材料是否已经“想清楚到可以写”。

## Trigger

Use this skill before manuscript-scale drafting when any of these are true:

- The core contribution cannot be stated in one readable sentence.
- The title, abstract, or introduction introduces many hot terms without a
  single controlling claim.
- Terms appear before definition or change names across sections.
- The abstract or introduction promises an abstraction, model, experiment, or
  capability that later sections do not realize.
- Advisor/reviewer feedback says the draft is hard to understand, not logically
  organized, overly enumerative, or unclear about what the paper does.
- A first-time reader could plausibly ask "what is this paper actually doing?"
  after the title, abstract, or first introduction page.
- The title, abstract, method, results, or conclusion appear to optimize
  different promises, metrics, or contribution labels.

## Required Outputs

Produce these artifacts before `PAPER_PLAN` and before section drafting:

1. `CORE_CLAIM_CONTRACT`
   - one-sentence claim
   - central problem
   - paper type and venue
   - allowed focus, max 3 items
   - forbidden focus

2. `ARGUMENT_TREE`
   - root claim
   - max 3 problems
   - each problem maps to one contribution, evidence, and section locations

3. `TERM_REGISTRY`
   - term
   - definition
   - first use
   - allowed aliases
   - forbidden aliases

4. `PROMISE_REALIZATION_MATRIX`
   - promise made in title, abstract, or introduction
   - where the promise is realized
   - evidence IDs or result artifacts

5. `PARAGRAPH_INTENT_TREE`
   - section
   - paragraph ID
   - paragraph intent
   - whether it serves the root claim
   - allowed terms for that paragraph

6. `READER_CONFUSION_TRACE`
   - sentence or paragraph ID
   - surface reading from a first-time reader
   - reader question or confusion
   - cause: `undefined_term`, `sudden_topic_shift`, `unmotivated_list`,
     `promise_without_setup`, `claim_result_mismatch`, `literal_misread`, or
     `missing_transition`
   - smallest repair needed

7. `CENTRAL_THREAD_AUDIT`
   - single controlling thread
   - competing threads or hot terms
   - keep, merge, or remove decision for each competing thread
   - pass only when every kept thread serves the root claim

8. `ENUMERATION_DISCIPLINE_GATE`
   - enumerated items per sentence or paragraph
   - abstraction level check
   - reason the list is needed
   - compressed higher-level category when the list does not need to stay open

9. `TITLE_ABSTRACT_RESULT_ALIGNMENT`
   - title terms
   - abstract problem terms
   - method mechanism terms
   - result metrics or evidence artifacts
   - conclusion claims
   - mismatches and repairs

10. `TERM_SURFACE_SEMANTICS_AUDIT`
    - term
    - likely literal reading
    - intended meaning
    - likely reviewer misreading
    - risk level
    - replacement or first-use clarification

11. `PARAGRAPH_MICRO_PLAN`
    - paragraph ID
    - role in section
    - sentence-role plan: background, gap, contrast, definition, method,
      evidence, transition, limitation, or takeaway
    - reader belief expected after the paragraph

12. `REVIEWER_PERSUASION_PREFLIGHT`
    - what the paper does
    - why it matters
    - why existing work is insufficient
    - why the proposed mechanism can work
    - what evidence would convince a skeptical reader
    - what the paper does not claim

13. `MATERIAL_TO_ARGUMENT_GATE`
    - candidate material, example, module, citation, result, or term
    - argument role: motivation, gap, method need, mechanism, evidence,
      limitation, or repair route
    - keep or drop decision
    - reason if dropped

14. `manuscript_logic_gate_report`
    - status: `pass` or `block`
    - blockers
    - warnings
    - metrics

## Execution Order

Apply the gate in this order:

1. Run `REVIEWER_PERSUASION_PREFLIGHT` to force the writer to answer the
   skeptical reader's five questions before polishing any sentence.
2. Build `CORE_CLAIM_CONTRACT` and `CENTRAL_THREAD_AUDIT`; remove competing
   threads before expanding the outline.
3. Build `ARGUMENT_TREE`, `MATERIAL_TO_ARGUMENT_GATE`, and
   `PROMISE_REALIZATION_MATRIX` so every kept material has an argument role and
   every promise has a realization target.
4. Build `TERM_REGISTRY` and `TERM_SURFACE_SEMANTICS_AUDIT` before approving
   title, abstract, or contribution terminology.
5. Build `PARAGRAPH_INTENT_TREE` and `PARAGRAPH_MICRO_PLAN` before section
   drafting.
6. Run `READER_CONFUSION_TRACE` and `TITLE_ABSTRACT_RESULT_ALIGNMENT` as the
   final reader-facing audit.

## Gate Rules

Block drafting when:

- `CORE_CLAIM_CONTRACT.one_sentence_claim` is empty, too long, or more than
  one sentence.
- `allowed_focus` has more than 3 items.
- `ARGUMENT_TREE` has more than 3 problems for an original research paper.
- Any problem lacks a contribution, evidence IDs, or section IDs.
- Any term lacks a definition or first-use location.
- A paragraph uses a term outside `TERM_REGISTRY` or a forbidden alias.
- A paragraph does not serve the root claim.
- A promise has no realization target or no evidence IDs.
- `READER_CONFUSION_TRACE` contains unresolved first-time-reader confusion that
  changes the perceived paper goal, contribution, or evaluation target.
- `CENTRAL_THREAD_AUDIT` finds more than one controlling thread, or a kept hot
  term cannot be attached to the root claim.
- `ENUMERATION_DISCIPLINE_GATE` finds an abstract/introduction sentence with
  more than three examples or parallel items without a classification reason or
  compression plan.
- `TITLE_ABSTRACT_RESULT_ALIGNMENT` finds title terms, abstract promises, method
  mechanisms, result metrics, or conclusion claims that do not map to each other.
- `TERM_SURFACE_SEMANTICS_AUDIT` marks a title or core-contribution term as high
  risk for literal misreading without replacement or first-use repair.
- `PARAGRAPH_MICRO_PLAN` shows a paragraph mixing incompatible roles, or the
  reader belief after the paragraph does not advance the section goal.
- `REVIEWER_PERSUASION_PREFLIGHT` cannot answer what the paper does, why it
  matters, why existing work is insufficient, why the mechanism can work, and
  what evidence would convince a skeptical reader.
- `MATERIAL_TO_ARGUMENT_GATE` keeps related material that has no argument role.

## RH Integration

`PAPER_PLAN` must carry the five core logic artifacts, the reader-facing audit
artifacts, and `manuscript_logic_gate_report`. If the gate report is not `pass`,
do not call `section_draft` for abstract, introduction, or manuscript-scale
sections.

Use `research_harness._selfdev.manuscript_logic_gate.evaluate_manuscript_logic_bundle`
as the deterministic private checker in RH self-development and tests.

## Output Discipline

Keep this skill at the logic layer. Do not generate polished prose until the
gate passes. If the gate blocks, return blockers and the smallest repair needed
to make the paper logically writable. Prefer deleting, merging, or renaming
claims and terms over smoothing them in prose; a readable but unaligned sentence
is still a failed gate.
