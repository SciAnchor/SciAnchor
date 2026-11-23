# Research Harness Architecture

## Overview

Research Harness is an MCP-based research automation system that orchestrates the full lifecycle from literature review to paper writing. It provides evidence-gated stage progression, adversarial review, provenance tracking, and self-improving skill evolution.

## Core Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   MCP Server                            │
│  (25 public tools; 141 compatibility-dispatch names)    │
├─────────────────────────────────────────────────────────┤
│              Orchestrator Service                       │
│  ┌─────┐ ┌─────┐ ┌───────┐ ┌───────┐ ┌──────────┐ ┌─────┐│
│  │init │→│build│→│analyze│→│propose│→│experiment│→│write││
│  └─────┘ └─────┘ └───────┘ └───────┘ └──────────┘ └─────┘│
│  Gates: approval│coverage│adversarial│experiment│review │
├─────────────────────────────────────────────────────────┤
│  Primitives    │  Provenance  │  Observation            │
│  (87 ops)      │  (audit trail)│  (evaluator evolution) │
├─────────────────────────────────────────────────────────┤
│  Execution Backends (LLM, Local, Plugin)                │
├─────────────────────────────────────────────────────────┤
│  SQLite Storage (pool.db)                               │
└─────────────────────────────────────────────────────────┘
```

## Dual-Axis Execution Model

- **workflow_mode** (explore|standard|strict|demo): Controls depth and quality thresholds
- **autonomy_mode** (supervised|autonomous): Controls who resolves gates
  - Supervised: Human approval at key checkpoints
  - Autonomous: Agent auto-resolves gates (with budget limits and safety rails)

## Key Design Principles

1. **Evidence-gated progression**: Advance only when structured artifacts prove readiness
2. **Separation of generation and evaluation**: Adversarial review via independent models
3. **Persistent artifacts over ephemeral outputs**: Typed, versioned artifacts in SQLite
4. **Provenance for audit**: Every primitive execution recorded with cost and lineage
5. **Human authority preserved**: Override capability at all stages
6. **Plugin-extensible**: New primitives, gates, stages, and backends via plugin manifests

## Delivery Protocol Layer

RH layers a research delivery protocol on top of the evidence/state kernel
without changing it. The RH research delivery protocol treats brief,
proposal, experiment, review, paper, presubmission, and rebuttal deliverables
as RH artifact conventions recorded through existing skills and provenance.
The protocol has no external runtime dependency and does not add public MCP
tools, storage tables, or orchestrator semantics. See
[research-delivery-protocol.md](research-delivery-protocol.md).

## Extension Points

| Point | What It Extends | Registration |
|-------|----------------|-------------|
| Primitives | Paper sources, analysis tools | `@register_primitive(spec)` |
| Gates | Quality checks at stage boundaries | `GateEvaluator` subclass |
| Stages | Orchestrator pipeline steps | `STAGE_REGISTRY` + `STAGE_GRAPH` |
| Advisory Rules | Heuristic warnings | `AdvisoryEngine` methods |
| Backends | Execution providers | `ExecutionBackend` interface |

## Current Status

See [STATUS.md](STATUS.md) for the current source of truth. In short:

- MCP `tools/list` advertises 25 public contracted tools from
  `research_harness_mcp.tool_surface`.
- Internal compatibility dispatch still recognizes 141 executable names,
  including 87 registered primitives.
- The current orchestrator is a 6-stage bounded graph, not a generic arbitrary
  DAG. [planned] Generalized workflow DAG editing remains future work.

## License

GNU AGPL-3.0, with a commercial license available; see `LICENSE`, `NOTICE` and `THIRD_PARTY_NOTICES.md`.
