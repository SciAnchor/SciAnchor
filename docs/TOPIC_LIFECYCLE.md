# Topic Lifecycle — Normative State Model

> **L2 reference.** This document defines the schema every Research Harness topic
> follows: where state lives, the stage machine, how a topic starts from zero, how
> it resumes mid-way, and what reset/repair do. Agents should normally rely on
> `rh topic state --topic <id> --json` instead of re-deriving this from code; read
> this when debugging or extending the workflow.
> Code of record: `packages/research_harness/research_harness/_workflow/orchestrator/`
> (models.py, stages.py, service.py) and `auto_runner/checkpoint.py`.

## 1. Where state lives

| State | Storage | Source of truth |
|---|---|---|
| Topic metadata (name, venue, deadline, status) | `topics` table | DB |
| Workflow position (stage, stage_status, mode, gate_status) | `orchestrator_runs` table | DB |
| Transition history | `orchestrator_stage_events` table (append-only) | DB |
| Stage outputs | `project_artifacts` table (typed, versioned, `active`/`deprecated`/`superseded`) | DB |
| Runner execution state (retries, pending human decision, run trace) | Checkpoint JSON: `<state_dir>/auto_runner/checkpoints/topic_<id>.json` | Checkpoint, re-synced to DB on every resume |
| Gate outcome | Re-evaluated on demand by the gate evaluator | Live evaluation (the persisted `gate_status` is a cache and may be stale) |
| Papers & PDFs | `papers`/`paper_topics` tables + `.research-harness/downloads/` | DB |
| Human-readable staging area (optional) | `~/code/rh-workspace/<domain>/<topic-slug>/` | Materialized view only — **never** holds a `pool.db` |

### DB resolution order (`_core/config.py::load_runtime_config`)

1. Explicit `--db` flag → `source="explicit"`
2. `RESEARCH_HARNESS_DB_PATH` / `RESEARCH_HUB_DB_PATH` env → `"env"` (beats project config!)
3. `<workspace_root>/.research-harness/config.json` `db_path` → `"project-config"`
4. `<workspace_root>/.research-harness/pool.db` → `"project-default"`
5. `~/.research-harness/pool.db` → `"global-default"` (reached only outside a checkout — usually a cwd-drift accident)

`workspace_root` is found by walking up from cwd until
`packages/research_harness/pyproject.toml` exists. **Every checkout must pin its DB
with `rh config init`** so resolution reports `project-config`; `rh doctor` warns
when multiple non-empty state trees are visible or resolution fell through to the
global default.

## 2. Stage machine (V2, six stages)

Allowed transitions (`STAGE_GRAPH` in models.py — self-loops allowed everywhere):

```text
init → build → analyze → propose → experiment → write
              ↑________ↆ↑________ↆ            ↑____ↆ
        analyze→build   propose→build|analyze   write→experiment
                        experiment→propose
```

| Stage | Required artifacts | Gate | Soft prerequisites (advisory, not enforced) |
|---|---|---|---|
| `init` | topic_brief | approval | — |
| `build` | literature_map, paper_pool_snapshot, citation_expansion_report, acquisition_report | coverage | — |
| `analyze` | evidence_pack, claim_candidate_set, direction_proposal | approval | ≥ RH_MIN_CORPUS_SIZE (50) papers; ≥1 gap run; claims from ≥5 papers |
| `propose` | adversarial_resolution, study_spec | adversarial | claims from ≥10 papers; algorithm loop done |
| `experiment` | experiment_code, experiment_result, verified_registry | experiment | study spec approved; baselines identified |
| `write` | draft_pack, final_bundle, process_summary | review | ≥1 successful experiment run |

Enums (models.py): stage_status ∈ {not_started, in_progress, blocked,
awaiting_review, awaiting_resolution, approved, rejected, completed};
workflow mode ∈ {explore, standard, strict, demo}; gate decisions include
pass / fail / needs_approval / needs_coverage / needs_adversarial / needs_review /
needs_integrity / needs_experiment / needs_expansion. Legacy 13-stage names map
onto these six via `STAGE_SUBSTEP_MAP`.

