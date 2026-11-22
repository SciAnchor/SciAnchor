"""Tests for the local offload task-pack contract."""

from __future__ import annotations

import json
import os
import shutil
import shlex
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from research_harness.offload import (
    OffloadError,
    RECEIPT_FILE,
    build_runner_command,
    compute_file_hashes,
    create_batch_plan,
    create_offload_queue,
    doctor,
    fetch_task,
    import_task_result,
    load_task_manifest,
    prepare_task,
    preflight_batch_plan,
    reconcile_batch_plan,
    remote_cleanup,
    remote_status,
    run_local_task,
    run_offload_queue_once,
    scan_remote_library,
    status_payload,
    status_batch_plan,
    status_offload_queue,
    upload_task,
    validate_remote_library_snapshot,
    validate_result_package,
    validate_host_alias,
    validate_status_transition,
    validate_task_manifest,
)
from research_harness.primitives import deepread_impls
from research_harness.storage.db import Database


def _seed_topic(db_path: Path) -> None:
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, 'demo-topic', 'Demo', 'active')"
        )
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, venue, year, status, pdf_path, pdf_hash)
            VALUES
                (1, 'A paper', 'Ada', 'TestConf', 2026, 'pending', '/tmp/a.pdf', 'hash-a')
            """
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (topic_id, stage, artifact_type, title, path, payload_json, metadata_json)
            VALUES
                (
                    1,
                    'build',
                    'wiki_context_pack',
                    'Wiki context',
                    '/Users/example/private/wiki.json',
                    '{"secret_path": "/Users/example/private/source.txt", "summary": "time series wiki summary", "pages": [{"title": "Forecasting", "excerpt": "seasonal transformer evidence"}]}',
                    '{"source": "local"}'
                )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _write_result(task_dir: Path, status: str = "succeeded") -> Path:
    manifest = json.loads((task_dir / "task_manifest.json").read_text())
    result_root = (
        task_dir.parent.parent
        if task_dir.parent.name == "incoming"
        else task_dir.parent
    )
    result_dir = result_root / "results" / manifest["task_id"]
    if result_dir.exists():
        shutil.rmtree(result_dir)
    outputs = result_dir / "outputs"
    logs = result_dir / "logs"
    outputs.mkdir(parents=True)
    logs.mkdir()
    (outputs / "summary.json").write_text('{"ok": true}\n')
    if manifest["task_type"] == "paper_text_extraction_batch":
        (outputs / "paper_text_extraction_results.jsonl").write_text("")
    (logs / "stdout.log").write_text("done\n")
    (logs / "stderr.log").write_text("")
    (result_dir / "task_manifest.json").write_text(
        (task_dir / "task_manifest.json").read_text()
    )
    output_hashes = compute_file_hashes(outputs)
    (result_dir / "result_manifest.json").write_text(
        json.dumps(
            {
                "task_id": manifest["task_id"],
                "task_type": manifest["task_type"],
                "status": status,
                "started_at": "2026-06-19T00:00:00Z",
                "finished_at": "2026-06-19T00:01:00Z",
                "exit_code": 0 if status == "succeeded" else 1,
                "output_hashes": output_hashes,
                "warnings": [],
                "server_hostname": "fake-worker",
                "git_commit": "abcdef0",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result_dir


def _rewrite_result_manifest_hashes(result_dir: Path) -> None:
    manifest_path = result_dir / "result_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_hashes"] = compute_file_hashes(result_dir / "outputs")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _write_successful_paper_text_result(task_dir: Path) -> Path:
    result_dir = _write_result(task_dir, status="succeeded")
    rows = [
        {
            "paper_id": 1,
            "status": "succeeded",
            "pdf_hash": "hash-a",
            "page_count": 2,
            "pages_text": ["first imported page", "second imported page"],
            "parser": "test-extractor",
        }
    ]
    (result_dir / "outputs" / "paper_text_extraction_results.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"
    )
    _rewrite_result_manifest_hashes(result_dir)
    return result_dir


def _write_successful_retrieval_eval_result(task_dir: Path) -> Path:
    result_dir = _write_result(task_dir, status="succeeded")
    (result_dir / "outputs" / "summary.json").unlink()
    report = {
        "schema_version": "retrieval_eval_sweep.report.v1",
        "task_type": "retrieval_eval_sweep",
        "method": "fake_model_snapshot_rerank_v1",
        "query_count": 1,
        "evaluated_count": 1,
        "top_k": 2,
        "model_policy": {
            "backend": "fake_model",
            "model_id": "generic-local-reranker",
            "cache_policy": {"cleanup": "manual", "cache_root": "cache"},
        },
        "note": "Schema exercise only; not a retrieval quality claim.",
    }
    predictions = [
        {
            "paper_id": 1,
            "query": "time series forecasting",
            "method": "fake_model_snapshot_rerank_v1",
            "top_matches": [
                {
                    "basename": "forecasting-transformer.pdf",
                    "relative_path_hash": "a" * 64,
                    "score": 0.91,
                },
                {
                    "basename": "shapelet-baseline.pdf",
                    "relative_path_hash": "b" * 64,
                    "score": 0.72,
                },
            ],
        }
    ]
    (result_dir / "outputs" / "retrieval_eval_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True)
    )
    (result_dir / "outputs" / "predictions.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in predictions) + "\n"
    )
    _rewrite_result_manifest_hashes(result_dir)
    return result_dir


def _write_successful_wiki_embedding_result(task_dir: Path) -> Path:
    result_dir = _write_result(task_dir, status="succeeded")
    summary = {
        "schema_version": "remote_offload_contract_output.v1",
        "wiki_embedding_schema_version": "wiki_embedding_batch.summary.v1",
        "method": "fake_model_embedding_v1",
        "succeeded_count": 1,
        "failed_count": 0,
        "model_policy": {
            "backend": "fake_model",
            "model_id": "generic-local-test-model",
            "cache_policy": {"cleanup": "manual", "cache_root": "cache"},
        },
        "note": "Schema exercise only; not an embedding quality claim.",
    }
    embeddings = [
        {
            "artifact_id": 1,
            "status": "succeeded",
            "method": "fake_model_embedding_v1",
            "model_id": "generic-local-test-model",
            "embedding_dim": 4,
            "embedding": [0.1, 0.2, 0.3, 0.4],
            "embedding_text_sha256": "c" * 64,
            "source_artifact_type": "wiki_context_pack",
        }
    ]
    (result_dir / "outputs" / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True)
    )
    (result_dir / "outputs" / "wiki_embeddings.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in embeddings) + "\n"
    )
    _rewrite_result_manifest_hashes(result_dir)
    return result_dir


def _write_existing_paperindex_structure(
    db_path: Path,
    *,
    paper_id: int = 1,
    pages_text: list[str] | object | None = None,
    structure_path: Path | None = None,
    pdf_hash: str = "hash-a",
) -> Path:
    pages = ["local explicit page one", "local explicit page two"]
    if pages_text is not None:
        pages = pages_text  # type: ignore[assignment]
    resolved_path = (
        structure_path
        or db_path.parent
        / "artifacts"
        / "paperindex"
        / f"paper_{paper_id}"
        / "structure.json"
    )
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        json.dumps(
            {
                "doc_name": f"paper_{paper_id}",
                "pdf_hash": pdf_hash,
                "page_count": len(pages) if isinstance(pages, list) else 0,
                "structure": [],
                "raw": {
                    "parser": "local-test-parser",
                    "pages_text": pages,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    conn = Database(db_path).connect()
    try:
        conn.execute(
            """
            INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)
            VALUES (?, 'paperindex_structure', ?, ?)
            """,
            (
                paper_id,
                str(resolved_path),
                json.dumps(
                    {
                        "source": "local",
                        "pdf_hash": pdf_hash,
                        "page_count": len(pages) if isinstance(pages, list) else 0,
                    },
                    sort_keys=True,
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return resolved_path


def _seed_wiki_context_artifacts(db_path: Path, *, count: int) -> None:
    conn = Database(db_path).connect()
    try:
        for index in range(2, count + 1):
            conn.execute(
                """
                INSERT INTO project_artifacts
                    (id, topic_id, stage, artifact_type, title, path,
                     payload_json, metadata_json)
                VALUES (?, 1, 'build', 'wiki_context_pack', ?, '', ?, ?)
                """,
                (
                    index,
                    f"Wiki context {index}",
                    json.dumps(
                        {
                            "summary": f"time series wiki summary {index}",
                            "pages": [
                                {
                                    "title": f"Forecasting {index}",
                                    "excerpt": "seasonal transformer evidence",
                                }
                            ],
                        },
                        sort_keys=True,
                    ),
                    json.dumps({"source": "local"}, sort_keys=True),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _write_minimal_text_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = f"BT\n/F1 24 Tf\n100 700 Td\n({text}) Tj\nET\n".encode()
    content = b"\n".join(
        [
            b"%PDF-1.4",
            b"1 0 obj",
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"endobj",
            b"2 0 obj",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"endobj",
            b"3 0 obj",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"endobj",
            b"4 0 obj",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"endobj",
            b"5 0 obj",
            f"<< /Length {len(stream)} >>".encode(),
            b"stream",
            stream,
            b"endstream",
            b"endobj",
            b"xref",
            b"0 6",
            b"0000000000 65535 f ",
            b"0000000009 00000 n ",
            b"0000000058 00000 n ",
            b"0000000115 00000 n ",
            b"0000000241 00000 n ",
            b"0000000311 00000 n ",
            b"trailer",
            b"<< /Root 1 0 R /Size 6 >>",
            b"startxref",
            b"429",
            b"%%EOF",
            b"",
        ]
    )
    path.write_bytes(content)


def _read_receipt(path: Path) -> dict[str, object]:
    return json.loads((path / RECEIPT_FILE).read_text())


def _remote_library_snapshot() -> dict[str, object]:
    return {
        "schema_version": "remote_library_snapshot.v1",
        "created_at": "2026-06-20T00:00:00+00:00",
        "query": "time series forecasting",
        "host_alias_hash": "a" * 64,
        "library_root_hash": "b" * 64,
        "max_files_scanned": 1000,
        "scanned_file_count": 128,
        "matched_file_count": 2,
        "truncated": False,
        "extension_counts": {".pdf": 120, ".json": 8},
        "samples": [
            {
                "basename": "time-series-transformers.pdf",
                "extension": ".pdf",
                "size_bytes": 12345,
                "relative_path_hash": "c" * 64,
                "path_depth": 2,
                "matched_terms": ["time", "series"],
            }
        ],
        "warnings": [],
    }


def test_prepare_task_writes_minimal_manifest_and_rejects_db_copy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)

    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )

    manifest = json.loads((task_dir / "task_manifest.json").read_text())
    validate_task_manifest(manifest)
    assert manifest["task_type"] == "paper_text_extraction_batch"
    assert manifest["status"] == "prepared"
    assert manifest["topic"] == "demo-topic"
    assert "paper_text_extraction_inputs.json" in manifest["input_hashes"]
    assert "pool.db" not in manifest["input_hashes"]
    assert not (task_dir / "inputs" / "pool.db").exists()
    assert (task_dir / "runner.sh").exists()
    assert (task_dir / "README.md").exists()


def test_prepare_task_redacts_local_paths_from_inputs(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)

    paper_task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )
    paper_inputs = json.loads(
        (paper_task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    assert "pdf_path" not in paper_inputs["papers"][0]
    assert "pdf_hash" in paper_inputs["papers"][0]
    assert "/tmp/a.pdf" not in json.dumps(paper_inputs)

    wiki_task = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    wiki_inputs = json.loads(
        (wiki_task / "inputs" / "wiki_embedding_inputs.json").read_text()
    )
    artifact = wiki_inputs["artifacts"][0]
    assert "path" not in artifact
    assert "payload_excerpt" not in artifact
    assert "/Users/example" not in json.dumps(wiki_inputs)


def test_prepare_wiki_embedding_packages_safe_text_without_local_paths(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)

    task = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )

    payload = json.loads((task / "inputs" / "wiki_embedding_inputs.json").read_text())
    artifact = payload["artifacts"][0]
    assert artifact["embedding_text"] == (
        "time series wiki summary\n\nForecasting\n\nseasonal transformer evidence"
    )
    assert (
        artifact["embedding_text_sha256"]
        == hashlib.sha256(artifact["embedding_text"].encode("utf-8")).hexdigest()
    )
    assert artifact["embedding_text_origin"] == "project_artifact_payload"
    packed = json.dumps(payload)
    assert "/Users/example" not in packed
    assert "secret_path" not in packed
    assert "wiki.json" not in packed
    assert "pool.db" not in packed


def test_prepare_task_packages_explicit_paperindex_text_only(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    structure_path = _write_existing_paperindex_structure(
        db_path,
        pages_text=["explicit first page", "explicit second page"],
    )

    task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )

    payload = json.loads(
        (task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    source_text = "explicit first page\n\nexplicit second page"
    assert paper["source_text"] == source_text
    assert (
        paper["source_text_sha256"]
        == hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    )
    assert paper["source_text_page_count"] == 2
    assert paper["source_text_origin"] == "paperindex_structure"
    assert "pdf_path" not in paper
    packed = json.dumps(payload)
    assert str(structure_path) not in packed
    assert "/tmp/a.pdf" not in packed
    assert "pool.db" not in packed


def test_prepare_task_explicitly_packages_safe_pdf_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    pdf_path = workspace / "papers" / "paper-1.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_bytes = b"%PDF-1.4\n% test pdf bytes\n%%EOF\n"
    pdf_path.write_bytes(pdf_bytes)
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ?, pdf_hash = ? WHERE id = 1",
            (str(pdf_path), hashlib.sha256(pdf_bytes).hexdigest()),
        )
        conn.commit()
    finally:
        conn.close()

    task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
        include_pdf_files=True,
    )

    payload = json.loads(
        (task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    packed_pdf = task / "inputs" / paper["pdf_file"]
    assert packed_pdf.is_file()
    assert packed_pdf.read_bytes() == pdf_bytes
    assert paper["pdf_file_origin"] == "explicit_pdf_pack"
    assert paper["pdf_file_sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert paper["pdf_file_size_bytes"] == len(pdf_bytes)
    packed = json.dumps(payload)
    assert str(pdf_path) not in packed
    assert "paper-1.pdf" not in packed
    assert "pool.db" not in packed


def test_prepare_task_rejects_explicit_pdf_pack_outside_db_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\noutside\n%%EOF\n")
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ? WHERE id = 1",
            (str(outside_pdf),),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(OffloadError, match="outside_db_root"):
        prepare_task(
            task_type="paper_text_extraction_batch",
            topic="demo-topic",
            out_dir=tmp_path / "paper-task",
            db_path=db_path,
            include_pdf_files=True,
        )


def test_prepare_task_rejects_explicit_pdf_pack_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    target = workspace / "papers" / "target.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-1.4\nsymlink target\n%%EOF\n")
    link = workspace / "papers" / "link.pdf"
    link.symlink_to(target)
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ? WHERE id = 1",
            (str(link),),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(OffloadError, match="unsafe_pdf_path"):
        prepare_task(
            task_type="paper_text_extraction_batch",
            topic="demo-topic",
            out_dir=tmp_path / "paper-task",
            db_path=db_path,
            include_pdf_files=True,
        )


def test_prepare_task_rejects_explicit_pdf_pack_oversized_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    pdf_path = workspace / "papers" / "too-large.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n0123456789\n%%EOF\n")
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ? WHERE id = 1",
            (str(pdf_path),),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(OffloadError, match="pdf_file_too_large"):
        prepare_task(
            task_type="paper_text_extraction_batch",
            topic="demo-topic",
            out_dir=tmp_path / "paper-task",
            db_path=db_path,
            include_pdf_files=True,
            max_pdf_bytes=8,
        )


def test_prepare_task_rejects_explicit_pdf_pack_bad_magic(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    pdf_path = workspace / "papers" / "not-really.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"not a pdf")
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ? WHERE id = 1",
            (str(pdf_path),),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(OffloadError, match="unsupported_pdf_file_type"):
        prepare_task(
            task_type="paper_text_extraction_batch",
            topic="demo-topic",
            out_dir=tmp_path / "paper-task",
            db_path=db_path,
            include_pdf_files=True,
        )


def test_prepare_task_does_not_read_paperindex_structure_outside_db_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    structure_path = tmp_path / "outside" / "structure.json"
    _write_existing_paperindex_structure(
        db_path,
        pages_text=["must stay local"],
        structure_path=structure_path,
    )

    task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )

    payload = json.loads(
        (task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    packed = json.dumps(payload)
    assert "source_text" not in paper
    assert "must stay local" not in packed
    assert str(structure_path) not in packed
    assert "source_text_warning" in paper


def test_prepare_task_reads_relative_paperindex_structure_under_db_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    structure_path = workspace / "artifacts" / "paper_1" / "structure.json"
    _write_existing_paperindex_structure(
        db_path,
        pages_text=["relative artifact page"],
        structure_path=structure_path,
    )
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE paper_artifacts SET path = ? WHERE paper_id = 1",
            ("artifacts/paper_1/structure.json",),
        )
        conn.commit()
    finally:
        conn.close()

    task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )

    payload = json.loads(
        (task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    assert paper["source_text"] == "relative artifact page"
    assert "source_text_warning" not in paper


def test_prepare_task_reads_cwd_relative_structure_under_db_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    structure_path = workspace / "artifacts" / "paper_1" / "structure.json"
    _write_existing_paperindex_structure(
        db_path,
        pages_text=["cwd relative artifact page"],
        structure_path=structure_path,
    )
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE paper_artifacts SET path = ? WHERE paper_id = 1",
            (structure_path.relative_to(tmp_path).as_posix(),),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.chdir(tmp_path)

    task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )

    payload = json.loads(
        (task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    assert paper["source_text"] == "cwd relative artifact page"
    assert "source_text_warning" not in paper


def test_prepare_task_omits_invalid_explicit_paperindex_text(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    _write_existing_paperindex_structure(
        db_path,
        pages_text=["valid page", {"not": "text"}],
    )

    task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )

    payload = json.loads(
        (task / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    packed = json.dumps(payload)
    assert "source_text" not in paper
    assert "valid page" not in packed
    assert "source_text_warning" in paper


def test_prepare_task_redacts_local_paths_for_all_task_types(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)

    for task_type in (
        "paper_text_extraction_batch",
        "wiki_embedding_batch",
        "retrieval_eval_sweep",
        "researchflowbench_batch_eval",
    ):
        task = prepare_task(
            task_type=task_type,
            topic="demo-topic",
            out_dir=tmp_path / task_type,
            db_path=db_path,
        )
        inputs_text = "\n".join(
            path.read_text() for path in sorted((task / "inputs").glob("*.json"))
        )

        assert "/tmp/a.pdf" not in inputs_text
        assert "/Users/example" not in inputs_text
        assert "pool.db" not in inputs_text
        assert "pdf_path" not in inputs_text


def test_prepare_task_can_include_redacted_remote_library_snapshot(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    snapshot_path = tmp_path / "remote_library_snapshot.json"
    snapshot_path.write_text(json.dumps(_remote_library_snapshot()))

    task = prepare_task(
        task_type="retrieval_eval_sweep",
        topic="demo-topic",
        out_dir=tmp_path / "retrieval-task",
        db_path=db_path,
        library_snapshot=snapshot_path,
    )

    inputs = json.loads((task / "inputs" / "retrieval_eval_inputs.json").read_text())
    external = inputs["external_corpus_snapshot"]
    assert external["schema_version"] == "remote_library_snapshot.v1"
    assert external["matched_file_count"] == 2
    assert external["samples"][0]["basename"] == "time-series-transformers.pdf"
    raw = json.dumps(inputs)
    assert "/data5" not in raw
    assert "pku" not in raw
    assert "pool.db" not in raw


def test_remote_library_snapshot_validation_rejects_path_leaks() -> None:
    validate_remote_library_snapshot(_remote_library_snapshot())

    unsafe = _remote_library_snapshot()
    unsafe["samples"] = [
        {
            "basename": "../secret.pdf",
            "extension": ".pdf",
            "size_bytes": 1,
            "relative_path_hash": "c" * 64,
            "path_depth": 1,
            "matched_terms": [],
        }
    ]
    with pytest.raises(OffloadError, match="basename"):
        validate_remote_library_snapshot(unsafe)

    unsafe_key = _remote_library_snapshot()
    unsafe_key["samples"] = [
        {
            "basename": "paper.pdf",
            "extension": ".pdf",
            "size_bytes": 1,
            "relative_path_hash": "c" * 64,
            "path_depth": 1,
            "matched_terms": [],
            "absolute_path": "/data5/private/paper.pdf",
        }
    ]
    with pytest.raises(OffloadError, match="sample fields"):
        validate_remote_library_snapshot(unsafe_key)


def test_remote_library_snapshot_accepts_redacted_bm25_statistics() -> None:
    snapshot = _remote_library_snapshot()
    snapshot["document_frequency"] = {
        "time": 2,
        "series": 2,
        "forecasting": 1,
        "anomaly": 1,
    }
    snapshot["samples"] = [
        {
            "basename": "time-series-anomaly-forecasting.pdf",
            "extension": ".pdf",
            "size_bytes": 12345,
            "relative_path_hash": "c" * 64,
            "path_depth": 2,
            "matched_terms": ["time", "series", "anomaly", "forecasting"],
            "token_counts": {
                "time": 1,
                "series": 1,
                "anomaly": 1,
                "forecasting": 1,
            },
            "token_count": 4,
        }
    ]

    validate_remote_library_snapshot(snapshot)

    raw = json.dumps(snapshot)
    assert "/data5" not in raw
    assert "pku" not in raw
    assert "abstract excerpt" not in raw


def test_remote_library_snapshot_validation_rejects_bm25_stat_leaks() -> None:
    unsafe_doc_frequency = _remote_library_snapshot()
    unsafe_doc_frequency["document_frequency"] = {"/data5/private/paper": 1}
    with pytest.raises(OffloadError, match="document_frequency"):
        validate_remote_library_snapshot(unsafe_doc_frequency)

    unsafe_token_counts = _remote_library_snapshot()
    unsafe_token_counts["samples"] = [
        {
            "basename": "paper.pdf",
            "extension": ".pdf",
            "size_bytes": 1,
            "relative_path_hash": "c" * 64,
            "path_depth": 1,
            "matched_terms": [],
            "token_counts": {"full sentence excerpt": 1},
            "token_count": 3,
        }
    ]
    with pytest.raises(OffloadError, match="token_counts"):
        validate_remote_library_snapshot(unsafe_token_counts)


def test_scan_remote_library_writes_redacted_snapshot_from_ssh(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_runner(argv: list[str]):
        calls.append(argv)
        from subprocess import CompletedProcess

        payload = {
            **_remote_library_snapshot(),
            "host_alias_hash": "",
            "library_root_hash": "",
        }
        return CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    out_path = scan_remote_library(
        host="worker",
        library_root="/remote/library",
        query="time series",
        out_path=tmp_path / "snapshot.json",
        limit=5,
        max_files=100,
        command_runner=fake_runner,
    )

    assert calls[0][:2] == ["ssh", "worker"]
    snapshot = json.loads(out_path.read_text())
    validate_remote_library_snapshot(snapshot)
    assert snapshot["host_alias_hash"] != ""
    assert snapshot["library_root_hash"] != ""
    assert snapshot["samples"][0]["basename"] == "time-series-transformers.pdf"
    raw = out_path.read_text()
    assert "/remote/library" not in raw
    assert "worker" not in raw


def test_upload_task_execute_creates_remote_layout_before_rsync(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str]):
        calls.append(argv)

    payload = upload_task(
        task_dir,
        remote_root="remote-offload-root",
        host="worker",
        execute=True,
        command_runner=fake_runner,
    )

    assert payload["status"] == "uploaded"
    assert calls[0][:2] == ["ssh", "worker"]
    assert "mkdir -p" in calls[0][2]
    assert "remote-offload-root/incoming" in calls[0][2]
    assert "remote-offload-root/runs" in calls[0][2]
    assert "remote-offload-root/results" in calls[0][2]
    assert "remote-offload-root/cache" in calls[0][2]
    assert calls[1][0] == "rsync"
    assert "--partial" in calls[1]
    assert "--checksum" in calls[1]


def test_scan_remote_library_timeout_error_does_not_leak_remote_path(
    tmp_path: Path,
) -> None:
    def timeout_runner(argv: list[str]):
        raise subprocess.TimeoutExpired(argv, 3)

    with pytest.raises(OffloadError, match="timed out after 3 seconds") as excinfo:
        scan_remote_library(
            host="worker",
            library_root="/private/remote/library",
            query="time series",
            out_path=tmp_path / "snapshot.json",
            timeout_seconds=3,
            command_runner=timeout_runner,
        )

    message = str(excinfo.value)
    assert "/private/remote/library" not in message
    assert "worker" not in message


def test_doctor_timeout_error_does_not_leak_remote_root() -> None:
    def timeout_runner(argv: list[str]):
        raise subprocess.TimeoutExpired(argv, 5)

    with pytest.raises(OffloadError, match="timed out after 5 seconds") as excinfo:
        doctor(
            host="worker",
            remote_root="/private/remote/offload-root",
            timeout_seconds=5,
            command_runner=timeout_runner,
        )

    message = str(excinfo.value)
    assert "/private/remote/offload-root" not in message
    assert "worker" not in message


def test_retrieval_eval_sweep_runner_uses_bm25_snapshot_rerank(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    db = Database(db_path)
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE papers SET title = ? WHERE id = 1",
            ("Shapelet anomaly drift forecasting for time series",),
        )
        conn.commit()
    finally:
        conn.close()

    snapshot_path = tmp_path / "remote_library_snapshot.json"
    snapshot = _remote_library_snapshot()
    snapshot["matched_file_count"] = 2
    snapshot["document_frequency"] = {
        "time": 3,
        "series": 3,
        "forecasting": 2,
        "shapelet": 1,
        "anomaly": 1,
        "drift": 1,
    }
    snapshot["samples"] = [
        {
            "basename": "time-series-forecasting-overview.pdf",
            "extension": ".pdf",
            "size_bytes": 12345,
            "relative_path_hash": "c" * 64,
            "path_depth": 2,
            "matched_terms": ["time", "series", "forecasting"],
            "token_counts": {"time": 8, "series": 8, "forecasting": 1},
            "token_count": 17,
        },
        {
            "basename": "shapelet-anomaly-drift-forecasting.pdf",
            "extension": ".pdf",
            "size_bytes": 54321,
            "relative_path_hash": "d" * 64,
            "path_depth": 2,
            "matched_terms": ["shapelet", "anomaly", "drift", "forecasting"],
            "token_counts": {
                "shapelet": 1,
                "anomaly": 1,
                "drift": 1,
                "forecasting": 1,
            },
            "token_count": 4,
        },
    ]
    snapshot_path.write_text(json.dumps(snapshot))

    task_dir = prepare_task(
        task_type="retrieval_eval_sweep",
        topic="demo-topic",
        out_dir=tmp_path / "retrieval-task",
        db_path=db_path,
        library_snapshot=snapshot_path,
    )
    uploaded = upload_task(task_dir, remote_root=tmp_path / "remote", host="worker")

    result = run_local_task(uploaded["task_id"], remote_root=tmp_path / "remote")

    assert result["status"] == "succeeded"
    result_dir = Path(result["result_path"])
    report = json.loads(
        (result_dir / "outputs" / "retrieval_eval_report.json").read_text()
    )
    predictions = [
        json.loads(line)
        for line in (result_dir / "outputs" / "predictions.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]

    assert report["method"] == "bm25_remote_snapshot_rerank"
    assert predictions[0]["top_matches"][0]["basename"] == (
        "shapelet-anomaly-drift-forecasting.pdf"
    )
    assert predictions[0]["top_matches"][0]["relative_path_hash"] == "d" * 64
    raw = json.dumps({"report": report, "predictions": predictions})
    assert "/data5" not in raw
    assert "pku" not in raw


def test_retrieval_eval_sweep_runner_uses_explicit_fake_rerank_policy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    snapshot_path = tmp_path / "remote_library_snapshot.json"
    snapshot = _remote_library_snapshot()
    snapshot["samples"] = [
        {
            "basename": "forecasting-transformer.pdf",
            "extension": ".pdf",
            "size_bytes": 12345,
            "relative_path_hash": "e" * 64,
            "path_depth": 2,
            "matched_terms": ["forecasting", "transformer"],
            "token_counts": {"forecasting": 2, "transformer": 2},
            "token_count": 4,
        }
    ]
    snapshot_path.write_text(json.dumps(snapshot))

    task_dir = prepare_task(
        task_type="retrieval_eval_sweep",
        topic="demo-topic",
        out_dir=tmp_path / "retrieval-task",
        db_path=db_path,
        library_snapshot=snapshot_path,
        model_policy={
            "backend": "fake_model",
            "model_id": "generic-local-reranker",
            "device": "cpu",
            "cache_policy": {
                "max_gb": 1,
                "cleanup": "manual",
                "cache_root": "cache/",
            },
        },
    )
    payload = json.loads(
        (task_dir / "inputs" / "retrieval_eval_inputs.json").read_text()
    )
    assert payload["model_policy"]["backend"] == "fake_model"
    uploaded = upload_task(task_dir, remote_root=tmp_path / "remote", host="worker")

    result = run_local_task(uploaded["task_id"], remote_root=tmp_path / "remote")

    assert result["status"] == "succeeded"
    result_dir = Path(result["result_path"])
    report = json.loads(
        (result_dir / "outputs" / "retrieval_eval_report.json").read_text()
    )
    predictions = [
        json.loads(line)
        for line in (result_dir / "outputs" / "predictions.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]
    assert report["method"] == "fake_model_snapshot_rerank_v1"
    assert report["model_policy"]["model_id"] == "generic-local-reranker"
    assert "quality claim" in report["note"]
    assert predictions[0]["method"] == "fake_model_snapshot_rerank_v1"
    assert predictions[0]["top_matches"][0]["relative_path_hash"] == "e" * 64


def test_prepare_task_rejects_unsupported_model_policy(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)

    with pytest.raises(OffloadError, match="unsupported model_policy backend"):
        prepare_task(
            task_type="wiki_embedding_batch",
            topic="demo-topic",
            out_dir=tmp_path / "bad-backend",
            db_path=db_path,
            model_policy={"backend": "auto_download_model", "model_id": "bad"},
        )

    with pytest.raises(OffloadError, match="cache_policy is invalid"):
        prepare_task(
            task_type="retrieval_eval_sweep",
            topic="demo-topic",
            out_dir=tmp_path / "bad-cache",
            db_path=db_path,
            model_policy={
                "backend": "fake_model",
                "model_id": "generic-local-reranker",
                "cache_policy": {"cleanup": "automatic"},
            },
        )


def test_retrieval_eval_sweep_runner_succeeds_with_remote_library_snapshot(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    snapshot_path = tmp_path / "remote_library_snapshot.json"
    snapshot = _remote_library_snapshot()
    snapshot["samples"] = [
        {
            "basename": "a-paper-time-series-forecasting.pdf",
            "extension": ".pdf",
            "size_bytes": 12345,
            "relative_path_hash": "c" * 64,
            "path_depth": 2,
            "matched_terms": ["time", "series", "forecasting"],
        }
    ]
    snapshot_path.write_text(json.dumps(snapshot))
    task_dir = prepare_task(
        task_type="retrieval_eval_sweep",
        topic="demo-topic",
        out_dir=tmp_path / "retrieval-task",
        db_path=db_path,
        library_snapshot=snapshot_path,
    )
    uploaded = upload_task(task_dir, remote_root=tmp_path / "remote", host="worker")

    result = run_local_task(uploaded["task_id"], remote_root=tmp_path / "remote")

    assert result["status"] == "succeeded"
    result_dir = Path(result["result_path"])
    report = json.loads(
        (result_dir / "outputs" / "retrieval_eval_report.json").read_text()
    )
    predictions = [
        json.loads(line)
        for line in (result_dir / "outputs" / "predictions.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]
    assert report["status"] == "succeeded"
    assert report["method"] == "bm25_remote_snapshot_rerank"
    assert report["external_corpus_snapshot"]["present"] is True
    assert report["external_corpus_snapshot"]["matched_file_count"] == 2
    assert predictions[0]["status"] == "ranked"
    assert predictions[0]["top_matches"][0]["basename"] == (
        "a-paper-time-series-forecasting.pdf"
    )
    assert predictions[0]["top_matches"][0]["relative_path_hash"] == "c" * 64
    raw = json.dumps({"report": report, "predictions": predictions})
    assert "/data5" not in raw
    assert "pku" not in raw


def test_manifest_validation_rejects_unsafe_paths_and_statuses() -> None:
    valid = {
        "task_id": "paper_text_extraction_batch-20260619T000000Z-demo",
        "task_type": "paper_text_extraction_batch",
        "created_at": "2026-06-19T00:00:00Z",
        "topic": "demo-topic",
        "status": "prepared",
        "input_hashes": {"inputs/papers.json": "a" * 64},
        "expected_outputs": ["outputs/text.jsonl"],
        "resource_hint": {"cpu": 4},
        "timeout": 3600,
        "cleanup_policy": {"cache_max_gb": 50},
    }
    validate_task_manifest(valid)

    unsafe = dict(valid)
    unsafe["expected_outputs"] = ["../escape.json"]
    with pytest.raises(OffloadError, match="unsafe path"):
        validate_task_manifest(unsafe)

    bad_status = dict(valid)
    bad_status["status"] = "done"
    with pytest.raises(OffloadError, match="status"):
        validate_task_manifest(bad_status)

    bad_task_id = dict(valid)
    bad_task_id["task_id"] = "../escape"
    with pytest.raises(OffloadError, match="task_id"):
        validate_task_manifest(bad_task_id)


def test_result_manifest_validation_rejects_untrusted_metadata() -> None:
    valid = {
        "task_id": "paper_text_extraction_batch-20260619T000000Z-demo",
        "task_type": "paper_text_extraction_batch",
        "status": "failed",
        "started_at": "2026-06-19T00:00:00Z",
        "finished_at": "2026-06-19T00:01:00Z",
        "exit_code": 1,
        "output_hashes": {},
        "warnings": ["runner failed"],
        "server_hostname": "worker",
        "git_commit": "abcdef0",
    }
    from research_harness.offload import validate_result_manifest

    validate_result_manifest(valid)

    bad_task_id = dict(valid, task_id="../escape")
    with pytest.raises(OffloadError, match="task_id"):
        validate_result_manifest(bad_task_id)

    bad_warning = dict(valid, warnings=["x" * 2001])
    with pytest.raises(OffloadError, match="warnings"):
        validate_result_manifest(bad_warning)

    bad_hostname = dict(valid, server_hostname="x" * 256)
    with pytest.raises(OffloadError, match="server_hostname"):
        validate_result_manifest(bad_hostname)

    bad_commit = dict(valid, git_commit={"sha": "abcdef0"})
    with pytest.raises(OffloadError, match="git_commit"):
        validate_result_manifest(bad_commit)


def test_status_transition_validation() -> None:
    validate_status_transition("prepared", "uploaded")
    validate_status_transition("running", "succeeded")
    validate_status_transition("partial", "failed")

    with pytest.raises(OffloadError, match="invalid status transition"):
        validate_status_transition("succeeded", "running")


def test_host_alias_validation_requires_explicit_safe_host() -> None:
    assert validate_host_alias("worker") == "worker"
    assert validate_host_alias("user@worker.example") == "user@worker.example"

    for host in (None, "", " worker", "-oProxyCommand=bad", "worker;bad"):
        with pytest.raises(OffloadError, match="host|unsafe"):
            validate_host_alias(host)


def test_upload_and_fetch_are_idempotent_with_fake_remote(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "task",
        db_path=db_path,
    )
    remote_root = tmp_path / "remote"

    first_upload = upload_task(task_dir, remote_root=remote_root)
    second_upload = upload_task(task_dir, remote_root=remote_root)
    assert first_upload["remote_path"] == second_upload["remote_path"]
    assert (remote_root / "incoming" / first_upload["task_id"] / "runner.sh").exists()

    remote_result = _write_result(remote_root / "incoming" / first_upload["task_id"])
    fetched_once = fetch_task(
        first_upload["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )
    fetched_twice = fetch_task(
        first_upload["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )

    assert fetched_once == fetched_twice
    assert (
        tmp_path / "fetched" / first_upload["task_id"] / "result_manifest.json"
    ).exists()
    assert validate_result_package(remote_result)["status"] == "succeeded"


def test_multi_task_fake_remote_scale_lifecycle_imports_without_duplicates(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    _write_existing_paperindex_structure(db_path)
    snapshot_path = tmp_path / "remote_library_snapshot.json"
    snapshot = _remote_library_snapshot()
    snapshot["samples"] = [
        {
            "basename": "time-series-forecasting-transformer.pdf",
            "extension": ".pdf",
            "size_bytes": 12345,
            "relative_path_hash": "d" * 64,
            "path_depth": 2,
            "matched_terms": ["time", "series", "forecasting"],
        }
    ]
    snapshot_path.write_text(json.dumps(snapshot))
    task_dirs = [
        prepare_task(
            task_type="paper_text_extraction_batch",
            topic="demo-topic",
            out_dir=tmp_path / "local" / "paper-task",
            db_path=db_path,
        ),
        prepare_task(
            task_type="wiki_embedding_batch",
            topic="demo-topic",
            out_dir=tmp_path / "local" / "wiki-task",
            db_path=db_path,
        ),
        prepare_task(
            task_type="retrieval_eval_sweep",
            topic="demo-topic",
            out_dir=tmp_path / "local" / "retrieval-task",
            db_path=db_path,
            library_snapshot=snapshot_path,
        ),
    ]
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "DELETE FROM paper_artifacts WHERE artifact_type = 'paperindex_structure'"
        )
        conn.commit()
    finally:
        conn.close()
    remote_root = tmp_path / "remote"
    local_root = tmp_path / "fetched"

    imported = []
    for task_dir in task_dirs:
        uploaded_once = upload_task(task_dir, remote_root=remote_root)
        uploaded_twice = upload_task(task_dir, remote_root=remote_root)
        assert uploaded_once["remote_path"] == uploaded_twice["remote_path"]
        run_payload = run_local_task(uploaded_once["task_id"], remote_root=remote_root)
        assert run_payload["status"] == "succeeded"
        fetched_once = fetch_task(
            uploaded_once["task_id"],
            local_root=local_root,
            remote_root=remote_root,
        )
        fetched_twice = fetch_task(
            uploaded_once["task_id"],
            local_root=local_root,
            remote_root=remote_root,
        )
        assert fetched_once == fetched_twice
        imported.append(
            import_task_result(
                fetched_once["local_path"],
                db_path=db_path,
                topic="demo-topic",
            )
        )
        imported.append(
            import_task_result(
                fetched_once["local_path"],
                db_path=db_path,
                topic="demo-topic",
            )
        )

    assert [item["status"] for item in imported] == ["succeeded"] * 6
    conn = Database(db_path).connect()
    try:
        paper_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_artifacts
            WHERE artifact_type = 'paperindex_structure'
              AND metadata LIKE '%remote_offload%'
            """
        ).fetchone()[0]
        wiki_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_wiki_embedding_index'
            """
        ).fetchone()[0]
        retrieval_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_retrieval_eval_result'
            """
        ).fetchone()[0]
        receipt_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_offload_result'
            """
        ).fetchone()[0]
        assert paper_count == 1
        assert wiki_count == 1
        assert retrieval_count == 1
        assert receipt_count == 6
    finally:
        conn.close()


def test_corrupt_result_manifest_rejects_fetch_and_preserves_remote_result(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)
    run_local_task(uploaded["task_id"], remote_root=remote_root)
    remote_result = remote_root / "results" / uploaded["task_id"]
    manifest_path = remote_result / "result_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_hashes"]["wiki_embeddings.jsonl"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    with pytest.raises(OffloadError, match="output_hashes"):
        fetch_task(
            uploaded["task_id"],
            local_root=tmp_path / "fetched",
            remote_root=remote_root,
        )

    assert remote_result.is_dir()
    assert manifest_path.is_file()


def test_wiki_embedding_many_artifacts_scale_imports_one_candidate_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    _seed_wiki_context_artifacts(db_path, count=24)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "wiki-task",
        db_path=db_path,
    )
    payload = json.loads(
        (task_dir / "inputs" / "wiki_embedding_inputs.json").read_text()
    )
    assert len(payload["artifacts"]) == 24
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    assert run_payload["status"] == "succeeded"
    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )
    imported = import_task_result(
        fetched["local_path"],
        db_path=db_path,
        topic="demo-topic",
    )
    assert imported["deep_result_imports"]["imported"] == 1
    conn = Database(db_path).connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE artifact_type = 'remote_wiki_embedding_index'
            """
        ).fetchone()
        payload = json.loads(row["payload_json"])
        assert payload["embedding_summary"]["row_count"] == 24
        assert payload["embedding_summary"]["succeeded_count"] == 24
        assert len(payload["source_links"]) == 24
    finally:
        conn.close()


