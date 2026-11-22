-- Runtime event store schema-only foundation.
--
-- This migration creates an append-only table for normalized runtime event
-- records. It intentionally does not add writers, backfills, provenance
-- ownership changes, public surfaces, or orchestrator behavior changes.

CREATE TABLE IF NOT EXISTS runtime_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  trace_id TEXT,
  event_type TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  origin_surface TEXT NOT NULL,
  actor TEXT,
  topic_id INTEGER,
  job_id TEXT,
  tool_name TEXT,
  artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  gate_decision TEXT,
  error_code TEXT,
  schema_version TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_events_event_id
ON runtime_events(event_id);

CREATE INDEX IF NOT EXISTS idx_runtime_events_trace_created
ON runtime_events(trace_id, created_at);

CREATE INDEX IF NOT EXISTS idx_runtime_events_topic_created
ON runtime_events(topic_id, created_at);

CREATE INDEX IF NOT EXISTS idx_runtime_events_job_created
ON runtime_events(job_id, created_at);

CREATE INDEX IF NOT EXISTS idx_runtime_events_type_created
ON runtime_events(event_type, created_at);

CREATE TRIGGER IF NOT EXISTS trg_runtime_events_no_update
BEFORE UPDATE ON runtime_events
BEGIN
  SELECT RAISE(ABORT, 'runtime_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_runtime_events_no_delete
BEFORE DELETE ON runtime_events
BEGIN
  SELECT RAISE(ABORT, 'runtime_events is append-only');
END;
