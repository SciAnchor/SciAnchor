"""Focused tests for MCP primitive tool helpers."""

from __future__ import annotations

from types import SimpleNamespace


def test_primitive_tool_definitions_uses_supplied_primitive_lister() -> None:
    from research_harness_mcp.tools_primitives import _primitive_tool_definitions

    specs = [
        SimpleNamespace(
            name="demo_primitive",
            description="Demo primitive",
            input_schema={
                "type": "object",
                "properties": {"topic_id": {"type": "integer"}},
            },
        )
    ]

    tools = _primitive_tool_definitions(primitive_lister=lambda: specs)

    assert len(tools) == 1
    assert tools[0].name == "demo_primitive"
    assert tools[0].description == "Demo primitive"
    assert tools[0].inputSchema == specs[0].input_schema


def test_execute_primitive_preserves_paper_search_callbacks_and_freshness_update() -> (
    None
):
    from research_harness_mcp.tools_primitives import _execute_primitive

    calls: list[tuple[str, object]] = []
    result = SimpleNamespace(
        primitive="paper_search",
        success=True,
        output={"papers": [{"id": 1}]},
        cost_usd=0.25,
    )

    class FakeConn:
        def execute(self, sql: str, params=()):
            calls.append(("sql", (sql, params)))
            return self

        def commit(self) -> None:
            calls.append(("commit", None))

        def close(self) -> None:
            calls.append(("close", None))

    class FakeDB:
        def connect(self) -> FakeConn:
            calls.append(("connect", None))
            return FakeConn()

    class FakeBackend:
        def execute(self, name: str, **arguments):
            calls.append(("execute", (name, arguments)))
            return result

    db = FakeDB()

    def serialize_result(primitive_result, orch_state, *, session_advisory, nudge):
        calls.append(
            (
                "serialize",
                (primitive_result, orch_state, session_advisory, nudge),
            )
        )
        return {"serialized": True}

    output = _execute_primitive(
        "paper_search",
        {"topic_id": 7, "query": "retrieval"},
        db_resolver=lambda: db,
        backend_factory=lambda resolved_db: FakeBackend(),
        result_serializer=serialize_result,
        orch_state_provider=lambda resolved_db, topic_id: {"topic_id": topic_id},
        session_advisory_provider=lambda resolved_db, name, arguments, orch_state: (
            "advice"
        ),
        nudge_provider=lambda resolved_db, name, arguments, primitive_result: "nudge",
    )

    assert output == {"serialized": True}
    assert calls[0] == (
        "execute",
        ("paper_search", {"topic_id": 7, "query": "retrieval"}),
    )
    assert ("connect", None) in calls
    assert ("commit", None) in calls
    assert ("close", None) in calls
    assert calls[-1][0] == "serialize"
    assert calls[-1][1][1:] == ({"topic_id": 7}, "advice", "nudge")
    sql_calls = [payload[0] for kind, payload in calls if kind == "sql"]
    assert any("UPDATE topics SET last_search_at" in sql for sql in sql_calls)
    assert any("INSERT INTO search_query_registry" in sql for sql in sql_calls)


def test_execute_primitive_preserves_deep_read_writing_pattern_followup() -> None:
    from research_harness_mcp.tools_primitives import _execute_primitive

    calls: list[tuple[str, object]] = []
    result = SimpleNamespace(
        primitive="deep_read",
        success=True,
        output={"paper_id": 9},
        cost_usd=0.0,
    )

    class FakeBackend:
        def execute(self, name: str, **arguments):
            calls.append(("execute", (name, arguments)))
            return result

    output = _execute_primitive(
        "deep_read",
        {"paper_id": "9", "topic_id": 3},
        db_resolver=lambda: object(),
        backend_factory=lambda resolved_db: FakeBackend(),
        result_serializer=lambda primitive_result, orch_state, *, session_advisory, nudge: {
            "primitive": primitive_result.primitive,
            "orch_state": orch_state,
            "session_advisory": session_advisory,
            "nudge": nudge,
        },
        orch_state_provider=lambda resolved_db, topic_id: {"topic_id": topic_id},
        session_advisory_provider=lambda resolved_db, name, arguments, orch_state: "",
        nudge_provider=lambda resolved_db, name, arguments, primitive_result: "",
    )

    assert calls == [
        ("execute", ("deep_read", {"paper_id": "9", "topic_id": 3})),
        ("execute", ("writing_pattern_extract", {"paper_id": 9})),
    ]
    assert output == {
        "primitive": "deep_read",
        "orch_state": {"topic_id": 3},
        "session_advisory": "",
        "nudge": "",
    }