def test_offload_lifecycle_writes_local_receipts(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "task",
        db_path=db_path,
    )
    task_receipt = _read_receipt(task_dir)
    assert task_receipt["schema_version"] == "remote_offload_receipt.v1"
    assert [item["operation"] for item in task_receipt["attempts"]] == ["prepare"]

    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root, host="worker")
    task_receipt = _read_receipt(task_dir)
    assert [item["operation"] for item in task_receipt["attempts"]] == [
        "prepare",
        "upload",
    ]
    assert task_receipt["attempts"][-1]["host_configured"] is True
    assert task_receipt["attempts"][-1]["remote_layout"] == (
        f"incoming/{uploaded['task_id']}"
    )

    run_local_task(uploaded["task_id"], remote_root=remote_root)
    result_receipt = _read_receipt(remote_root / "results" / uploaded["task_id"])
    assert [item["operation"] for item in result_receipt["attempts"]] == ["run_local"]
    assert result_receipt["attempts"][-1]["status"] == "partial"

    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
        host="worker",
    )
    fetched_receipt = _read_receipt(Path(fetched["local_path"]))
    assert [item["operation"] for item in fetched_receipt["attempts"]] == [
        "run_local",
        "fetch",
    ]

    imported = import_task_result(
        fetched["local_path"],
        db_path=db_path,
        topic="demo-topic",
    )
    imported_receipt = _read_receipt(Path(fetched["local_path"]))
    assert [item["operation"] for item in imported_receipt["attempts"]] == [
        "run_local",
        "fetch",
        "import",
    ]
    assert imported_receipt["attempts"][-1]["artifact_id"] == imported["artifact_id"]


