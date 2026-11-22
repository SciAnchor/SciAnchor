# Paper Production Workspace Protocol

This protocol defines how Research Harness paper-production sessions organize reusable rules and local working artifacts. The goal is to make the workflow portable while keeping concrete experiment and manuscript outputs private by default.

## Storage model

RH remains the source of truth for topics, papers, claims, evidence, artifacts, provenance, and gates. Local workspace files are fallback, cache, or delivery-staging artifacts unless they have been recorded into RH.

Use [Paper Management (EN)](PAPER_MANAGEMENT.md) for the single `pool.db`, managed PDF downloads, and absolute-path rules. Generated paper-production runs should stay under ignored local state such as `.research-harness/`, a project-specific ignored workspace, or another private path configured by the user.

## Recommended local layout

A topic workspace may use this ignored structure when RH MCP or artifact recording is unavailable:

```text
<repo>/.research-harness/
├── pool.db
├── downloads/
└── topics/
    └── <topic-slug>/
        └── paper-production/
            ├── 00-topic-brief/
            ├── 01-dataset-survey/
            ├── 02-paper-pool/
            ├── 03-literature-map/
            ├── 04-deep-read-synthesis/
            ├── 05-experiment-design/
            ├── 06-figure-plan/
            ├── 07-draft-pack/
            ├── 08-authorship/
            └── 09-publication-pack/
```

These folder names map to the public artifact lineage used by `rh-paper-production`:

| Folder | Artifact type |
| --- | --- |
| `00-topic-brief/` | `topic_brief` |
| `01-dataset-survey/` | `dataset_survey` |
| `02-paper-pool/` | `paper_pool` |
| `03-literature-map/` | `literature_map` |
| `04-deep-read-synthesis/` | `deep_read_synthesis` |
| `05-experiment-design/` | `experiment_design` |
| `06-figure-plan/` | `figure_plan` |
| `07-draft-pack/` | `draft_pack` |
| `08-authorship/` | `authorship_statement` |
| `09-publication-pack/` | `publication_pack` |

When recording artifacts later, preserve dependency IDs or local dependency paths so lineage remains recoverable.

## Public/private boundary

Commit reusable protocol assets:

- public docs and skill contracts;
- sanitized templates or examples;
- gate definitions, artifact schemas, and workflow rules;
- generic project guidance that does not expose a real topic's private contents.

Do not commit instance assets:

- generated TeX, DOCX, PDFs, slides, status JSON, progress logs, and draft bundles;
- local databases, downloaded papers, paper caches, and private bibliographies;
- unpublished experiment outputs, raw datasets, credentials, or personal machine paths;
- topic-specific rules that should live only in RH artifacts or a private workspace profile.

If a concrete artifact must become an example, rewrite it as a sanitized fixture under a docs or tests path. Do not publish an active run directory directly.

## Fallback artifact metadata

When RH artifact recording is unavailable, local fallback files should keep RH-compatible metadata:

```yaml
artifact_type: paper_pool
topic_slug: <topic-slug>
status: RH_SYNC_PENDING
provenance:
  source:
    type: <mcp|web|local>
    query_or_path: <stable-source-or-private-local-path>
    access_date: <YYYY-MM-DD>
dependencies:
  - artifact_type: topic_brief
    ref: <artifact-id-or-local-path>
```

Replace `artifact_type` with the appropriate lineage value for the stage. Use private local paths only inside ignored workspace files; public docs and examples should use placeholders.

## Claim boundaries

For `main` mode, manuscript claims must reflect observed or provenance-backed evidence. Planned, expected, or missing results remain explicit in artifact metadata and should not be promoted into completed evidence.

## Workspace profiles

A project may define a private workspace profile with local venue defaults, directory shortcuts, or template preferences. Keep that profile ignored unless it is fully generic and sanitized. Public RH skills should refer to project profiles when present, but must not hard-code one user's workspace path as the default for everyone.
