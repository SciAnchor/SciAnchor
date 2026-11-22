from research_harness.core.paper_pool import PaperPool
from research_harness.primitives.impls import paper_ingest
from research_harness.storage.models import Paper


def test_ingest_dedupes_doi_across_case_and_resolver_prefix(db):
    """DOIs differing only by case or ``https://doi.org/`` prefix must collapse
    to a single paper row rather than inserting duplicates."""
    conn = db.connect()
    try:
        pool = PaperPool(conn)
        first = pool.ingest(Paper(title="Paper One", doi="10.1234/AbC.99"))
        # same DOI, different case + resolver prefix
        second = pool.ingest(
            Paper(title="Paper One v2", doi="https://doi.org/10.1234/abc.99")
        )
        assert first == second
        count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_ingest_dedupes_pmcid_case_insensitively(db):
    conn = db.connect()
    try:
        pool = PaperPool(conn)
        first = pool.ingest(Paper(title="PMC Paper", pmcid="PMC123456"))
        second = pool.ingest(Paper(title="PMC Paper dup", pmcid="pmc123456"))
        assert first == second
        count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_paper_ingest_accepts_prefixed_doi_source(db, monkeypatch):
    monkeypatch.setattr(PaperPool, "enrich_metadata", lambda self, paper_id: {})

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('demo')")
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[
            0
        ]
        conn.commit()
    finally:
        conn.close()

    result = paper_ingest(db=db, source="doi:10.1234/test", topic_id=topic_id)

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title, doi, arxiv_id FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
    finally:
        conn.close()

    assert result.status == "new"
    assert row["doi"] == "10.1234/test"
    assert row["arxiv_id"] in (None, "")
    assert row["title"] != "doi:10.1234/test"


def test_paper_ingest_repairs_prefixed_doi_placeholder_without_duplicate(
    db, monkeypatch
):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('demo')")
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO papers (title, status) VALUES (?, 'meta_only')",
            ("doi:10.1234/test",),
        )
        paper_id = conn.execute(
            "SELECT id FROM papers WHERE title = ?", ("doi:10.1234/test",)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (paper_id, topic_id, "high"),
        )
        conn.commit()
    finally:
        conn.close()

    def _fake_enrich(self, pid):
        self._conn.execute(
            "UPDATE papers SET title = ?, venue = ?, year = ? WHERE id = ?",
            ("Recovered Paper Title", "AAAI", 2024, pid),
        )
        self._conn.commit()
        return {"title": "Recovered Paper Title"}

    monkeypatch.setattr(PaperPool, "enrich_metadata", _fake_enrich)

    result = paper_ingest(db=db, source="doi:10.1234/test", topic_id=topic_id)

    conn = db.connect()
    try:
        rows = conn.execute("SELECT id, title, doi FROM papers ORDER BY id").fetchall()
    finally:
        conn.close()

    assert result.status == "existing"
    assert result.paper_id == paper_id
    assert len(rows) == 1
    assert rows[0]["title"] == "Recovered Paper Title"
    assert rows[0]["doi"] == "10.1234/test"


def test_paper_ingest_accepts_prefixed_arxiv_source(db, monkeypatch):
    monkeypatch.setattr(PaperPool, "enrich_metadata", lambda self, paper_id: {})

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('demo')")
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[
            0
        ]
        conn.commit()
    finally:
        conn.close()

    result = paper_ingest(db=db, source="arxiv:2401.12345", topic_id=topic_id)

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title, doi, arxiv_id FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
    finally:
        conn.close()

    assert result.status == "new"
    assert row["doi"] in (None, "")
    assert row["arxiv_id"] == "2401.12345"
    assert row["title"] != "arxiv:2401.12345"


def test_paper_ingest_accepts_prefixed_pmid_source(db, monkeypatch):
    monkeypatch.setattr(PaperPool, "enrich_metadata", lambda self, paper_id: {})

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('demo')")
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[
            0
        ]
        conn.commit()
    finally:
        conn.close()

    result = paper_ingest(db=db, source="pmid:12345678", topic_id=topic_id)

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title, doi, arxiv_id, pmid FROM papers WHERE id = ?",
            (result.paper_id,),
        ).fetchone()
    finally:
        conn.close()

    assert result.status == "new"
    assert row["pmid"] == "12345678"
    assert row["doi"] in (None, "")
    assert row["arxiv_id"] in (None, "")


