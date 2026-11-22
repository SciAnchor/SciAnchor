from __future__ import annotations

from research_harness.auto_runner.final_status import collect_final_pdf_paths
from research_harness.orchestrator.service import OrchestratorService
from research_harness.storage.db import Database


def test_collect_final_pdf_paths_ignores_reference_paper_downloads(tmp_path) -> None:
    db = Database(tmp_path / "final-status.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
        )
        conn.commit()
    finally:
        conn.close()

    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id=1,
        stage="write",
        artifact_type="final_bundle",
        title="Wrong bundle",
        payload={"pdf_path": str(tmp_path / "papers" / "downloaded_reference.pdf")},
    )
    svc.record_artifact(
        topic_id=1,
        stage="write",
        artifact_type="final_bundle",
        title="Final bundle",
        payload={"compiled_pdf_path": str(tmp_path / "final_bundle" / "paper.pdf")},
    )
    svc.record_artifact(
        topic_id=1,
        stage="write",
        artifact_type="publication_pack",
        title="Publication pack",
        payload={
            "outputs": {
                "manuscript_pdf_path": str(tmp_path / "publication_pack" / "paper.pdf")
            }
        },
    )

    assert collect_final_pdf_paths(db) == [
        str(tmp_path / "final_bundle" / "paper.pdf"),
        str(tmp_path / "publication_pack" / "paper.pdf"),
    ]
