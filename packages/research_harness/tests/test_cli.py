import json

from research_harness.cli import main
from research_harness.storage.db import Database


def test_cli_end_to_end_json_contracts(runner):
    topic = runner.invoke(
        main, ["--json", "topic", "init", "auto-bidding", "--venue", "KDD 2027"]
    )
    assert topic.exit_code == 0
    assert json.loads(topic.output)["id"] == 1

    ingest = runner.invoke(
        main,
        [
            "--json",
            "paper",
            "ingest",
            "--arxiv-id",
            "1706.03762",
            "--title",
            "Attention Is All You Need",
            "--authors",
            "Vaswani,Shazeer",
            "--year",
            "2017",
            "--venue",
            "NeurIPS",
            "--topic",
            "auto-bidding",
            "--relevance",
            "high",
        ],
    )
    assert ingest.exit_code == 0
    assert json.loads(ingest.output)["paper_id"] == 1

    task = runner.invoke(
        main,
        [
            "--json",
            "task",
            "add",
            "--topic",
            "auto-bidding",
            "--title",
            "Read paper",
            "--priority",
            "high",
        ],
    )
    assert task.exit_code == 0
    assert json.loads(task.output)["task_id"] == 1

    update = runner.invoke(
        main, ["--json", "task", "update", "1", "--status", "in_progress"]
    )
    assert update.exit_code == 0
    assert json.loads(update.output)["updated"] is True

    search = runner.invoke(
        main,
        [
            "--json",
            "search",
            "log",
            "--topic",
            "auto-bidding",
            "--query",
            "budget pacing",
            "--provider",
            "semantic-scholar",
            "--result-count",
            "15",
            "--ingested-count",
            "3",
        ],
    )
    assert search.exit_code == 0
    assert json.loads(search.output)["id"] == 1

    review = runner.invoke(
        main,
        [
            "--json",
            "review",
            "add",
            "--topic",
            "auto-bidding",
            "--gate",
            "novelty",
            "--reviewer",
            "codex",
            "--verdict",
            "pass",
        ],
    )
    assert review.exit_code == 0
    assert json.loads(review.output)["id"] == 1

    paper_show = runner.invoke(main, ["--json", "paper", "show", "1"])
    assert paper_show.exit_code == 0
    payload = json.loads(paper_show.output)
    assert payload["paper"]["title"] == "Attention Is All You Need"


def test_topic_init_materializes_configured_rh_workspace(runner, tmp_path, monkeypatch):
    workspace_root = tmp_path / "rh-workspace"
    monkeypatch.delenv(
        "RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION", raising=False
    )
    monkeypatch.setenv("RESEARCH_HARNESS_WORKSPACE_ROOT", str(workspace_root))

    result = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "init",
            "workspace-demo",
            "--description",
            "Workspace scope.",
            "--venue",
            "AAAI",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    topic_workspace = workspace_root / "workspace-demo"
    assert payload["workspace_path"] == str(topic_workspace)
    assert (topic_workspace / "README.md").exists()
    assert (topic_workspace / "00-task-framing" / "topic-brief-v0.md").exists()
    assert (topic_workspace / "01-literature" / "papers" / "manifest.md").exists()
    brief = (topic_workspace / "00-task-framing" / "topic-brief-v0.md").read_text()
    assert "RH topic id: 1" in brief
    assert "Workspace scope." in brief


def test_topic_workspace_command_materializes_existing_topic_under_domain(
    runner, tmp_path, monkeypatch
):
    create = runner.invoke(
        main,
        [
            "topic",
            "init",
            "science-discovery-aaai-e2e",
            "--description",
            "AAAI-style evidence-governed science discovery paper.",
        ],
    )
    assert create.exit_code == 0, create.output

    workspace_root = tmp_path / "rh-workspace"
    monkeypatch.delenv(
        "RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION", raising=False
    )
    result = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "workspace",
            "science-discovery-aaai-e2e",
            "--workspace-root",
            str(workspace_root),
            "--workspace-domain",
            "auto-academic",
            "--slug",
            "science-discovery-aaai",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    topic_workspace = workspace_root / "auto-academic" / "science-discovery-aaai"
    assert payload["workspace_path"] == str(topic_workspace)
    assert topic_workspace.exists()
    readme = (topic_workspace / "README.md").read_text()
    assert "Canonical Research Harness topic: `science-discovery-aaai-e2e`" in readme
    assert "RH topic id: 1" in readme


