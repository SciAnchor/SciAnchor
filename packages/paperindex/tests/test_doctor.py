import json

from click.testing import CliRunner

from paperindex.cli import main


def test_doctor_accepts_cli_route_without_api_key(monkeypatch, tmp_path):
    agent = tmp_path / "agent"
    agent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    agent.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    from llm_router import client as client_mod

    monkeypatch.setattr(client_mod.LLMClient, "chat", lambda self, prompt, **_: "ok")

    result = CliRunner().invoke(main, ["doctor", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["provider"] == "cursor_agent"
    assert payload["route_kind"] == "host-cli"
    assert payload["connectivity"] == "ok"
