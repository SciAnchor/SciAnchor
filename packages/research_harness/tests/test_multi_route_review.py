from __future__ import annotations

from pathlib import Path
import subprocess

from research_harness.reviewing import (
    build_aaai_review_prompt,
    MultiRouteReviewConfig,
    detect_review_route_availability,
    run_codex_agent_review,
    run_cursor_agent_review,
    run_host_agent_proxy_review,
    run_multi_route_review_probe,
)


def _write_candidate(root: Path, *, tex: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "paper.tex").write_text(tex, encoding="utf-8")
    (root / "references.bib").write_text(
        """@misc{ref1,
  title = {One},
  author = {A. Author},
  year = {2025},
  howpublished = {arXiv.org}
}

@misc{ref2,
  title = {Two},
  author = {B. Author},
  year = {2024},
  howpublished = {AAAI}
}
""",
        encoding="utf-8",
    )
    (root / "paper.log").write_text(
        """LaTeX Font Warning: Font shape `TU/ptm/m/n' undefined
Underfull \\hbox (badness 1852) in paragraph at lines 10--11
""",
        encoding="utf-8",
    )


def test_probe_flags_custom_non_aaai_style_and_missing_tables(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass[letterpaper]{article}
\usepackage[letterpaper]{geometry}
\usepackage[compact]{titlesec}
\usepackage{natbib}
\begin{document}
\begin{figure*}
\caption{Architecture.}
\end{figure*}
We cite prior work \citep{ref1}.
\bibliographystyle{plainnat}
\bibliography{references}
\end{document}
""",
    )

    report = run_multi_route_review_probe(
        candidate,
        config=MultiRouteReviewConfig(
            module_available=lambda _name: False,
            env={"OPENAI_API_KEY": ""},
        ),
    )

    assert report.deterministic.verdict == "not_aaai_ready"
    findings = {
        (item.severity, item.category) for item in report.deterministic.findings
    }
    assert ("critical", "format") in findings
    assert ("high", "evidence") in findings
    assert (
        report.deterministic.summary["tex_bib"]["official_aaai_style_detected"] is False
    )
    assert report.deterministic.summary["tex_bib"]["figures"] == 1
    assert report.deterministic.summary["tex_bib"]["tables"] == 0
    assert report.deterministic.summary["tex_bib"]["bib_entries"] == 2
    assert report.deterministic.summary["tex_bib"]["citation_keys_used"] == 1
    assert report.deterministic.summary["tex_bib"]["unused_bib_entries_estimate"] == 1
    assert report.deterministic.summary["log"]["underfull_hbox"] == 1


def test_official_style_with_table_passes_hard_format_gate(tmp_path):
    candidate = tmp_path / "candidate"
    (candidate / "aaai26.sty").parent.mkdir(parents=True)
    (candidate / "aaai26.sty").write_text("% style marker\n", encoding="utf-8")
    _write_candidate(
        candidate,
        tex=r"""\documentclass[letterpaper]{article}
\usepackage{aaai26}
\begin{document}
\begin{figure}
\caption{Architecture.}
\end{figure}
\begin{table}
\caption{Artifact coverage.}
\end{table}
Evidence \cite{ref1,ref2}.
\bibliographystyle{aaai26}
\bibliography{references}
\end{document}
""",
    )

    report = run_multi_route_review_probe(
        candidate,
        config=MultiRouteReviewConfig(module_available=lambda _name: False, env={}),
    )

    assert (
        report.deterministic.summary["tex_bib"]["official_aaai_style_detected"] is True
    )
    assert report.deterministic.summary["tex_bib"]["tables"] == 1
    assert ("critical", "format") not in {
        (item.severity, item.category) for item in report.deterministic.findings
    }


def test_route_availability_reports_installed_openjudge_and_missing_key():
    available = {
        "openjudge",
        "cookbooks.paper_review",
        "openai",
        "loguru",
        "json_repair",
        "fire",
    }

    routes = detect_review_route_availability(
        config=MultiRouteReviewConfig(
            module_available=lambda name: name in available,
            env={"OPENAI_API_KEY": ""},
            python_version=(3, 11),
            executable_finder=lambda _name: None,
        )
    )

    by_name = {route.route: route for route in routes}
    assert by_name["openjudge_paper_review"].status == "blocked"
    assert by_name["openjudge_paper_review"].missing == ("LLM_API_KEY",)
    assert by_name["openjudge_paper_review"].metadata["native_status"] == "blocked"
    assert by_name["openaireview"].missing == ("python>=3.12",)


def test_route_availability_marks_routes_runnable_when_deps_and_key_exist(tmp_path):
    ai_scientist_root = tmp_path / "AI-Scientist"
    ai_scientist_root.mkdir()
    available = {
        "numpy",
        "pypdf",
        "pymupdf4llm",
        "openai",
        "openjudge",
        "cookbooks.paper_review",
        "loguru",
        "json_repair",
        "fire",
    }

    routes = detect_review_route_availability(
        ai_scientist_root=ai_scientist_root,
        config=MultiRouteReviewConfig(
            module_available=lambda name: name in available,
            env={"OPENAI_API_KEY": "sk-test"},
            python_version=(3, 12),
            executable_finder=lambda _name: None,
        ),
    )

    by_name = {route.route: route for route in routes}
    assert by_name["ai_scientist_reviewer"].status == "runnable"
    assert by_name["openjudge_paper_review"].status == "runnable"
    assert by_name["openaireview"].status == "installable"
    assert by_name["rh_adversarial_review"].status == "runnable"


def test_route_availability_marks_host_agents_runnable_without_api_keys():
    routes = detect_review_route_availability(
        config=MultiRouteReviewConfig(
            module_available=lambda _name: False,
            env={},
            executable_finder=lambda name: {
                "codex": "/opt/homebrew/bin/codex",
                "agent": "/Users/example/.local/bin/agent",
            }.get(name),
        )
    )

    by_name = {route.route: route for route in routes}
    assert by_name["codex_agent_review"].status == "runnable"
    assert by_name["codex_agent_review"].missing == ()
    assert by_name["cursor_agent_review"].status == "runnable"
    assert by_name["cursor_agent_review"].missing == ()


def test_api_key_routes_use_host_agent_fallback_when_available(tmp_path):
    ai_scientist_root = tmp_path / "AI-Scientist"
    ai_scientist_root.mkdir()
    routes = detect_review_route_availability(
        ai_scientist_root=ai_scientist_root,
        config=MultiRouteReviewConfig(
            module_available=lambda _name: False,
            env={},
            executable_finder=lambda name: (
                "/Users/example/.local/bin/agent" if name == "agent" else None
            ),
            python_version=(3, 11),
        ),
    )

    by_name = {route.route: route for route in routes}
    for route_name in (
        "ai_scientist_reviewer",
        "openjudge_paper_review",
        "openaireview",
        "rh_adversarial_review",
    ):
        route = by_name[route_name]
        assert route.status == "runnable_via_host_agent"
        assert route.missing == ()
        assert route.metadata["native_status"] in {"blocked", "installable"}
        assert route.metadata["fallback_route"] == "cursor_agent_review"
        assert route.metadata["native_missing"]


def test_route_availability_blocks_host_agents_when_cli_missing():
    routes = detect_review_route_availability(
        config=MultiRouteReviewConfig(
            module_available=lambda _name: False,
            env={},
            executable_finder=lambda _name: None,
        )
    )

    by_name = {route.route: route for route in routes}
    assert by_name["codex_agent_review"].status == "blocked"
    assert by_name["codex_agent_review"].missing == ("codex",)
    assert by_name["cursor_agent_review"].status == "blocked"
    assert by_name["cursor_agent_review"].missing == ("agent",)


def test_build_aaai_review_prompt_requires_strict_json(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass{article}
\begin{document}
Review me.
\end{document}
""",
    )

    prompt = build_aaai_review_prompt(
        candidate,
        candidate_label="layout-v8",
        deterministic_summary={"tex_bib": {"tables": 0}},
    )

    assert "AAAI main track" in prompt
    assert "layout-v8" in prompt
    assert "strict JSON" in prompt
    assert '"aaai_readiness"' in prompt
    assert "visual/table complexity" in prompt


