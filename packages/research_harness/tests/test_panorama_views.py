"""Tests for the panorama L2 view layer (views + context pack)."""

from __future__ import annotations

from pathlib import Path

from research_harness.panorama.context_pack import (
    build_context_pack,
    write_context_pack,
)
from research_harness.panorama.store import PanoramaStore
from research_harness.panorama.views import GENERATED_HEADER, generate_views

SLUG = "agentic-eval"


def _strip_timestamp(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("<!-- generated_at:")
    )


def _build_store(tmp_path: Path) -> tuple[PanoramaStore, dict[str, int]]:
    store = PanoramaStore(tmp_path / "panorama")
    store.init()
    direction = store.get_or_create_direction(
        SLUG, "Agentic Evaluation", description="Test direction for L2 views."
    )
    ids: dict[str, int] = {"direction": direction}

    ids["system"] = store.upsert_entity(
        direction,
        "system",
        "AgentBoard X",
        summary="An agent evaluation harness with audit probes.",
        ext_ids={"github": "example/agentboard-x"},
        attrs={"language": "python"},
    )
    ids["benchmark"] = store.upsert_entity(
        direction,
        "benchmark",
        "RigorBench",
        summary="Benchmark of rigor perturbation probes.",
    )
    ids["mechanism"] = store.upsert_entity(
        direction,
        "mechanism",
        "Perturbation Factory",
        summary="Gold-standard perturbation generator.",
    )
    ids["claim_a"] = store.upsert_entity(
        direction,
        "claim",
        "Perturbations expose hollow rigor",
        summary="Positive transfer claim.",
    )
    ids["claim_b"] = store.upsert_entity(
        direction,
        "claim",
        "Perturbations do not transfer",
        summary="Negative transfer claim.",
    )
    ids["dataset"] = store.upsert_entity(
        direction,
        "dataset",
        "ErrataSet",
        summary="Real errata migration dataset used for held-out checks.",
    )
    for index in range(3):
        ids[f"paper_{index}"] = store.upsert_entity(
            direction,
            "paper",
            f"Survey Paper {index}",
            summary=(
                f"Paper number {index} with a deliberately long abstract-style "
                "summary so that trimming the paper section reclaims enough "
                "characters to matter for the truncation test."
            ),
            ext_ids={"arxiv": f"2401.0000{index}"},
        )

    store.add_edge(direction, ids["system"], ids["benchmark"], "evaluates_on")
    store.add_edge(direction, ids["claim_a"], ids["claim_b"], "contradicts")

    store.add_anchor(
        "entity",
        ids["system"],
        keywords="agents, evaluation",
        summary="Anchor summary for the harness.",
        insight="Audit probes are free signal.",
        quote="verbatim harness quote",
        source_ref="L0/sha256-abc#p3",
    )

    ids["cell_open"] = store.upsert_cell(
        direction, "rigor audit", "perturbation", "benchmark", status="open"
    )
    ids["cell_occupied"] = store.upsert_cell(
        direction, "rigor audit", "prm", "benchmark", evidence_strength="strong"
    )
    store.occupy_cell(ids["cell_occupied"], ids["claim_a"])
    ids["cell_contested"] = store.upsert_cell(
        direction,
        "format tax",
        "draft-conditioning",
        "",
        evidence_strength="weak",
        status="contested",
    )
    store.occupy_cell(ids["cell_contested"], ids["claim_a"])
    store.occupy_cell(ids["cell_contested"], ids["claim_b"])

    store.record_verdict(
        direction,
        "Perturbation factory is novel",
        "novel",
        cell_id=ids["cell_open"],
        tool="gap_ground_verify",
    )
    return store, ids


def _vault_files(store: PanoramaStore) -> set[str]:
    return {
        str(path.relative_to(store.vault_dir)) for path in store.vault_dir.rglob("*.md")
    }


def test_generate_views_writes_expected_files_with_headers(tmp_path):
    store, _ = _build_store(tmp_path)
    counts = generate_views(store, SLUG)

    files = _vault_files(store)
    assert "00-overview.md" in files
    assert "frontier.md" in files
    # One page per paged-kind entity: system, benchmark, mechanism, 2 claims.
    entity_pages = {f for f in files if f.startswith("entities/")}
    assert len(entity_pages) == 5
    assert counts == {"files_written": 7, "entity_pages": 5, "stale_removed": 0}
    # No pages for paper/dataset kinds.
    assert not any("/paper/" in f or "/dataset/" in f for f in entity_pages)

    for rel in files:
        text = (store.vault_dir / rel).read_text(encoding="utf-8")
        assert text.startswith(GENERATED_HEADER), rel
        assert f"<!-- direction: {SLUG} -->" in text

    overview = (store.vault_dir / "00-overview.md").read_text(encoding="utf-8")
    assert "| Entities (total) | 9 |" in overview
    assert "### system (1)" in overview
    assert "entities/system/agentboard-x-" in overview


