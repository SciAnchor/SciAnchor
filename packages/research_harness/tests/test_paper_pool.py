import pytest

from research_harness.core.paper_pool import PaperIdentityConflict, PaperPool
from research_harness.storage.models import Paper, PaperAnnotation, TopicPaperNote


def test_ingest_is_idempotent_and_updates_topic_link(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    pool = PaperPool(conn)
    first_id = pool.ingest(
        Paper(
            title="Attention Is All You Need",
            arxiv_id="1706.03762",
            authors=["A"],
            year=2017,
            venue="NeurIPS",
        ),
        topic_id=topic_id,
        relevance="high",
    )
    second_id = pool.ingest(
        Paper(
            title="Attention Is All You Need",
            arxiv_id="1706.03762",
            authors=["A", "B"],
            year=2017,
            venue="NeurIPS",
        ),
        topic_id=topic_id,
        relevance="medium",
    )
    rows = conn.execute("SELECT * FROM paper_topics").fetchall()
    assert first_id == second_id
    assert len(rows) == 1
    assert rows[0]["relevance"] == "medium"


def test_annotations_upsert(conn):
    conn.execute("INSERT INTO papers (title) VALUES ('p1')")
    paper_id = conn.execute("SELECT id FROM papers WHERE title = 'p1'").fetchone()[0]
    pool = PaperPool(conn)
    pool.upsert_annotation(
        PaperAnnotation(
            paper_id=paper_id, section="summary", content="a", source="test"
        )
    )
    pool.upsert_annotation(
        PaperAnnotation(
            paper_id=paper_id, section="summary", content="b", source="test2"
        )
    )
    annotations = pool.get_annotations(paper_id)
    assert len(annotations) == 1
    assert annotations[0].content == "b"


def test_topic_notes_upsert_and_filter(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    conn.execute("INSERT INTO papers (title) VALUES ('p1')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    paper_id = conn.execute("SELECT id FROM papers WHERE title = 'p1'").fetchone()[0]
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
        (paper_id, topic_id, "high"),
    )
    conn.commit()

    pool = PaperPool(conn)
    note_id = pool.upsert_topic_note(
        TopicPaperNote(
            paper_id=paper_id,
            topic_id=topic_id,
            note_type="relevance",
            content="first",
            source="codex",
        )
    )
    pool.upsert_topic_note(
        TopicPaperNote(
            paper_id=paper_id,
            topic_id=topic_id,
            note_type="relevance",
            content="updated",
            source="claude",
        )
    )

    notes = pool.get_topic_notes(paper_id, topic_id=topic_id)
    assert len(notes) == 1
    assert notes[0].id == note_id
    assert notes[0].content == "updated"
    assert notes[0].source == "claude"


def test_topic_note_requires_existing_topic_link(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    conn.execute("INSERT INTO papers (title) VALUES ('p1')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    paper_id = conn.execute("SELECT id FROM papers WHERE title = 'p1'").fetchone()[0]
    pool = PaperPool(conn)

    try:
        pool.upsert_topic_note(
            TopicPaperNote(
                paper_id=paper_id,
                topic_id=topic_id,
                note_type="relevance",
                content="x",
                source="codex",
            )
        )
    except ValueError as exc:
        assert "not linked to topic" in str(exc)
    else:
        raise AssertionError("expected ValueError for unlinked paper/topic pair")


def test_update_path_keeps_absent_identifiers_null(conn):
    """The UPDATE branch must not write '' into the identity columns.

    ``papers.(doi, arxiv_id, s2_id)`` are plain ``UNIQUE`` (migration 064), so
    '' is an ordinary value that only one row may hold. The INSERT branch maps
    '' -> NULL via ``_optional_identifier``; the UPDATE branch must do the same.
    """
    pool = PaperPool(conn)
    paper_id = pool.ingest(Paper(title="Seed", arxiv_id="2510.17932"))
    pool.ingest(Paper(title="Seed v2", arxiv_id="2510.17932", venue="NeurIPS"))

    row = conn.execute(
        "SELECT doi, s2_id, pmid, pmcid FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    assert row["doi"] is None
    assert row["s2_id"] is None
    assert row["pmid"] is None
    assert row["pmcid"] is None


def test_second_identifier_less_update_does_not_violate_doi_unique(conn):
    """BUG-01: re-ingesting two DOI-less papers must not abort on papers.doi.

    Reproduces ``sqlite3.IntegrityError: UNIQUE constraint failed: papers.doi``
    raised from the UPDATE branch of ``_ingest_in_txn``: the first update stores
    ``doi = ''`` and the second one collides with it.
    """
    pool = PaperPool(conn)
    first = pool.ingest(Paper(title="A", arxiv_id="2510.17932", s2_id="s2-a"))
    second = pool.ingest(Paper(title="B", arxiv_id="2510.99999", s2_id="s2-b"))

    assert (
        pool.ingest(Paper(title="A v2", arxiv_id="2510.17932", s2_id="s2-a")) == first
    )
    assert (
        pool.ingest(Paper(title="B v2", arxiv_id="2510.99999", s2_id="s2-b")) == second
    )

    dois = [row["doi"] for row in conn.execute("SELECT doi FROM papers ORDER BY id")]
    assert dois == [None, None]


def test_ingest_matches_existing_doi_across_arxiv_doi_case(conn):
    """A seed pack's lower-case arXiv DOI must match RH's camel-case row."""
    pool = PaperPool(conn)
    first = pool.ingest(Paper(title="Paper", doi="10.48550/arXiv.2510.17932"))
    second = pool.ingest(
        Paper(
            title="Paper from seed pack",
            doi="10.48550/arxiv.2510.17932",
            arxiv_id="2510.17932",
        )
    )

    assert second == first
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1


def test_identity_collision_raises_typed_conflict_and_rolls_back(conn):
    """An unavoidable identity collision must surface as a typed, catchable error.

    Two rows describe the same paper under different identifiers; ingesting a
    record that carries both would have to give one row an identifier another
    row already owns. RH must report that as a skippable conflict instead of an
    opaque ``sqlite3.IntegrityError`` that aborts a whole batch import.
    """
    pool = PaperPool(conn)
    pool.ingest(Paper(title="By DOI", doi="10.5555/dup"))
    pool.ingest(Paper(title="By arXiv", arxiv_id="2510.00001"))

    with pytest.raises(PaperIdentityConflict) as excinfo:
        pool.ingest(Paper(title="Merged", doi="10.5555/dup", arxiv_id="2510.00001"))

    assert excinfo.value.field == "arxiv_id"
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2
    # the aborted ingest must leave the connection usable
    assert not conn.in_transaction
    assert pool.ingest(Paper(title="Next", arxiv_id="2510.00002")) > 0
