"""Concurrent multi-writer behavior of PaperPool against one SQLite DB."""

import threading
from concurrent.futures import ThreadPoolExecutor

from research_harness.core.paper_pool import PaperPool
from research_harness.storage.models import Paper

WORKERS = 8


def _ingest(db, barrier, paper, topic_id=None):
    conn = db.connect()
    try:
        barrier.wait(timeout=30)
        return PaperPool(conn).ingest(paper, topic_id=topic_id)
    finally:
        conn.close()


def test_concurrent_ingest_of_same_paper_creates_single_row(db):
    barrier = threading.Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [
            executor.submit(
                _ingest,
                db,
                barrier,
                Paper(
                    title="Concurrent Ingest",
                    arxiv_id="2401.00001",
                    authors=["A"],
                    year=2024,
                ),
            )
            for _ in range(WORKERS)
        ]
        ids = [future.result(timeout=60) for future in futures]

    assert len(set(ids)) == 1
    conn = db.connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE arxiv_id = '2401.00001'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_concurrent_ingest_of_distinct_papers_all_succeed(db):
    barrier = threading.Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [
            executor.submit(
                _ingest,
                db,
                barrier,
                Paper(
                    title=f"Distinct Paper {i}",
                    arxiv_id=f"2402.{i:05d}",
                    authors=["A"],
                    year=2024,
                ),
            )
            for i in range(WORKERS)
        ]
        ids = [future.result(timeout=60) for future in futures]

    assert len(set(ids)) == WORKERS


def test_concurrent_ingest_with_topic_links(db):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('concurrency-demo')")
        conn.commit()
        topic_id = conn.execute(
            "SELECT id FROM topics WHERE name = 'concurrency-demo'"
        ).fetchone()[0]
    finally:
        conn.close()

    barrier = threading.Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [
            executor.submit(
                _ingest,
                db,
                barrier,
                Paper(
                    title="Shared Topic Paper",
                    doi=f"10.1000/demo.{i}",
                    authors=["A"],
                    year=2024,
                ),
                topic_id,
            )
            for i in range(WORKERS)
        ]
        for future in futures:
            future.result(timeout=60)

    conn = db.connect()
    try:
        links = conn.execute(
            "SELECT COUNT(*) FROM paper_topics WHERE topic_id = ?", (topic_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert links == WORKERS
