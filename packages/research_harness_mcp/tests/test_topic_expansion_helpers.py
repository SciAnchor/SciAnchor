from contextlib import contextmanager
import sqlite3


def _build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            doi TEXT,
            arxiv_id TEXT,
            url TEXT,
            year INTEGER,
            deep_read INTEGER
        );
        CREATE TABLE paper_topics (
            paper_id INTEGER,
            topic_id INTEGER,
            relevance TEXT
        );
        CREATE TABLE expansion_jobs (
            id INTEGER PRIMARY KEY,
            topic_id INTEGER,
            status TEXT,
            retrieval_target INTEGER,
            deep_read_target INTEGER,
            rounds_target INTEGER,
            current_round INTEGER,
            papers_fetched INTEGER,
            papers_deep_read INTEGER,
            last_error TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    rows = [
        (
            1,
            "First Matching Paper",
            "10.1000/demo",
            "2401.00001",
            "https://one",
            2025,
            1,
        ),
        (
            2,
            "A Long Descriptive Method Title For Query Building",
            "",
            "abc123",
            "https://two",
            2024,
            0,
        ),
        (3, "Lower Priority Evidence Study", "", "abc123", "https://three", 2023, None),
        (4, "URL Matched Paper", "", "", "https://matched.example/paper", 2022, 1),
    ]
    conn.executemany(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, url, year, deep_read)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.executemany(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
        [(1, 7, "high"), (2, 7, "high"), (3, 7, "low"), (4, 7, "medium")],
    )
    return conn


def _conn_context(conn: sqlite3.Connection):
    @contextmanager
    def _ctx():
        yield conn

    return _ctx


class _FakeExpansionApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def paper_search(self, **kwargs):
        self.calls.append(("paper_search", kwargs))
        return {"kind": "search", "kwargs": kwargs}

    def paper_ingest(self, **kwargs):
        self.calls.append(("paper_ingest", kwargs))
        return {"kind": "ingest", "kwargs": kwargs}


def test_topic_expansion_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, topic_expansion_helpers

    assert (
        http_api._pick_candidate_source is topic_expansion_helpers.pick_candidate_source
    )
    assert (
        http_api._find_paper_id_in_topic_by_source
        is topic_expansion_helpers.find_paper_id_in_topic_by_source
    )
    assert (
        http_api._paper_already_in_topic
        is topic_expansion_helpers.paper_already_in_topic
    )
    assert (
        http_api._build_expansion_query is topic_expansion_helpers.build_expansion_query
    )
    assert (
        http_api._get_latest_expansion_job
        is topic_expansion_helpers.latest_expansion_job
    )
    assert http_api._topic_paper_stats is topic_expansion_helpers.topic_paper_stats
    assert (
        http_api._deep_read_provider_pool
        is topic_expansion_helpers.deep_read_provider_pool
    )
    assert (
        http_api._expansion_deep_read_concurrency
        is topic_expansion_helpers.expansion_deep_read_concurrency
    )
    assert (
        http_api._expansion_deep_read_paper_timeout
        is topic_expansion_helpers.expansion_deep_read_paper_timeout
    )


def test_pick_candidate_source_preserves_source_precedence_and_blank_handling():
    from research_harness_mcp import topic_expansion_helpers

    assert (
        topic_expansion_helpers.pick_candidate_source(
            {
                "arxiv_id": " 2401.12345 ",
                "doi": "10.1000/demo",
                "url": "https://example.com",
                "title": "Title",
            }
        )
        == "2401.12345"
    )
    assert (
        topic_expansion_helpers.pick_candidate_source(
            {"doi": " 10.1000/demo ", "url": "https://example.com"}
        )
        == "10.1000/demo"
    )
    assert topic_expansion_helpers.pick_candidate_source(
        {"title": "  Only Title  "}
    ) == ("Only Title")
    assert topic_expansion_helpers.pick_candidate_source({}) == ""


def test_search_papers_impl_builds_args_and_serializes_result():
    from research_harness_mcp import topic_expansion_helpers

    api = _FakeExpansionApi()
    serialized_inputs = []

    def serialize_result(result):
        serialized_inputs.append(result)
        return {"serialized": result["kind"], "kwargs": result["kwargs"]}

    assert topic_expansion_helpers.search_papers_impl(
        api,
        query="graph agents",
        topic_id=7,
        max_results=12,
        serialize_result=serialize_result,
    ) == {
        "serialized": "search",
        "kwargs": {"query": "graph agents", "topic_id": 7, "max_results": 12},
    }
    assert api.calls == [
        (
            "paper_search",
            {"query": "graph agents", "topic_id": 7, "max_results": 12},
        )
    ]
    assert serialized_inputs == [
        {
            "kind": "search",
            "kwargs": {"query": "graph agents", "topic_id": 7, "max_results": 12},
        }
    ]


def test_ingest_paper_impl_builds_optional_args_and_serializes_result():
    from research_harness_mcp import topic_expansion_helpers

    api = _FakeExpansionApi()

    def serialize_result(result):
        return {"serialized": result["kind"], "kwargs": result["kwargs"]}

    assert topic_expansion_helpers.ingest_paper_impl(
        api,
        source="10.1000/demo",
        relevance="high",
        serialize_result=serialize_result,
    ) == {
        "serialized": "ingest",
        "kwargs": {"source": "10.1000/demo", "relevance": "high"},
    }
    assert topic_expansion_helpers.ingest_paper_impl(
        api,
        source="2401.00001",
        topic_id=7,
        serialize_result=serialize_result,
    ) == {
        "serialized": "ingest",
        "kwargs": {"source": "2401.00001", "relevance": "medium", "topic_id": 7},
    }


def test_http_api_search_and_ingest_wrappers_use_dynamic_serializer(monkeypatch):
    from research_harness_mcp import http_api

    api = _FakeExpansionApi()
    monkeypatch.setattr(
        http_api,
        "_serialize_result",
        lambda result: {"wrapped": result["kind"], "kwargs": result["kwargs"]},
    )

    assert http_api._search_papers_impl(
        api, query="survey", topic_id=9, max_results=3
    ) == {
        "wrapped": "search",
        "kwargs": {"query": "survey", "topic_id": 9, "max_results": 3},
    }
    assert http_api._ingest_paper_impl(api, source="https://example/paper") == {
        "wrapped": "ingest",
        "kwargs": {"source": "https://example/paper", "relevance": "medium"},
    }


def test_deep_read_paper_impl_runs_tool_updates_db_and_serializes_result():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    calls = []

    def execute_tool_fn(name, arguments):
        calls.append((name, arguments))
        return {"kind": "deep_read", "arguments": arguments}

    def serialize_result(result):
        return {
            "serialized": result["kind"],
            "arguments": result["arguments"],
        }

    try:
        assert topic_expansion_helpers.deep_read_paper_impl(
            paper_id=2,
            topic_id=7,
            focus="methods",
            execute_tool_fn=execute_tool_fn,
            get_db_context=_conn_context(conn),
            serialize_result=serialize_result,
        ) == {
            "serialized": "deep_read",
            "arguments": {"paper_id": 2, "topic_id": 7, "focus": "methods"},
        }
        assert calls == [
            ("deep_read", {"paper_id": 2, "topic_id": 7, "focus": "methods"})
        ]
        row = conn.execute("SELECT deep_read FROM papers WHERE id = 2").fetchone()
        assert row is not None
        assert row["deep_read"] == 1
    finally:
        conn.close()


def test_http_api_deep_read_wrapper_uses_dynamic_dependencies(monkeypatch):
    from research_harness_mcp import http_api

    conn = _build_conn()
    calls = []

    def execute_tool_fn(name, arguments):
        calls.append((name, arguments))
        return {"kind": "deep_read", "arguments": arguments}

    @contextmanager
    def fake_get_db():
        yield conn

    try:
        monkeypatch.setattr(http_api, "execute_tool", execute_tool_fn)
        monkeypatch.setattr(http_api, "get_db", fake_get_db)
        monkeypatch.setattr(
            http_api,
            "_serialize_result",
            lambda result: {
                "wrapped": result["kind"],
                "arguments": result["arguments"],
            },
        )

        assert http_api._deep_read_paper_impl(object(), paper_id=3, topic_id=7) == {
            "wrapped": "deep_read",
            "arguments": {"paper_id": 3, "topic_id": 7},
        }
        assert calls == [("deep_read", {"paper_id": 3, "topic_id": 7})]
        row = conn.execute("SELECT deep_read FROM papers WHERE id = 3").fetchone()
        assert row is not None
        assert row["deep_read"] == 1
    finally:
        conn.close()


def test_find_and_existing_topic_paper_helpers_match_source_classification():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    try:
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(
                conn, 7, "10.1000/demo"
            )
            == 1
        )
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(conn, 7, "abc123")
            == 2
        )
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(
                conn, 7, "https://matched.example/paper"
            )
            == 4
        )
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(
                conn, 7, "A Long Descriptive Method Title For Query Building"
            )
            == 2
        )
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(
                conn, 7, "URL Matched Paper"
            )
            is None
        )
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(conn, 7, "")
            is None
        )
        assert (
            topic_expansion_helpers.find_paper_id_in_topic_by_source(
                conn, 999, "10.1000/demo"
            )
            is None
        )

        assert topic_expansion_helpers.paper_already_in_topic(conn, 7, "10.1000/demo")
        assert topic_expansion_helpers.paper_already_in_topic(conn, 7, "abc123")
        assert topic_expansion_helpers.paper_already_in_topic(
            conn, 7, "https://matched.example/paper"
        )
        assert not topic_expansion_helpers.paper_already_in_topic(
            conn, 999, "10.1000/demo"
        )
    finally:
        conn.close()


