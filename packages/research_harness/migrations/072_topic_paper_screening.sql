ALTER TABLE paper_topics ADD COLUMN screening_status TEXT DEFAULT 'screened_in';
ALTER TABLE paper_topics ADD COLUMN evidence_role TEXT DEFAULT 'unreviewed';
ALTER TABLE paper_topics ADD COLUMN manuscript_eligible INTEGER DEFAULT 1;
ALTER TABLE paper_topics ADD COLUMN screened_at TEXT;
ALTER TABLE paper_topics ADD COLUMN screening_reason TEXT DEFAULT '';
ALTER TABLE paper_topics ADD COLUMN candidate_source TEXT DEFAULT '';
