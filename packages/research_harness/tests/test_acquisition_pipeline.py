import asyncio

from research_harness.acquisition import pipeline
from research_harness.acquisition.downloader import DownloadResult


class DummyCandidate:
    paper_id = 1


async def _fake_download_batch(candidates, download_path):
    return ["ok", len(candidates), str(download_path)]


def test_run_download_batch_inside_running_event_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "download_batch", _fake_download_batch)

    async def call_inside_loop():
        return pipeline._run_download_batch([DummyCandidate()], tmp_path)

    assert asyncio.run(call_inside_loop()) == ["ok", 1, str(tmp_path)]


def test_build_candidates_preserves_pubmed_identifiers(db):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('medical')")
        conn.execute(
            """
            INSERT INTO papers (title, year, venue, doi, pmid, pmcid, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Climate change and pregnancy outcomes.",
                2025,
                "Environmental Health Perspectives",
                "10.1289/example",
                "12345678",
                "PMC1234567",
                "https://pubmed.ncbi.nlm.nih.gov/12345678/",
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_topics (
                paper_id, topic_id, relevance, screening_status, manuscript_eligible
            ) VALUES (1, 1, 'high', 'screened_in', 1)
            """
        )
        conn.commit()
    finally:
        conn.close()

    candidates = pipeline._build_candidates(db, topic_id=1)

    assert len(candidates) == 1
    assert candidates[0].pmid == "12345678"
    assert candidates[0].pmcid == "PMC1234567"


def test_build_candidates_excludes_unscreened_candidates_by_default(db):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('candidate-topic')")
        conn.execute(
            """
            INSERT INTO papers (title, year, venue, doi, status)
            VALUES ('Raw provider candidate', 2025, 'arXiv', '10.test/raw', 'meta_only')
            """
        )
        conn.execute(
            """
            INSERT INTO paper_topics (
                paper_id, topic_id, relevance, screening_status, manuscript_eligible
            ) VALUES (1, 1, 'low', 'candidate', 0)
            """
        )
        conn.commit()
    finally:
        conn.close()

    assert pipeline._build_candidates(db, topic_id=1) == []


def test_build_candidates_can_explicitly_include_candidates(db):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('candidate-topic')")
        conn.execute(
            """
            INSERT INTO papers (title, year, venue, doi, status)
            VALUES ('Raw provider candidate', 2025, 'arXiv', '10.test/raw', 'meta_only')
            """
        )
        conn.execute(
            """
            INSERT INTO paper_topics (
                paper_id, topic_id, relevance, screening_status, manuscript_eligible
            ) VALUES (1, 1, 'low', 'candidate', 0)
            """
        )
        conn.commit()
    finally:
        conn.close()

    candidates = pipeline._build_candidates(db, topic_id=1, include_candidates=True)

    assert len(candidates) == 1
    assert candidates[0].title == "Raw provider candidate"


def test_process_results_manual_list_includes_pubmed_identifiers(db, tmp_path):
    candidate = pipeline.PaperDownloadCandidate(
        paper_id=1,
        title="Climate change and pregnancy outcomes.",
        year=2025,
        venue="Environmental Health Perspectives",
        doi="10.1289/example",
        pmid="12345678",
        pmcid="PMC1234567",
    )
    result = DownloadResult(
        paper_id=1,
        status="needs_manual",
        failure_reason="browser challenge required",
    )

    report = pipeline._process_results(
        db,
        [result],
        [candidate],
        artifacts_root=tmp_path,
    )

    assert report.manual_list == [
        {
            "paper_id": 1,
            "title": "Climate change and pregnancy outcomes.",
            "year": 2025,
            "venue": "Environmental Health Perspectives",
            "doi": "10.1289/example",
            "arxiv_id": "",
            "pmid": "12345678",
            "pmcid": "PMC1234567",
            "failure_reason": "browser challenge required",
            "failure_taxonomy": None,
        }
    ]


def test_process_results_annotates_successes_in_parallel(db, tmp_path, monkeypatch):
    """Backlog E4: annotation runs across worker threads, results unchanged."""
    import threading

    seen_threads: set[str] = set()
    barrier = threading.Barrier(2, timeout=5)

    def _fake_annotate(db_arg, paper_id, pdf_path, artifacts_root):
        seen_threads.add(threading.current_thread().name)
        # Both workers must be in-flight at once to pass the barrier.
        barrier.wait()
        return paper_id != 3

    monkeypatch.setattr(pipeline, "_annotate_paper", _fake_annotate)
    monkeypatch.setenv("RESEARCH_HARNESS_ANNOTATE_WORKERS", "2")

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    candidates = [
        pipeline.PaperDownloadCandidate(paper_id=i, title=f"P{i}") for i in (2, 3)
    ]
    results = [
        DownloadResult(paper_id=2, status="success", path=pdf, provider="arxiv"),
        DownloadResult(paper_id=3, status="success", path=pdf, provider="arxiv"),
    ]

    report = pipeline._process_results(db, results, candidates, artifacts_root=tmp_path)

    assert report.downloaded == 2
    assert report.annotated == 1
    annotated_by_id = {e["paper_id"]: e["annotated"] for e in report.results}
    assert annotated_by_id == {2: True, 3: False}
    assert len(seen_threads) == 2