def test_entity_page_renders_edges_and_anchor_backlink(tmp_path):
    store, ids = _build_store(tmp_path)
    generate_views(store, SLUG)

    system_dir = store.vault_dir / "entities" / "system"
    (page,) = list(system_dir.glob("*.md"))
    text = page.read_text(encoding="utf-8")
    assert page.name.endswith(f"-{ids['system']}.md")
    assert "### evaluates_on" in text
    assert "RigorBench" in text
    assert "| language | python |" in text
    assert "| github | example/agentboard-x |" in text
    assert "> **Quote:**" in text
    assert "L0/sha256-abc#p3" in text


def test_generate_views_is_idempotent_except_timestamp(tmp_path):
    store, _ = _build_store(tmp_path)
    generate_views(store, SLUG)
    first = {
        rel: _strip_timestamp((store.vault_dir / rel).read_text(encoding="utf-8"))
        for rel in _vault_files(store)
    }
    counts = generate_views(store, SLUG)
    second = {
        rel: _strip_timestamp((store.vault_dir / rel).read_text(encoding="utf-8"))
        for rel in _vault_files(store)
    }
    assert counts["stale_removed"] == 0
    assert first == second


def test_generate_views_removes_stale_entity_pages(tmp_path):
    store, ids = _build_store(tmp_path)
    generate_views(store, SLUG)
    claim_pages = list((store.vault_dir / "entities" / "claim").glob("*.md"))
    assert len(claim_pages) == 2

    # The store has no entity-delete API yet; drop the row directly.
    conn = store.connect()
    try:
        conn.execute("DELETE FROM entities WHERE id = ?", (ids["claim_b"],))
        conn.commit()
    finally:
        conn.close()

    counts = generate_views(store, SLUG)
    assert counts["stale_removed"] == 1
    remaining = list((store.vault_dir / "entities" / "claim").glob("*.md"))
    assert len(remaining) == 1
    assert remaining[0].name.endswith(f"-{ids['claim_a']}.md")
    # The contradicts edge cascaded away with the entity.
    frontier = (store.vault_dir / "frontier.md").read_text(encoding="utf-8")
    assert "No live `contradicts` edges" in frontier


def test_frontier_lists_open_cell_verdicts_and_contradiction(tmp_path):
    store, _ = _build_store(tmp_path)
    generate_views(store, SLUG)
    frontier = (store.vault_dir / "frontier.md").read_text(encoding="utf-8")

    assert "## Open cells" in frontier
    assert "**rigor audit × perturbation × benchmark**" in frontier
    assert "## Contested cells" in frontier
    assert "Perturbations do not transfer" in frontier
    # Weak bucket picks up the contested weak-evidence cell.
    assert "format tax × draft-conditioning" in frontier
    # Verdict ledger row. A cell-scoped verdict is live, and the row now carries
    # the scope it was decided under so a reader can tell what it is about.
    assert "## Verdict ledger (live)" in frontier
    assert (
        "| Perturbation factory is novel | novel | cell: cell:1 | gap_ground_verify |"
        in frontier
    )
    # Contradiction with both endpoint names on one line.
    line = next(
        row
        for row in frontier.splitlines()
        if "contradicts" in row and row.startswith("- ")
    )
    assert "Perturbations expose hollow rigor" in line
    assert "Perturbations do not transfer" in line


def test_context_pack_contains_territory_table_and_digests(tmp_path):
    store, _ = _build_store(tmp_path)
    pack = build_context_pack(store, SLUG)

    assert pack.startswith("# Context pack — Agentic Evaluation (agentic-eval)")
    assert "| Problem | Mechanism | Facet | Status | Strength " in pack
    assert "| rigor audit | perturbation | benchmark | open |" in pack
    assert "### Latest verdicts" in pack
    assert "- [novel] Perturbation factory is novel" in pack
    assert "### paper" in pack
    assert "[arxiv:2401.00000]" in pack
    # Papers come after every non-paper kind.
    assert pack.index("### system") < pack.index("### paper")
    assert pack.index("### dataset") < pack.index("### paper")
    assert "Truncated" not in pack


def test_context_pack_respects_max_chars_with_truncation_note(tmp_path):
    store, _ = _build_store(tmp_path)
    full = build_context_pack(store, SLUG)
    cap = len(full) - 100  # force at least one paper entry to be dropped

    pack = build_context_pack(store, SLUG, max_chars=cap)
    assert len(pack) <= cap
    assert "_Truncated to fit" in pack
    assert "| Problem | Mechanism | Facet | Status | Strength " in pack

    # Degenerate cap still holds the invariant.
    tiny = build_context_pack(store, SLUG, max_chars=400)
    assert len(tiny) <= 400
    assert "Truncated" in tiny


def test_write_context_pack_adds_generated_header(tmp_path):
    store, _ = _build_store(tmp_path)
    path = write_context_pack(store, SLUG)
    assert path == store.vault_dir / "context-pack.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith(GENERATED_HEADER)
    assert f"<!-- direction: {SLUG} -->" in text
    assert "# Context pack — Agentic Evaluation" in text