def test_create_batch_plan_is_local_only_and_aggregates_status(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_a = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-a",
        db_path=db_path,
    )
    task_b = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-b",
        db_path=db_path,
    )
    uploaded = upload_task(task_a, remote_root=tmp_path / "remote", host="worker")
    run_local_task(uploaded["task_id"], remote_root=tmp_path / "remote")
    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "results",
        remote_root=tmp_path / "remote",
        host="worker",
    )

    plan_path = create_batch_plan(
        [task_a, task_b, Path(fetched["local_path"])],
        out_path=tmp_path / "batch" / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=2,
    )
    plan = json.loads(plan_path.read_text())

    assert plan["schema_version"] == "remote_offload_batch_plan.v1"
    assert plan["concurrency"] == 2
    assert plan["remote_root"] == "remote-offload-root"
    assert [item["kind"] for item in plan["items"]] == ["task", "task", "result"]
    assert [item["status"] for item in plan["items"]] == [
        "prepared",
        "prepared",
        "partial",
    ]
    assert all(
        "ssh " in item["commands"]["run"]
        for item in plan["items"]
        if item["kind"] == "task"
    )
    assert all(not Path(item["path"]).is_absolute() for item in plan["items"])

    status = status_batch_plan(plan_path)
    assert status["total"] == 3
    assert status["by_status"]["prepared"] == 2
    assert status["by_status"]["partial"] == 1
    assert status["ready_to_upload"] == 2
    assert status["ready_to_import"] == 1


