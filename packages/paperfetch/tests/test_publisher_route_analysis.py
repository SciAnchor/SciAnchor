from __future__ import annotations

import json

from paperfetch.downloaders.pipeline.analysis import analyze_publisher_routes


def test_publisher_route_analysis_aggregates_and_redacts(tmp_path):
    root = tmp_path / "validation"
    round_root = root / "round_1"
    round_root.mkdir(parents=True)
    (round_root / "run_report.json").write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "paper_id": "secret-paper-id",
                        "title": "secret title",
                        "doi": "10.1000/secret",
                        "publisher_key": "publisher-a",
                        "discovery_events": [
                            {
                                "source": "crossref",
                                "outcome": "success",
                                "elapsed_ms": 25,
                                "diagnostics": {"url": "https://secret.example"},
                            }
                        ],
                        "transfer_attempts": [
                            {
                                "route": "public_browser",
                                "outcome": "degraded",
                                "elapsed_ms": 1200,
                                "error_class": "publisher_challenge",
                                "diagnostics": {
                                    "proxy_mode": "direct",
                                    "client_kind": "oa_browser",
                                    "decision_reason": "ordinary_html_confirmed",
                                    "url": "https://secret.example/path?token=secret",
                                    "diagnostics": {
                                        "challenge_mode": "automatic_verification",
                                    },
                                },
                            }
                        ],
                        "verification": {"identity_status": "not_checked"},
                        "final_result": {
                            "download_status": "failed",
                            "identity_verified": False,
                            "failure_taxonomy": "publisher_challenge",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = analyze_publisher_routes([root])

    publisher = result["publishers"]["publisher-a"]
    assert publisher["success_rate"] == 0.0
    assert publisher["final_errors"] == {"publisher_challenge": 1}
    assert publisher["routes"]["public_browser"]["timing"]["p95_ms"] == 1200
    assert publisher["challenge_modes"] == {"automatic_verification": 1}
    assert result["run_reports"] == 1

    serialized = json.dumps(result, ensure_ascii=False)
    for secret in (
        "10.1000/secret",
        "secret title",
        "secret-paper-id",
        "secret.example",
        "token=secret",
    ):
        assert secret not in serialized
