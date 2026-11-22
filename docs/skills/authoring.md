# Authoring a Skill

A skill is a folder under [`skills/`](../../skills/) with a single required
file: `SKILL.md`. The format is the same one Claude Code and Codex
already understand, so any compliant agent can consume it.

## Minimum viable skill

```
skills/my-skill/
└── SKILL.md
```

```markdown
---
name: my-skill
description: |
  One-line summary of what this skill does. Trigger on phrases like
  "my-skill", "/my-skill", or "do the thing".
---

# My Skill

Body — any Markdown the agent should follow when this skill is selected.
```

## Promoted skill package v2

`SKILL.md` remains the compatibility entrypoint for every agent runtime. For
promoted, project-level RH skills, add a machine-readable package contract next
to it:

```
skills/my-skill/
├── SKILL.md
├── skill.yaml
└── contracts/
    ├── input.yaml
    ├── output.yaml
    └── guardrails.yaml
```

Use this layout when a skill is promoted by lifecycle/replay evidence or when
Python runtime code needs to validate its inputs, outputs, tools, guardrails,
and promotion policy. `skill.yaml` should include at least `name`, `version`,
`license`, `capability_type`, `description`, `input_schema`, `output_schema`,
`allowed_tools`, `required_artifacts`, `guardrails`, `replay_tests`, and
`promotion_policy`. Runtime capability types are `primitive`, `skill`,
`adapter`, and `evaluator`.

The `SKILL.md` front-matter name and version must match `skill.yaml`. Keep
`SKILL.md` concise and agent-facing; put durable schemas and promotion gates in
the contract files so they can be tested without loading the whole handbook.

Promoted evaluator packages can also be made callable by registering a Python
runtime through `research_harness.evaluator.runtime`. The
runtime entrypoint receives the materialized `CapabilityManifest` and `RunSpec`,
validates the referenced artifacts, runs the evaluator, records the produced
artifact, and records a sidecar `run_trace` plus `runtime_trace_grade` artifact
for replay/debugging.
For example, `final-bundle-quality` is callable from an auto-runner checkpoint
with:

```yaml
runtime_contract:
  skill_name: final-bundle-quality
  execute_skill: true
  artifact_refs:
    - artifact:final_bundle:123
  literal_inputs:
    mode: quality_scan
```

Keep `skill.yaml` tool names abstract (`artifact.read`,
`pdf.scan_quality_bundle`, `orchestrator.record_artifact`) and map them inside
the registered runtime. Do not put topic-specific paths, artifact IDs, or
promotion shortcuts into the runtime.

## Front-matter fields

| Key             | Required | Notes                                                    |
|-----------------|----------|----------------------------------------------------------|
| `name`          | yes      | kebab-case; must match the directory name                |
| `description`   | yes      | One-line summary; embed natural-language triggers here   |
| `public_suite`  | yes      | One of `research`, `paper`, `review`, `zotero`, `benchmark` |
| `task_type`     | yes      | Short task label such as `discovery`, `writing`, `gating` |
| `data_access_level` | yes  | Human-readable data boundary, e.g. `local`, `local+external`, `zotero-local` |
| `inputs`        | yes      | Compact comma-separated input contract                   |
| `outputs`       | yes      | Compact comma-separated output contract                  |
| `gates`         | yes      | Safety/readiness gate the agent must respect             |
| `artifact_schemas` | yes   | RH artifact names or `none`                              |
| `estimated_runtime` | yes  | Rough human-visible time range                           |
| `category`      | no       | Free-form group label, e.g. `writing`, `discovery`       |
| `version`       | no       | Skill version, semver recommended                        |
| `allowed-tools` | no       | List of tool names the agent should restrict to          |

Anything else is preserved under `extras` in the manifest.

The lightweight product contract is intentionally scalar front matter rather
than a full runtime package. Use it for public discovery, UI grouping, and
agent routing. Use `skill.yaml` plus `contracts/` only when the skill is
promoted into a replayable runtime capability.

## Triggers

Triggers are not a separate field — they live in the `description`. Convention
is to write a sentence like:

> Trigger on phrases like "X", "/X", "中文 X", or equivalent requests.

Agent runtimes match user messages against the description text, so explicit
trigger lists improve recall.

## Multi-track skills

If a skill has variants (like `paper-writing` covering 6 different paper
types), put each track in `tracks/<name>.md`:

```
skills/paper-writing/
├── SKILL.md                ← entrypoint, picks track by user intent
└── tracks/
    ├── original-research.md
    ├── survey-review.md
    └── ...
```

The manifest auto-detects the tracks subdirectory and lists them under the
skill's `tracks` field. The MCP `skill_get` tool accepts a `track` parameter
to fetch a specific variant.

## Supporting files

Anything else in the skill folder — `references/`, examples, JSON
templates — is shipped along with the skill via symlink/copy. Keep it light.

## Conventions in this repo

* Top-level `skills/` is only for user-facing research workflow skills.
* All shipped public skills are vendor-neutral; don't bake "Claude" or "Codex"
  into the body unless behavior really differs.
* Reference RH primitives by their MCP tool name (e.g.
  `mcp__research-harness__paper_search`), not by CLI command.
* When a skill produces an artifact, mention `orchestrator_record_artifact`
  so it shows up in provenance.

## Local iteration

```bash
# Edit a skill, then:
rh skill index            # regenerate skills/manifest.json
rh skill list             # confirm it shows up
rh skill verify           # confirm install is in sync
```

If you symlinked the skill in (the default), the agent picks up the change
on its next session automatically.
