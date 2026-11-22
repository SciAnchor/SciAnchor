from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research_harness.storage.db import Database


def _load_fetch_pdfs_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "fetch_pdfs.py"
    spec = importlib.util.spec_from_file_location("fetch_pdfs_script_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_pdfs_dry_run_includes_pmcid_candidate_urls(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / ".research-harness" / "pool.db"
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, pmid, pmcid)
            VALUES ('PMC paper', '12345678', 'PMC1234567')
            """
        )
        conn.commit()
    finally:
        conn.close()

    module = _load_fetch_pdfs_module()
    monkeypatch.setattr(module, "find_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_pdfs.py",
            "--dry-run",
            "--limit",
            "1",
            "--download-dir",
            str(tmp_path / "pdfs"),
        ],
    )

    assert module.main() == 0

    output = capsys.readouterr().out
    assert "https://europepmc.org/articles/PMC1234567?pdf=render" in output
    assert "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC1234567" in output
