# Research Bootstrap Checklist

Use this checklist when initializing a new Research Harness topic or adding RH guidance to an existing project. It is a reusable protocol, not a place for concrete paper drafts, local databases, downloaded PDFs, or experiment outputs.

## Required inputs

Start with the smallest stable topic state:

- topic title or slug;
- research scope, problem, or motivating question;
- target venue, journal, or delivery type when known;
- optional seed papers, DOI, arXiv IDs, URLs, or local PDFs;
- writing mode `main`: evidence-backed reporting.

If a field is missing, record it as an assumption or blocker instead of inventing evidence.

## Bootstrap artifacts

For a paper-bound topic, create or update these durable RH artifacts as early as possible:

- `RESEARCH_BRIEF`: topic, audience, venue constraints, intended contribution, success criteria, and open questions.
- `PROBLEM_ANCHOR`: concrete problem, closest baseline or authority, baseline mode, paper/data access status, fatal flaws, and pilot decision boundary.
- `frontier_attention_evidence`: recent academic and official industry signals showing the topic is active and important.
- `EVALUATION_GATE_PROFILE`: baseline mode, access status, fatal flaws, and pilot boundary before promoting the topic into proposal or experiment work.

Attach every paper, claim, and generated artifact to an explicit topic. Use RH artifact recording when available; if RH MCP is unavailable, keep local fallback artifacts structured with the same artifact names and mark them `RH_SYNC_PENDING`.

## Workspace boundary

Use `.research-harness/` or the configured `RESEARCH_HARNESS_DB_PATH` for local RH state. Follow [Paper Management (EN)](PAPER_MANAGEMENT.md) for the single `pool.db`, PDF ingestion, and absolute-path rules.

Tracked project files should contain only reusable protocol assets:

- RH guidance such as `AGENTS.md`, `CLAUDE.md`, or public docs;
- skill contracts and workflow rules;
- sanitized templates or examples with no real experiment content.

Do not commit generated manuscripts, PDFs, status JSON, progress logs, local databases, downloaded papers, private drafts, unpublished experiment outputs, credentials, or files containing personal machine paths.

## Project guidance

When integrating RH into another project:

1. Add or update `AGENTS.md` for Codex-facing guidance.
2. Update `CLAUDE.md` only when Claude compatibility is explicitly needed.
3. Point project guidance back to RH docs and skills instead of copying long workflow rules into every topic folder.
4. Keep topic-specific decisions in RH artifacts or ignored local workspace state.

## Minimal setup report

After bootstrap, report:

- topic slug;
- files touched;
- seed papers or PDFs ingested or queued;
- assumptions and missing inputs;
- next three actions needed to advance the topic.