def test_create_batch_plan_rejects_invalid_concurrency_and_missing_items(
    tmp_path: Path,
) -> None:
    with pytest.raises(OffloadError, match="concurrency"):
        create_batch_plan(
            [],
            out_path=tmp_path / "plan.json",
            host="worker",
            remote_root="remote-offload-root",
            concurrency=0,
        )
    with pytest.raises(OffloadError, match="at least one item"):
        create_batch_plan(
            [],
            out_path=tmp_path / "plan.json",
            host="worker",
            remote_root="remote-offload-root",
            concurrency=1,
        )
    with pytest.raises(OffloadError, match="no offload manifest"):
        create_batch_plan(
            [tmp_path / "missing"],
            out_path=tmp_path / "plan.json",
            host="worker",
            remote_root="remote-offload-root",
            concurrency=1,
        )


def test_reconcile_batch_plan_reports_drift_and_resume_buckets(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_a = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-a",
        db_path=db_path,
    )
    task_b = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-b",
        db_path=db_path,
    )
    uploaded = upload_task(task_a, remote_root=tmp_path / "remote", host="worker")
    run_local_task(uploaded["task_id"], remote_root=tmp_path / "remote")
    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "results",
        remote_root=tmp_path / "remote",
        host="worker",
    )
    plan_path = create_batch_plan(
        [task_a, task_b, Path(fetched["local_path"])],
        out_path=tmp_path / "batch" / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=2,
    )

    shutil.rmtree(task_b)
    result_path = Path(fetched["local_path"])
    manifest_path = result_path / "result_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "failed"
    manifest["exit_code"] = 1
    manifest_path.write_text(json.dumps(manifest))

    reconciled = reconcile_batch_plan(plan_path)

    assert reconciled["total"] == 3
    assert reconciled["drift_count"] == 2
    assert reconciled["missing_count"] == 1
    assert reconciled["invalid_count"] == 0
    assert reconciled["resume"]["ready_to_upload"] == [uploaded["task_id"]]
    assert reconciled["resume"]["ready_to_import"] == []
    assert reconciled["resume"]["manual_remote_action"] == [uploaded["task_id"]]
    assert reconciled["resume"]["missing"] == [
        json.loads((plan_path).read_text())["items"][1]["task_id"]
    ]
    result_item = reconciled["items"][2]
    assert result_item["plan_status"] == "partial"
    assert result_item["actual_status"] == "failed"
    assert result_item["drift"] is True


