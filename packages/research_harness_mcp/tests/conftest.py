from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_topic_workspace_materialization(monkeypatch):
    """Keep HTTP tests from writing to a user's real rh-workspace by default."""
    monkeypatch.setenv("RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION", "1")