def test_build_candidates_carries_stored_pdf_candidates(db):
    from research_harness.acquisition.candidate_store import save_pdf_candidates

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('stored-candidates')")
        conn.execute(
            """
            INSERT INTO papers (title, doi, url)
            VALUES ('Stored candidate paper', '10.1/stored',
                    'https://www.semanticscholar.org/paper/landing')
            """
        )
        conn.execute(
            """
            INSERT INTO paper_topics (
                paper_id, topic_id, relevance, screening_status, manuscript_eligible
            ) VALUES (1, 1, 'high', 'screened_in', 1)
            """
        )
        save_pdf_candidates(
            conn,
            1,
            [
                {
                    "url": "https://oa.example.org/paper.pdf",
                    "source_type": "open_access_pdf",
                },
                {
                    "url": "https://browser-only.example.org/paper",
                    "source_type": "browser_session",
                    "requires_browser": True,
                },
            ],
        )
    finally:
        conn.close()

    candidates = pipeline._build_candidates(db, topic_id=1)

    assert len(candidates) == 1
    assert candidates[0].extra_urls == ("https://oa.example.org/paper.pdf",)


def test_process_results_tallies_failure_taxonomies(db, tmp_path):
    from research_harness.acquisition.routes import PDFRouteAudit

    candidates = [
        pipeline.PaperDownloadCandidate(paper_id=i, title=f"P{i}") for i in (1, 2, 3)
    ]
    results = [
        DownloadResult(
            paper_id=1,
            status="failed",
            failure_reason="no identifiers",
            audit=PDFRouteAudit(paper_id=1, failure_taxonomy="no_candidate_identifier"),
        ),
        DownloadResult(
            paper_id=2,
            status="needs_manual",
            failure_reason="landing pages only",
            audit=PDFRouteAudit(paper_id=2, failure_taxonomy="no_direct_pdf_metadata"),
        ),
        DownloadResult(
            paper_id=3,
            status="needs_manual",
            failure_reason="browser challenge required",
            audit=PDFRouteAudit(paper_id=3, failure_taxonomy="browser_challenge"),
        ),
    ]

    report = pipeline._process_results(db, results, candidates, artifacts_root=tmp_path)

    assert report.failure_taxonomies == {
        "no_candidate_identifier": 1,
        "no_direct_pdf_metadata": 1,
        "browser_challenge": 1,
    }
    assert {
        entry["paper_id"]: entry.get("failure_taxonomy") for entry in report.results
    } == {
        1: "no_candidate_identifier",
        2: "no_direct_pdf_metadata",
        3: "browser_challenge",
    }
    manual_taxonomies = {
        item["paper_id"]: item["failure_taxonomy"] for item in report.manual_list
    }
    assert manual_taxonomies == {
        2: "no_direct_pdf_metadata",
        3: "browser_challenge",
    }


def test_an_unscreened_pool_is_named_and_not_silently_complete(db):
    """A topic with a full pool and no screening is a blocker, not a finished acquisition."""
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('auto-ingested')")
        for i in range(3):
            conn.execute(
                "INSERT INTO papers (title, year, venue, doi, status) "
                "VALUES (?, 2025, 'arXiv', ?, 'meta_only')",
                (f"Raw provider candidate {i}", f"10.test/raw{i}"),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance, "
                "screening_status, manuscript_eligible) VALUES (?, 1, 'low', 'candidate', 0)",
                (i + 1,),
            )
        conn.commit()
    finally:
        conn.close()

    assert pipeline.unscreened_pool(db, topic_id=1) == 3
    report = pipeline.acquire_papers(db, topic_id=1)
    assert report.total_papers == 0
    assert report.unscreened_candidates == 3


def test_a_genuinely_empty_topic_is_not_reported_as_blocked(db):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('empty')")
        conn.commit()
    finally:
        conn.close()

    report = pipeline.acquire_papers(db, topic_id=1)
    assert report.total_papers == 0
    assert report.unscreened_candidates == 0


def test_auto_ingest_screens_on_the_score_search_already_computed(db):
    """A search hit RH ranked as relevant is acquirable; one it ranked as noise is not."""
    from research_harness.primitives.impls import _auto_ingest_refs
    from research_harness.primitives.types import PaperRef

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('auto')")
        conn.commit()
    finally:
        conn.close()

    _auto_ingest_refs(
        db,
        [
            PaperRef(title="Squarely on topic", doi="10.test/hi", relevance_score=0.9),
            PaperRef(title="Partly on topic", doi="10.test/mid", relevance_score=0.5),
            PaperRef(
                title="Noise from the provider", doi="10.test/lo", relevance_score=0.1
            ),
        ],
        topic_id=1,
    )

    conn = db.connect()
    try:
        rows = dict(
            conn.execute(
                "SELECT p.doi, pt.screening_status FROM papers p "
                "JOIN paper_topics pt ON pt.paper_id = p.id"
            ).fetchall()
        )
    finally:
        conn.close()
    assert rows["10.test/hi"] == "screened_in"
    assert rows["10.test/mid"] == "screened_in"
    assert rows["10.test/lo"] == "candidate"

    acquirable = {c.doi for c in pipeline._build_candidates(db, topic_id=1)}
    assert acquirable == {"10.test/hi", "10.test/mid"}