def test_status_payload_prefers_result_manifest_when_result_contains_task_manifest(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    result_dir = _write_result(task_dir, status="succeeded")

    payload = status_payload(str(result_dir))

    assert payload["kind"] == "result"
    assert payload["status"] == "succeeded"
    assert payload["output_count"] == 2


def test_reconcile_batch_plan_reports_invalid_package(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    uploaded = upload_task(task_dir, remote_root=tmp_path / "remote", host="worker")
    run_local_task(uploaded["task_id"], remote_root=tmp_path / "remote")
    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "results",
        remote_root=tmp_path / "remote",
        host="worker",
    )
    plan_path = create_batch_plan(
        [Path(fetched["local_path"])],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )
    (Path(fetched["local_path"]) / "logs" / "stdout.log").unlink()

    reconciled = reconcile_batch_plan(plan_path)

    assert reconciled["invalid_count"] == 1
    assert reconciled["items"][0]["actual_kind"] == "invalid"
    assert "stdout.log" in reconciled["items"][0]["error"]
    assert reconciled["resume"]["invalid"] == [uploaded["task_id"]]


def test_offload_queue_create_status_and_local_upload_step(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    queue_path = create_offload_queue(
        [task_dir],
        out_path=tmp_path / "queue" / "offload_queue.json",
        host="worker",
        remote_root=tmp_path / "remote",
    )

    status = status_offload_queue(queue_path)
    assert status["schema_version"] == "remote_offload_queue.v1"
    assert status["total"] == 1
    assert status["by_next_action"] == {"upload": 1}
    assert status["by_queue_status"] == {"queued": 1}

    stepped = run_offload_queue_once(queue_path, local_copy=True)

    assert stepped["task_id"] == load_task_manifest(task_dir)["task_id"]
    assert stepped["action"] == "upload"
    assert stepped["status"] == "uploaded"
    updated = json.loads(queue_path.read_text())
    item = updated["items"][0]
    assert item["queue_status"] == "waiting_remote_run"
    assert item["next_action"] == "fetch"
    assert len(item["attempts"]) == 1
    assert item["attempts"][0]["action"] == "upload"
    assert (tmp_path / "remote" / "incoming" / item["task_id"]).is_dir()


def test_offload_queue_retries_fetch_without_destroying_uploaded_task(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    queue_path = create_offload_queue(
        [task_dir],
        out_path=tmp_path / "queue.json",
        host="worker",
        remote_root=tmp_path / "remote",
        local_root=tmp_path / "local-results",
    )
    run_offload_queue_once(queue_path, local_copy=True)

    failed_fetch = run_offload_queue_once(queue_path, local_copy=True)

    assert failed_fetch["action"] == "fetch"
    assert failed_fetch["status"] == "retryable_error"
    queue = json.loads(queue_path.read_text())
    item = queue["items"][0]
    assert item["queue_status"] == "retryable_error"
    assert item["next_action"] == "fetch"
    assert len(item["attempts"]) == 2
    assert item["attempts"][-1]["success"] is False
    assert (tmp_path / "remote" / "incoming" / item["task_id"]).is_dir()


def test_offload_queue_identifies_result_import_action(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    result_dir = _write_result(task_dir, status="partial")

    queue_path = create_offload_queue(
        [result_dir],
        out_path=tmp_path / "queue.json",
        host="worker",
        remote_root="remote-offload-root",
    )

    payload = status_offload_queue(queue_path)
    assert payload["by_next_action"] == {"import": 1}
    item = payload["items"][0]
    assert item["kind"] == "result"
    assert item["queue_status"] == "queued"
    assert item["next_action"] == "import"


def test_preflight_batch_plan_blocks_unsupported_task_type_and_gpu_mismatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    paper_task = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "paper-task",
        db_path=db_path,
    )
    gpu_task = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "gpu-task",
        db_path=db_path,
    )
    plan_path = create_batch_plan(
        [paper_task, gpu_task],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )

    preflight = preflight_batch_plan(
        plan_path,
        capabilities={
            "schema_version": "rh_offload_worker_capabilities.v1",
            "supported_task_types": ["paper_text_extraction_batch"],
            "resources": {"gpu": False, "cpu": 8, "memory_gb": 32},
        },
    )

    assert preflight["total"] == 2
    assert preflight["allowed_count"] == 1
    assert preflight["blocked_count"] == 1
    blocked = [item for item in preflight["items"] if not item["allowed"]]
    assert (
        blocked[0]["task_id"]
        == json.loads((gpu_task / "task_manifest.json").read_text())["task_id"]
    )
    assert {"unsupported_task_type", "gpu_required_unavailable"}.issubset(
        set(blocked[0]["reasons"])
    )


def test_preflight_batch_plan_without_capabilities_warns_but_allows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    plan_path = create_batch_plan(
        [task_dir],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )

    preflight = preflight_batch_plan(plan_path)

    assert preflight["allowed_count"] == 1
    assert preflight["blocked_count"] == 0
    assert preflight["warning_count"] == 1
    assert preflight["items"][0]["warnings"] == ["worker_capabilities_not_provided"]


def test_preflight_batch_plan_blocks_pdf_pack_when_no_pdf_parser(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "workspace" / "pool.db"
    _seed_topic(db_path)
    pdf_path = db_path.parent / "papers" / "paper-1.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_bytes = b"%PDF-1.4\n% test pdf bytes\n%%EOF\n"
    pdf_path.write_bytes(pdf_bytes)
    with Database(db_path).connect() as conn:
        conn.execute(
            "UPDATE papers SET pdf_path = ?, pdf_hash = ? WHERE id = 1",
            (str(pdf_path), hashlib.sha256(pdf_bytes).hexdigest()),
        )
        conn.commit()
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "pdf-task",
        db_path=db_path,
        include_pdf_files=True,
    )
    plan_path = create_batch_plan(
        [task_dir],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )

    preflight = preflight_batch_plan(
        plan_path,
        capabilities={
            "schema_version": "rh_offload_worker_capabilities.v1",
            "supported_task_types": ["paper_text_extraction_batch"],
            "resources": {"gpu": False, "cpu": 8, "memory_gb": 32},
            "features": {"pdf_parsers": []},
            "cache_policy": {"max_gb": 50, "cleanup": "manual"},
        },
    )

    item = preflight["items"][0]
    assert item["allowed"] is False
    assert item["pdf_input_count"] == 1
    assert "pdf_parser_unavailable" in item["reasons"]


def test_preflight_batch_plan_blocks_model_task_without_model_and_cache_policy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    plan_path = create_batch_plan(
        [task_dir],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )

    preflight = preflight_batch_plan(
        plan_path,
        capabilities={
            "schema_version": "rh_offload_worker_capabilities.v1",
            "supported_task_types": ["wiki_embedding_batch"],
            "resources": {"gpu": True, "cpu": 8, "memory_gb": 64},
            "features": {"embedding": {"backends": []}},
        },
    )

    item = preflight["items"][0]
    assert item["allowed"] is False
    assert item["model_policy"]["required"] is True
    assert item["model_policy"]["capability"] == "embedding"
    assert item["model_policy"]["available"] is False
    assert item["model_policy"]["backends"] == []
    assert {
        "model_capability_not_declared",
        "cache_policy_missing",
    }.issubset(set(item["reasons"]))


def test_preflight_batch_plan_blocks_invalid_cache_policy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    plan_path = create_batch_plan(
        [task_dir],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )

    preflight = preflight_batch_plan(
        plan_path,
        capabilities={
            "schema_version": "rh_offload_worker_capabilities.v1",
            "supported_task_types": ["wiki_embedding_batch"],
            "resources": {"gpu": True, "cpu": 8, "memory_gb": 64},
            "features": {
                "embedding": {
                    "backends": ["sentence-transformers"],
                    "models": ["generic-local-model"],
                }
            },
            "cache_policy": {
                "max_gb": 50,
                "cleanup": "automatic",
                "cache_root": "cache/",
            },
        },
    )

    item = preflight["items"][0]
    assert item["allowed"] is False
    assert item["model_policy"]["available"] is True
    assert "cache_policy_invalid" in item["reasons"]


def test_preflight_batch_plan_allows_model_task_with_declared_cache_policy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    plan_path = create_batch_plan(
        [task_dir],
        out_path=tmp_path / "batch_plan.json",
        host="worker",
        remote_root="remote-offload-root",
        concurrency=1,
    )

    preflight = preflight_batch_plan(
        plan_path,
        capabilities={
            "schema_version": "rh_offload_worker_capabilities.v1",
            "supported_task_types": ["wiki_embedding_batch"],
            "resources": {"gpu": True, "cpu": 8, "memory_gb": 64},
            "features": {
                "embedding": {
                    "backends": ["sentence-transformers"],
                    "models": ["generic-local-model"],
                    "default_device": "cuda",
                }
            },
            "cache_policy": {
                "max_gb": 100,
                "cleanup": "manual",
                "cache_root": "cache/",
            },
        },
    )

    item = preflight["items"][0]
    assert preflight["blocked_count"] == 0
    assert item["allowed"] is True
    assert item["model_policy"]["available"] is True
    assert item["cache_policy"]["cleanup"] == "manual"


def test_remote_status_summarizes_fake_remote_root(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    remote_root = tmp_path / "remote-root"
    upload_task(task_dir, remote_root=remote_root, execute=False)
    result_dir = run_local_task(
        load_task_manifest(task_dir)["task_id"],
        remote_root=remote_root,
    )["result_path"]

    payload = remote_status(remote_root=remote_root)

    assert payload["remote_root"] == remote_root.as_posix()
    assert payload["read_only"] is True
    assert payload["total_size_bytes"] > 0
    assert payload["sections"]["incoming"]["count"] == 1
    assert payload["sections"]["runs"]["count"] == 1
    assert payload["sections"]["results"]["count"] == 1
    assert payload["sections"]["cache"]["count"] == 0
    result_item = payload["sections"]["results"]["items"][0]
    assert result_item["task_id"] == load_task_manifest(task_dir)["task_id"]
    assert result_item["status"] in {"partial", "succeeded"}
    assert result_item["path"] == f"results/{result_item['task_id']}"
    assert str(tmp_path) not in json.dumps(result_item)
    assert Path(result_dir).is_dir()


def test_remote_cleanup_is_dry_run_by_default_and_deletes_explicit_task(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task",
        db_path=db_path,
    )
    task_id = load_task_manifest(task_dir)["task_id"]
    remote_root = tmp_path / "remote-root"
    upload_task(task_dir, remote_root=remote_root, execute=False)
    run_local_task(task_id, remote_root=remote_root)

    dry_run = remote_cleanup(remote_root=remote_root, task_ids=[task_id])

    assert dry_run["dry_run"] is True
    assert dry_run["deleted_count"] == 0
    assert {item["section"] for item in dry_run["candidates"]} == {
        "incoming",
        "runs",
        "results",
    }
    assert (remote_root / "incoming" / task_id).is_dir()

    executed = remote_cleanup(
        remote_root=remote_root,
        task_ids=[task_id],
        dry_run=False,
    )

    assert executed["dry_run"] is False
    assert executed["deleted_count"] == 3
    assert not (remote_root / "incoming" / task_id).exists()
    assert not (remote_root / "runs" / task_id).exists()
    assert not (remote_root / "results" / task_id).exists()
    assert (remote_root / "cache").exists() is False


def test_remote_cleanup_requires_filter_and_rejects_unsafe_ids(
    tmp_path: Path,
) -> None:
    remote_root = tmp_path / "remote-root"
    remote_root.mkdir()

    with pytest.raises(OffloadError, match="cleanup requires"):
        remote_cleanup(remote_root=remote_root)

    with pytest.raises(OffloadError, match="unsafe task_id"):
        remote_cleanup(remote_root=remote_root, task_ids=["../escape"])


def test_run_local_task_executes_contract_runner_and_imports_partial(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "task",
        db_path=db_path,
    )
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    result_manifest = validate_result_package(result_dir)
    assert run_payload["status"] == "partial"
    assert result_manifest["status"] == "partial"
    assert result_manifest["exit_code"] == 0
    assert sorted(result_manifest["output_hashes"]) == [
        "paper_text_extraction_results.jsonl",
        "summary.json",
    ]
    summary = json.loads((result_dir / "outputs" / "summary.json").read_text())
    assert summary["schema_version"] == "remote_offload_contract_output.v1"
    assert summary["task_type"] == "paper_text_extraction_batch"

    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )
    imported = import_task_result(
        fetched["local_path"],
        db_path=db_path,
        topic="demo-topic",
    )
    assert imported["artifact_type"] == "remote_offload_diagnostic"


def test_run_local_task_extracts_explicit_paper_text_and_imports_structure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    existing_structure = _write_existing_paperindex_structure(
        db_path,
        pages_text=["remote first page", "remote second page"],
    )
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "task",
        db_path=db_path,
    )
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "DELETE FROM paper_artifacts WHERE artifact_type = 'paperindex_structure'"
        )
        conn.commit()
    finally:
        conn.close()
    existing_structure.unlink()
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    result_manifest = validate_result_package(result_dir)
    assert run_payload["status"] == "succeeded"
    assert result_manifest["status"] == "succeeded"
    rows = [
        json.loads(line)
        for line in (result_dir / "outputs" / "paper_text_extraction_results.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows == [
        {
            "doc_name": "A paper",
            "page_count": 2,
            "pages_text": ["remote first page", "remote second page"],
            "paper_id": 1,
            "parser": "explicit_text_pack_v1",
            "pdf_hash": "hash-a",
            "source_text_sha256": hashlib.sha256(
                "remote first page\n\nremote second page".encode("utf-8")
            ).hexdigest(),
            "status": "succeeded",
            "structure": [],
        }
    ]

    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )
    imported = import_task_result(
        fetched["local_path"],
        db_path=db_path,
        topic="demo-topic",
    )
    assert imported["artifact_type"] == "remote_offload_result"
    assert imported["paper_artifact_imports"]["imported"] == 1
    conn = Database(db_path).connect()
    try:
        artifact = conn.execute(
            """
            SELECT path
            FROM paper_artifacts
            WHERE paper_id = 1 AND artifact_type = 'paperindex_structure'
            """
        ).fetchone()
        structure = json.loads(Path(artifact["path"]).read_text())
        assert structure["raw"]["parser"] == "explicit_text_pack_v1"
        assert structure["raw"]["pages_text"] == [
            "remote first page",
            "remote second page",
        ]
    finally:
        conn.close()


