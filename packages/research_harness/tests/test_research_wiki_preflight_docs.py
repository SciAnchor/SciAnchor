from __future__ import annotations

from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "skills").exists()
)


def _skill_text(name: str) -> str:
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_research_workflow_skills_require_wiki_context_pack_preflight() -> None:
    required = {
        "research-harness": ("rh-workspace/", "wiki-context-pack"),
        "paper-writing": ("paper_wiki_status", "wiki_context_pack.v1"),
        "gap-analysis": ("paper_wiki_status", "Research Wiki"),
        "section-drafting": ("paper_wiki_status", "wiki_context_pack.v1"),
    }

    for skill_name, fragments in required.items():
        text = _skill_text(skill_name)
        assert "Research Wiki Context Preflight" in text
        for fragment in fragments:
            assert fragment in text
        assert "DESA" not in text
        assert "EventWiki" not in text


def test_research_harness_skill_forbids_silent_markdown_fallback() -> None:
    text = _skill_text("research-harness")

    assert "Do not silently substitute local markdown synthesis" in text
    assert "paper_wiki_status: loaded" in text
    assert "paper_wiki_status: unavailable" in text
    assert "paper_wiki_status: not_triggered" in text


def test_workflow_wrapper_contract_records_runtime_wiki_preflight() -> None:
    text = (REPO_ROOT / "docs/contracts/workflow-wrapper-contracts.md").read_text(
        encoding="utf-8"
    )

    assert "Research Wiki Preflight" in text
    assert "research_wiki_preflight.v1" in text
    assert "`analyze`, `propose`, `experiment`, and `write`" in text
    assert "paper_wiki_status" in text
    assert "must not be silently substituted" in text
