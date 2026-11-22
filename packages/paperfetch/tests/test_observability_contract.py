"""统一事件、报告、输出边界和敏感信息契约。"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

import pytest

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.pipeline.report import build_download_run_report
from paperfetch.observability import (
    SPCLogEvent,
    bind_event_context,
    configure_observability,
    emit_event,
    events_snapshot,
    reset_event_state,
    write_output,
)


def _paper(paper_id: str, doi: str, *, success: bool) -> PaperRecord:
    paper = PaperRecord(
        paper_id=paper_id, doi=doi, title=f"Paper {paper_id}", publisher="ScienceDirect"
    )
    status = paper.fulltext_status
    status.download_attempted = True
    status.download_status = "downloaded" if success else "failed"
    status.identity_verified = success
    status.identity_status = "verified" if success else "metadata_poisoned"
    status.identity_confidence = "high" if success else "none"
    status.successful_route = "public_http" if success else None
    status.failure_taxonomy = None if success else "metadata_poisoned"
    return paper


def test_elsevier_recovered_route_error_is_not_final_failure():
    paper = _paper("spc:elsevier", "10.1016/j.example.2026.1", success=True)
    paper.fulltext_status.route_errors = [
        {"route": "elsevier_api", "error_class": "auth_failed"}
    ]
    paper.fulltext_status.download_attempts = [
        {"route": "elsevier_api", "error_class": "auth_failed", "duration_ms": 10},
        {"route": "public_http", "duration_ms": 20},
    ]
    report = build_download_run_report([paper], total_candidates=1)
    assert report["papers"][0]["publisher_key"] == "elsevier"
    assert report["papers"][0]["final_result"]["identity_verified"] is True
    assert all(
        event["outcome"] != "failed"
        for event in report["papers"][0]["events"]
        if not event["terminal"]
    )


def test_all_routes_failed_and_identity_pollution_are_terminal_failures():
    missed = _paper("spc:miss", "10.1000/miss", success=False)
    poisoned = _paper("spc:poison", "10.1000/poison", success=False)
    missed.fulltext_status.failure_taxonomy = "not_found"
    report = build_download_run_report([missed, poisoned], total_candidates=2)
    finals = [paper["events"][-1] for paper in report["papers"]]

    assert [event["outcome"] for event in finals] == ["failed", "failed"]
    assert [event["error_class"] for event in finals] == [
        "not_found",
        "metadata_poisoned",
    ]
    assert all(event["terminal"] and event["elapsed_ms"] >= 0 for event in finals)


def test_compatibility_logger_treats_nonterminal_failure_as_degraded():
    from paperfetch.observability import get_event_logger

    reset_event_state("degraded-message")
    configure_observability(stderr=False)
    get_event_logger("paperfetch.download.test").info("候选响应捕获失败，继续后续策略")

    [event] = events_snapshot()
    assert event.terminal is False
    assert event.outcome == "degraded"
    assert event.level == "INFO"


def test_compatibility_logger_does_not_mark_zero_failure_batch_as_degraded():
    from paperfetch.observability import get_event_logger

    reset_event_state("successful-batch-summary")
    configure_observability(stderr=False)
    get_event_logger("paperfetch.download.test").info(
        "[PDF 下载] 完成，目标数=1，尝试数=1，成功数=1，失败数=0"
    )

    [event] = events_snapshot()
    assert event.outcome == "success"


def test_compatibility_logger_extracts_core_fields_without_human_duplication(capsys):
    from paperfetch.observability import get_event_logger

    reset_event_state("legacy-fields")
    configure_observability(stderr=True, color=False, mode="development")
    get_event_logger("paperfetch.download.test").info(
        "[PDF 传输] 开始，DOI=%s，出版社=%s，来源=%s，transport=%s，route=%s，代理=%s，耗时=%dms",
        "10.1016/j.example.1",
        "ScienceDirect",
        "elsevier_api",
        "http",
        "public_http",
        "no-proxy",
        25,
    )

    captured = capsys.readouterr()
    [event] = events_snapshot()
    assert event.doi == "10.1016/j.example.1"
    assert event.publisher_key == "elsevier"
    assert event.route == "public_http"
    assert event.source == "elsevier_api"
    assert event.elapsed_ms == 25
    assert event.diagnostics["transport"] == "http"
    assert event.diagnostics["proxy_mode"] == "no-proxy"
    assert captured.err.count("DOI=10.1016/j.example.1") == 1
    assert captured.err.count("出版社=elsevier") == 1
    assert "transport=" not in captured.err
    assert "代理=" not in captured.err


def test_multiple_discovery_sources_remain_one_structured_field(capsys):
    from paperfetch.observability import get_event_logger

    reset_event_state("multiple-sources")
    configure_observability(stderr=True, color=False, mode="development")
    get_event_logger("paperfetch.download.discovery").info(
        "[PDF 发现] 完成，DOI=%s，出版社=%s，来源=%s，资源数=2，重复数=0，耗时=20ms",
        "10.1000/source",
        "Example",
        "arxiv+doi_landing",
    )

    captured = capsys.readouterr()
    [event] = events_snapshot()
    assert event.source == "arxiv+doi_landing"
    assert "完成,doi_landing" not in captured.err
    assert captured.err.count("来源=arxiv+doi_landing") == 1


def test_terminal_human_log_hides_internal_state_machine_terms(capsys):
    reset_event_state("professional-terminal")
    configure_observability(stderr=True, color=False, mode="development")
    emit_event(
        SPCLogEvent(
            event_code="download.paper.terminal",
            domain="download",
            phase="final",
            action="download_paper",
            outcome="success",
            terminal=True,
            level="INFO",
            task_id="professional-terminal",
            doi="10.1000/professional",
            publisher_key="elsevier",
            route="public_http",
            elapsed_ms=100,
            message="OK",
        )
    )

    line = capsys.readouterr().err
    assert "[论文下载] OK" in line
    assert "终局" not in line
    assert "结果=success" not in line
    assert "状态=OK" not in line
    assert line.count("OK") == 1


def test_terminal_elapsed_does_not_double_count_parallel_discovery_or_verification():
    paper = _paper("spc:elapsed", "10.1000/elapsed", success=True)
    paper.fulltext_status.discovery_events = [
        {"source": "one", "result": "found", "duration_ms": 100},
        {"source": "two", "result": "found", "duration_ms": 120},
    ]
    paper.fulltext_status.download_attempts = [
        {"route": "public_http", "duration_ms": 80},
        {"route": "public_http", "duration_ms": 200},
    ]
    paper.fulltext_status.verification = {"duration_ms": 30}

    terminal = build_download_run_report([paper])["papers"][0]["events"][-1]

    assert terminal["elapsed_ms"] == 120 + 80 + 200


def test_logs_use_stderr_and_business_json_owns_stdout(capsys):
    reset_event_state("stdio")
    configure_observability(stderr=True, mode="development")
    emit_event(
        SPCLogEvent(
            event_code="test.started",
            domain="test",
            phase="test",
            action="run",
            outcome="started",
            terminal=False,
            level="INFO",
            message="开始",
        )
    )
    write_output({"ok": True})
    captured = capsys.readouterr()

    assert json.loads(captured.out) == {"ok": True}
    assert "[测试][test] 开始" in captured.err
    assert "event=" not in captured.err
    assert re.search(r"\[\d{2}:\d{2}:\d{2}\] INFO\s+", captured.err)
    assert "event=" not in captured.out


def test_tty_uses_color_but_text_and_jsonl_files_never_contain_ansi(tmp_path, capsys):
    text_log = tmp_path / "events.log"
    event_log = tmp_path / "events.jsonl"
    reset_event_state("color")
    configure_observability(
        stderr=True,
        color=True,
        log_file=str(text_log),
        event_file=str(event_log),
    )
    emit_event(
        SPCLogEvent(
            event_code="paper.download.terminal",
            domain="download",
            phase="verification",
            action="download",
            outcome="failed",
            terminal=True,
            level="ERROR",
            task_id="color-test",
            doi="10.1000/color",
            publisher_key="elsevier",
            route="public_http",
            elapsed_ms=125,
            error_class="not_pdf",
            message="身份验证失败",
        )
    )

    captured = capsys.readouterr()
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    assert ansi.search(captured.err)
    field_colors = [
        re.search(r"(\x1b\[[0-9;]*m)10\.1000/color", captured.err).group(1),
        re.search(r"(\x1b\[[0-9;]*m)elsevier", captured.err).group(1),
        re.search(r"(\x1b\[[0-9;]*m)public_http", captured.err).group(1),
    ]
    assert len(set(field_colors)) == 3
    assert not ansi.search(text_log.read_text(encoding="utf-8"))
    assert not ansi.search(event_log.read_text(encoding="utf-8"))
    event = json.loads(event_log.read_text(encoding="utf-8"))
    assert event["entity"] == {"type": "paper", "id": "10.1000/color"}
    detail = json.loads((tmp_path / event["details_ref"]).read_text(encoding="utf-8"))
    assert detail["doi"] == "10.1000/color"


def test_human_log_is_compact_while_jsonl_keeps_event_code_and_diagnostics(
    tmp_path, capsys
):
    event_log = tmp_path / "events.jsonl"
    reset_event_state("compact")
    configure_observability(stderr=True, color=False, event_file=str(event_log))
    emit_event(
        SPCLogEvent(
            event_code="download.public_browser.response_capture",
            domain="download",
            phase="publisher_download",
            action="capture_pdf_response",
            outcome="miss",
            terminal=False,
            level="INFO",
            route="public_http",
            message="[OA 浏览器] 响应阶段未捕获 PDF，继续页面下载策略",
            diagnostics={"exception_type": "Error", "payload_sha256": "abc"},
        )
    )

    captured = capsys.readouterr()
    assert "event=" not in captured.err
    assert "payload_sha256" not in captured.err
    assert "捕获失败" not in captured.err
    assert "状态=" not in captured.err
    structured = json.loads(event_log.read_text(encoding="utf-8"))
    assert structured["action"] == "capture_pdf_response"
    detail = json.loads(
        (tmp_path / structured["details_ref"]).read_text(encoding="utf-8")
    )
    assert detail["diagnostics"]["payload_sha256"] == "abc"


def test_publisher_phases_use_compact_chinese_terminal_labels(capsys):
    reset_event_state("publisher-phase-labels")
    configure_observability(stderr=True, color=False, mode="development")
    emit_event(
        SPCLogEvent(
            event_code="download.publisher_authorization.started",
            domain="download",
            phase="publisher_authorization",
            action="establish_publisher_session",
            outcome="started",
            terminal=False,
            level="INFO",
            doi="10.1016/example",
            publisher_key="elsevier",
            route="public_http",
            message="开始",
        )
    )
    emit_event(
        SPCLogEvent(
            event_code="download.publisher_download.started",
            domain="download",
            phase="publisher_download",
            action="download_pdf",
            outcome="started",
            terminal=False,
            level="INFO",
            doi="10.1016/example",
            publisher_key="elsevier",
            route="public_http",
            message="开始请求",
        )
    )

    captured = capsys.readouterr().err
    assert "[下载][授权] 开始" in captured
    assert "[下载][PDF] 开始请求" in captured
    assert "publisher_authorization" not in captured
    assert "publisher_download" not in captured


def test_sensitive_fields_and_signed_urls_are_redacted():
    event = SPCLogEvent(
        event_code="test.redaction",
        domain="test",
        phase="test",
        action="redact",
        outcome="success",
        terminal=False,
        level="INFO",
        message="user@example.com Bearer secret-token",
        diagnostics={
            "api_key": "sk-secret-value-123456",
            "url": "https://example.org/a.pdf?X-Amz-Signature=secret&view=1",
            "captcha": "ABCD",
            "html": "<form>secret</form>",
            "title_token_coverage": 0.75,
        },
    ).to_dict()
    encoded = json.dumps(event)

    assert "secret-value" not in encoded
    assert "Signature=secret" not in encoded
    assert "ABCD" not in encoded
    assert "<form>" not in encoded
    assert "user@example.com" not in encoded
    assert event["diagnostics"]["title_token_coverage"] == 0.75


@pytest.mark.asyncio
async def test_concurrent_paper_context_does_not_cross_lines():
    reset_event_state("concurrent")
    configure_observability(stderr=False)

    async def emit(doi: str) -> None:
        with bind_event_context(task_id="batch", paper_id=doi, doi=doi):
            await asyncio.sleep(0)
            emit_event(
                event_code="paper.step",
                domain="test",
                phase="work",
                action="step",
                outcome="success",
                terminal=False,
                level="INFO",
                elapsed_ms=1,
            )

    await asyncio.gather(emit("10.1/a"), emit("10.1/b"))
    assert {(event.paper_id, event.doi) for event in events_snapshot()} == {
        ("10.1/a", "10.1/a"),
        ("10.1/b", "10.1/b"),
    }


def test_production_sources_do_not_use_naked_print_or_private_loggers():
    package = Path(__file__).parents[1] / "src" / "paperfetch"
    violations: list[str] = []
    for path in package.rglob("*.py"):
        if "tests" in path.parts or "data" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                violations.append(f"{path}:print:{node.lineno}")
        if path.name != "events.py" and (
            "logging.getLogger" in source or "logging.basicConfig" in source
        ):
            violations.append(f"{path}:logging")
    assert violations == []


def test_doctor_text_output_does_not_reveal_account_identifiers(monkeypatch, capsys):
    from argparse import Namespace
    from unittest.mock import patch

    from paperfetch.cli.doctor import run_doctor

    monkeypatch.setenv(
        "DOWNLOAD_PROXY", "http://sensitive-student-id:sensitive-password@127.0.0.1:9"
    )
    monkeypatch.setenv("ELSEVIER_API_KEY", "sensitive-email@example.com")
    monkeypatch.setenv("MINERU_API_TOKEN", "sensitive-cloud-password")
    with patch("requests.get") as get_mock:
        get_mock.return_value.status_code = 200
        run_doctor(Namespace(output_format="text"))

    output = capsys.readouterr().out
    assert "sensitive-student-id" not in output
    assert "sensitive-email@example.com" not in output
    assert "sensitive-password" not in output
    assert "sensitive-cloud-password" not in output


def test_doctor_public_json_is_slim_and_does_not_embed_env_file(
    capsys, monkeypatch, tmp_path
):
    from argparse import Namespace
    from unittest.mock import patch

    from paperfetch.cli.doctor import run_doctor

    monkeypatch.setattr(
        "paperfetch.cli.doctor._proxy_endpoint_status",
        lambda _name, timeout_seconds=1.0: {
            "configured": True,
            "scheme": "http",
            "tcp_reachable": True,
        },
    )
    monkeypatch.setattr(
        "paperfetch.cli.doctor.os.path.exists",
        lambda _path: True,
    )

    env_file = r"D:\Research\spc-config\.env"
    with patch("requests.get") as get_mock:
        get_mock.return_value.status_code = 503
        assert run_doctor(Namespace(output_format="json", env_file=env_file)) == 0

    raw = capsys.readouterr().out
    report = json.loads(raw)
    assert report["schema"] == "spc.result.v2"
    assert set(report["data"]) == {"verdict", "checks", "blockers"}
    assert "diagnostics" not in report
    assert "summary" not in report
    assert env_file not in raw
    ids = {item["id"] for item in report["data"]["checks"]}
    assert {
        "environment",
        "proxy.public",
        "settings.unknown",
        "paper.metadata.files",
        "paper.parse",
    } <= ids
    assert not any(item.startswith("cst.") for item in ids)
    assert all(
        set(item) == {"id", "verdict", "message"} for item in report["data"]["checks"]
    )
