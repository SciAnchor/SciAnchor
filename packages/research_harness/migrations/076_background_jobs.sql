-- BUG-011: durable background-job registry so a long operation can return a
-- job_id immediately and run in the background, while callers poll status /
-- progress instead of blocking past the MCP transport timeout (and re-submitting,
-- which produced duplicate work).
CREATE TABLE IF NOT EXISTS background_jobs (
    job_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK(status IN ('running', 'done', 'failed', 'cancelled')),
    progress REAL DEFAULT 0.0,
    total INTEGER DEFAULT 0,
    result_json TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
