---
name: research-init
description: Initialize a new research topic or new project integration for Research Harness. Trigger on phrases like "research-init", "/research-init", "初始化研究主题", "初始化 Research Harness", "给项目接入 Research Harness", or equivalent requests to create topic scaffolding, update AGENTS or CLAUDE guidance, and ingest seed papers.
public_suite: research
task_type: initialization
data_access_level: local+external
inputs: topic name, research scope, venue, seed papers, project workspace, optional PAPER_PROFILE
outputs: topic record, bootstrap guidance, seed ingestion plan, RESEARCH_BRIEF, PROBLEM_ANCHOR, initial artifacts
gates: every ingested paper needs topic_id; record durable bootstrap outputs; paper-bound topics need an explicit PROBLEM_ANCHOR and later EVALUATION_GATE_PROFILE with baseline_mode, paper_access_status, fatal_flaws, and pilot boundary
artifact_schemas: topic, RESEARCH_BRIEF, PROBLEM_ANCHOR, frontier_attention_evidence, EVALUATION_GATE_PROFILE
estimated_runtime: 10-30 min
---

# Research Init

Use this skill when the user wants to bootstrap a project or topic into Research Harness.

## RH research delivery protocol

Use RH as the evidence and state source of truth. The protocol has no external runtime dependency.
When the user gives a `protocol_call`, create or update the
requested bootstrap artifact directly. When the user gives a
`human_in_loop_call`, infer whether the missing entry point is topic metadata,
seed evidence, or a `RESEARCH_BRIEF`, then record the durable output as an RH
artifact.

## Problem Anchor Seed

For any topic intended to become a paper, survey, experiment, position paper,
or serious research direction, seed `PROBLEM_ANCHOR` early. It should capture:

- the concrete problem, beneficiary, policy issue, scholarly debate, source
  corpus, or construct gap;
- the closest baseline, authority, prior theory, source anchor, or control
  condition known so far;
- the intended `baseline_mode` such as `extract-only`, replication/access
  check, public-dataset analysis, archive access, or authority access;
- the current `paper_access_status` for required papers, code, tables,
  statistical values, source corpus, or authorities;
- known `fatal_flaws` and whether the next decision will require a signal
  `pilot`.

Do not silently initialize a paper-bound topic as STEM. If discipline,
research type, study design, baseline_mode, or paper_access_status is unknown,
record that as a blocker or assumption rather than promoting it.

## Workflow

1. Read `docs/agent-guide.md` in the Research Harness checkout.
2. Identify:
   - topic slug or project name
   - target venue or timeline if provided
   - seed papers, DOI, arXiv IDs, or PDFs if provided
3. Ensure the target project has Research Harness guidance:
   - add or update `AGENTS.md` for Codex
   - if the user explicitly wants Claude compatibility, update `CLAUDE.md` too
4. If `rhub` or MCP is available, perform the minimum viable setup:
   - initialize the topic
   - ingest any provided seed papers
   - record `RESEARCH_BRIEF` when the topic needs delivery-level scope,
     constraints, venue, success criteria, or explicit review criteria
   - seed `PROBLEM_ANCHOR` when the topic is paper-bound
   - record assumptions when metadata is incomplete
5. If the user did not provide a topic slug, derive one from the title using lowercase hyphen-case.
6. Return a compact setup report with:
   - topic slug
   - touched files
   - ingested seeds
   - missing inputs
   - next 3 actions

## Execution Heuristic

Prefer doing the setup directly instead of only describing it when the repo context is clear enough.

If inputs are partial, continue with safe defaults:

- missing venue: omit it
- missing seeds: create integration files first
- missing project-level guidance: use `docs/research-bootstrap.md` as the source template

Do not block on optional metadata.

## Rules

- Prefer using existing Research Harness conventions from `docs/research-bootstrap.md`.
- Do not invent seed papers.
- If topic metadata is missing, make the minimum safe assumptions and state them clearly.
- For any topic intended for a paper, survey, or serious research direction,
  create or request a `frontier_attention_evidence` artifact: latest top
  academic signals plus official industry signals proving the direction is
  actively important. If either side is weak, report it as a scope risk rather
  than overstating the topic.
- For any topic intended to advance into proposal or experiments, require a
  later `EVALUATION_GATE_PROFILE` before promotion; it must include
  baseline_mode, paper_access_status, fatal_flaws, and pilot decision.