def test_run_codex_agent_review_parses_json_without_api_key(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass{article}
\begin{document}
Codex review target.
\end{document}
""",
    )
    seen: dict[str, object] = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"verdict":"reject","issues":[{"severity":"high","category":"format","target":"style","reasoning":"custom style","suggested_fix":"use aaai26"}],"scores":{"aaai_readiness":1},"notes":"not ready"}',
            stderr="",
        )

    result = run_codex_agent_review(
        candidate,
        config=MultiRouteReviewConfig(
            env={},
            executable_finder=lambda name: (
                "/opt/homebrew/bin/codex" if name == "codex" else None
            ),
            command_runner=runner,
        ),
        workspace_path=tmp_path,
        timeout_seconds=5,
    )

    assert result.status == "completed"
    assert result.verdict == "reject"
    assert result.issues[0]["suggested_fix"] == "use aaai26"
    cmd = seen["cmd"]
    assert cmd[:2] == ["/opt/homebrew/bin/codex", "exec"]
    assert "--sandbox" in cmd
    assert "read-only" in cmd
    assert "-C" in cmd
    assert str(tmp_path) in cmd
    assert seen["kwargs"]["timeout"] == 5


def test_run_cursor_agent_review_parses_json_fence_without_api_key(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass{article}
\begin{document}
Cursor review target.
\end{document}
""",
    )
    seen: dict[str, object] = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='```json\n{"verdict":"revise","issues":[],"scores":{"content":3},"notes":"needs more experiments"}\n```',
            stderr="",
        )

    result = run_cursor_agent_review(
        candidate,
        config=MultiRouteReviewConfig(
            env={},
            executable_finder=lambda name: (
                "/Users/example/.local/bin/agent" if name == "agent" else None
            ),
            command_runner=runner,
        ),
        workspace_path=tmp_path,
        timeout_seconds=7,
    )

    assert result.status == "completed"
    assert result.verdict == "revise"
    assert result.scores["content"] == 3
    cmd = seen["cmd"]
    assert cmd[:4] == [
        "/Users/example/.local/bin/agent",
        "-p",
        "--output-format",
        "text",
    ]
    assert "--workspace" in cmd
    assert "--trust" in cmd
    assert "--mode" in cmd
    assert "ask" in cmd
    assert seen["kwargs"]["timeout"] == 7


