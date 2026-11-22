-- Topic Knowledge Layer v1 derived read model.
-- Canonical sources remain papers, cards, annotations, claims, gaps, taxonomy,
-- method atoms, and project artifacts. These tables are rebuildable.

CREATE TABLE IF NOT EXISTS semantic_atoms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  atom_type TEXT NOT NULL CHECK(atom_type IN (
    'claim',
    'method',
    'task',
    'dataset',
    'metric',
    'result',
    'limitation',
    'assumption',
    'baseline',
    'gap_signal',
    'doc_signal'
  )),
  normalized_key TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  paper_id INTEGER,
  source_section TEXT NOT NULL DEFAULT '',
  snippet TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0.0,
  source_hash TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
  FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_atoms_unique_source
ON semantic_atoms(topic_id, atom_type, normalized_key, source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_semantic_atoms_topic_type
ON semantic_atoms(topic_id, atom_type);

CREATE INDEX IF NOT EXISTS idx_semantic_atoms_paper
ON semantic_atoms(paper_id);

CREATE INDEX IF NOT EXISTS idx_semantic_atoms_source
ON semantic_atoms(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_semantic_atoms_source_hash
ON semantic_atoms(source_hash);

CREATE TABLE IF NOT EXISTS semantic_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  edge_type TEXT NOT NULL CHECK(edge_type IN (
    'supports',
    'contradicts',
    'extends',
    'compares_with',
    'evaluates_on',
    'uses_dataset',
    'reports_metric',
    'derived_from'
  )),
  from_atom_id INTEGER NOT NULL,
  to_atom_id INTEGER NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,
  source_hash TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
  FOREIGN KEY (from_atom_id) REFERENCES semantic_atoms(id) ON DELETE CASCADE,
  FOREIGN KEY (to_atom_id) REFERENCES semantic_atoms(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_edges_unique_source
ON semantic_edges(topic_id, edge_type, from_atom_id, to_atom_id, source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_semantic_edges_topic_type
ON semantic_edges(topic_id, edge_type);

CREATE INDEX IF NOT EXISTS idx_semantic_edges_from_atom
ON semantic_edges(from_atom_id);

CREATE INDEX IF NOT EXISTS idx_semantic_edges_to_atom
ON semantic_edges(to_atom_id);

CREATE INDEX IF NOT EXISTS idx_semantic_edges_source
ON semantic_edges(source_type, source_id);

CREATE TABLE IF NOT EXISTS topic_knowledge_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  artifact_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN (
    'active',
    'stale',
    'superseded'
  )),
  snapshot_version TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  source_manifest_json TEXT NOT NULL DEFAULT '{}',
  coverage_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
  FOREIGN KEY (artifact_id) REFERENCES project_artifacts(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_knowledge_snapshots_unique_source
ON topic_knowledge_snapshots(topic_id, source_hash, snapshot_version);

CREATE INDEX IF NOT EXISTS idx_topic_knowledge_snapshots_topic_status
ON topic_knowledge_snapshots(topic_id, status);

CREATE INDEX IF NOT EXISTS idx_topic_knowledge_snapshots_artifact
ON topic_knowledge_snapshots(artifact_id);

CREATE INDEX IF NOT EXISTS idx_topic_knowledge_snapshots_source_hash
ON topic_knowledge_snapshots(source_hash);
