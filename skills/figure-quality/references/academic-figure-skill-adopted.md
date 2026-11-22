# Adopted from academic-figure-skill

Source: https://github.com/TingxiYu/academic-figure-skill (read 2026-09-23).
The pack is not installed. `figure-quality` already names it as a fork of this
router, and that line stands. What follows is the part of it that our stack
did not already say, rewritten against our own gates.

## What we already have, so it is not copied

- One claim per figure, panels that each carry unique evidence, a named
  archetype, and a review-risk pass before render. That is the five-point
  contract in the pack's `references/figure-contract.md`, and it is already
  `figure_suite_plan` plus `R-FIG.plan` (a figure names claim, purpose and
  track before WRITE) and `R-FIG.story` (a panel the story names needs records).
- A single palette, the same colour meaning the same method across panels.
  Ours is the rh pool of eight hexes, enforced by `check_palette` and
  `check_cross_figure_palette`. The pack's Nature/Cell/Science hexes
  (`#2166AC`, `#B2182B`, `#1B7837`, …) are a second pool. They are not added.
- Vector master plus a raster preview, and a refusal to invent numbers.
  `figure_suite_render` already draws only from recorded results and skips a
  panel whose records are missing.

## What we did not have

Print geometry. Our renderers set a size, but nothing says the size is the
journal column and nothing checks it after the fact. The pack's export spec
does, and the numbers are the journal's, not ours:

- single column 89 mm, double column 183 mm, set at creation, never scaled
  down afterwards
- type at or above 5 pt at that print size
- vector master (PDF or SVG); a raster panel only where the content is raster,
  at or above 300 dpi
- PDF fonts embedded as Type 42, so the file does not depend on the machine
  that drew it

These four are the print contract. A rendered PDF that misses one is a finding
of the same family as `check_palette`, not a new skill and not a new renderer.
The function that checks them does not exist yet; until it does, this file is
the spec and the renderers are not changed to chase it.

## What was read and taken

The pack's chart scripts (`assets/figures/Violin/*.py` and the rest) are
seaborn with a default palette and a fuzzy column matcher. They are not where
the figures look better. The difference is in `scripts/compose.py`, and it is
five habits, not a palette:

- an embedded sans face (`pdf.fonttype` 42, Arial/Helvetica/Liberation Sans)
  instead of DejaVu
- two spines, not four
- 0.6 pt lines and outward ticks
- a legend with no frame
- type that shrinks as the panel count grows, so a six-panel figure is not set
  at the size of a one-panel figure and then scaled down

Those five are now `nature_family` in
`research_harness/visualization/experiment_figures.py`, commit `1663bdb` on
`fix/rh-nature-family-style-20260923`. The rh pool is untouched. Their hexes
(`#2166AC` and the rest) are not in the profile.

## What stays out

- The pack's 29 chart scripts and its QA runner. The scripts draw with seaborn
  defaults; the runner checks that a script pasted their palette block
  verbatim, which is the opposite of reading one pool from one place.
- R, and any chart kind our renderers do not already emit.
- A second palette.
