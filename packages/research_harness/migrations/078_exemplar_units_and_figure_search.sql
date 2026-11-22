-- Migration 078: first-class exemplar units (IDX03/W4) + figure search helpers (W5).
-- Quality axes for figures remain deferred; caption/interpretation text is the local index.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS exemplar_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    unit_type TEXT NOT NULL DEFAULT '',
    source_paper_id INTEGER NOT NULL DEFAULT 0,
    source_title TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '',
    venue_tier TEXT NOT NULL DEFAULT '',
    quality REAL NOT NULL DEFAULT 0,
    form_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (topic_id, unit_type, source_paper_id)
);

CREATE INDEX IF NOT EXISTS idx_exemplar_units_topic_type
ON exemplar_units(topic_id, unit_type, quality DESC);

-- Optional local quality score for extracted figures (0-10). NULL = unscored.
-- Does not invent SciDraw axes; just a durable slot for later gates.
ALTER TABLE extracted_figures ADD COLUMN quality_score REAL;

CREATE INDEX IF NOT EXISTS idx_extracted_figures_type
ON extracted_figures(figure_type);

COMMIT;
