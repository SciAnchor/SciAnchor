# Topic Knowledge HTTP API

Status: stable local/internal HTTP bridge; K211-approved refresh endpoints active.

The Topic Knowledge HTTP API exposes status, refresh, and cross-topic atlas
endpoints from the local Research Harness FastAPI bridge. It is stable for local
dashboards and internal automation that already have access to an RH pool
database.

stable external API release is not approved. Do not expose this bridge on a
public network without a separate release/deployment gate covering TLS, network
allowlisting, scoped CORS origins, rollback, monitoring, and a reviewed
public-support commitment. For this local/internal bridge, public internet deployment
remains out of scope.
Non-loopback HTTP binding is unsupported and not release-approved.
Public HTTP deployment requires RESEARCH_HARNESS_HTTP_API_TOKEN plus reviewed
TLS/proxy, network allowlist, scoped CORS origins, private/no-store cache
policy, rollback, and monitoring plan.

## Endpoints

- `GET /api/topics/{topic_id}/knowledge-status`
- `POST /api/topics/{topic_id}/knowledge-refresh`
- `POST /api/topics/knowledge-refresh-all`
- `GET /api/topics/cross-topic-atlas?topic_id=<id>&topic_id=<id>`

The `GET` endpoints are read-only. They read existing Topic Knowledge snapshots
and Research Wiki-derived signals. A status or atlas request does not build snapshots and does not write artifacts.

The `POST` refresh endpoints rebuild the derived Topic Knowledge snapshot rows,
semantic atoms/edges, and snapshot artifact metadata from existing canonical RH
paper/evidence rows. Refresh does not ingest papers, call LLMs, write
provenance, or change orchestrator state.

The API:

- reads existing snapshots for status and atlas;
- builds only derived Topic Knowledge snapshots for refresh requests;
- writes only rebuildable Topic Knowledge artifact/read-model rows;
- does not write provenance;
- does not execute research primitives;
- does not ingest papers;
- does not change orchestrator state.

## Start

Install the HTTP bridge extras, set a local bridge token, scope CORS, and start
the local API:

```bash
pip install -e "packages/research_harness_mcp[api]"

export RESEARCH_HARNESS_DB_PATH="$PWD/.research-harness/pool.db"
export RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN="<secret-beta-token>"
export RESEARCH_HARNESS_CORS_ORIGINS="http://127.0.0.1:3000,http://localhost:3000"

python -m research_harness_mcp.http_api
```

The default host is loopback-only: `127.0.0.1:8000`.

Non-loopback startup fails closed unless `RESEARCH_HARNESS_HTTP_API_TOKEN` is
configured. That token is only the mandatory app-level auth gate; it does not
replace the required TLS/proxy, network allowlist, scoped CORS, cache, rollback,
and monitoring review for any public deployment.

`RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN` is optional for trusted loopback
development but required for shared local/internal use. When it is set, callers
must send either:

```http
X-RH-Knowledge-Token: <secret-beta-token>
```

or:

```http
Authorization: Bearer <secret-beta-token>
```

## Examples

```bash
curl -s \
  -H "Authorization: Bearer $RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN" \
  "http://127.0.0.1:8000/api/topics/1/knowledge-status"
```

```bash
curl -s \
  -H "X-RH-Knowledge-Token: $RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN" \
  "http://127.0.0.1:8000/api/topics/cross-topic-atlas?topic_id=1&topic_id=2&query=provenance"
```

```bash
curl -s -X POST \
  -H "Authorization: Bearer $RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN" \
  "http://127.0.0.1:8000/api/topics/1/knowledge-refresh"
```

## Response Contracts

`knowledge-status` returns a `knowledge_status.v1` JSON payload with topic id,
readiness status, snapshot reference, coverage counts, wiki aggregate counts,
warnings, links, and existing RH next-action names.

`cross-topic-atlas` returns a `cross_topic_knowledge_atlas.v1` JSON payload with
topic ids, ranked cross-topic links, public evidence summaries, warnings, and
optional query ranking.

`knowledge-refresh` returns a public-safe refresh result with `status`, topic
id, artifact id, snapshot id, source hash, and error fields. `knowledge-refresh-
all` returns per-topic results plus refreshed/reused/skipped/failed counts.

Every Topic Knowledge HTTP API response includes:

```http
Cache-Control: private, no-store
```

Public error responses use:

```json
{
  "error": {
    "code": "knowledge_api_token_required",
    "message": "knowledge API beta token required"
  }
}
```

Token failures also return the public JSON error envelope. The message keeps
legacy beta-token compatibility and must not be interpreted as approval for an
external beta or stable public API.
CORS response headers are only emitted for origins listed in
`RESEARCH_HARNESS_CORS_ORIGINS`; browser clients from other origins should
expect the browser to block access to the JSON body. Startup fails closed when
`RESEARCH_HARNESS_CORS_ORIGINS=*` is configured because credentialed wildcard
CORS is unsupported.

Other expected public error codes include `invalid_topic_id`,
`invalid_topic_ids`, `knowledge_status_unavailable`, and
`cross_topic_atlas_unavailable`, `topic_not_found`, and
`topic_knowledge_refresh_failed`.

## Local/Internal Stable Boundary

Approved:

- local/internal status, refresh, and atlas use;
- existing local FastAPI bridge;
- optional token gate through `RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN`;
- scoped CORS through `RESEARCH_HARNESS_CORS_ORIGINS`;
- public-safe JSON only.

Not approved:

- stable external API release;
- Zotero UI or sync changes;
- skill/workflow advertising;
- database schema changes;
- provenance writes;
- orchestrator gate changes;
- benchmark or release-readiness claims beyond this local/internal boundary.