def test_run_local_task_extracts_packaged_pdf_and_imports_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # runner.sh invokes whatever ``python3`` is first on PATH (the remote's
    # interpreter). Pin it to the interpreter running the suite, which has the
    # declared pypdf/PyPDF2 dependency, so an un-activated venv or a bare
    # system python3 does not silently turn this into a parser-missing run.
    interpreter_bin = tmp_path / "interpreter-bin"
    interpreter_bin.mkdir()
    shim = interpreter_bin / "python3"
    shim.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{interpreter_bin}:{os.environ.get('PATH', '')}")
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    pdf_path = workspace / "papers" / "paper-1.pdf"
    _write_minimal_text_pdf(pdf_path, "remote offload pdf text page")
    pdf_hash = compute_file_hashes(pdf_path)["paper-1.pdf"]
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ?, pdf_hash = ? WHERE id = 1",
            (str(pdf_path), pdf_hash),
        )
        conn.commit()
    finally:
        conn.close()
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "pdf-task",
        db_path=db_path,
        include_pdf_files=True,
    )
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    result_manifest = validate_result_package(result_dir)
    assert run_payload["status"] == "succeeded"
    assert result_manifest["status"] == "succeeded"
    rows = [
        json.loads(line)
        for line in (result_dir / "outputs" / "paper_text_extraction_results.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows[0]["parser"] == "explicit_pdf_pack_pypdf_v1"
    assert rows[0]["pdf_hash"] == pdf_hash
    assert rows[0]["pages_text"] == ["remote offload pdf text page"]

    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )
    imported = import_task_result(
        fetched["local_path"],
        db_path=db_path,
        topic="demo-topic",
    )
    assert imported["artifact_type"] == "remote_offload_result"
    assert imported["paper_artifact_imports"]["imported"] == 1
    conn = Database(db_path).connect()
    try:
        artifact = conn.execute(
            """
            SELECT path
            FROM paper_artifacts
            WHERE paper_id = 1 AND artifact_type = 'paperindex_structure'
            """
        ).fetchone()
        structure = json.loads(Path(artifact["path"]).read_text())
        assert structure["raw"]["parser"] == "explicit_pdf_pack_pypdf_v1"
        assert structure["raw"]["pages_text"] == ["remote offload pdf text page"]
    finally:
        conn.close()


def test_run_local_task_extracts_packaged_pdf_with_pdftotext_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "pool.db"
    _seed_topic(db_path)
    pdf_path = workspace / "papers" / "paper-1.pdf"
    _write_minimal_text_pdf(pdf_path, "ignored by fake pdftotext")
    pdf_hash = compute_file_hashes(pdf_path)["paper-1.pdf"]
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ?, pdf_hash = ? WHERE id = 1",
            (str(pdf_path), pdf_hash),
        )
        conn.commit()
    finally:
        conn.close()
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_pdftotext = fake_bin / "pdftotext"
    fake_pdftotext.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "printf 'fallback page one\\f fallback page two\\n'",
            ]
        )
        + "\n"
    )
    fake_pdftotext.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("RH_OFFLOAD_DISABLE_PYTHON_PDF", "1")
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "pdf-task",
        db_path=db_path,
        include_pdf_files=True,
    )
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    assert run_payload["status"] == "succeeded"
    rows = [
        json.loads(line)
        for line in (result_dir / "outputs" / "paper_text_extraction_results.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows[0]["parser"] == "explicit_pdf_pack_pdftotext_v1"
    assert rows[0]["pages_text"] == ["fallback page one", "fallback page two"]


def test_run_local_task_embeds_wiki_context_text_and_imports_result(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "wiki-task",
        db_path=db_path,
    )
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    result_manifest = validate_result_package(result_dir)
    assert run_payload["status"] == "succeeded"
    assert result_manifest["status"] == "succeeded"
    assert sorted(result_manifest["output_hashes"]) == [
        "summary.json",
        "wiki_embeddings.jsonl",
    ]
    rows = [
        json.loads(line)
        for line in (result_dir / "outputs" / "wiki_embeddings.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["artifact_id"] == 1
    assert row["status"] == "succeeded"
    assert row["method"] == "deterministic_hash_embedding_v1"
    assert row["embedding_dim"] == 16
    assert len(row["embedding"]) == 16
    assert all(isinstance(value, float) for value in row["embedding"])
    assert (
        row["embedding_text_sha256"]
        == hashlib.sha256(
            "time series wiki summary\n\nForecasting\n\nseasonal transformer evidence".encode(
                "utf-8"
            )
        ).hexdigest()
    )
    summary = json.loads((result_dir / "outputs" / "summary.json").read_text())
    assert summary["schema_version"] == "remote_offload_contract_output.v1"
    assert summary["wiki_embedding_schema_version"] == "wiki_embedding_batch.summary.v1"
    assert summary["succeeded_count"] == 1

    fetched = fetch_task(
        uploaded["task_id"],
        local_root=tmp_path / "fetched",
        remote_root=remote_root,
    )
    imported = import_task_result(
        fetched["local_path"],
        db_path=db_path,
        topic="demo-topic",
    )
    assert imported["artifact_type"] == "remote_offload_result"


def test_run_local_task_wiki_embedding_without_safe_text_is_partial(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    conn = Database(db_path).connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?
            WHERE artifact_type = 'wiki_context_pack'
            """,
            (
                json.dumps(
                    {
                        "secret_path": "/Users/example/private/source.txt",
                        "url": "https://example.test/private",
                    },
                    sort_keys=True,
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "wiki-task",
        db_path=db_path,
    )
    payload = json.loads(
        (task_dir / "inputs" / "wiki_embedding_inputs.json").read_text()
    )
    assert "embedding_text" not in payload["artifacts"][0]
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    result_manifest = validate_result_package(result_dir)
    assert run_payload["status"] == "partial"
    assert result_manifest["status"] == "partial"
    rows = [
        json.loads(line)
        for line in (result_dir / "outputs" / "wiki_embeddings.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows == [
        {
            "artifact_id": 1,
            "reason": "missing_explicit_embedding_text",
            "status": "pending_embedding",
        }
    ]


def test_run_local_task_wiki_embedding_uses_explicit_fake_model_policy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "local" / "wiki-task",
        db_path=db_path,
        model_policy={
            "backend": "fake_model",
            "model_id": "generic-local-test-model",
            "embedding_dim": 8,
            "device": "cpu",
            "cache_policy": {
                "max_gb": 1,
                "cleanup": "manual",
                "cache_root": "cache/",
            },
        },
    )
    payload = json.loads(
        (task_dir / "inputs" / "wiki_embedding_inputs.json").read_text()
    )
    assert payload["model_policy"]["backend"] == "fake_model"
    assert payload["model_policy"]["cache_policy"]["cleanup"] == "manual"
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    run_payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    assert run_payload["status"] == "succeeded"
    rows = [
        json.loads(line)
        for line in (result_dir / "outputs" / "wiki_embeddings.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows[0]["method"] == "fake_model_embedding_v1"
    assert rows[0]["model_id"] == "generic-local-test-model"
    assert rows[0]["device"] == "cpu"
    assert rows[0]["embedding_dim"] == 8
    assert len(rows[0]["embedding"]) == 8
    summary = json.loads((result_dir / "outputs" / "summary.json").read_text())
    assert summary["method"] == "fake_model_embedding_v1"
    assert summary["model_policy"]["cache_policy"]["cache_root"] == "cache"
    assert "quality claim" in summary["note"]


def test_run_local_task_creates_failed_manifest_for_runner_failure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    runner = task_dir / "runner.sh"
    runner.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "echo boom >&2",
                "exit 7",
            ]
        )
        + "\n"
    )
    runner.chmod(0o755)
    remote_root = tmp_path / "remote"
    uploaded = upload_task(task_dir, remote_root=remote_root)

    payload = run_local_task(uploaded["task_id"], remote_root=remote_root)

    result_dir = remote_root / "results" / uploaded["task_id"]
    manifest = validate_result_package(result_dir)
    assert payload["status"] == "failed"
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == 7
    assert manifest["warnings"] == ["runner did not write result_manifest.json"]
    assert (result_dir / "logs" / "stderr.log").read_text() == "boom\n"


def test_validate_result_package_rejects_forged_success_and_missing_outputs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    result_dir = _write_result(task_dir, status="succeeded")
    manifest_path = result_dir / "result_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["exit_code"] = 1
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(OffloadError, match="succeeded.*exit_code"):
        validate_result_package(result_dir)

    manifest["exit_code"] = 0
    missing_output = result_dir / "outputs" / "summary.json"
    missing_output.unlink()
    manifest["output_hashes"] = compute_file_hashes(result_dir / "outputs")
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(OffloadError, match="expected output"):
        validate_result_package(result_dir)


def test_validate_result_package_rejects_symlink_outputs(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    result_dir = _write_result(task_dir, status="succeeded")
    link = result_dir / "outputs" / "linked.txt"
    link.symlink_to(tmp_path / "outside.txt")

    with pytest.raises(OffloadError, match="symlink"):
        validate_result_package(result_dir)


def test_validate_result_package_rejects_symlink_manifests_and_logs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    result_dir = _write_result(task_dir, status="succeeded")
    outside = tmp_path / "outside.json"
    outside.write_text((result_dir / "result_manifest.json").read_text())
    (result_dir / "result_manifest.json").unlink()
    (result_dir / "result_manifest.json").symlink_to(outside)

    with pytest.raises(OffloadError, match="symlink"):
        validate_result_package(result_dir)

    result_dir = _write_result(task_dir, status="succeeded")
    outside_task = tmp_path / "outside-task.json"
    outside_task.write_text((result_dir / "task_manifest.json").read_text())
    (result_dir / "task_manifest.json").unlink()
    (result_dir / "task_manifest.json").symlink_to(outside_task)

    with pytest.raises(OffloadError, match="symlink"):
        validate_result_package(result_dir)

    result_dir = _write_result(task_dir, status="succeeded")
    outside_log = tmp_path / "outside.log"
    outside_log.write_text("leaked\n")
    (result_dir / "logs" / "stdout.log").unlink()
    (result_dir / "logs" / "stdout.log").symlink_to(outside_log)

    with pytest.raises(OffloadError, match="symlink"):
        validate_result_package(result_dir)

    result_dir = _write_result(task_dir, status="succeeded")
    root_link = tmp_path / "result-link"
    root_link.symlink_to(result_dir)

    with pytest.raises(OffloadError, match="symlink"):
        validate_result_package(root_link)


def test_runner_command_is_repeatable_and_quoted() -> None:
    command = build_runner_command(
        "paper_text_extraction_batch-20260619T000000Z-demo",
        host="worker",
        remote_root="/srv/rh-offload",
    )

    assert "ssh worker" in command
    assert (
        "/srv/rh-offload/incoming/paper_text_extraction_batch-20260619T000000Z-demo"
        in command
    )
    remote_script = shlex.split(command)[2]
    assert "result_manifest.json" in command
    assert "set -euo pipefail" in command
    assert (
        "'status': 'partial' if int(os.environ['exit_code']) == 0 else 'failed'"
        in remote_script
    )
    assert "'started_at': started_at" in remote_script


def test_runner_command_requires_explicit_host() -> None:
    with pytest.raises(OffloadError, match="host is required"):
        build_runner_command(
            "paper_text_extraction_batch-20260619T000000Z-demo",
            host=None,
        )


def test_runner_command_rejects_dangerous_remote_roots() -> None:
    for remote_root in ("", ".", "/", "~", str(Path.home()), "../escape"):
        with pytest.raises(OffloadError, match="remote_root"):
            build_runner_command(
                "paper_text_extraction_batch-20260619T000000Z-demo",
                host="worker",
                remote_root=remote_root,
            )


def test_upload_and_fetch_execute_paths_build_safe_rsync_argv(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    commands: list[list[str]] = []

    upload_task(
        task_dir,
        remote_root="/srv/rh-offload",
        host="worker",
        execute=True,
        command_runner=lambda command: commands.append(list(command)),
    )

    task_id = json.loads((task_dir / "task_manifest.json").read_text())["task_id"]
    assert commands[0][:2] == ["ssh", "worker"]
    assert "mkdir -p" in commands[0][2]
    assert commands[1] == [
        "rsync",
        "-a",
        "--partial",
        "--checksum",
        f"{task_dir.as_posix().rstrip('/')}/",
        f"worker:/srv/rh-offload/incoming/{task_id}/",
    ]

    result_dir = _write_result(task_dir, status="succeeded")
    local_root = tmp_path / "fetched"
    commands.clear()

    def _fake_fetch(command: list[str]) -> None:
        commands.append(list(command))
        shutil.copytree(result_dir, local_root / task_id, dirs_exist_ok=True)

    fetch_task(
        task_id,
        local_root=local_root,
        remote_root=result_dir.parent.parent,
        host="worker",
        execute=True,
        command_runner=_fake_fetch,
    )

    assert commands[0][:4] == ["rsync", "-a", "--partial", "--checksum"]
    assert commands[0][4].startswith("worker:")
    assert commands[0][5].endswith("/")


def test_doctor_parses_read_only_remote_probe() -> None:
    commands: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "\n".join(
            [
                "Python 3.11.9",
                "root_exists",
                "incoming_exists",
                "runs_exists",
                "results_exists",
                "cache_exists",
                "/dev/nvme0n1  100G 50G 50G 50% /srv/rh-offload",
                "GPU 0: A100",
                "GPU 1: A100",
                "runner_not_checked",
                "package:json:ok",
                "package:sqlite3:ok",
                "package:pypdf:ok",
                "package:PyPDF2:missing",
                "command:pdftotext:ok",
                "package:sentence_transformers:ok",
                "package:torch:missing",
                'RH_OFFLOAD_CAPABILITIES_JSON={"schema_version":"rh_offload_worker_capabilities.v1","supported_task_types":["paper_text_extraction_batch","wiki_embedding_batch"],"resources":{"gpu":true,"cpu":32,"memory_gb":256},"features":{"pdf_parsers":["pypdf","pdftotext"],"embedding":{"backends":["sentence-transformers"],"models":["generic-local-model"],"default_device":"cuda"}},"cache_policy":{"max_gb":50,"cleanup":"manual","cache_root":"cache/"},"notes":["generic worker"]}',
            ]
        )
        stderr = ""

    payload = doctor(
        host="worker",
        remote_root="/srv/rh-offload",
        command_runner=lambda command: commands.append(list(command)) or Completed(),
    )

    checks = {item["check"]: item for item in payload["checks"]}
    assert commands and commands[0][0] == "ssh"
    assert "mkdir" not in commands[0][2]
    assert payload["read_only"] is True
    assert payload["task_types"] == [
        "paper_text_extraction_batch",
        "wiki_embedding_batch",
    ]
    assert checks["ssh"]["ok"] is True
    assert checks["remote_python"]["ok"] is True
    assert checks["remote_root"]["ok"] is True
    assert checks["remote_directories"]["ok"] is True
    assert checks["remote_directories"]["status"]["incoming"] == "exists"
    assert checks["remote_disk"]["ok"] is True
    assert checks["remote_gpu"]["count"] == 2
    assert checks["remote_gpu"]["devices"] == ["GPU 0: A100", "GPU 1: A100"]
    assert checks["remote_packages"]["packages"]["torch"] == "missing"
    assert checks["remote_packages"]["packages"]["pypdf"] == "ok"
    assert checks["remote_commands"]["commands"]["pdftotext"] == "ok"
    assert checks["worker_capabilities"]["ok"] is True
    assert checks["worker_capabilities"]["resources"]["gpu"] is True
    assert checks["worker_capabilities"]["features"]["pdf_parsers"] == [
        "pypdf",
        "pdftotext",
    ]
    assert checks["worker_capabilities"]["features"]["embedding"]["backends"] == [
        "sentence-transformers"
    ]
    assert checks["worker_capabilities"]["cache_policy"]["max_gb"] == 50


def test_doctor_skip_ssh_needs_no_host_and_reports_static_task_types() -> None:
    payload = doctor(host=None, remote_root="relative-offload-root", skip_ssh=True)

    checks = {item["check"]: item for item in payload["checks"]}
    assert payload["host"] is None
    assert payload["read_only"] is True
    assert payload["task_types"] == sorted(
        [
            "paper_text_extraction_batch",
            "researchflowbench_batch_eval",
            "retrieval_eval_sweep",
            "wiki_embedding_batch",
        ]
    )
    assert checks["ssh"]["skipped"] is True
    assert checks["remote_root_policy"]["ok"] is True


def test_import_records_success_and_failed_diagnostic_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    success_result = _write_result(task_dir, status="succeeded")

    imported = import_task_result(success_result, db_path=db_path, topic="demo-topic")

    assert imported["artifact_type"] == "remote_offload_result"
    conn = Database(db_path).connect()
    try:
        row = conn.execute(
            """
            SELECT artifact_type, payload_json, metadata_json, provenance_record_id
            FROM project_artifacts
            WHERE id = ?
            """,
            (imported["artifact_id"],),
        ).fetchone()
        assert row["artifact_type"] == "remote_offload_result"
        assert row["provenance_record_id"] == imported["provenance_record_id"]
        payload = json.loads(row["payload_json"])
        metadata = json.loads(row["metadata_json"])
        assert payload["result_manifest"]["status"] == "succeeded"
        assert payload["task_manifest"]["input_hashes"]
        assert payload["result_path"] == f"results/{imported['task_id']}"
        assert metadata["origin"] == "remote_offload"
        assert metadata["task_id"] == imported["task_id"]
        assert metadata["input_hashes"]
        provenance = conn.execute(
            """
            SELECT primitive, backend, origin, artifact_id, success
            FROM provenance_records
            WHERE id = ?
            """,
            (imported["provenance_record_id"],),
        ).fetchone()
        assert provenance["primitive"] == "offload_import"
        assert provenance["backend"] == "remote_offload"
        assert provenance["origin"] == "remote_offload"
        assert provenance["artifact_id"] == imported["artifact_id"]
        assert provenance["success"] == 1
    finally:
        conn.close()

    failed_dir = tmp_path / "failed-result"
    (failed_dir / "outputs").mkdir(parents=True)
    (failed_dir / "logs").mkdir()
    (failed_dir / "logs" / "stdout.log").write_text("")
    (failed_dir / "logs" / "stderr.log").write_text("boom\n")
    manifest = json.loads((success_result / "result_manifest.json").read_text())
    manifest["status"] = "failed"
    manifest["exit_code"] = 1
    manifest["output_hashes"] = {}
    (failed_dir / "result_manifest.json").write_text(json.dumps(manifest))

    diagnostic = import_task_result(failed_dir, db_path=db_path, topic="demo-topic")

    assert diagnostic["artifact_type"] == "remote_offload_diagnostic"


def test_import_retrieval_eval_sweep_creates_conservative_project_artifact(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="retrieval_eval_sweep",
        topic="demo-topic",
        out_dir=tmp_path / "retrieval-task",
        db_path=db_path,
    )
    result_dir = _write_successful_retrieval_eval_result(task_dir)

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["artifact_type"] == "remote_offload_result"
    assert imported["deep_result_imports"]["imported"] == 1
    assert imported["deep_result_imports"]["skipped"] == 0
    assert imported["deep_result_imports"]["artifacts"][0]["artifact_type"] == (
        "remote_retrieval_eval_result"
    )
    conn = Database(db_path).connect()
    try:
        row = conn.execute(
            """
            SELECT artifact_type, path, payload_json, metadata_json,
                   provenance_record_id
            FROM project_artifacts
            WHERE artifact_type = 'remote_retrieval_eval_result'
            """
        ).fetchone()
        assert row is not None
        assert row["path"] == f"results/{imported['task_id']}/outputs"
        assert row["provenance_record_id"] == imported["provenance_record_id"]
        payload = json.loads(row["payload_json"])
        metadata = json.loads(row["metadata_json"])
        assert payload["schema_version"] == "remote_retrieval_eval_result.v1"
        assert payload["receipt_artifact_id"] == imported["artifact_id"]
        assert payload["report"]["method"] == "fake_model_snapshot_rerank_v1"
        assert payload["prediction_summary"]["row_count"] == 1
        assert payload["prediction_summary"]["top_match_count"] == 2
        assert (
            payload["prediction_summary"]["sample_top_matches"][0]["relative_path_hash"]
            == "a" * 64
        )
        assert metadata["origin"] == "remote_offload"
        assert metadata["task_type"] == "retrieval_eval_sweep"
        assert metadata["canonical"] is False
        assert metadata["trusted_remote_metadata"] is False
        assert "predictions.jsonl" in metadata["output_hashes"]
    finally:
        conn.close()

    receipt = json.loads((result_dir / RECEIPT_FILE).read_text())
    assert receipt["attempts"][-1]["deep_result_imports"]["imported"] == 1

    imported_again = import_task_result(result_dir, db_path=db_path, topic="demo-topic")
    assert imported_again["deep_result_imports"]["imported"] == 0
    assert imported_again["deep_result_imports"]["skipped"] == 1
    conn = Database(db_path).connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_retrieval_eval_result'
            """
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_import_wiki_embedding_batch_creates_retrieval_index_link_artifact(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    result_dir = _write_successful_wiki_embedding_result(task_dir)

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["artifact_type"] == "remote_offload_result"
    assert imported["deep_result_imports"]["imported"] == 1
    assert imported["deep_result_imports"]["artifacts"][0]["artifact_type"] == (
        "remote_wiki_embedding_index"
    )
    conn = Database(db_path).connect()
    try:
        row = conn.execute(
            """
            SELECT artifact_type, path, payload_json, metadata_json,
                   provenance_record_id
            FROM project_artifacts
            WHERE artifact_type = 'remote_wiki_embedding_index'
            """
        ).fetchone()
        assert row is not None
        assert row["provenance_record_id"] == imported["provenance_record_id"]
        payload = json.loads(row["payload_json"])
        metadata = json.loads(row["metadata_json"])
        assert payload["schema_version"] == "remote_wiki_embedding_index.v1"
        assert payload["receipt_artifact_id"] == imported["artifact_id"]
        assert payload["summary"]["method"] == "fake_model_embedding_v1"
        assert payload["embedding_summary"]["row_count"] == 1
        assert payload["embedding_summary"]["succeeded_count"] == 1
        assert payload["embedding_summary"]["embedding_dim"] == 4
        assert payload["source_links"] == ["project_artifacts:1"]
        assert payload["retrieval_index_role"] == "remote_candidate_index"
        assert metadata["canonical"] is False
        assert metadata["artifact_role"] == "topic_knowledge_retrieval_index"
        assert metadata["output_hashes"]["wiki_embeddings.jsonl"]
    finally:
        conn.close()

    imported_again = import_task_result(result_dir, db_path=db_path, topic="demo-topic")
    assert imported_again["deep_result_imports"]["imported"] == 0
    assert imported_again["deep_result_imports"]["skipped"] == 1
    conn = Database(db_path).connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_wiki_embedding_index'
            """
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_import_partial_or_failed_result_does_not_deep_import(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    result_dir = _write_successful_wiki_embedding_result(task_dir)
    manifest = json.loads((result_dir / "result_manifest.json").read_text())
    manifest["status"] = "partial"
    manifest["exit_code"] = 2
    (result_dir / "result_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["artifact_type"] == "remote_offload_diagnostic"
    assert imported["deep_result_imports"]["imported"] == 0
    conn = Database(db_path).connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_wiki_embedding_index'
            """
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_import_malformed_deep_result_keeps_generic_receipt(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="wiki_embedding_batch",
        topic="demo-topic",
        out_dir=tmp_path / "wiki-task",
        db_path=db_path,
    )
    result_dir = _write_successful_wiki_embedding_result(task_dir)
    (result_dir / "outputs" / "wiki_embeddings.jsonl").write_text("{bad-json\n")
    _rewrite_result_manifest_hashes(result_dir)

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["artifact_type"] == "remote_offload_result"
    assert imported["deep_result_imports"]["imported"] == 0
    assert imported["deep_result_imports"]["skipped"] == 1
    assert "invalid JSONL row" in imported["deep_result_imports"]["warnings"][0]
    conn = Database(db_path).connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE artifact_type = 'remote_wiki_embedding_index'
            """
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_import_paper_text_extraction_creates_paperindex_structure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    result_dir = _write_successful_paper_text_result(task_dir)

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["artifact_type"] == "remote_offload_result"
    assert imported["paper_artifact_imports"]["imported"] == 1
    conn = Database(db_path).connect()
    try:
        row = conn.execute(
            """
            SELECT artifact_type, path, metadata
            FROM paper_artifacts
            WHERE paper_id = 1 AND artifact_type = 'paperindex_structure'
            """
        ).fetchone()
        assert row is not None
        metadata = json.loads(row["metadata"])
        assert metadata["source"] == "remote_offload"
        assert metadata["task_id"] == imported["task_id"]
        structure = json.loads(Path(row["path"]).read_text())
        assert structure["pdf_hash"] == "hash-a"
        assert structure["raw"]["pages_text"] == [
            "first imported page",
            "second imported page",
        ]
        paper = conn.execute("SELECT * FROM papers WHERE id = 1").fetchone()
        assert deepread_impls._get_pdf_pages_text(conn, 1, paper, max_pages=1) == [
            "first imported page"
        ]
    finally:
        conn.close()

    imported_again = import_task_result(result_dir, db_path=db_path, topic="demo-topic")
    assert imported_again["paper_artifact_imports"]["imported"] == 0
    assert imported_again["paper_artifact_imports"]["skipped"] == 1
    conn = Database(db_path).connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_artifacts
            WHERE paper_id = 1 AND artifact_type = 'paperindex_structure'
            """
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_import_paper_text_extraction_does_not_overwrite_existing_structure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    local_structure = tmp_path / "local-structure.json"
    local_structure.write_text(
        json.dumps(
            {
                "doc_name": "local",
                "pdf_hash": "local-hash",
                "page_count": 1,
                "structure": [],
                "raw": {"pages_text": ["local page"]},
            }
        )
    )
    conn = Database(db_path).connect()
    try:
        conn.execute(
            """
            INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)
            VALUES (1, 'paperindex_structure', ?, ?)
            """,
            (
                str(local_structure),
                json.dumps({"source": "local", "pdf_hash": "local-hash"}),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    result_dir = _write_successful_paper_text_result(task_dir)

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["paper_artifact_imports"]["imported"] == 0
    assert imported["paper_artifact_imports"]["skipped"] == 1
    conn = Database(db_path).connect()
    try:
        rows = conn.execute(
            """
            SELECT path
            FROM paper_artifacts
            WHERE paper_id = 1 AND artifact_type = 'paperindex_structure'
            """
        ).fetchall()
        assert [row["path"] for row in rows] == [str(local_structure)]
        assert json.loads(local_structure.read_text())["raw"]["pages_text"] == [
            "local page"
        ]
    finally:
        conn.close()


def test_import_paper_text_extraction_skips_hash_mismatch_and_bad_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pool.db"
    _seed_topic(db_path)
    task_dir = prepare_task(
        task_type="paper_text_extraction_batch",
        topic="demo-topic",
        out_dir=tmp_path / "task-pack",
        db_path=db_path,
    )
    result_dir = _write_successful_paper_text_result(task_dir)
    rows = [
        {
            "paper_id": 1,
            "status": "succeeded",
            "pdf_hash": "different-hash",
            "page_count": 1,
            "pages_text": ["wrong file"],
        },
        {
            "paper_id": 1,
            "status": "succeeded",
            "pdf_hash": "hash-a",
            "page_count": 1,
            "pages_text": "not a list",
        },
    ]
    (result_dir / "outputs" / "paper_text_extraction_results.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"
    )
    _rewrite_result_manifest_hashes(result_dir)

    imported = import_task_result(result_dir, db_path=db_path, topic="demo-topic")

    assert imported["paper_artifact_imports"]["imported"] == 0
    assert imported["paper_artifact_imports"]["skipped"] == 2
    assert any(
        "pdf_hash mismatch" in warning
        for warning in imported["paper_artifact_imports"]["warnings"]
    )
    assert any(
        "pages_text" in warning
        for warning in imported["paper_artifact_imports"]["warnings"]
    )
    conn = Database(db_path).connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_artifacts
            WHERE paper_id = 1 AND artifact_type = 'paperindex_structure'
            """
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()