def test_paper_ingest_materializes_topic_knowledge_read_model(db, monkeypatch):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('demo')")
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[
            0
        ]
        conn.commit()
    finally:
        conn.close()

    def _fake_enrich(self, paper_id):
        self._conn.execute(
            """
            INSERT INTO normalized_claims
                (topic_id, paper_id, claim_text, method, dataset, metric, task,
                 value, direction, confidence, evidence_spans_json)
            VALUES
                (?, ?, 'Knowledge refresh captures ingest evidence',
                 'knowledge refresh', 'RH', 'snapshot_count',
                 'topic knowledge refresh', '+1', 'higher', 0.83,
                 '[{"section":"results","text":"refresh captures evidence"}]')
            """,
            (topic_id, paper_id),
        )
        self._conn.commit()
        return {}

    monkeypatch.setattr(PaperPool, "enrich_metadata", _fake_enrich)

    result = paper_ingest(
        db=db,
        source="doi:10.1234/topic-knowledge-guard",
        topic_id=topic_id,
    )

    conn = db.connect()
    try:
        artifact_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'topic_knowledge_snapshot'
            """,
            (topic_id,),
        ).fetchone()[0]
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM topic_knowledge_snapshots WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()[0]
        atom_count = conn.execute(
            "SELECT COUNT(*) FROM semantic_atoms WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()[0]
        edge_count = conn.execute(
            "SELECT COUNT(*) FROM semantic_edges WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result.status == "new"
    assert result.knowledge_refresh["status"] == "refreshed"
    assert result.knowledge_refresh["topic_id"] == topic_id
    assert result.knowledge_refresh["paper_id"] == result.paper_id
    assert result.knowledge_refresh["artifact_id"]
    assert result.knowledge_refresh["snapshot_id"]
    assert result.knowledge_refresh["source_hash"]
    assert artifact_count == 1
    assert snapshot_count == 1
    assert atom_count >= 1
    assert edge_count >= 1


def test_paper_ingest_keeps_success_when_topic_knowledge_refresh_fails(db, monkeypatch):
    monkeypatch.setattr(PaperPool, "enrich_metadata", lambda self, paper_id: {})

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('demo')")
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[
            0
        ]
        conn.commit()
    finally:
        conn.close()

    def _boom(*args, **kwargs):
        raise RuntimeError("internal builder exploded")

    monkeypatch.setattr(
        "research_harness.knowledge.topic_refresh.build_topic_knowledge_snapshot",
        _boom,
    )

    result = paper_ingest(
        db=db,
        source="doi:10.1234/topic-knowledge-failure",
        topic_id=topic_id,
    )

    conn = db.connect()
    try:
        paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM topic_knowledge_snapshots WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result.status == "new"
    assert paper_count == 1
    assert snapshot_count == 0
    assert result.knowledge_refresh == {
        "status": "failed",
        "topic_id": topic_id,
        "paper_id": result.paper_id,
        "artifact_id": None,
        "snapshot_id": None,
        "source_hash": "",
        "error": "topic knowledge refresh failed",
    }


def test_paper_ingest_without_topic_skips_topic_knowledge_refresh(db, monkeypatch):
    monkeypatch.setattr(PaperPool, "enrich_metadata", lambda self, paper_id: {})

    result = paper_ingest(
        db=db,
        source="doi:10.1234/topic-knowledge-skipped",
        topic_id=None,
    )

    conn = db.connect()
    try:
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM topic_knowledge_snapshots"
        ).fetchone()[0]
    finally:
        conn.close()

    assert result.status == "new"
    assert snapshot_count == 0
    assert result.knowledge_refresh == {
        "status": "skipped",
        "topic_id": None,
        "paper_id": result.paper_id,
        "artifact_id": None,
        "snapshot_id": None,
        "source_hash": "",
        "error": "",
    }


def test_ingest_dedupes_arxiv_across_version_and_prefix(db):
    """arXiv ids differing only by ``vN`` suffix or ``arxiv:`` prefix must
    collapse to a single paper row.

    Live defect (2026-08-25): the arXiv API reports ``2608.14036v1`` while
    Semantic Scholar reports ``2608.14036``, and older ingest paths stored
    ``arxiv:2608.14036``. ``_find_existing`` matched arxiv_id exactly, so each
    shape became its own paper row — 48 duplicate groups in the live pool.

    Dedupe is by canonical (unversioned, unprefixed) id, but the stored id keeps
    the first-ingested requested version: under managed acquisition a version
    is identity evidence (see ``test_search_and_ingest_retain_requested_arxiv_version``
    in ``test_managed_literature_routing.py``), so ingest must not strip it.
    """
    conn = db.connect()
    try:
        pool = PaperPool(conn)
        first = pool.ingest(
            Paper(title="Demystifying Agent Skills", arxiv_id="2608.14036v1")
        )
        second = pool.ingest(
            Paper(title="Demystifying Agent Skills", arxiv_id="2608.14036")
        )
        third = pool.ingest(
            Paper(title="Demystifying Agent Skills", arxiv_id="arXiv:2608.14036")
        )
        assert first == second == third
        rows = conn.execute("SELECT arxiv_id FROM papers").fetchall()
        assert len(rows) == 1
        assert rows[0]["arxiv_id"] == "2608.14036v1", (
            "stored id must keep the first requested version, not a per-shape copy"
        )
    finally:
        conn.close()


def test_ingest_matches_legacy_versioned_arxiv_row(db):
    """A pool written before canonicalization still dedups correctly."""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, arxiv_id, status) VALUES (?, ?, 'meta_only')",
            ("Legacy Row", "2407.04363v3"),
        )
        conn.commit()
        legacy_id = conn.execute(
            "SELECT id FROM papers WHERE title = 'Legacy Row'"
        ).fetchone()[0]

        pool = PaperPool(conn)
        same = pool.ingest(Paper(title="Legacy Row", arxiv_id="2407.04363"))
        assert same == legacy_id, "canonical id must reach the legacy versioned row"
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
    finally:
        conn.close()