## 3. Checkpoint schema (v1 envelope, `human_decision` v2)

Top-level keys of `topic_<id>.json` (`auto_runner/checkpoint.py::new_checkpoint`):
`schema_version, topic_id, mode, session_command, current_stage,
current_stage_attempt, stage_state, artifacts, stage_context, codex_handoff,
human_decision, last_error, history (last 200 events), run_trace, created_at,
updated_at`.

- `stage_state` ∈ pending | running | needs_codex | needs_human | blocked | complete | error.
- `human_decision` (schema `rh.human_decision_request.v2`) carries the pending
  decision: request_id, stage, reason_code, prompt, options (action / label /
  preference_score / recommended), selected, decision_status, auto_selected.
- Writes are atomic (tmp + fsync + rename). The checkpoint is runner-local truth;
  on every `run_topic`/resume it is re-aligned to the orchestrator run
  (`runner.py::_sync_checkpoint_with_orchestrator`). If they disagree,
  `paper-production preflight` reports `db_checkpoint_mismatch`.

## 4. Cold start (S1) — from zero to running

```bash
rh topic init "my-topic" --description ... --venue "ICLR 2026"   # topics row
rh paper-production start --topic my-topic --target-venue "ICLR 2026" \
  --interaction-mode checkpoint      # orchestrator run + checkpoint + first stage
```

`start` performs preflight, creates/repairs the orchestrator run at the inferred
stage, writes a fresh checkpoint, and begins `init`. Optional before/after:
`rh paper ingest ... --topic my-topic` (seed papers), `rh topic workspace my-topic`
(materialize the human-readable rh-workspace folder).

## 5. Resume (S2) — from the middle

Resume never trusts a single record; it recomputes:
`OrchestratorService.resume_run` → `infer_stage_from_artifacts` walks the six
stages in order and stops at the first stage whose required artifacts are missing
**or** whose gate does not pass; the run row is updated to that stage and the
checkpoint follows. Entry points, in preference order:

1. `rh topic state --topic <id> --json` — read-only full picture + `next_action`.
2. Pending decision? → `rh paper-production decide` / MCP `paper_production_decide`.
3. `rh paper-production resume --topic <id>` (or MCP `paper_production_resume` /
   `orchestrator_resume`) — continues from the recomputed stage.
4. Something inconsistent? → `rh paper-production preflight --topic <id>` lists
   blockers (`missing_checkpoint`, `db_checkpoint_mismatch`, `gate_blocked`,
   `missing_required_artifacts`, …) with repair suggestions.

## 6. Reset, repair, and reinforcement (S3)

- `rh paper-production reset-run --topic <id> [--stages ...] [--section ...]`
  supersedes manuscript artifacts (draft_pack, final_bundle, section_draft,
  publication_pack, figure_plan, …) but **always preserves** gate_decision,
  rollback_event, provenance_record, and human_feedback_record. Decision history
  is never deleted.
- Targeted reinforcement of a finished topic goes through the feedback loop:
  `rh feedback add` (records reset-safe `human_feedback_record` artifacts) →
  `rh feedback plan` (maps open items to a re-entry stage + invalidation set) →
  `rh feedback apply` (scoped supersede + `resume_run(force_stage=...)` + feedback
  context injected into the write stage) → `rh paper-production resume`.
- A corrupted checkpoint may be deleted; the next resume re-infers state from
  artifacts. Never hand-edit `orchestrator_runs` — use `rh orchestrator init` to
  re-create a run at the inferred stage.

## 7. Invariants to preserve when extending

1. One non-empty `pool.db` per machine context; rh-workspace materialization never
   contains a DB.
2. Artifacts are append-mostly: new versions supersede, nothing is hard-deleted by
   workflow commands; only payload status fields of feedback records are mutated.
3. Stage moves happen through `resume_run` / `advance` / `force_stage` so a stage
   event is always recorded — never by writing `current_stage` directly.
4. Gates are recomputed, not trusted from cache, before any advance.
5. The checkpoint may lag the DB, never the reverse: sync direction is checkpoint → DB
   position, DB → checkpoint stage on resume.
