-- Migration 071: first-class PubMed identifiers for medical literature.
--
-- PMID is the stable PubMed record identifier. PMCID identifies PubMed Central
-- full-text availability and drives manual full-text/PDF acquisition queues.
-- Both are nullable so non-medical papers are unaffected.

ALTER TABLE papers ADD COLUMN pmid TEXT;
ALTER TABLE papers ADD COLUMN pmcid TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pmid_unique
ON papers(pmid)
WHERE pmid IS NOT NULL AND TRIM(pmid) != '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pmcid_unique
ON papers(pmcid)
WHERE pmcid IS NOT NULL AND TRIM(pmcid) != '';
