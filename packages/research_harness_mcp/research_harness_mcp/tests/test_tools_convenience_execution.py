"""Focused tests for MCP convenience execution extraction."""

from __future__ import annotations

from typing import Any


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


def test_execute_convenience_uses_injected_db_resolver_for_topic_list() -> None:
    from research_harness_mcp.tools_convenience import _execute_convenience

    calls: list[tuple[str, tuple[Any, ...]]] = []

    class FakeConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Rows:
            calls.append((sql, tuple(params)))
            return _Rows(
                [
                    {
                        "id": 7,
                        "name": "release-readiness",
                        "description": "docs and guards",
                        "status": "active",
                    }
                ]
            )

        def close(self) -> None:
            calls.append(("close", ()))

    class FakeDB:
        def connect(self) -> FakeConn:
            return FakeConn()

    result = _execute_convenience(
        "topic_list",
        {},
        db_resolver=FakeDB,
        zotero_sync_executor=lambda db, arguments: {"unexpected": True},
    )

    assert result == {
        "topics": [
            {
                "id": 7,
                "name": "release-readiness",
                "description": "docs and guards",
                "status": "active",
            }
        ]
    }
    assert calls[-1] == ("close", ())


def test_execute_convenience_available_from_execution_module() -> None:
    from research_harness_mcp.tools_convenience_execution import _execute_convenience

    class FakeConn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Rows:
            del sql, params
            return _Rows([])

        def close(self) -> None:
            pass

    class FakeDB:
        def connect(self) -> FakeConn:
            return FakeConn()

    result = _execute_convenience(
        "topic_list",
        {},
        db_resolver=FakeDB,
        zotero_sync_executor=lambda db, arguments: {"unexpected": True},
    )

    assert result == {"topics": []}


def test_execute_convenience_delegates_zotero_to_injected_executor() -> None:
    from research_harness_mcp.tools_convenience import _execute_convenience

    calls: list[str] = []

    class FakeConn:
        def close(self) -> None:
            calls.append("close")

    class FakeDB:
        def connect(self) -> FakeConn:
            calls.append("connect")
            return FakeConn()

    def fake_zotero_sync(db: FakeDB, arguments: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(db, FakeDB)
        assert arguments == {"topic": "demo", "dry_run": True}
        calls.append("zotero")
        return {"topic": "demo", "dry_run": True}

    result = _execute_convenience(
        "zotero_sync",
        {"topic": "demo", "dry_run": True},
        db_resolver=FakeDB,
        zotero_sync_executor=fake_zotero_sync,
    )

    assert result == {"topic": "demo", "dry_run": True}
    assert calls == ["connect", "zotero", "close"]


def test_venue_refresh_propagates_spc_failure(monkeypatch):
    import pytest
    from research_harness.acquisition.spc_bridge import SPCAcquisitionError
    from research_harness.paper_sources import SearchAggregator
    from research_harness_mcp.tools_convenience_execution import _execute_convenience

    failure = SPCAcquisitionError(
        "search", {"error": {"code": "rate_limited", "retryable": True}}
    )

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(SearchAggregator, "search", fail)
    monkeypatch.setattr("time.sleep", lambda _: None)

    class FakeConn:
        def execute(self, *args):
            return _Rows(
                [
                    {
                        "id": 1,
                        "arxiv_id": "2606.00001",
                        "doi": "",
                        "s2_id": "",
                        "venue": "arxiv",
                    }
                ]
            )

        def commit(self):
            pass

        def close(self):
            pass

    class FakeDB:
        def connect(self):
            return FakeConn()

    with pytest.raises(SPCAcquisitionError, match="rate_limited"):
        _execute_convenience(
            "venue_refresh",
            {"topic_id": 1},
            db_resolver=FakeDB,
            zotero_sync_executor=lambda *_: {},
        )
