"""C-70 (RH half): EAG's paid calls report their usage, and `rh exemplar ...` prints it for its caller.

A caller that books every `rh exemplar` call against a stage budget, with no usage in the CLI's output,
booked each one unknown ($0 in the stage's budget_usd, ipss-genai-20260920 005_WRITE).
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from research_harness.cli import main
from research_harness.primitives import exemplar_impls as eag


@pytest.fixture(autouse=True)
def _fresh_calls():
    eag._CALLS.clear()
    yield
    eag._CALLS.clear()


def _router(monkeypatch, usage):
    from research_harness.execution import llm_primitives

    monkeypatch.setattr(eag, "_ROUTER_OK", None)
    monkeypatch.setattr(
        llm_primitives, "_get_client", lambda *a, **k: SimpleNamespace(model="gpt-4.1")
    )
    monkeypatch.setattr(llm_primitives, "_client_chat", lambda client, prompt: "reply")
    monkeypatch.setattr("llm_router.client.get_last_usage", lambda: usage)


def test_a_router_call_books_its_tokens_and_cost(monkeypatch):
    _router(monkeypatch, SimpleNamespace(prompt_tokens=1000, completion_tokens=500))
    assert eag._chat(eag._llm("gpt-4.1", "writing", "exemplar_curate"), "p") == "reply"
    report = eag.usage_report()
    assert report["calls"] == [
        {
            "model": "gpt-4.1",
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "cost_usd": pytest.approx(0.006),
            "price_basis": "table",
        }
    ]
    assert report["cost_usd"] == pytest.approx(0.006)


def test_a_call_whose_provider_reports_no_usage_makes_the_total_unknown(monkeypatch):
    _router(monkeypatch, None)
    eag._chat(eag._llm("gpt-4.1", "writing", "exemplar_curate"), "p")
    assert eag.usage_report()["cost_usd"] is None


def test_a_direct_call_books_the_usage_in_the_reply(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = {
        "choices": [{"message": {"content": "reply"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        eag.urllib.request,
        "urlopen",
        lambda req, timeout: Reply(json.dumps(body).encode()),
    )
    assert eag._direct_chat("grok-4.6", "p") == "reply"
    call = eag.usage_report()["calls"][0]
    assert (call["prompt_tokens"], call["completion_tokens"], call["price_basis"]) == (
        10,
        5,
        "estimate",
    )
    assert call["cost_usd"] is not None


def test_an_accounting_error_does_not_buy_the_prompt_again_on_the_direct_path(
    monkeypatch,
):
    _router(monkeypatch, SimpleNamespace(prompt_tokens=1, completion_tokens=1))
    monkeypatch.setattr(
        eag, "_book", lambda *a: (_ for _ in ()).throw(RuntimeError("ledger down"))
    )
    monkeypatch.setattr(
        eag, "_direct_chat", lambda *a: pytest.fail("the prompt was bought again")
    )
    with pytest.raises(RuntimeError, match="ledger down"):
        eag._chat(eag._llm("gpt-4.1", "writing", "exemplar_curate"), "p")


def test_the_cli_prints_the_commands_usage_on_stderr(monkeypatch):
    def fake_curate(**kwargs):
        eag._book("gpt-4.1", 1000, 500)
        return SimpleNamespace(
            unit_type=kwargs["unit_type"],
            candidates_seen=1,
            kept=0,
            rejected=1,
            model_used="gpt-4.1",
            units=[],
        )

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    try:
        runner = CliRunner(mix_stderr=False)  # click < 8.2 mixes stderr by default
    except TypeError:
        runner = CliRunner()  # click >= 8.2 always keeps stderr separate
    result = runner.invoke(
        main,
        [
            "exemplar",
            "curate",
            "--topic",
            "1",
            "--unit-type",
            "intro_arc",
            "--no-record",
        ],
    )
    assert result.exit_code == 0, result.output
    line = [ln for ln in result.stderr.splitlines() if ln.startswith("rh-usage: ")]
    assert len(line) == 1 and "rh-usage" not in result.stdout
    report = json.loads(line[0][len("rh-usage: ") :])
    assert report["schema_version"] == "rh.eag_usage.v1" and report[
        "cost_usd"
    ] == pytest.approx(0.006)
