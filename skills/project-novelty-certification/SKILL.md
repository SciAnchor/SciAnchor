---
name: project-novelty-certification
description: Two-stage GO/NO-GO certification for committing a mined research direction to a real project, targeting ICLR main track. Runs AFTER gap_ground_verify. Trigger on phrases like "project-novelty-certification", "立项认证", "能不能立项", "值不值得投 ICLR", "novelty certification", "reviewer panel", or when deciding whether to commit effort to a gap/direction found by gap-analysis or the panorama.
public_suite: review
task_type: gating
data_access_level: local
inputs: candidate direction/claim, gap_ground_verify verdict, design notes, panorama direction slug
outputs: per-axis reviewer scores, discovered pre-emptors, candidate-scoped novelty verdict, separate promotion decision, recorded territory-map verdict, residual analysis
gates: NEVER commit a direction on gap_ground_verify alone; the web-enabled 4-axis reviewer panel is MANDATORY; the novelty verdict and the promotion decision are SEPARATE artifacts and non-novelty axes may never rewrite the novelty verdict; a gap_ground_verify verdict of occupied alone yields unclear, never refuted; insufficient coverage yields unclear, never a positive finding; stop closes ONE candidate version after residual analysis, never a direction or a research area; NO field-, domain-, or area-level conclusion may be written under any circumstances
artifact_schemas: certification_decision, reviewer_panel, PROBLEM_ANCHOR
estimated_runtime: 15-40 min
---

# Project Novelty Certification (立项认证)

Decide whether a mined research candidate is worth committing real effort to,
defaulting to ICLR main track. This is the gate that sits AFTER
`gap_ground_verify` and BEFORE building anything. Declining to promote a weak
candidate is a success — but it must be recorded as what it actually is.

The gate emits **two artifacts that must never be conflated**:

| Artifact | Answers | States |
|---|---|---|
| Novelty verdict | Is the core contribution refuted by the evidence retrieved? | `refuted` / `not_refuted_by_retrieved_evidence` / `unclear` |
| Promotion decision | Should we invest now? | `advance` / `incubate` / `hold` / `stop` |

The novelty verdict is always scoped to **one candidate version**. Only the
novelty axis and concrete pre-emptor evidence may set it. Methodology,
significance, rigor, resources, and venue fit belong to the promotion decision
and **may not rewrite the novelty verdict** — a weak methodology score is a
`hold`, not evidence that the idea is unoriginal.

## Why this exists (load-bearing)

`gap_ground_verify` retrieves via **academic providers (OpenAlex/S2/arXiv)**
that **under-sample very recent literature**. On C2 (conclusion-stability
benchmark) it returned `partially_occupied` 0.62 three times, yet a
web-enabled reviewer panel found **direct ICLR-year pre-emptors it missed**
(e.g. *When Agents Disagree With Themselves* 2602.11619, *When Stability Fails*
2603.15840 — an ICLR-2026 workshop paper stating the exact thesis). Automated
certification alone systematically **over-estimates novelty**. The web panel is
therefore mandatory, not optional.

## Protocol

### Stage 0 — Preconditions
- The direction must already have a `gap_ground_verify` verdict and, ideally, a
  one-page design (claim, metric, subjects, differentiation). If not, run
  gap-analysis / `rh primitive exec gap_ground_verify` first.
- **NOV02 mandate (2026-08-13):** for this certification path, run
  `gap_ground_verify` with **`judge_mode=panel`** and retrieval budget
  **`max_candidates ≥ 15`**. Default `single` is for everyday exploration only;
  high-stakes occupation verdicts that feed certify must use the three-perspective
  panel (coverage / mechanism-equivalence / narrowness). See
  `docs/innovation-kb/evidence/nov02-three-arm-report-2026-08-13.md`.
  ```bash
  rh primitive exec gap_ground_verify \
    --arg topic_id=<id> --arg gap='...' \
    --arg max_candidates=25 --arg judge_mode=panel
  # or, for release-quality false-open curves:
  rh panorama calibrate --fixture ... --judge-mode panel --budgets 15,25
  ```
- Have the panorama direction slug ready so the decision is recorded on the map.

### Stage 1 — Automated verdict (record, do not trust alone)
Take the `gap_ground_verify` verdict (open / partially_occupied / occupied) and
its retrieved neighbors as INPUT to the panel. Prefer a **panel-mode** automated
verdict when available (`judge_votes` / `narrowness` fields). Treat
`partially_occupied` as a yellow flag and `occupied` as an immediate NO-GO
candidate — but never GO on this signal alone. A `single`-mode exploratory
verdict is not enough for Stage 3; re-run under `judge_mode=panel` first.

