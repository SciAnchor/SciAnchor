# RH Release Boundary

Status: active release-readiness reference.

This document is the compact pre-release boundary for Research Harness. It is
the wording source for README, quickstart, and status pages when describing what
is stable, local/internal, private, or deferred.

## Stable And Local

- Stable public/local CLI-MCP-skill workflow.
- Local/internal HTTP bridge only.
- Stable Zotero push dry-run validation only.
- Fake/sandbox Zotero pull/both and apply evidence is local-only.
- Private benchmark/performance regression governance only.

## Deferred

- Stable external API release: deferred.
- Public internet deployment: deferred.
- Real Zotero network sync/apply remains deferred.
- Real Zotero pull/both-direction reads remain deferred outside fake/sandbox
  adapters.
- Public benchmark/performance claims remain deferred.
- Public leaderboard/ranking claims remain deferred.
- Release, publish, commit, push, and PR actions remain deferred unless the user
  explicitly requests that external action.

## Operational Notes

The public MCP and local CLI/skill workflow are the stable agent-facing path.
The HTTP bridge is a loopback/local integration surface for dashboards and
Zotero-side tooling; it is not a public hosted API commitment.
Non-loopback HTTP binding is unsupported and not release-approved.
Public HTTP deployment requires RESEARCH_HARNESS_HTTP_API_TOKEN plus reviewed
TLS/proxy, network allowlist, scoped CORS origins, private/no-store cache
policy, rollback, and monitoring plan. Runtime startup rejects
`RESEARCH_HARNESS_CORS_ORIGINS=*` because credentialed wildcard CORS is not a
supported local or public configuration.

The local app may be bound to non-loopback only for reviewed local experiments,
and startup must fail closed unless `RESEARCH_HARNESS_HTTP_API_TOKEN` is set.
Any actual public deployment must terminate TLS at a reviewed proxy, restrict
source networks or clients with an allowlist, avoid wildcard credentialed CORS,
keep sensitive and beta responses non-cacheable, and include a rollback and
monitoring plan before exposure.

Zotero is stable only for local `direction=push`, `dry_run=true` validation
that does not create a real Zotero client or write to a Zotero library. Phase B
fake/sandbox coverage validates pull/both dry-run and non-dry-run apply
evidence with injected sandbox adapters, intent plans, previews, receipts, and
rollback/recovery notes. Sandbox seed-apply evidence defers provider-backed
paper acquisition, deep-read, and PDF annotation postprocessors and records
receipt warnings instead of executing them. Any real network-backed sync/apply
or provider-backed seed-apply postprocess path requires a separate gate and
explicit user authorization.

Benchmark and performance artifacts are private/local regression evidence. They
can guide RH development, but they do not support public benchmark, leaderboard,
ranking, release-grade, or public performance claims.
