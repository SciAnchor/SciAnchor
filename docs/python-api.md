# Python API

Research Harness exposes a partial/programmatic facade that does not require an
agent tool or MCP client. It is useful from notebooks, scripts, and integration
tests, but it is not promoted as a stable external API release or as a complete
replacement for the public CLI/MCP/skills workflow.

## When to use this

- Jupyter notebooks during exploratory literature review
- Custom pipelines that embed research primitives alongside your own code
- CI checks (e.g., verify that a topic's paper pool hasn't regressed)
- Testing a new primitive you are developing

For agentic workflows, use an MCP client instead (see the [Agent Guide](agent-guide.md)).
For shell scripting, use the `rh` CLI.

## Setup

```bash
pip install -e "packages/research_harness[dev]"
```

Make sure your `.env` has at least one LLM provider key (see `.env.example`).

## Minimal Example

```python
from research_harness import ResearchAPI

# Auto-resolves DB path from .env / env vars (default: .research-harness/pool.db)
api = ResearchAPI()

# 1. Search papers (returns a structured result dict)
hits = api.paper_search(
    query="instruction tuning for reasoning",
    max_results=5,
    auto_ingest=True,      # save top hits into the pool
)
print(f"Found {len(hits.get('papers', []))} papers")

# 2. Ingest a specific paper by arXiv ID
result = api.paper_ingest(source="2401.12345", topic_id=1, relevance="high")
print(result)

# 3. Run any primitive by name — `execute_primitive` is the escape hatch
gaps = api.execute_primitive("gap_detect", topic_id=1, focus="reasoning benchmarks")
print(gaps)

# 4. Check orchestrator status for a topic
status = api.orchestrator_status(topic_id=1)
print(status["current_stage"], status["gate_status"])
```

## API Surface

The `ResearchAPI` class in `packages/research_harness/research_harness/api.py` provides
convenience wrappers for the most common operations, plus a general escape hatch:

| Method | Purpose |
|--------|---------|
| `paper_search(query, **kwargs)` | Delegate to the `paper_search` primitive |
| `paper_ingest(source, **kwargs)` | Ingest a paper by arxiv ID, DOI, or PDF path |
| `record_artifact(topic_id, stage, artifact_type, payload)` | Write a topic artifact |
| `orchestrator_status(topic_id)` | Stage + gate status |
| `gate_check(topic_id, stage=None)` | Run the gate for a specific stage |
| `add_artifact_dependency(from_id, to_id)` | Declare lineage between artifacts |
| `mark_artifact_stale(artifact_id, reason)` | Invalidate + optionally propagate downstream |
| `list_stale_artifacts(topic_id)` | What needs refreshing |
| `execute_primitive(name, **kwargs)` | **Escape hatch** — run currently registered primitives |

Currently registered primitives are reachable via `execute_primitive("<name>", ...)`
as a compatibility escape hatch. To enumerate:

```python
from research_harness.primitives.registry import list_primitives

for spec in list_primitives():
    print(f"{spec.name:30s}  {spec.category.value:12s}  {spec.description}")
```

## Research Delivery Paper-Production Snapshot

`delivery_paper_production_snapshot(topic_id=None, artifact_states=None, payloads=None)`
returns `rh.delivery.paper_production_snapshot.v1` as a read-only dry-run
view of the RH research delivery paper-production protocol.

- `topic_id` reads existing recorded topic artifacts and maps matching artifact
  labels into protocol state.
- `artifact_states` overrides topic-derived state for hypothetical planning.
- `payloads` supplies candidate artifact payloads for validation.

The snapshot reports the next artifact/action, readiness records, blockers,
summary counts, `dry_run=true`, and input-source metadata. The snapshot does
not call `orchestrator_record_artifact`; it does not advance stages, does not
write artifacts, and is not exposed as MCP, CLI, or HTTP.

## Using a Custom DB Path

```python
from research_harness import ResearchAPI

api = ResearchAPI(db_path="/path/to/my/pool.db")
```

Or set `RESEARCH_HARNESS_DB_PATH` in your environment before import.

## Notebook Pattern

```python
import pandas as pd
from research_harness import ResearchAPI

api = ResearchAPI()

# Pull all papers in topic 1 into a DataFrame for ad-hoc analysis
import sqlite3
conn = sqlite3.connect(api.db_path)
df = pd.read_sql_query(
    "SELECT id, title, venue, year, citation_count FROM papers "
    "JOIN topic_papers ON papers.id = topic_papers.paper_id "
    "WHERE topic_papers.topic_id = 1",
    conn,
)
df.head()
```

The database is a plain SQLite file — read-only queries from pandas, duckdb, or
your favorite tool are safe and do not conflict with the harness.

## Running Primitives in Bulk

```python
from research_harness import ResearchAPI
from research_harness.primitives.registry import list_primitives

api = ResearchAPI()

# Summarize every paper in topic 1
summaries = []
rows = api.db.query("SELECT id FROM topic_papers WHERE topic_id = ?", (1,))
for row in rows:
    paper_id = row["paper_id"]
    result = api.execute_primitive("paper_summarize", paper_id=paper_id)
    summaries.append(result)
```

## Differences vs. MCP

| Aspect | Python API | MCP |
|--------|-----------|-----|
| Transport | in-process function calls | stdio JSON-RPC |
| Auth/sandboxing | none (runs in your process) | managed by the MCP client |
| Error handling | Python exceptions bubble up | serialized in JSON response |
| Provenance tracking | still recorded | still recorded |
| Primitive coverage | Partial facade plus compatibility escape hatch via `execute_primitive` | 30 public contracted tools; hidden/internal compatibility names are not advertised |

Both paths hit the same primitive registry and the same database, so you can
mix them freely — e.g., use the Python API in a Jupyter notebook to prep data,
then switch to Claude Code for an agentic write-up session.

## Further Reading

- [Primitive reference](../packages/research_harness/research_harness/primitives/) — every `*_impls.py` module lists its specs
- [Orchestrator stages](architecture/06_orchestrator.md) — gate and artifact specifications
- [RH research delivery protocol](research-delivery-protocol.md) — read-only paper-production snapshot protocol
- [Plugin guide](plugin-guide.md) — adding your own primitives
