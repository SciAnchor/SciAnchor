"""Focused tests for MCP workflow helper extraction."""

from __future__ import annotations


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def test_candidate_evidence_dereferences_gap_and_contradiction_ids() -> None:
    from research_harness_mcp.tools_workflow import _candidate_evidence

    calls: list[tuple[str, tuple]] = []

    class FakeConn:
        def execute(self, sql: str, params=()):
            calls.append((sql, tuple(params)))
            if "FROM gaps" in sql:
                return _Rows(
                    [
                        {
                            "id": 3,
                            "description": "gap",
                            "severity": "high",
                            "confidence": 0.8,
                            "cross_verified": 1,
                        }
                    ]
                )
            if "FROM contradictions" in sql:
                return _Rows(
                    [{"id": 5, "conflict_reason": "conflict", "status": "open"}]
                )
            raise AssertionError(sql)

        def close(self) -> None:
            calls.append(("close", ()))

    class FakeDB:
        def connect(self) -> FakeConn:
            return FakeConn()

    result = _candidate_evidence(
        FakeDB(),
        {"evidence_gap_ids": "[3]", "evidence_contradiction_ids": "[5]"},
    )

    assert result == {
        "gaps": [
            {
                "id": 3,
                "description": "gap",
                "severity": "high",
                "confidence": 0.8,
                "cross_verified": 1,
            }
        ],
        "contradictions": [{"id": 5, "conflict_reason": "conflict", "status": "open"}],
    }
    assert calls[-1] == ("close", ())


def test_workflow_entry_preserves_ranked_next_actions() -> None:
    from research_harness_mcp.tools_workflow import _execute_workflow_entry

    class FakeSvc:
        def get_status(self, topic_id: int):
            assert topic_id == 7
            return {
                "run": {"current_stage": "experiment"},
                "gate": {"decision": "pass", "can_advance": True},
            }

    class FakeConn:
        def __init__(self) -> None:
            self._rows = [
                {"total": 2, "verified": 2},
                {"n": 1},
                {"n": 0},
            ]

        def execute(self, sql: str, params=()):
            del sql, params
            return _Rows([self._rows.pop(0)])

        def close(self) -> None:
            pass

    class FakeDB:
        def connect(self) -> FakeConn:
            return FakeConn()

    result = _execute_workflow_entry(FakeSvc(), FakeDB(), {"topic_id": 7})

    assert result == {
        "success": True,
        "topic_id": 7,
        "stage": "experiment",
        "gate_decision": "pass",
        "can_advance": True,
        "gaps": {"total": 2, "cross_verified": 2},
        "candidates": {"live": 1, "promoted": 0},
        "next_actions": [
            "experiment_handoff_prepare — 1 live candidates ready for experiment brief",
            "orchestrator_advance — gate passed for stage experiment",
        ],
    }
