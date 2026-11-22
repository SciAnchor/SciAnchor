import json

import pytest

from paperfetch.observability import (
    configure_observability,
    get_event_logger,
    observability_status,
    reset_event_state,
)
from paperfetch.runtime_mode import resolve_log_mode


def test_resolve_log_mode_uses_explicit_and_environment_values(monkeypatch):
    monkeypatch.setenv("SPC_LOG_MODE", "production")
    assert resolve_log_mode() == "production"
    assert resolve_log_mode("development") == "development"

    with pytest.raises(ValueError, match="SPC_LOG_MODE"):
        resolve_log_mode("verbose")


def test_production_mode_suppresses_info_console_but_keeps_audit_file(tmp_path, capsys):
    event_file = tmp_path / "events.jsonl"
    try:
        configure_observability(
            level="INFO", event_file=str(event_file), mode="production", color=False
        )
        reset_event_state("production-mode")
        get_event_logger("test").info("用户任务已进入下载阶段")

        captured = capsys.readouterr()
        assert captured.err == ""
        [event] = [
            json.loads(line)
            for line in event_file.read_text(encoding="utf-8").splitlines()
        ]
        assert event["schema_version"] == "spc.event.v1"
        assert "message" not in event
        assert event["action"] == "test.message"
        assert event["details_ref"] is None
        assert not (tmp_path / "audit").exists()
        assert observability_status() == {
            "mode": "production",
            "stderr_minimum_level": "WARNING",
            "text_log_enabled": False,
            "event_log_enabled": True,
        }
    finally:
        configure_observability(mode="development")