def test_build_expansion_query_uses_topic_text_and_ranked_title_phrases():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    try:
        query = topic_expansion_helpers.build_expansion_query(
            conn,
            7,
            "Retrieval Agents",
            "Survey methods",
        )
    finally:
        conn.close()

    assert query.splitlines()[0] == "Retrieval Agents Survey methods"
    assert "First Matching Paper" in query
    assert "Long Descriptive Method Title" in query
    assert "Matched Paper" in query


def test_topic_paper_stats_counts_total_and_deep_read_papers():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    try:
        assert topic_expansion_helpers.topic_paper_stats(conn, 7) == {
            "total": 4,
            "deep_read": 2,
        }
        assert topic_expansion_helpers.topic_paper_stats(conn, 999) == {
            "total": 0,
            "deep_read": 0,
        }
    finally:
        conn.close()


def test_latest_expansion_job_prefers_newest_created_at_then_highest_id():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    try:
        conn.executemany(
            """
            INSERT INTO expansion_jobs (
                id, topic_id, status, retrieval_target, deep_read_target,
                rounds_target, current_round, papers_fetched, papers_deep_read,
                last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 7, "queued", 10, 2, 1, 0, 0, 0, None, "2026-01-01T00:00:00Z", "a"),
                (2, 7, "running", 20, 3, 2, 1, 5, 1, None, "2026-01-02T00:00:00Z", "b"),
                (3, 7, "done", 30, 4, 3, 3, 30, 4, None, "2026-01-02T00:00:00Z", "c"),
                (
                    4,
                    8,
                    "other-topic",
                    40,
                    5,
                    4,
                    4,
                    40,
                    5,
                    None,
                    "2026-01-03T00:00:00Z",
                    "d",
                ),
            ],
        )

        row = topic_expansion_helpers.latest_expansion_job(conn, 7)
        assert row is not None
        assert dict(row) == {
            "id": 3,
            "status": "done",
            "retrieval_target": 30,
            "deep_read_target": 4,
            "rounds_target": 3,
            "current_round": 3,
            "papers_fetched": 30,
            "papers_deep_read": 4,
            "last_error": None,
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": "c",
        }
        assert topic_expansion_helpers.latest_expansion_job(conn, 999) is None
    finally:
        conn.close()


def test_expansion_job_is_cancelled_reads_status_by_job_id():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    try:
        conn.executemany(
            "INSERT INTO expansion_jobs (id, topic_id, status) VALUES (?, ?, ?)",
            [
                (10, 7, "cancelled"),
                (11, 7, "running"),
                (12, 7, "completed"),
            ],
        )

        get_db_context = _conn_context(conn)
        assert topic_expansion_helpers.expansion_job_is_cancelled(
            10, get_db_context=get_db_context
        )
        assert not topic_expansion_helpers.expansion_job_is_cancelled(
            11, get_db_context=get_db_context
        )
        assert not topic_expansion_helpers.expansion_job_is_cancelled(
            12, get_db_context=get_db_context
        )
        assert not topic_expansion_helpers.expansion_job_is_cancelled(
            999, get_db_context=get_db_context
        )
    finally:
        conn.close()


def test_http_api_expansion_job_cancelled_wrapper_uses_dynamic_get_db(monkeypatch):
    from research_harness_mcp import http_api

    conn = _build_conn()
    calls: list[int] = []

    @contextmanager
    def fake_get_db():
        calls.append(1)
        yield conn

    try:
        conn.execute(
            "INSERT INTO expansion_jobs (id, topic_id, status) VALUES (?, ?, ?)",
            (20, 7, "cancelled"),
        )
        monkeypatch.setattr(http_api, "get_db", fake_get_db)

        assert http_api._expansion_job_is_cancelled(20)
        assert calls == [1]
    finally:
        conn.close()


def test_update_expansion_job_sets_requested_fields_and_preserves_omitted_fields():
    from research_harness_mcp import topic_expansion_helpers

    conn = _build_conn()
    try:
        conn.execute(
            """
            INSERT INTO expansion_jobs (
                id, topic_id, status, current_round, papers_fetched,
                papers_deep_read, last_error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (30, 7, "queued", 0, 0, 0, "old", "old-time"),
        )

        topic_expansion_helpers.update_expansion_job(
            conn,
            30,
            now_iso=lambda: "new-time",
            status="running",
            current_round=2,
            papers_fetched=5,
            papers_deep_read=1,
            last_error="x" * 2105,
        )

        row = conn.execute("SELECT * FROM expansion_jobs WHERE id = 30").fetchone()
        assert row is not None
        assert row["status"] == "running"
        assert row["current_round"] == 2
        assert row["papers_fetched"] == 5
        assert row["papers_deep_read"] == 1
        assert row["last_error"] == "x" * 2000
        assert row["updated_at"] == "new-time"

        topic_expansion_helpers.update_expansion_job(
            conn,
            30,
            now_iso=lambda: "later-time",
        )
        row = conn.execute("SELECT * FROM expansion_jobs WHERE id = 30").fetchone()
        assert row is not None
        assert row["status"] == "running"
        assert row["current_round"] == 2
        assert row["papers_fetched"] == 5
        assert row["papers_deep_read"] == 1
        assert row["last_error"] == "x" * 2000
        assert row["updated_at"] == "later-time"
    finally:
        conn.close()


def test_http_api_update_expansion_job_wrapper_uses_dynamic_now_iso(monkeypatch):
    from research_harness_mcp import http_api

    conn = _build_conn()
    try:
        conn.execute(
            "INSERT INTO expansion_jobs (id, topic_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (31, 7, "queued", "old-time"),
        )
        monkeypatch.setattr(http_api, "_now_iso", lambda: "wrapped-time")

        http_api._update_expansion_job(conn, 31, status="running")

        row = conn.execute("SELECT * FROM expansion_jobs WHERE id = 31").fetchone()
        assert row is not None
        assert row["status"] == "running"
        assert row["updated_at"] == "wrapped-time"
    finally:
        conn.close()


def test_deep_read_provider_pool_uses_override_and_loader(monkeypatch):
    from research_harness_mcp import topic_expansion_helpers

    called = False

    def available_providers() -> list[str]:
        nonlocal called
        called = True
        return ["unused"]

    monkeypatch.setenv(
        "RESEARCH_HARNESS_DEEP_READ_PROVIDERS",
        " anthropic,cursor_agent, ,openai ",
    )
    assert topic_expansion_helpers.deep_read_provider_pool(
        available_providers=available_providers
    ) == ["anthropic", "cursor_agent", "openai"]
    assert called is False

    monkeypatch.delenv("RESEARCH_HARNESS_DEEP_READ_PROVIDERS", raising=False)
    assert topic_expansion_helpers.deep_read_provider_pool(
        available_providers=lambda: ["anthropic", "openai"]
    ) == ["anthropic", "openai"]
    assert topic_expansion_helpers.deep_read_provider_pool(
        available_providers=lambda: []
    ) == [""]


def test_expansion_deep_read_concurrency_env_and_defaults(monkeypatch):
    from research_harness_mcp import topic_expansion_helpers

    monkeypatch.delenv("RESEARCH_HARNESS_DEEP_READ_CONCURRENCY", raising=False)
    assert topic_expansion_helpers.expansion_deep_read_concurrency(0) == 2
    assert topic_expansion_helpers.expansion_deep_read_concurrency(4) == 8
    assert topic_expansion_helpers.expansion_deep_read_concurrency(99) == 8

    monkeypatch.setenv("RESEARCH_HARNESS_DEEP_READ_CONCURRENCY", "12")
    assert topic_expansion_helpers.expansion_deep_read_concurrency(1) == 12

    monkeypatch.setenv("RESEARCH_HARNESS_DEEP_READ_CONCURRENCY", "99")
    assert topic_expansion_helpers.expansion_deep_read_concurrency(1) == 16

    monkeypatch.setenv("RESEARCH_HARNESS_DEEP_READ_CONCURRENCY", "bad")
    assert topic_expansion_helpers.expansion_deep_read_concurrency(3) == 6


def test_expansion_deep_read_paper_timeout_env_and_default(monkeypatch):
    from research_harness_mcp import topic_expansion_helpers

    monkeypatch.delenv("RESEARCH_HARNESS_DEEP_READ_TIMEOUT", raising=False)
    assert topic_expansion_helpers.expansion_deep_read_paper_timeout() == 300.0

    monkeypatch.setenv("RESEARCH_HARNESS_DEEP_READ_TIMEOUT", "45")
    assert topic_expansion_helpers.expansion_deep_read_paper_timeout() == 45.0

    monkeypatch.setenv("RESEARCH_HARNESS_DEEP_READ_TIMEOUT", "20")
    assert topic_expansion_helpers.expansion_deep_read_paper_timeout() == 300.0

    monkeypatch.setenv("RESEARCH_HARNESS_DEEP_READ_TIMEOUT", "bad")
    assert topic_expansion_helpers.expansion_deep_read_paper_timeout() == 300.0
