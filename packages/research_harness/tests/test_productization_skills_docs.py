from __future__ import annotations

from pathlib import Path


def test_lg10_productization_boundary_is_documented_as_gate_bound_skills_docs():
    repo_root = Path(__file__).resolve().parents[3]
    docs = (repo_root / "docs" / "skills" / "README.md").read_text(encoding="utf-8")

    assert "lg10-public-productization-boundary" in docs
    assert "lg10_productization_boundary.v1" in docs
    assert "one_public_surface_per_gate_slice" in docs
    assert "opt-in" in docs
    assert "backwards-compatible" in docs
    assert "LG8/LG9 evidence is a prerequisite, not approval to productize" in docs
    assert "CLI, MCP, HTTP, and Python facade" in docs
    assert "skills/docs boundary preview" in docs
    assert "does not publish a Zotero integration" in docs
    assert "does not change doctor or showcase behavior" in docs
    assert "release-ready" not in docs.lower()
    assert "production-ready public product" not in docs.lower()
