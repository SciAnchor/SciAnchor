"""CLI tests for the SPC bridge commands on the paper group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "failed", "error": {"code": "rate_limited"}},
        {"hits": []},
        {"status": "completed", "data": {"hits": []}},
        {"hits": [{}]},
        [],
    ],
)
def test_sciverse_rejects_failed_or_empty_spc_response(runner, monkeypatch, payload):
    from types import SimpleNamespace
    from research_harness.cli import main

    monkeypatch.setattr("shutil.which", lambda _: "/installed/spc")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
        ),
    )
    result = runner.invoke(main, ["search", "sciverse", "--query", "paper", "--json"])
    assert result.exit_code != 0
    assert "SPC" in result.output


@pytest.mark.parametrize(
    "payload",
    [
        {"hits": [{"title": "Paper", "doc_id": "p1"}]},
        {"status": "completed", "data": {"hits": [{"title": "Paper", "doc_id": "p1"}]}},
    ],
)
def test_sciverse_renders_spc_hits(runner, monkeypatch, payload):
    from types import SimpleNamespace
    from research_harness.cli import main

    monkeypatch.setattr("shutil.which", lambda _: "/installed/spc")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
        ),
    )
    result = runner.invoke(main, ["search", "sciverse", "--query", "paper"])
    assert result.exit_code == 0, result.output
    assert "Sciverse hits: 1" in result.output
    assert "Paper" in result.output


@pytest.mark.parametrize(
    "text, expected_exit", [("", 1), ("  ", 1), ("Paper content", 0)]
)
def test_sciverse_rejects_empty_content(runner, monkeypatch, text, expected_exit):
    from types import SimpleNamespace
    from research_harness.cli import main

    monkeypatch.setattr("shutil.which", lambda _: "/installed/spc")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"text": text}),
        ),
    )
    result = runner.invoke(main, ["search", "sciverse", "--doc-id", "p1", "--json"])
    assert result.exit_code == expected_exit, result.output


def test_paper_search_reports_spc_failure_as_cli_error(runner, monkeypatch):
    from research_harness.cli import main
    from research_harness.acquisition.spc_bridge import SPCAcquisitionError

    def fail_search(*args, **kwargs):
        raise SPCAcquisitionError("search", {"error": {"code": "rate_limited"}})

    monkeypatch.setattr(
        "research_harness.paper_sources.SearchAggregator.search", fail_search
    )
    result = runner.invoke(main, ["search", "papers", "--query", "paper", "--json"])
    assert result.exit_code == 1
    assert "Error: SPC search: rate_limited" in result.output
    assert "result_count" not in result.output


def _cli_db(tmp_path):
    """The runner fixture points the CLI at tmp_path/cli.db via env."""
    from research_harness.storage.db import Database

    db = Database(tmp_path / "cli.db")
    db.migrate()
    return db


def _topic_with_paper(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name) VALUES ('rag')")
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO papers (title, doi, status)"
            " VALUES ('Wanted Paper', '10.5555/w.1', 'meta_only')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance,"
            " screening_status, manuscript_eligible)"
            " VALUES (1, ?, 'high', 'screened_in', 1)",
            (topic_id,),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def test_import_seed_pack_command(runner, tmp_path):
    from research_harness.cli import main

    conn = _cli_db(tmp_path).connect()
    try:
        cur = conn.execute("INSERT INTO topics (name) VALUES ('rag')")
        topic_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "seed_papers.jsonl").write_text(
        json.dumps({"paper_id": "spc:1", "title": "CLI Imported Paper"}),
        encoding="utf-8",
    )

    result = runner.invoke(
        main,
        [
            "--json",
            "paper",
            "import-seed-pack",
            str(pack),
            "--topic",
            str(topic_id),
            "--download-dir",
            str(tmp_path / "dl"),
            "--no-annotate",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "rh.seed_pack_import_report.v1"
    assert payload["papers_seen"] == 1


def test_import_seed_pack_contract_error_is_clean(runner, tmp_path):
    from research_harness.cli import main

    result = runner.invoke(
        main,
        ["paper", "import-seed-pack", str(tmp_path / "nope"), "--topic", "1"],
    )

    assert result.exit_code != 0
    assert "seed pack contract error" in result.output


def test_export_spc_wants_command(runner, tmp_path):
    from research_harness.cli import main

    topic_id = _topic_with_paper(_cli_db(tmp_path))
    output = tmp_path / "wants.json"

    result = runner.invoke(
        main,
        [
            "--json",
            "paper",
            "export-spc-wants",
            str(topic_id),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["paper_count"] == 1
    assert Path(output).is_file()


def test_diagnose_acquisition_command(runner, tmp_path):
    from research_harness.cli import main

    topic_id = _topic_with_paper(_cli_db(tmp_path))

    result = runner.invoke(
        main, ["--json", "paper", "diagnose-acquisition", str(topic_id)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "rh.acquisition_diagnosis.v1"
    assert payload["totals"]["papers"] == 1
    assert payload["totals"]["without_pdf"] == 1