def test_run_host_agent_proxy_review_profiles_external_route(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass{article}
\begin{document}
Proxy review target.
\end{document}
""",
    )
    seen: dict[str, object] = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"verdict":"reject","issues":[{"severity":"critical","category":"evidence","target":"experiments","reasoning":"no baselines","suggested_fix":"add benchmark table"}],"scores":{"evidence":1},"notes":"OpenJudge-style proxy"}',
            stderr="",
        )

    result = run_host_agent_proxy_review(
        candidate,
        source_route="openjudge_paper_review",
        config=MultiRouteReviewConfig(
            env={},
            executable_finder=lambda name: (
                "/Users/example/.local/bin/agent" if name == "agent" else None
            ),
            command_runner=runner,
        ),
        workspace_path=tmp_path,
        timeout_seconds=9,
    )

    assert result.route == "openjudge_paper_review_via_cursor_agent"
    assert result.status == "completed"
    assert result.verdict == "reject"
    assert result.issues[0]["suggested_fix"] == "add benchmark table"
    prompt = seen["cmd"][-1]
    assert "OpenJudge-style paper review" in prompt
    assert seen["kwargs"]["timeout"] == 9


def test_multi_route_probe_executes_proxy_reviews_for_non_native_routes(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass{article}
\begin{document}
Proxy review target.
\end{document}
""",
    )
    calls: list[str] = []

    def runner(cmd, **kwargs):
        prompt = cmd[-1]
        route = "cursor_agent_review"
        if "AI Scientist-style" in prompt:
            route = "ai_scientist_reviewer_via_cursor_agent"
        elif "OpenJudge-style" in prompt:
            route = "openjudge_paper_review_via_cursor_agent"
        elif "OpenAIReview-style" in prompt:
            route = "openaireview_via_cursor_agent"
        elif "RH adversarial-review-style" in prompt:
            route = "rh_adversarial_review_via_cursor_agent"
        calls.append(route)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"verdict":"revise","issues":[],"scores":{"aaai_readiness":2},"notes":"ok"}',
            stderr="",
        )

    report = run_multi_route_review_probe(
        candidate,
        execute_host_agents=True,
        host_agent_timeout_seconds=3,
        config=MultiRouteReviewConfig(
            env={},
            executable_finder=lambda name: (
                "/Users/example/.local/bin/agent" if name == "agent" else None
            ),
            command_runner=runner,
        ),
    )

    executed = {route.route for route in report.executed_routes}
    assert "cursor_agent_review" in executed
    assert "ai_scientist_reviewer_via_cursor_agent" in executed
    assert "openjudge_paper_review_via_cursor_agent" in executed
    assert "openaireview_via_cursor_agent" in executed
    assert "rh_adversarial_review_via_cursor_agent" in executed
    assert "codex_agent_review" not in executed
    assert calls.count("cursor_agent_review") == 1


def test_host_agent_review_missing_cli_returns_blocked(tmp_path):
    result = run_codex_agent_review(
        tmp_path,
        config=MultiRouteReviewConfig(
            env={},
            executable_finder=lambda _name: None,
        ),
    )

    assert result.status == "blocked"
    assert result.missing == ("codex",)


def test_report_payload_is_artifact_ready(tmp_path):
    candidate = tmp_path / "candidate"
    _write_candidate(
        candidate,
        tex=r"""\documentclass{article}
\begin{document}
No visuals.
\end{document}
""",
    )

    report = run_multi_route_review_probe(
        candidate,
        topic_id=8,
        candidate_label="layout-v8",
        config=MultiRouteReviewConfig(
            module_available=lambda _name: False,
            env={},
            executable_finder=lambda name: (
                "/Users/example/.local/bin/agent" if name == "agent" else None
            ),
        ),
    )

    payload = report.to_artifact_payload()

    assert payload["topic_id"] == 8
    assert payload["candidate_label"] == "layout-v8"
    assert payload["deterministic_route"]["status"] == "completed"
    assert (
        payload["external_routes"]["openjudge_paper_review"]["status"]
        == "runnable_via_host_agent"
    )
    assert (
        payload["external_routes"]["openjudge_paper_review"]["metadata"][
            "native_status"
        ]
        == "blocked"
    )
    assert payload["decision"].startswith("Do not redevelop reviewer logic")
