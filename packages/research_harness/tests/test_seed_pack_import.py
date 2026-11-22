"""Contract regression tests for the seed pack import adapter.

The fixture pack mirrors the paperfetch seed pack contract
(seed_papers.jsonl + run_report.json + pdf/) without importing SPC.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_harness.acquisition.seed_pack_import import (
    SeedPackContractError,
    import_seed_pack,
    load_seed_pack,
    map_spc_failure_class,
    spc_pdf_key,
)

RUN_REPORT_VERSION = "seed-paper-curator.run-report.v1"


def _record(
    spc_id: str = "spc:0001",
    title: str = "Retrieval Augmented Generation for Long Tasks",
    doi: str = "10.5555/rag.2026",
    **overrides,
) -> dict:
    record = {
        "paper_id": spc_id,
        "doi": doi,
        "title": title,
        "year": 2026,
        "venue": "NeurIPS",
        "journal": None,
        "publisher": "Curran",
        "document_type": "conference_paper",
        "abstract": "We study retrieval.",
        "arxiv_id": "2601.00001",
        "semantic_scholar_id": "s2-abc",
        "openalex_id": "W123",
        "pubmed_id": None,
        "pmc_id": None,
        "citation_count": 12,
        "reference_count": 40,
        "authors": [
            {
                "name": "Ada Lovelace",
                "affiliations": ["Analytical Engine Lab"],
                "source": "openalex",
            },
        ],
        "source_refs": [
            {
                "source": "openalex",
                "field": "title",
                "value": title,
                "retrieved_at": "2026-07-01T00:00:00",
                "query_or_endpoint": "works?search=rag",
                "confidence": 1.0,
            }
        ],
        "recall_hits": [
            {
                "source": "openalex",
                "query_family": "core",
                "query": "rag",
                "source_rank": 1,
            }
        ],
        "field_conflicts": [
            {
                "field": "year",
                "value_1": "2025",
                "value_2": "2026",
                "chosen_value": "2026",
            }
        ],
        "merged_from": ["openalex:W123", "s2:abc"],
        "recorded_facts": {"title": title, "venue_metadata": {"ccf_rank": "A"}},
        "available_files": {},
        "curation_signals": {},
        "selection_rank": 1,
        "selection_bucket": "core_method_candidate",
        "selection_basis": ["core query hit"],
        "requires_agent_review": [],
        "fulltext_status": {
            "oa_status": "open",
            "pdf_url": "https://example.org/paper.pdf",
            "download_status": "not_attempted",
            "extracted_code_url": "https://github.com/ada/rag-engine",
            "reproducibility_status": "verified_runnable",
            "repo_metadata": {"stars": 42},
        },
    }
    record.update(overrides)
    return record


def _write_pack(
    tmp_path: Path,
    records: list[dict],
    run_report: dict | None = None,
    pdfs: dict[str, bytes] | None = None,
) -> Path:
    pack = tmp_path / "rag__20260707__abc123"
    pack.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    (pack / "seed_papers.jsonl").write_text("\n".join(lines), encoding="utf-8")
    if run_report is not None:
        (pack / "run_report.json").write_text(
            json.dumps(run_report, ensure_ascii=False), encoding="utf-8"
        )
    if pdfs:
        pdf_dir = pack / "pdf"
        pdf_dir.mkdir(exist_ok=True)
        for name, content in pdfs.items():
            (pdf_dir / name).write_bytes(content)
    return pack


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n" + b"0" * 12_000


def _matching_extractor(path: Path) -> str:
    return "Retrieval Augmented Generation for Long Tasks 10.5555/rag.2026"


def _mismatching_extractor(path: Path) -> str:
    return "an entirely different paper about protein folding"


def _topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name) VALUES ('rag')")
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


class TestLoadSeedPack:
    def test_missing_dir_raises_deterministic_reason(self, tmp_path):
        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(tmp_path / "nope")
        assert exc.value.reason == "pack_dir_missing"

    def test_missing_jsonl_raises(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(pack)
        assert exc.value.reason == "seed_papers_missing"

    def test_invalid_json_line_raises_with_line_number(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        (pack / "seed_papers.jsonl").write_text(
            '{"title": "ok"}\n{broken', encoding="utf-8"
        )
        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(pack)
        assert exc.value.reason == "seed_papers_invalid_json"
        assert "line 2" in exc.value.detail

    def test_record_without_title_raises(self, tmp_path):
        pack = _write_pack(tmp_path, [{"paper_id": "spc:1"}])
        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(pack)
        assert exc.value.reason == "record_invalid"

    def test_unsupported_run_report_version_raises(self, tmp_path):
        pack = _write_pack(
            tmp_path, [_record()], run_report={"report_version": "v99", "papers": []}
        )
        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(pack)
        assert exc.value.reason == "run_report_version_unsupported"
        assert exc.value.detail == "v99"

    def test_supported_pack_loads(self, tmp_path):
        pack = _write_pack(
            tmp_path,
            [_record()],
            run_report={"report_version": RUN_REPORT_VERSION, "papers": []},
        )
        loaded = load_seed_pack(pack)
        assert len(loaded.records) == 1
        assert loaded.run_report_version == RUN_REPORT_VERSION

    @pytest.mark.parametrize(
        "version", ["paperfetch.run-report.v1", "paperfetch.run-report.v3"]
    )
    def test_paperfetch_packs_load(self, tmp_path, version):
        pack = _write_pack(
            tmp_path,
            [_record()],
            run_report={"report_version": version, "papers": []},
        )
        assert load_seed_pack(pack).run_report_version == version


class TestTaxonomyMapping:
    def test_known_classes_map_onto_rh_taxonomy(self):
        assert map_spc_failure_class("publisher_challenge") == "browser_challenge"
        assert map_spc_failure_class("subscription_required") == "subscription_required"
        assert map_spc_failure_class("auth_failed") == "auth_failed"
        assert map_spc_failure_class("not_found") == "http_404"
        assert (
            map_spc_failure_class("flaresolverr_unavailable")
            == "optional_route_unavailable"
        )

    def test_unknown_class_maps_deterministically(self):
        assert map_spc_failure_class("weird_new_class") == "external_unmapped"

    def test_none_stays_none(self):
        assert map_spc_failure_class(None) is None

    def test_mapped_values_are_valid_rh_taxonomy(self):
        from research_harness.acquisition.routes import FAILURE_TAXONOMY
        from research_harness.acquisition.seed_pack_import import (
            SPC_FAILURE_TAXONOMY_MAP,
        )

        for mapped in SPC_FAILURE_TAXONOMY_MAP.values():
            assert mapped in FAILURE_TAXONOMY


class TestPdfKey:
    def test_doi_key_matches_spc_derivation(self):
        record = {"doi": "10.5555/RAG.2026", "arxiv_id": "", "title": "x"}
        assert spc_pdf_key(record) == "doi_10.5555_rag.2026"

    def test_arxiv_key_when_no_doi(self):
        record = {"doi": "", "arxiv_id": "2601.00001", "title": "x"}
        assert spc_pdf_key(record) == "arxiv_2601.00001"


class TestImportSeedPack:
    def test_papers_and_facts_are_ingested(self, db, tmp_path):
        topic_id = _topic(db)
        pack = _write_pack(tmp_path, [_record()])

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.papers_seen == 1
        assert report.papers_new == 1
        conn = db.connect()
        try:
            paper = conn.execute(
                "SELECT * FROM papers WHERE doi = '10.5555/rag.2026'"
            ).fetchone()
            assert paper is not None
            assert paper["title"] == "Retrieval Augmented Generation for Long Tasks"
            link = conn.execute(
                "SELECT screening_status FROM paper_topics WHERE paper_id = ?",
                (paper["id"],),
            ).fetchone()
            assert link["screening_status"] == "candidate"
            facts_row = conn.execute(
                "SELECT metadata FROM paper_artifacts WHERE paper_id = ?"
                " AND artifact_type = 'paper_metadata_facts'",
                (paper["id"],),
            ).fetchone()
            facts = json.loads(facts_row["metadata"])
            assert facts["schema_version"] == "rh.paper_metadata_facts.v1"
            assert facts["source_refs"][0]["source"] == "openalex"
            assert facts["field_conflicts"][0]["field"] == "year"
            assert (
                facts["curation_signals"]["code_url"]
                == "https://github.com/ada/rag-engine"
            )
            assert (
                facts["curation_signals"]["reproducibility_status"]
                == "verified_runnable"
            )
        finally:
            conn.close()

    def test_reimport_updates_instead_of_duplicating(self, db, tmp_path):
        topic_id = _topic(db)
        pack = _write_pack(tmp_path, [_record()])

        import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )
        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.papers_updated == 1
        conn = db.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM papers WHERE doi = '10.5555/rag.2026'"
            ).fetchone()["n"]
            assert count == 1
            facts_count = conn.execute(
                "SELECT COUNT(*) AS n FROM paper_artifacts"
                " WHERE artifact_type = 'paper_metadata_facts'"
            ).fetchone()["n"]
            assert facts_count == 1
        finally:
            conn.close()

    def test_records_without_doi_do_not_abort_the_import(self, db, tmp_path):
        """BUG-01: several DOI-less records must all import, not crash the batch.

        Papers already ingested by arXiv id take the pool's UPDATE branch; a
        pack record carrying no DOI used to store ``doi = ''`` there, so the
        second such record aborted the whole import with
        ``UNIQUE constraint failed: papers.doi``.
        """
        topic_id = _topic(db)
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO papers (title, arxiv_id) VALUES ('First', '2510.17932')"
            )
            conn.execute(
                "INSERT INTO papers (title, arxiv_id) VALUES ('Second', '2510.99999')"
            )
            conn.commit()
        finally:
            conn.close()
        pack = _write_pack(
            tmp_path,
            [
                _record(
                    spc_id="spc:a",
                    title="First",
                    doi="",
                    arxiv_id="2510.17932",
                    semantic_scholar_id="",
                ),
                _record(
                    spc_id="spc:b",
                    title="Second",
                    doi="",
                    arxiv_id="2510.99999",
                    semantic_scholar_id="",
                ),
            ],
        )

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.papers_seen == 2
        assert report.papers_updated == 2
        assert report.papers_skipped == 0
        conn = db.connect()
        try:
            dois = [
                row["doi"] for row in conn.execute("SELECT doi FROM papers ORDER BY id")
            ]
            assert dois == [None, None]
        finally:
            conn.close()

    def test_identity_conflict_skips_one_record_and_reports_it(self, db, tmp_path):
        """BUG-01: one unimportable record must never abort the whole pack.

        The pool rows below describe the same paper split across two identifier
        families, so the first pack record cannot be merged without stealing an
        identifier another row owns. That record must be skipped with a reason
        while the rest of the pack still imports.
        """
        topic_id = _topic(db)
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO papers (title, doi) VALUES ('By DOI', '10.5555/rag.2026')"
            )
            conn.execute(
                "INSERT INTO papers (title, arxiv_id) VALUES ('By arXiv', '2601.00001')"
            )
            conn.commit()
        finally:
            conn.close()
        pack = _write_pack(
            tmp_path,
            [
                _record(spc_id="spc:conflict"),
                _record(
                    spc_id="spc:clean",
                    title="A Clean Paper",
                    doi="10.5555/clean.2026",
                    arxiv_id="2601.00002",
                    semantic_scholar_id="s2-clean",
                ),
            ],
        )

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.papers_seen == 2
        assert report.papers_new == 1
        assert report.papers_skipped == 1
        assert len(report.papers_rejected) == 1
        rejected = report.papers_rejected[0]
        assert rejected["spc_paper_id"] == "spc:conflict"
        assert rejected["reason"] == "identity_conflict"
        assert rejected["field"] == "arxiv_id"

        payload = report.to_dict()
        assert payload["papers_skipped"] == 1
        assert payload["papers_rejected"][0]["reason"] == "identity_conflict"

        conn = db.connect()
        try:
            titles = {row["title"] for row in conn.execute("SELECT title FROM papers")}
            assert "A Clean Paper" in titles
        finally:
            conn.close()

    def test_pdf_from_figure_url_is_rejected_despite_identity_pass(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["resolved_pdf_url"] = (
            "https://journals.plos.org/plosone/article/figure/image?id=10.1371/x"
        )
        key = spc_pdf_key(record)
        pack = _write_pack(tmp_path, [record], pdfs={f"{key}.pdf": _pdf_bytes()})

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_matching_extractor,
        )

        assert report.pdfs_imported == 0
        assert report.pdfs_rejected[0]["reason"] == "not_pdf"

    def test_verified_pdf_is_imported_with_route_audit(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        key = spc_pdf_key(record)
        pack = _write_pack(tmp_path, [record], pdfs={f"{key}.pdf": _pdf_bytes()})

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_matching_extractor,
        )

        assert report.pdfs_imported == 1
        assert report.pdfs_rejected == []
        conn = db.connect()
        try:
            paper = conn.execute(
                "SELECT id, pdf_path, pdf_hash, status FROM papers"
            ).fetchone()
            assert paper["status"] == "downloaded"
            assert Path(paper["pdf_path"]).is_file()
            assert len(paper["pdf_hash"]) == 64
            audit_row = conn.execute(
                "SELECT metadata FROM paper_artifacts WHERE paper_id = ?"
                " AND artifact_type = 'pdf_route_audit'",
                (paper["id"],),
            ).fetchone()
            audit = json.loads(audit_row["metadata"])
            assert audit["successful_route"] == "external_seed_pack"
            assert audit["sha256"] == paper["pdf_hash"]
        finally:
            conn.close()

    def test_identity_mismatch_rejects_pdf(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        key = spc_pdf_key(record)
        pack = _write_pack(tmp_path, [record], pdfs={f"{key}.pdf": _pdf_bytes()})

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_mismatching_extractor,
        )

        assert report.pdfs_imported == 0
        assert report.pdfs_rejected[0]["reason"] == "identity_mismatch"
        conn = db.connect()
        try:
            paper = conn.execute("SELECT pdf_path, status FROM papers").fetchone()
            assert (paper["pdf_path"] or "") == ""
            assert paper["status"] == "meta_only"
        finally:
            conn.close()

    def test_non_pdf_and_too_small_are_rejected(self, db, tmp_path):
        topic_id = _topic(db)
        rec_a = _record(spc_id="spc:a", doi="10.5555/a", title="Paper Alpha Study")
        rec_b = _record(spc_id="spc:b", doi="10.5555/b", title="Paper Beta Study")
        pack = _write_pack(
            tmp_path,
            [rec_a, rec_b],
            pdfs={
                f"{spc_pdf_key(rec_a)}.pdf": b"<html>login page</html>" + b"0" * 12_000,
                f"{spc_pdf_key(rec_b)}.pdf": b"%PDF-1.4 tiny",
            },
        )

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        reasons = {item["reason"] for item in report.pdfs_rejected}
        assert reasons == {"not_pdf", "too_small"}

    def test_local_path_outside_pack_is_not_followed(self, db, tmp_path):
        secret = tmp_path / "outside.pdf"
        secret.write_bytes(_pdf_bytes())
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["local_path"] = str(secret)
        record["fulltext_status"]["download_status"] = "downloaded"
        pack = _write_pack(tmp_path, [record])

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_matching_extractor,
        )

        assert report.pdfs_imported == 0
        assert report.pdfs_missing == 1

    def test_run_report_audits_are_mapped_and_recorded(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        run_report = {
            "report_version": RUN_REPORT_VERSION,
            "papers": [
                {
                    "paper_id": record["paper_id"],
                    "doi": record["doi"],
                    "download_status": "failed",
                    "cache_hit": False,
                    "attempted_routes": ["publisher_portal", "doi_landing"],
                    "successful_route": None,
                    "failure_taxonomy": "subscription_required",
                    "route_errors": [
                        {
                            "route": "publisher_portal",
                            "error_class": "publisher_challenge",
                            "error": "cloudflare",
                        }
                    ],
                    "download_attempts": [
                        {
                            "route": "publisher_portal",
                            "url": "https://dl.acm.org/doi/pdf/10.5555/rag.2026?token=SECRET",
                            "error_class": "publisher_challenge",
                            "duration_ms": 15000,
                        },
                        {
                            "route": "totally_new_route",
                            "error_class": "weird_new_class",
                        },
                    ],
                }
            ],
        }
        pack = _write_pack(tmp_path, [record], run_report=run_report)

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.audits_imported == 1
        assert report.failure_taxonomies == {"subscription_required": 1}
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT metadata FROM paper_artifacts"
                " WHERE artifact_type = 'external_route_audit'"
            ).fetchone()
            payload = json.loads(row["metadata"])
            assert payload["schema_version"] == "rh.external_route_audit.v1"
            assert payload["failure_taxonomy"] == "subscription_required"
            assert payload["external_failure_taxonomy"] == "subscription_required"
            assert payload["attempted_routes"] == [
                "spc:publisher_portal",
                "spc:doi_landing",
            ]
            first, second = payload["download_attempts"]
            assert first["error_class"] == "browser_challenge"
            assert first["external_error_class"] == "publisher_challenge"
            assert "SECRET" not in (first["url"] or "")
            assert second["error_class"] == "external_unmapped"
            assert second["external_error_class"] == "weird_new_class"
        finally:
            conn.close()

    def test_unmatched_run_report_entry_is_counted(self, db, tmp_path):
        topic_id = _topic(db)
        run_report = {
            "report_version": RUN_REPORT_VERSION,
            "papers": [{"paper_id": "spc:ghost", "doi": "10.9999/ghost"}],
        }
        pack = _write_pack(tmp_path, [_record()], run_report=run_report)

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.audits_imported == 0
        assert report.audits_unmatched == 1

    def test_parse_markdown_is_imported_from_pack(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["mineru_status"] = "parsed"
        record["fulltext_status"]["parse_quality"] = "high"
        record["fulltext_status"]["mineru_markdown_path"] = (
            "/somewhere/on/spc/machine/full.md"
        )
        pack = _write_pack(tmp_path, [record])
        mineru_dir = pack / "mineru" / "10.5555_rag.2026"
        mineru_dir.mkdir(parents=True)
        (mineru_dir / "full.md").write_text("# Parsed paper\n", encoding="utf-8")

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            artifacts_root=tmp_path / "artifacts",
            annotate=False,
        )

        assert report.parse_imported == 1
        assert report.parse_missing == 0
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT metadata FROM paper_artifacts"
                " WHERE artifact_type = 'paper_parse_artifact'"
            ).fetchone()
            payload = json.loads(row["metadata"])
            assert payload["schema_version"] == "rh.paper_parse_artifact.v1"
            assert payload["provider"] == "mineru"
            assert payload["parse_quality"] == "high"
            copied = Path(payload["markdown_path"])
            assert copied.is_file()
            assert copied.read_text(encoding="utf-8") == "# Parsed paper\n"
            assert str(copied).startswith(str(tmp_path / "artifacts"))
        finally:
            conn.close()

    def test_parse_content_list_rides_along_when_present(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["mineru_status"] = "parsed"
        pack = _write_pack(tmp_path, [record])
        mineru_dir = pack / "mineru" / "10.5555_rag.2026"
        mineru_dir.mkdir(parents=True)
        (mineru_dir / "full.md").write_text("# Parsed paper\n", encoding="utf-8")
        (mineru_dir / "paper_content_list.json").write_text(
            '[{"type": "text", "text": "Parsed paper", "text_level": 1, "page_idx": 0}]',
            encoding="utf-8",
        )

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            artifacts_root=tmp_path / "artifacts",
            annotate=False,
        )

        assert report.parse_imported == 1
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT metadata FROM paper_artifacts"
                " WHERE artifact_type = 'paper_parse_artifact'"
            ).fetchone()
            payload = json.loads(row["metadata"])
            copied = Path(payload["content_list_path"])
            assert copied.is_file()
            assert copied.name == "content_list.json"
            assert str(copied).startswith(str(tmp_path / "artifacts"))
            assert payload["figure_assets"]["schema_version"] == (
                "rh.figure_asset_bridge.v1"
            )
            assert payload["figure_assets"]["records"] == []
        finally:
            conn.close()

    def test_parse_figure_assets_are_candidates_until_verified(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["mineru_status"] = "parsed"
        record["fulltext_status"]["mineru_version"] = "mineru-2.5-fixture"
        pack = _write_pack(tmp_path, [record])
        mineru_dir = pack / "mineru" / "10.5555_rag.2026"
        images = mineru_dir / "images"
        images.mkdir(parents=True)
        (mineru_dir / "full.md").write_text(
            "# Parsed paper\nSee Figure 1 in the method.\n",
            encoding="utf-8",
        )
        png = b"\x89PNG\r\n\x1a\nfig-bytes"
        (images / "fig1.png").write_bytes(png)
        (mineru_dir / "paper_content_list.json").write_text(
            json.dumps(
                [
                    {
                        "type": "image",
                        "img_path": "images/fig1.png",
                        "img_caption": "Figure 1. Overview.",
                        "page_idx": 0,
                        "bbox": [0, 0, 12, 8],
                    }
                ]
            ),
            encoding="utf-8",
        )

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            artifacts_root=tmp_path / "artifacts",
            annotate=False,
        )

        assert report.parse_imported == 1
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT metadata FROM paper_artifacts"
                " WHERE artifact_type = 'paper_parse_artifact'"
            ).fetchone()
            payload = json.loads(row["metadata"])
            rec = payload["figure_assets"]["records"][0]
            assert rec["verification_status"] == "verified"
            assert rec["figure_id"] == "fig:1"
            assert rec["body_references"] == ["Figure 1"]
            copied = Path(rec["asset_path"])
            assert copied.is_file()
            assert copied.read_bytes() == png
            assert str(copied).startswith(str(tmp_path / "artifacts"))
        finally:
            conn.close()

    def test_parsed_status_without_pack_markdown_counts_missing(self, db, tmp_path):
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["mineru_status"] = "parsed"
        pack = _write_pack(tmp_path, [record])

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            artifacts_root=tmp_path / "artifacts",
            annotate=False,
        )

        assert report.parse_imported == 0
        assert report.parse_missing == 1

    def test_markdown_outside_pack_is_not_followed(self, db, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "full.md").write_text("secret", encoding="utf-8")
        topic_id = _topic(db)
        record = _record()
        record["fulltext_status"]["mineru_status"] = "parsed"
        record["fulltext_status"]["mineru_extracted_dir"] = str(outside)
        pack = _write_pack(tmp_path, [record])
        # A symlink inside mineru/ pointing outside the pack must be refused.
        mineru_dir = pack / "mineru"
        mineru_dir.mkdir()
        (mineru_dir / "outside").symlink_to(outside)

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            artifacts_root=tmp_path / "artifacts",
            annotate=False,
        )

        assert report.parse_imported == 0
        assert report.parse_missing == 1

    def test_import_report_artifact_is_recorded(self, db, tmp_path):
        topic_id = _topic(db)
        pack = _write_pack(tmp_path, [_record()])

        import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM project_artifacts"
                " WHERE artifact_type = 'seed_pack_import_report'"
            ).fetchone()
            assert row is not None
            payload = json.loads(row["payload_json"])
            assert payload["schema_version"] == "rh.seed_pack_import_report.v1"
            assert payload["papers_seen"] == 1
        finally:
            conn.close()


MANIFEST_VERSION = "spc.seed-pack-manifest.v1"


def _v1_record(
    spc_id: str = "spc_0001",
    title: str | None = "Underwater Acoustic Networks Survey",
    doi: str = "10.5555/uan.2026",
    **overrides,
) -> dict:
    record = {
        "schema_version": "spc.paper-record.v1",
        "paper_id": spc_id,
        "revision": 1,
        "identifiers": {
            "doi": doi,
            "pubmed_id": None,
            "pmc_id": None,
            "arxiv_id": None,
        },
        "bibliographic": {
            "title": title,
            "paper_type": "journal_article",
            "authors": [
                {
                    "display_name": "Ada Lovelace",
                    "family_name": "Lovelace",
                    "given_name": "Ada",
                    "orcid": None,
                },
                {
                    "display_name": None,
                    "family_name": "Curie",
                    "given_name": "Marie",
                    "orcid": None,
                },
            ],
            "abstract": "We survey underwater networks.",
            "publication_date": "2021-06-15",
            "venue": {
                "name": "IEEE Communications Surveys & Tutorials",
                "issn": None,
                "eissn": None,
            },
            "publisher": "IEEE",
            "volume": "23",
            "issue": "2",
            "pages": "904-956",
            "language": None,
            "license": None,
        },
        "provenance": {
            "sources": [
                {
                    "source_id": "crossref-1",
                    "source": "crossref",
                    "record_id": doi,
                    "retrieved_at": "2026-08-14T14:44:33Z",
                    "payload_sha256": "abc",
                }
            ],
            "fields": [],
        },
        "fulltext": {
            "pdf": {"status": "not_attempted", "artifact": None, "error": None},
            "parse": {"status": "not_attempted", "artifact": None, "error": None},
        },
    }
    record.update(overrides)
    return record


def _write_v1_pack(
    tmp_path: Path, records: list[dict], manifest_version: str = MANIFEST_VERSION
) -> Path:
    pack = tmp_path / "seed-pack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": manifest_version,
                "layout_version": 1,
                "seed_pack_id": "pack_fixture",
                "name": "fixture pack",
                "created_at": "2026-08-14T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    (pack / "papers.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return pack


def _mark_pdf_available(record: dict, art_id: str) -> None:
    record["fulltext"]["pdf"] = {
        "status": "available",
        "artifact": {"artifact_id": art_id, "kind": "paper_pdf"},
        "error": None,
    }


def _v1_matching_extractor(path: Path) -> str:
    return "Underwater Acoustic Networks Survey 10.5555/uan.2026"


class TestSpcV1Layout:
    def test_v1_pack_loads_and_normalizes(self, tmp_path):
        pack = _write_v1_pack(tmp_path, [_v1_record()])

        loaded = load_seed_pack(pack)

        assert loaded.run_report is None
        assert loaded.manifest["schema_version"] == MANIFEST_VERSION
        assert len(loaded.records) == 1
        record = loaded.records[0]
        assert record["paper_id"] == "spc_0001"
        assert record["title"] == "Underwater Acoustic Networks Survey"
        assert record["authors"] == [{"name": "Ada Lovelace"}, {"name": "Marie Curie"}]
        assert record["year"] == 2021
        assert record["venue"] == "IEEE Communications Surveys & Tutorials"
        assert record["publisher"] == "IEEE"
        assert record["doi"] == "10.5555/uan.2026"
        assert record["source_refs"][0]["source"] == "crossref"

    def test_unknown_manifest_version_raises(self, tmp_path):
        pack = _write_v1_pack(
            tmp_path, [_v1_record()], manifest_version="spc.seed-pack-manifest.v99"
        )

        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(pack)
        assert exc.value.reason == "manifest_version_unsupported"
        assert exc.value.detail == "spc.seed-pack-manifest.v99"

    def test_manifest_without_papers_jsonl_raises(self, tmp_path):
        pack = _write_v1_pack(tmp_path, [_v1_record()])
        (pack / "papers.jsonl").unlink()

        with pytest.raises(SeedPackContractError) as exc:
            load_seed_pack(pack)
        assert exc.value.reason == "seed_papers_missing"

    def test_v1_record_imports_with_metadata_facts(self, db, tmp_path):
        topic_id = _topic(db)
        pack = _write_v1_pack(tmp_path, [_v1_record()])

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.papers_seen == 1
        assert report.papers_new == 1
        conn = db.connect()
        try:
            paper = conn.execute(
                "SELECT * FROM papers WHERE doi = '10.5555/uan.2026'"
            ).fetchone()
            assert paper["title"] == "Underwater Acoustic Networks Survey"
            assert paper["year"] == 2021
            assert paper["venue"] == "IEEE Communications Surveys & Tutorials"
            facts_row = conn.execute(
                "SELECT metadata FROM paper_artifacts WHERE paper_id = ?"
                " AND artifact_type = 'paper_metadata_facts'",
                (paper["id"],),
            ).fetchone()
            facts = json.loads(facts_row["metadata"])
            assert facts["source_refs"][0]["source"] == "crossref"
            assert facts["recorded_facts"]["publisher"] == "IEEE"
        finally:
            conn.close()

    def test_empty_title_record_is_rejected_per_record(self, db, tmp_path):
        topic_id = _topic(db)
        pack = _write_v1_pack(
            tmp_path,
            [
                _v1_record(),
                _v1_record(spc_id="spc_0002", title=None, doi="10.5555/notitle"),
            ],
        )

        report = import_seed_pack(
            db, pack, topic_id, download_dir=tmp_path / "dl", annotate=False
        )

        assert report.papers_seen == 2
        assert report.papers_new == 1
        assert report.papers_skipped == 1
        rejected = report.papers_rejected[0]
        assert rejected["spc_paper_id"] == "spc_0002"
        assert rejected["reason"] == "title_missing"

    def test_artifact_pdf_is_imported(self, db, tmp_path):
        topic_id = _topic(db)
        record = _v1_record()
        _mark_pdf_available(record, "art_aaa")
        pack = _write_v1_pack(tmp_path, [record])
        art_dir = pack / "artifacts" / "spc_0001" / "pdf" / "art_aaa"
        art_dir.mkdir(parents=True)
        (art_dir / "article.pdf").write_bytes(_pdf_bytes())

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_v1_matching_extractor,
        )

        assert report.pdfs_imported == 1
        assert report.pdfs_missing == 0
        conn = db.connect()
        try:
            paper = conn.execute("SELECT pdf_path, status FROM papers").fetchone()
            assert paper["status"] == "downloaded"
            assert Path(paper["pdf_path"]).is_file()
        finally:
            conn.close()

    def test_declared_artifact_id_wins_over_sorted_first(self, db, tmp_path):
        topic_id = _topic(db)
        record = _v1_record()
        _mark_pdf_available(record, "art_zzz")
        pack = _write_v1_pack(tmp_path, [record])
        decoy = pack / "artifacts" / "spc_0001" / "pdf" / "art_aaa"
        decoy.mkdir(parents=True)
        (decoy / "article.pdf").write_bytes(b"<html>not a pdf</html>" + b"0" * 12_000)
        declared = pack / "artifacts" / "spc_0001" / "pdf" / "art_zzz"
        declared.mkdir(parents=True)
        (declared / "article.pdf").write_bytes(_pdf_bytes())

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_v1_matching_extractor,
        )

        assert report.pdfs_imported == 1
        assert report.pdfs_rejected == []

    def test_artifact_pdf_outside_pack_is_not_followed(self, db, tmp_path):
        secret = tmp_path / "outside.pdf"
        secret.write_bytes(_pdf_bytes())
        topic_id = _topic(db)
        record = _v1_record()
        _mark_pdf_available(record, "art_aaa")
        pack = _write_v1_pack(tmp_path, [record])
        art_dir = pack / "artifacts" / "spc_0001" / "pdf" / "art_aaa"
        art_dir.mkdir(parents=True)
        (art_dir / "article.pdf").symlink_to(secret)

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            annotate=False,
            text_extractor=_v1_matching_extractor,
        )

        assert report.pdfs_imported == 0
        assert report.pdfs_missing == 1

    def test_artifact_markdown_is_imported(self, db, tmp_path):
        topic_id = _topic(db)
        record = _v1_record()
        record["fulltext"]["parse"] = {
            "status": "available",
            "artifact": {"artifact_id": "art_md1", "kind": "mineru_fulltext"},
            "error": None,
        }
        pack = _write_v1_pack(tmp_path, [record])
        art_dir = pack / "artifacts" / "spc_0001" / "fulltext" / "art_md1"
        art_dir.mkdir(parents=True)
        (art_dir / "document.md").write_text("# Parsed paper\n", encoding="utf-8")
        (art_dir / "content-list.json").write_text(
            '[{"type": "text", "text": "Parsed paper", "page_idx": 0}]',
            encoding="utf-8",
        )

        report = import_seed_pack(
            db,
            pack,
            topic_id,
            download_dir=tmp_path / "dl",
            artifacts_root=tmp_path / "artifacts",
            annotate=False,
        )

        assert report.parse_imported == 1
        assert report.parse_missing == 0
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT metadata FROM paper_artifacts"
                " WHERE artifact_type = 'paper_parse_artifact'"
            ).fetchone()
            payload = json.loads(row["metadata"])
            assert payload["schema_version"] == "rh.paper_parse_artifact.v1"
            copied = Path(payload["markdown_path"])
            assert copied.read_text(encoding="utf-8") == "# Parsed paper\n"
            content_list = Path(payload["content_list_path"])
            assert content_list.name == "content_list.json"
            assert content_list.is_file()
        finally:
            conn.close()
