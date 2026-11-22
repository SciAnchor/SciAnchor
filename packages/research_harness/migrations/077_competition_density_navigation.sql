-- Migration 077: make research-candidate ordering merit-first.
-- Competition density remains navigation metadata and is not an ordering lane.

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_rc_scope_sort;

CREATE INDEX idx_rc_scope_sort
ON research_candidates(
    scope,
    llm_score DESC,
    (CASE confidence_level
        WHEN 'high' THEN 0
        WHEN 'normal' THEN 1
        WHEN 'low' THEN 2
        ELSE 3
    END),
    id ASC
);

COMMIT;
