from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3


def test_http_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, http_helpers

    assert http_api._row_to_dict is http_helpers.row_to_dict
    assert http_api._rows_to_list is http_helpers.rows_to_list
    assert http_api._parse_json_field is http_helpers.parse_json_field
    assert http_api._now_iso is http_helpers.now_iso
    assert http_api._serialize_result is http_helpers.serialize_result
    assert http_api._topic_exists is http_helpers.topic_exists


def test_row_json_and_topic_helpers_match_existing_behavior():
    from research_harness_mcp import http_helpers

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO topics (id, name) VALUES (7, 'Demo')")
    row = conn.execute("SELECT id, name FROM topics WHERE id = 7").fetchone()

    assert http_helpers.row_to_dict(row) == {"id": 7, "name": "Demo"}
    assert http_helpers.rows_to_list([row]) == [{"id": 7, "name": "Demo"}]
    assert http_helpers.parse_json_field('{"ok": true}', {}) == {"ok": True}
    assert http_helpers.parse_json_field("not-json", {"fallback": True}) == {
        "fallback": True
    }
    assert http_helpers.parse_json_field(None, []) == []
    assert http_helpers.topic_exists(conn, 7) is True
    assert http_helpers.topic_exists(conn, 8) is False
    conn.close()


def test_now_and_serialize_helpers_keep_shapes():
    from research_harness_mcp import http_helpers

    @dataclass
    class Result:
        name: str
        created_at: datetime

    now = http_helpers.now_iso()
    serialized = http_helpers.serialize_result(
        Result(name="demo", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    )

    assert now.endswith("+00:00")
    assert serialized == {
        "name": "demo",
        "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    assert http_helpers.serialize_result(
        datetime(2026, 1, 2, tzinfo=timezone.utc)
    ) == datetime(2026, 1, 2, tzinfo=timezone.utc)
