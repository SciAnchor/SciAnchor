# Codex Workflow for Research Harness

> **Host-specific: Codex.** For the host-agnostic agent entry point (invariants +
> the three operating scenarios) read `docs/AGENT_OPERATIONS.md` first.

_Last updated: 2026-05-20_

This document turns Codex usage for this repo into a repeatable workflow. It is intentionally conservative: project files may define safe defaults, but user-level secrets and write-capable integrations stay outside the repo.

## What changed

- `.codex/config.toml` provides a project-scoped Codex baseline for the Research Harness MCP server without storing secrets.
- `.agents/skills` is a symlink to `skills/`, so Codex can discover repo-scoped skills from its standard skill path while the repository keeps `skills/` as the canonical workflow surface.
- `scripts/codex-check.sh` is the standard local validation entrypoint for Codex-authored workflow/config changes.
- `.github/workflows/codex-review.yml` is a manual-only Codex review workflow draft; it does not run on PRs until enabled deliberately.

## Daily operating loop

1. **Resume first**: call `orchestrator_resume` (plus `topic_show` / `decision_log_list`) before searching the web or starting a new topic-level workflow.
2. **Use MCP for research primitives**: paper search/ingest, claim extraction, gap detection, section drafting, and artifact recording should go through Research Harness MCP tools. Use CLI only for read-only/data-management tasks.
3. **Record outputs**: every durable research output should be recorded with an `orchestrator_record_artifact` call.
4. **Verify before handoff**: run `scripts/codex-check.sh --quick` for workflow/config/doc changes; use `--full` before PRs or broad changes.
5. **Checkpoint early**: when a session enters a new phase or context is getting large, write a short checkpoint (current stage, recorded artifacts, open blockers, next action) before opening more files or launching more searches.
6. **Self-evolve from workspace feedback**: when working under `rh-workspace/`, human feedback is an absolute trigger for RH self-evolution. Repeated agent-observed failures or unambiguous logic bugs are cautious triggers. Use the `rh-self-evolution` skill and patch reusable mechanisms in `research-harness`, not only in local Codex skill directories.
7. **Sync Codex after RH updates**: after RH skill/workflow changes, run `scripts/sync-rh-to-codex.sh`. Install `scripts/install-codex-sync-hook.sh` once per clone so successful local merges/checkouts/rebases refresh Codex automatically.

## Tool routing matrix

| Task | Preferred tool/workflow | Avoid |
| --- | --- | --- |
| Resume an existing topic | `orchestrator_resume`, `topic_show`, `decision_log_list` | Starting with web search |
| Paper search/ingest | Research Harness MCP `paper_search` / `paper_ingest` | Ad hoc paper lists outside the DB |
| Research primitive execution | MCP tools (`claim_extract`, `gap_detect`, `section_draft`, etc.) | RH CLI primitives that bypass provenance |
| Dependency/API docs | Context7 or official docs | Training-data-only API guesses |
| Current market/tool scans | Exa/web search with source attribution | Uncited recommendations |
| Zotero/local UI verification | Targeted asset tests or Playwright only for local/internal UI work | Visual claims without evidence |
| Cross-file refactors | Serena after local install | Fragile global search/replace |
| PR review automation | Manual Codex review workflow first | Auto-push/auto-merge before trust is established |

## Serena pilot

Serena is the recommended next tool for semantic code navigation/refactoring. It is not committed as a hard dependency because machines without Serena should still start Codex cleanly.

Install and initialize Serena once per machine:

```bash
uv tool install -p 3.13 serena-agent@latest --prerelease=allow
serena init
serena setup codex
```

Manual Codex MCP configuration, if needed in `~/.codex/config.toml`:

```toml
[mcp_servers.serena]
startup_timeout_sec = 15
command = "serena"
args = ["start-mcp-server", "--project-from-cwd", "--context=codex"]
```

For this repo, validate the pilot by asking Codex to locate definitions/references across `packages/` and `skills/` before using Serena for edits.

## Verification commands

Fast workflow/config validation:

```bash
scripts/codex-check.sh --quick
```

Synchronize RH skills to local Codex:

```bash
scripts/sync-rh-to-codex.sh
```

Install local git hooks that sync after successful local updates:

```bash
scripts/install-codex-sync-hook.sh
```

Full local gate before a PR:

```bash
scripts/codex-check.sh --full
```

Targeted options:

```bash
scripts/codex-check.sh --python
scripts/codex-check.sh --mcp
```

## GitHub Codex review workflow

The checked-in `.github/workflows/codex-review.yml` is intentionally `workflow_dispatch` only. To use it:

1. Add `OPENAI_API_KEY` as a GitHub Actions secret.
2. Trigger the workflow manually with a PR number.
3. Inspect the PR comment quality for several runs.
4. Only then consider adding pull request triggers.

## Sources checked while designing this workflow

- OpenAI Codex configuration reference: https://developers.openai.com/codex/config-reference
- OpenAI Codex skills documentation: https://developers.openai.com/codex/skills
- OpenAI Codex GitHub Action: https://github.com/openai/codex-action
- Serena Codex client setup: https://oraios.github.io/serena/02-usage/030_clients.html
- Serena project workflow: https://oraios.github.io/serena/02-usage/040_workflow.html
