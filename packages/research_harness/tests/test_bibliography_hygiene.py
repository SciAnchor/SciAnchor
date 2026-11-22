"""Tests for the write-gate bibliography hygiene lint (backlog Q3, 2026-07-04)."""

from __future__ import annotations

from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.orchestrator.invariants import (
    InvariantChecker,
    bibliography_hygiene_findings,
)


CLEAN_BIB = r"""
@article{vaswani2017attention,
  author  = {Vaswani, Ashish and Shazeer, Noam},
  title   = {Attention Is All You Need},
  journal = {Advances in Neural Information Processing Systems},
  year    = {2017},
  doi     = {10.5555/3295222.3295349},
}
"""

DEFECTIVE_BIB = r"""
@article{chuncheon2025impact,
  title   = {The Impact of a Regional Festival},
  journal = {Journal of Regional Studies},
  year    = {2025},
}

@article{li2024stkg,
  author  = {Li, Wei},
  title   = {Spatiotemporal Knowledge Graphs},
  journal = {IEEE Transactions on Knowledge and Data Engineering},
  year    = {2024},
  doi     = {10.48550/arXiv.2401.00001},
}

@article{rizvi2022aviation,
  author  = {Rizvi, Sana},
  title   = {Aviation Demand Forecasting},
  journal = {Transportation Research},
  year    = {2019},
}
"""


class TestBibliographyHygieneFindings:
    def test_clean_bibliography_yields_no_findings(self):
        assert bibliography_hygiene_findings(CLEAN_BIB) == []

    def test_flags_authorless_journal_and_key_year_defects(self):
        findings = bibliography_hygiene_findings(DEFECTIVE_BIB)
        by_code = {item["code"]: item for item in findings}

        assert by_code["authorless_entry"]["entry"] == "chuncheon2025impact"
        assert by_code["journal_with_arxiv_doi"]["entry"] == "li2024stkg"
        assert by_code["key_year_mismatch"]["entry"] == "rizvi2022aviation"
        assert "2022" in by_code["key_year_mismatch"]["message"]
        assert "2019" in by_code["key_year_mismatch"]["message"]

    def test_arxiv_entries_with_arxiv_journal_are_allowed(self):
        bib = r"""
@article{smith2024preprint,
  author  = {Smith, Jo},
  title   = {A Preprint},
  journal = {arXiv preprint arXiv:2401.00001},
  year    = {2024},
  doi     = {10.48550/arXiv.2401.00001},
}
"""
        assert bibliography_hygiene_findings(bib) == []

    def test_misc_entries_are_not_flagged_as_authorless(self):
        bib = r"""
@misc{dataset2024,
  title = {Public Mobility Dataset},
  year  = {2024},
}
"""
        assert bibliography_hygiene_findings(bib) == []

    def test_handwritten_thebibliography_is_flagged(self):
        tex = r"\begin{thebibliography}{99}\bibitem{a} A.\end{thebibliography}"
        findings = bibliography_hygiene_findings("", tex)
        assert [item["code"] for item in findings] == ["handwritten_thebibliography"]

    def test_malformed_bib_never_raises(self):
        assert bibliography_hygiene_findings("@article{broken", "") == []
        assert bibliography_hygiene_findings("not bibtex at all") == []


def _create_topic(db, name: str) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (name, "topic for bibliography hygiene tests", "HSSC"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


class TestBibliographyHygieneInvariant:
    def test_flags_defective_bundle_bibliography(self, db, tmp_path):
        topic_id = _create_topic(db, "bib-hygiene-defective")
        bib = tmp_path / "refs.bib"
        bib.write_text(DEFECTIVE_BIB, encoding="utf-8")
        ArtifactManager(db).record(
            topic_id=topic_id,
            stage="write",
            artifact_type="final_bundle",
            title="Final Bundle",
            payload={"files": {"bib": str(bib)}},
        )

        violations = InvariantChecker(db).check_bibliography_hygiene(topic_id, "write")

        assert {v.metadata["code"] for v in violations} == {
            "authorless_entry",
            "journal_with_arxiv_doi",
            "key_year_mismatch",
        }
        assert all(v.severity == "medium" for v in violations)
        assert all(v.check == "bibliography_hygiene" for v in violations)

    def test_clean_bundle_and_non_write_stages_pass(self, db, tmp_path):
        topic_id = _create_topic(db, "bib-hygiene-clean")
        bib = tmp_path / "refs.bib"
        bib.write_text(CLEAN_BIB, encoding="utf-8")
        ArtifactManager(db).record(
            topic_id=topic_id,
            stage="write",
            artifact_type="final_bundle",
            title="Final Bundle",
            payload={"files": {"bib": str(bib)}},
        )

        checker = InvariantChecker(db)
        assert checker.check_bibliography_hygiene(topic_id, "write") == []
        assert checker.check_bibliography_hygiene(topic_id, "build") == []

    def test_bundle_without_bib_or_tex_is_ignored(self, db):
        topic_id = _create_topic(db, "bib-hygiene-missing")
        ArtifactManager(db).record(
            topic_id=topic_id,
            stage="write",
            artifact_type="final_bundle",
            title="Final Bundle",
            payload={"files": {}},
        )

        assert InvariantChecker(db).check_bibliography_hygiene(topic_id, "write") == []