def test_self_evolution_archive_from_artifacts_cli_records_packs(
    runner,
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "self-evolution-cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    create = runner.invoke(main, ["topic", "init", "self-evolution-cli"])
    assert create.exit_code == 0, create.output

    db = Database(db_path)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("self-evolution-cli", "self-evolution CLI test"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, project_id, topic_id, stage, artifact_type, status, stale,
                 title, payload_json)
            VALUES (?, ?, ?, 'eval', 'researchflowbench_score_report', 'active',
                    0, ?, ?)
            """,
            (
                801,
                1,
                1,
                "ResearchFlowBench LitSearch score report",
                json.dumps(
                    {
                        "benchmark_id": "litsearch",
                        "scores": [{"task_id": "litsearch.q1", "recall_at_k": 1.0}],
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "archive-from-artifacts",
            "--topic",
            "self-evolution-cli",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["record_count"] == 1
    assert payload["champion_entry_count"] == 0
    assert payload["mutation_performed"] is False
    assert payload["archive_artifact_id"]


def test_self_evolution_record_rfb_score_report_cli_then_archive(
    runner,
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "rfb-score-cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    create = runner.invoke(main, ["topic", "init", "rfb-score-cli"])
    assert create.exit_code == 0, create.output

    db = Database(db_path)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("rfb-score-cli", "RFB score CLI test"),
        )
        conn.commit()
    finally:
        conn.close()

    score_file = tmp_path / "scores.json"
    score_file.write_text(
        json.dumps(
            {
                "benchmark_id": "litsearch",
                "split": "promotion_test",
                "gate_action": "promote",
                "scores": [
                    {
                        "task_id": "litsearch.q1",
                        "split": "promotion_test",
                        "source_refs": ["project_artifacts:source-litsearch.q1"],
                        "promotion_test_refs": ["litsearch.q1"],
                        "recall_at_k": 1.0,
                        "mrr": 0.75,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "record-rfb-score-report",
            "--topic",
            "rfb-score-cli",
            "--score-file",
            str(score_file),
        ],
    )
    assert record.exit_code == 0, record.output
    record_payload = json.loads(record.output)
    assert record_payload["artifact_type"] == "researchflowbench_score_report"
    assert record_payload["benchmark_id"] == "litsearch"
    assert record_payload["score_count"] == 1

    archive = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "archive-from-artifacts",
            "--topic",
            "rfb-score-cli",
        ],
    )
    assert archive.exit_code == 0, archive.output
    archive_payload = json.loads(archive.output)
    assert archive_payload["record_count"] == 1
    assert archive_payload["champion_entry_count"] == 1
    assert archive_payload["mutation_performed"] is False
    assert archive_payload["archive_artifact_id"]
    assert archive_payload["champion_artifact_id"]

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT artifact_type, payload_json
            FROM project_artifacts
            WHERE id IN (?, ?)
            ORDER BY artifact_type
            """,
            (
                archive_payload["archive_artifact_id"],
                archive_payload["champion_artifact_id"],
            ),
        ).fetchall()
    finally:
        conn.close()

    payloads = {row["artifact_type"]: json.loads(row["payload_json"]) for row in rows}
    archive_record = payloads["candidate_archive_pack"]["records"][0]
    champion_entry = payloads["champion_registry_pack"]["entries"][0]
    expected_axes = [
        "paper_search.recall",
        "citation.candidate_generation",
        "paper_search.rerank_quality",
    ]

    assert archive_record["metadata"]["benchmark_id"] == "litsearch"
    assert archive_record["metadata"]["task_id"] == "litsearch.q1"
    assert archive_record["metadata"]["replay_split_role"] == "promotion_test"
    assert archive_record["metrics"]["recall_at_k"] == 1.0
    assert archive_record["metrics"]["mrr"] == 0.75
    assert archive_record["rh_axis_ids"] == expected_axes
    assert archive_record["replay_split"]["source_refs"] == [
        "project_artifacts:source-litsearch.q1"
    ]
    assert archive_record["replay_split"]["promotion_test_refs"] == ["litsearch.q1"]
    assert archive_record["replay_split"]["incubating"] is False

    assert champion_entry["metadata"]["benchmark_id"] == "litsearch"
    assert champion_entry["metadata"]["task_id"] == "litsearch.q1"
    assert champion_entry["metadata"]["replay_split_role"] == "promotion_test"
    assert champion_entry["metrics"]["recall_at_k"] == 1.0
    assert champion_entry["rh_axis_ids"] == expected_axes


