# SciAnchor — Agent Guide

This is the SciAnchor repository. Its open-source engine, Research Harness (RH), is an agent-first research workflow platform for literature review, evidence management, experiment planning, and paper writing.

**Doing research work with RH?** Read `docs/AGENT_OPERATIONS.md` first — it is the
single L0 entry point (invariants, the three operating scenarios, the seven tools
that matter) and links everything else. The normative topic state model lives in
`docs/TOPIC_LIFECYCLE.md`. **Modifying RH itself?** See `AGENTS.md` self-development
mode. Do not start by reading the whole docs/ tree.

## Repository Layout

```text
packages/                  Python workspace packages
  llm_router/              Multi-provider tiered LLM router
  paperindex/              PDF parsing, paper cards, and retrieval engine
  research_harness/        Core workflow, primitives, provenance, CLI
  research_harness_mcp/    MCP and HTTP API surfaces
  paperfetch/              Optional paper fetch/verify/parse CLI (`paperfetch`, alias `spc`; Python 3.12)
apps/                      SciAnchor desktop and web clients (planned; not yet in the tree)
skills/                    Research Harness workflow skills
docs/                      Public setup, usage, architecture, and troubleshooting docs
```

The `paperindex` engine (PDF parsing, paper cards, retrieval) lives in the
workspace sibling package `packages/paperindex/`. `research_harness.paperindex`
is a compatibility shim over it; new code imports `paperindex` directly.

## Capability Decision Tree

When performing a Research Harness operation, choose one mechanism:

| If you want to... | Use | Example |
|---|---|---|
| Trigger a complete user-facing workflow | Workflow skill in `skills/` | `/literature-search` |
| Call a contracted agent-facing operation | Public MCP tool in `research_harness_mcp.tool_surface` | `paper_search` |
| Set up, list, or manage local RH data | `rh` CLI | `rh topic list` |
| Manage the workflow skill catalog or installable packages | Internal skill catalog tooling in `research_harness.skill` / `rh skill` | `rh skill list` |
| Use a low-level Python building block | Internal primitive in `research_harness.primitives` | `gap_detect` implementation helpers |
| Run a promoted capability candidate under replay/gates | Internal evaluator in `research_harness.evaluator` | `run_evaluator("final-bundle-quality", ...)` |

Do not confuse workflow skills with internal evaluators. Workflow skills are
agent-facing packages; evaluators are replay-gated runtime candidates. Internal
primitives may remain executable for compatibility, but only public MCP tools
are part of the advertised agent contract. The `research_harness.skill` package
is catalog/install tooling for top-level workflow skills; it is not an
evaluator runtime.

## Evidence Policy

Every task runs the formal RH workflow on real evidence: reported results come from completed experiments or cited, provenance-backed sources.

## Novelty Certification

Before advancing a new research direction, run the two-stage **project
novelty certification** (`project-novelty-certification` skill): automated
`gap_ground_verify` with **`judge_mode=panel`** and budget ≥15 (NOV02: default
`single` is exploration-only; high-stakes occupation needs the three-perspective
judge) FOLLOWED BY a mandatory web-enabled 4-axis reviewer panel (academic
retrieval under-samples recent work and over-estimates novelty on its own), then
the deterministic `rh panorama certify` gate, and persist the verdict.

`rh panorama certify` returns **two separate artifacts, and they must never be
conflated**:

- **Novelty verdict** — `refuted` / `not_refuted_by_retrieved_evidence` /
  `unclear`, always scoped to one candidate version. Only the novelty axis and
  concrete pre-emptor evidence may set it. A `gap_ground_verify` verdict of
  `occupied` describes what one query family retrieved; on its own it yields
  `unclear`, never `refuted`. When coverage is insufficient the answer is
  `unclear` — never a positive finding.
- **Promotion decision** — `advance` / `incubate` / `hold` / `stop`. Methodology,
  significance, rigor, resources, and venue fit belong here and **may not
  rewrite the novelty verdict**. A weak methodology score is a `hold`, not
  evidence that the work is unoriginal.