### Stage 2 — Web-enabled adversarial reviewer panel (MANDATORY)
Launch **four** parallel reviewer subagents (Task tool, general-purpose, run in
background). Each is a HARSH but FAIR ICLR reviewer on ONE axis, and each **MUST
use WebSearch** to hunt 2023-present pre-emptors — this is the step that catches
what academic retrieval missed. Give each the design doc + the gap_ground_verify
neighbors.

| Axis | Attack |
|---|---|
| **novelty** | Find the 3-5 closest works; is the delta genuine or already published (incl. workshops/preprints)? Does "nobody measured it" survive a determined search? |
| **methodology** | Construct validity of the metric/method; confounds; statistical power; is the measurement well-posed? |
| **significance** | The "so what"; is the finding surprising or an expected/known result; is there an actionable payload; ICLR-main bar vs workshop? |
| **rigor** | Experimental feasibility, cost, reproducibility, apples-to-oranges risks, meta-consistency. |

Each reviewer returns: `overall` (ICLR 1-10), `soundness`/`contribution` (1-4),
a `verdict` (commit / no-commit), the pre-emptors found (title + why it hurts),
and the concrete fixes required.

### Stage 3 — AC decision (deterministic gate)
Assemble the panel result and run the gate:

```bash
rh panorama certify <slug> \
  --claim "<the direction claim>" \
  --panel-json '{"auto_verdict":"partially_occupied",
    "reviewers":[{"axis":"novelty","overall":4,"verdict":"no-commit"},
                 {"axis":"methodology","overall":4,"verdict":"no-commit"},
                 {"axis":"significance","overall":3,"verdict":"no-commit"},
                 {"axis":"rigor","overall":4,"verdict":"no-commit"}],
    "preemptors":["When Stability Fails 2603.15840", ...]}'
```

**Novelty verdict.** `refuted` requires concrete pre-emptor evidence against the
core contribution, corroborated by a blocking novelty-axis review. An
`occupied` auto-verdict on its own yields `unclear` — it describes what one
query family retrieved, not the candidate's contribution. A missing novelty
reviewer or an `inconclusive` auto-verdict means coverage is insufficient, which
also yields `unclear`; emitting a positive finding on thin evidence would
launder a retrieval failure into a result.

**Promotion decision.** `stop` when novelty is `refuted`. `hold` when a
non-novelty axis is below the venue bar, the panel mean is below it, or the
panel is incomplete. `incubate` when novelty is `unclear`. `advance` otherwise.
`--target` selects the venue bar and is applied.

The promotion decision is recorded as a `project-certification` verdict on the
territory map automatically, preserving `hold`/`incubate`/`stop` separately.

### Stage 4 — Act on the decision
- **advance** → promote: create the RH topic, run the pilot. Record the design
  as a KB direction file.
- **incubate** → the evidence does not settle novelty. Widen the counter-search,
  add the missing reviewer axis, or sharpen the claim, then re-certify. Do not
  record this as a refutation.
- **hold** → novelty is untouched. Record which axis or resource blocked it, in
  those words. Do not write "not novel" or "occupied" into the KB.
- **stop** → run **residual analysis first**: which core facets were actually
  subsumed, and which were only adjacent or ancillary? If a meaningful residual
  survives, create a new candidate version and re-certify. Only when nothing
  survives do you close this candidate and move on. Record the verdict,
  pre-emptors, evidence snapshot, and what would revive it.

## Iron rules

1. **Novelty and promotion are separate.** Never let significance, methodology,
   rigor, resources, or venue fit change the novelty verdict. A `hold` recorded
   as "not novel" is the single most expensive error this gate can make.
2. **A candidate is not a direction, and a direction is not a field.** `stop`
   closes one candidate version. Consecutive NO-GOs across adjacent candidates
   are not an independent sample of a research area — they usually mean the
   candidates were clustered.
3. **Never write a field-level conclusion.** "Saturated", "exhausted",
   "red-ocean", "at a ceiling", "no room" are prohibited unless explicitly scoped
   to a candidate, query lane, or evidence snapshot with a cutoff.
   `assert_no_field_level_claim` enforces this; run it over any report you write.
4. **A zero marginal-return query family closes that query family**, not the
   topic, not the direction, and not the area.
5. **The web panel is mandatory.** Never promote a candidate on
   `gap_ground_verify` alone; academic retrieval under-samples recent work.
6. **Venue fit is a promotion input, not a novelty input.** If a candidate is
   real but only reaches workshop level, that is `hold`/`stop` on venue-fit
   grounds with the novelty verdict intact — not a finding that it is unoriginal.
4. **Persist every decision** to the panorama territory map and the KB direction
   file — certification is cumulative map annotation, not a throwaway query.
