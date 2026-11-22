# Research Harness — Agent Operations Manual

> **L0 entry point.** If you are an agent (Claude Code, Codex, Cursor, …) asked to do
> research work with Research Harness, read this file and nothing else first. Every
> other document is progressive disclosure — open it only when a step below points
> you there. If your task is to **modify Research Harness itself**, stop and read
> `AGENTS.md` (self-development mode) instead.

## 0. Invariants (every session, every host)

1. **One database.** The canonical state tree for this checkout is
   `<repo>/.research-harness/` (pinned by `.research-harness/config.json`). Never
   let your working directory pick a different `pool.db`. If unsure, run
   `rh doctor --json` and check the `state_trees` result.
2. **Papers enter through ingestion.** `paper_ingest(source=..., topic_id=<N>)` (MCP)
   or `rh paper ingest ... --topic <name>`. Never place PDFs in ad-hoc folders, never
   `UPDATE papers` via raw SQL. PDFs live in `.research-harness/downloads/`, absolute
   paths only.
3. **Every operation attaches to a topic.** Bare ingestion or analysis without a
   `topic_id` is not allowed.
4. **MCP first.** Research primitives (`claim_extract`, `gap_detect`, `section_draft`,
   `consistency_check`, …) go through MCP tools so provenance, gates, and artifact
   versioning apply. The `rh` CLI is for setup, listing, data management, and the
   lifecycle commands named below.
5. **Key outputs become artifacts** via `orchestrator_record_artifact`; reusable
   process feedback goes into a GitHub Issue — never new top-level report files.

## 1. Orient in one command

```bash
rh topic list                          # what topics exist
rh topic state --topic <id|name> --json   # full picture for ONE topic
```

`topic state` (also the MCP tool `topic_state`) returns: resolved DB path and any
competing state trees, orchestrator stage/gate, checkpoint state, pending human
decision, open feedback, blockers, and a computed `next_action` with runnable
commands. **Trust `next_action`** — do not reverse-engineer the workflow from code.

## 2. Pick your scenario

### S1 — Start a new topic from zero

| Style | How | When |
|---|---|---|
| One command | `/rh-write "topic" <venue>` | You just want a paper draft end to end |
| Controlled (recommended for HITL) | `rh topic init "name" --venue ...` → `rh paper-production start --topic <name> --target-venue ... --interaction-mode checkpoint` | Human wants to approve key decisions |
| Expert bootstrap | `/research-init` | You already have seed papers / a problem anchor |

Details: `docs/ONE_COMMAND_QUICKSTART.md`, `docs/NEW_RESEARCH_WORKFLOW.md`.

### S2 — Continue a half-done topic

```text
1. rh topic state --topic <id> --json     # or MCP topic_state
2. If next_action = answer_pending_decision:
     /rh-decide   (or MCP paper_production_decide(topic_id, choice, reasoning))
3. Otherwise: /rh-continue   (or MCP paper_production_resume / orchestrator_resume)
```

Never restart a topic from scratch because state looks confusing — run
`rh paper-production preflight --topic <id>` and repair per its blockers instead.

### S3 — Reinforce a finished topic from user feedback

```bash
rh feedback add --topic <id> --target-kind section --target related_work \
  --note "reviewer: evidence in Sec 4 is weak" --severity major
rh feedback plan --topic <id>            # maps open feedback → revision plan
rh feedback apply --topic <id> --dry-run # preview what gets invalidated
rh feedback apply --topic <id>           # scoped reset + re-enter stage
rh paper-production resume --topic <id>  # redraft with feedback injected
```

Target kinds: `section` (redraft named sections), `claim` / `evidence` (re-enter
analyze), `experiment` (re-enter experiment). Feedback records survive resets and
are marked `addressed` when resolved.

## 3. The eight tools that matter

| Need | Tool | Notes |
|---|---|---|
| Full topic picture | `topic_state` / `rh topic state` | Always your first call |
| Create topic | `topic_init` / `rh topic init` | Attach venue + deadline if known |
| Find what already exists | `paper_search` | Multi-provider academic retrieval (arXiv, OpenAlex, Crossref, Semantic Scholar, OpenReview, PubMed, Scholar). **Runs before Web Search on any prior-art / novelty question**, never after |
| Add papers | `paper_ingest` | Always with `topic_id` |
| Start production | `paper_production_start` | `interaction_mode`: autonomous \| checkpoint \| interactive |
| See / answer decisions | `paper_production_pending_decisions`, `paper_production_decide` | Or `/rh-decide` |
| Resume | `paper_production_resume` / `orchestrator_resume` | Or `/rh-continue` |
| Targeted revision | `rh feedback add|plan|apply` | Finished-topic reinforcement |

All other MCP tools are secondary; discover them when a stage needs them.

## 4. Reading path (progressive disclosure)

- **L0** — this file. Enough for all three scenarios.
- **L1** — scenario docs: `ONE_COMMAND_QUICKSTART.md` (S1 minimal),
  `NEW_RESEARCH_WORKFLOW.md` (S1 step-by-step), `PURE_CLI_WORKFLOW.md` (MCP-only
  hosts), `HITL_QUICK_START.md` (decisions & interaction modes),
  `codex-workflow.md` (Codex host specifics),
  `deploy-and-hitl.zh.md` (deploy on Codex/Claude Code + a full conversational HITL walkthrough).
- **L2** — deep references, read only when debugging or extending:
  `TOPIC_LIFECYCLE.md` (normative state model: stages, gates, checkpoints, resume,
  reset), `agent-guide.md` (full tool catalog + research norms),
  `PAPER_MANAGEMENT.md` (ingestion protocol), `TROUBLESHOOTING.md`.

## 5. Interaction modes in one line

`checkpoint` (default) pauses at structured decision points for the human;
`autonomous` auto-applies recommendations except high-risk ones; `interactive`
additionally lets the AI ask clarifying questions. Switch at runtime with
`rh paper-production set-mode --topic <id> --mode <m>`. Full reference:
`docs/HITL_QUICK_START.md`.