Default acceptance target is ICLR main track, but `--target` selects the venue
bar and is applied. `stop` closes **that candidate version**, not a direction
and never a research area: run residual analysis first, and if a meaningful
residual survives, create a new candidate version and re-certify rather than
abandoning the line of work.

**Never write a field-, domain-, or area-level conclusion.** Consecutive
candidate NO-GOs, an exhausted query family, and a high unseen fraction are
statements about candidates and retrieval lanes, not about a research area. Any
claim that a field is saturated, exhausted, red-ocean, or at a ceiling is
prohibited unless explicitly scoped to a candidate, query lane, or evidence
snapshot; `research_harness.panorama.certify.assert_no_field_level_claim`
enforces this and should be applied to reports and dashboards.

## Venue Writing Profiles

Per-venue writing/design profiles live in `docs/venue-profiles/`. A profile is
the normative source for that venue's paper type, section architecture, word
budgets, experiment matrix, and acceptance conventions — measured from
published articles, not inferred. Read the profile before drafting for that
venue.

**Information Processing & Management** — `docs/venue-profiles/ipm-computational-method-paper.md`.
Standing rule from that profile: IP&M's default genre is a **computational
method/model paper grounded in an information task** (measured: ~61% of
2024–2026 research articles are method-centric, ~7% behavioral-empirical).
Whenever the research question can be stated as *input → output → measurable
correctness*, RH designs the manuscript as **method-core**, with the
application domain supplying the task definition, the data, and the
implications section — not as a behavioral study. Fall back to an empirical or
qualitative design only when the question cannot be formalized as a computable
task. The profile's checklist (named method, ≥2 real datasets, ≥8 baselines,
ablation, complexity/efficiency analysis, a dedicated Implications section) is
the delivery bar.

**npj series (any Nature Portfolio `npj *` journal)** —
`docs/venue-profiles/npj-series-multimodal-method-paper.md`. **The moment a
task names an npj journal as the target, read that profile and apply the rules
below without being asked.**

1. **Computational style (method-core).** The claim shape is a *named
   model/framework/algorithm solving a formalizable task*; the clinical domain
   supplies the task, the data, and the implications. Same test as IP&M:
   *input → output → measurable correctness*. Fall back to an empirical design
   only when the question cannot be computed.
2. **Collection scope gate.** When the task targets an npj special issue
   (Collection), score that collection's key themes `hit` / `partial` /
   `miss` **before drafting**, require ≥3 `hit` including one of the
   collection's headline terms, and record the scoring with the topic. A
   near-miss is fixed by reshaping the modality mix or the task definition,
   never by seeding scope keywords into the abstract.
3. **Clinical-forward packaging.** The computational method is the kernel, but
   every outward layer — title, abstract, Introduction opening, headline
   result, Discussion close — is written in clinical language and must
   *demonstrate* clinical significance rather than assert it. Measured from 64
   npj titles: median **14 words** (p25–p75 12–15, max 18), and only **4/64**
   put a method acronym first — the name belongs in the abstract, the title
   states the clinical decision, population, treatment context and study
   design. No architecture vocabulary in the title. The abstract opens on the
   clinical decision currently being made badly and its cost, and the headline
   result carries at least one **clinical-utility** measure (decision-curve net
   benefit, lead time, share of management changed, examinations spared)
   alongside discrimination. Architecture, ablations and complexity stay in
   full — in Methods and the body, not in the packaging.
4. **Open-data gate.** An npj paper must have
   publicly available data it can name in Data Availability. Check this
   *before* writing the title or abstract. If none exists: **stop**, propose
   the smallest topic tweak that makes a public source fit, and wait — do
   not proceed, do not fill the gap with a simulated-only cohort.