def test_self_evolution_record_rfb_gate_report_cli(runner, tmp_path, monkeypatch):
    db_path = tmp_path / "rfb-gate-cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    create = runner.invoke(main, ["topic", "init", "rfb-gate-cli"])
    assert create.exit_code == 0, create.output

    gate_file = tmp_path / "gate.json"
    gate_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.score_comparison_gate.v0.1",
                "status": "pass",
                "benchmark_id": "litsearch",
                "baseline_id": "bm25_retrieval",
                "candidate_id": "paper_search_local_bm25",
                "metric_comparisons": [],
                "blockers": [],
                "automatic_mutation_enabled": False,
                "mutation_performed": False,
            }
        ),
        encoding="utf-8",
    )

    record = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "record-rfb-gate-report",
            "--topic",
            "rfb-gate-cli",
            "--gate-file",
            str(gate_file),
        ],
    )

    assert record.exit_code == 0, record.output
    payload = json.loads(record.output)
    assert payload["artifact_type"] == "researchflowbench_score_comparison_gate"
    assert payload["benchmark_id"] == "litsearch"
    assert payload["status"] == "pass"
    assert payload["candidate_id"] == "paper_search_local_bm25"

    db = Database(db_path)
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT artifact_type, path, payload_json
            FROM project_artifacts
            WHERE id = ?
            """,
            (payload["artifact_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert row["artifact_type"] == "researchflowbench_score_comparison_gate"
    assert row["path"] == str(gate_file)
    stored = json.loads(row["payload_json"])
    assert stored["mutation_performed"] is False


def test_self_evolution_record_note_without_topic(runner, tmp_path, monkeypatch):
    """D3: non-MCP self-dev notes land in experience_records without a topic."""
    db_path = tmp_path / "self-dev-note.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))

    record = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "record-note",
            "--note",
            "Xcientist writing-axis gap: no component↔ablation lock.",
            "--section",
            "competitor-audit",
            "--agent",
            "claude-code",
        ],
    )
    assert record.exit_code == 0, record.output
    payload = json.loads(record.output)
    assert payload["experience_record_id"]
    assert payload["topic_id"] is None
    assert payload["artifact_id"] is None

    db = Database(db_path)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT source_kind, stage, after_text, topic_id FROM experience_records WHERE id = ?",
            (payload["experience_record_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["source_kind"] == "auto_extracted"
    assert "component↔ablation" in row["after_text"]
    assert row["topic_id"] is None


def test_self_evolution_trajectory_list_show_diff(runner, tmp_path, monkeypatch):
    """D5: raw trajectory query/diff path without distillation."""
    db_path = tmp_path / "traj-cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    create = runner.invoke(main, ["topic", "init", "traj-cli"])
    assert create.exit_code == 0, create.output

    from research_harness.evolution.topic.trajectory import TrajectoryRecorder

    db = Database(db_path)
    rec_a = TrajectoryRecorder(db, "cli-sess-a")
    rec_a.record_tool_call("paper_search", stage="build", topic_id=1)
    rec_a.record_tool_call("paper_ingest", stage="build", topic_id=1)
    rec_b = TrajectoryRecorder(db, "cli-sess-b")
    rec_b.record_tool_call("paper_search", stage="build", topic_id=1)
    rec_b.record_decision("skip", "noise", stage="build", topic_id=1)

    listed = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "trajectory-list",
            "--topic",
            "traj-cli",
            "--stage",
            "build",
        ],
    )
    assert listed.exit_code == 0, listed.output
    listed_payload = json.loads(listed.output)
    ids = {s["session_id"] for s in listed_payload["sessions"]}
    assert "cli-sess-a" in ids and "cli-sess-b" in ids

    shown = runner.invoke(
        main,
        ["--json", "self-evolution", "trajectory-show", "--session", "cli-sess-a"],
    )
    assert shown.exit_code == 0, shown.output
    shown_payload = json.loads(shown.output)
    assert shown_payload["event_count"] == 2
    assert "paper_search" in shown_payload["text"]

    diffed = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "trajectory-diff",
            "--session-a",
            "cli-sess-a",
            "--session-b",
            "cli-sess-b",
        ],
    )
    assert diffed.exit_code == 0, diffed.output
    diff_payload = json.loads(diffed.output)
    assert diff_payload["count_a"] == 2
    assert diff_payload["first_mismatch_index"] is not None


def test_review_scoped_by_topic(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(main, ["topic", "init", "t2"])
    result = runner.invoke(
        main,
        [
            "review",
            "add",
            "--topic",
            "t2",
            "--gate",
            "method",
            "--reviewer",
            "codex",
            "--verdict",
            "pass",
        ],
    )
    assert result.exit_code == 0