The profile also carries the npj format spec, the collection-page scraping
recipe (`nature.com` 303s `WebFetch` to `idp.nature.com`; use a browser-UA
curl), the EAG **Nature-level exemplar anchors** (ceiling = Nature
Medicine/Nature Communications/Lancet; npj itself is venue_fit, teaching format
and reporting compliance only), and the medicine dual-bar module contract
(cohort flow, patient vignette plate, failure gallery, error-analysis section,
filled TRIPOD+AI, mandatory SI). Computational style does not exempt a
manuscript from the medicine dual bar.

## Paper Management

See `docs/PAPER_MANAGEMENT.md` for the full protocol.

In short:

1. Use one RH database (`.research-harness/pool.db` by default, or `RESEARCH_HARNESS_DB_PATH`).
2. Store PDFs through RH ingestion/acquisition, not ad-hoc folders.
3. Always attach paper ingestion and analysis to an explicit topic.
4. Use MCP tools for research primitives when provenance matters; use the `rh` CLI mainly for setup, listing, and data-management tasks.
5. **Retrieval lane order: academic retrieval first, Web Search second.** Every
   prior-art, novelty, related-work, competitor, or "does this already exist"
   question opens with RH's multi-provider academic retrieval — the
   `paper_search` primitive / MCP tool, backed by
   `paper_source_clients.build_provider_suite` (local PaperVault cache plus
   the keyless public sources Semantic Scholar, OpenAlex, Crossref, arXiv,
   PubMed and OpenReview; SPC joins when its CLI is installed). No source uses
   an API key; see `docs/managed-paper-acquisition.md`.
   Reaching for Web Search *first* on such a question is a defect, not a
   shortcut: web results under-sample the indexed literature that novelty
   verdicts are decided on, and a verdict built on them alone is unfounded.
   This applies to Claude, Codex, and all subagents, with no per-task
   authorization needed.
6. **Agent-native Web Search is a standing fallback/supplement lane** (applies to Claude, Codex, and all subagents — no per-task user authorization needed): whenever RH/SPC retrieval under-covers (recent work, niche venues, special-issue pages, submission requirements, fact checks), search the web proactively. Papers found this way still enter through the formal ingestion lanes; cite web evidence with its source.

## Manuscript Byline and CRediT (applies to every clean draft)

Standing rule — every produced manuscript, in every venue and
discipline, carries these two things. Both are enforced in
`_workflow/execution/latex_compiler.py`
(`PLACEHOLDER_AUTHOR_BLOCK`, `credit_authorship_block`), so a draft assembled
through RH gets them without being asked; hand-written drafts must match.

1. **Byline placeholder** — exactly **three authors across two departments,
   with the third author corresponding** and carrying a plausible generated
   email. Use `Author 1 / Author 2 / Author 3` as names. Authors 1–2 share
   Department A, Author 3 sits in Department B. Never emit `Anonymous`.
2. **CRediT authorship contribution statement** — one bolded author per
   paragraph followed by a comma-separated list of standard CRediT taxonomy
   roles, then `All authors have read and agreed to the submitted version of
   the manuscript.` No narrative gloss after the roles: the role list is the
   statement, and restating it in prose is redundant.

   ```latex
   \textbf{Author 1:} Conceptualization, Methodology, Software, Formal analysis, Writing -- original draft.
   ```

   **Roles must be reassigned to match what the paper actually reports** — a
   study with no software gets no `Software` role, a design-only paper gets no
   `Data curation`. The default split in the code is a starting point, not a
   fixed answer.

## Common Commands

```bash
# Install / verify
./setup.sh
rh --json doctor
python -m pytest packages/ -q

# Data management
rh topic list
rh topic init "my-research-topic"
rh paper ingest --arxiv-id 2401.12345 --topic my-research-topic
rh paper queue --topic my-research-topic
rh orchestrator status --topic my-research-topic

# MCP server
python -m research_harness_mcp
```

## Public Repository Hygiene

Keep this repository focused on reusable code, sanitized examples, and concise public documentation. Do not commit local databases, private research artifacts, unpublished drafts, credentials, one-off debug logs, or personal machine paths.

For bugs or process improvements, prefer GitHub Issues or the project backlog instead of new top-level report files.

