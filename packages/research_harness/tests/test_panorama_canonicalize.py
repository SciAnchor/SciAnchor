"""Tests for territory-map tag canonicalization (fake LLMs only)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.panorama.canonicalize import (
    _validate_mapping,
    canonicalize_tags,
)
from research_harness.panorama.store import PanoramaStore

SLUG = "agentic-eval"


class FakeLLM:
    """Returns a canned mapping per axis, keyed by the axis name in the prompt."""

    model = "fake-model"

    def __init__(self, by_axis: dict[str, dict[str, str]]):
        self._by_axis = by_axis
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        for axis, mapping in self._by_axis.items():
            if f'"{axis}" tags' in prompt:
                return json.dumps(mapping)
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")


def _build_store(tmp_path: Path) -> tuple[PanoramaStore, int]:
    store = PanoramaStore(tmp_path / "panorama")
    store.init()
    direction = store.get_or_create_direction(SLUG, "Agentic Evaluation")
    return store, direction


def _occupied_cell(
    store: PanoramaStore,
    direction: int,
    problem: str,
    mechanism: str,
    facet: str,
    n_claims: int = 1,
) -> int:
    cell_id = store.upsert_cell(direction, problem, mechanism, facet)
    for i in range(n_claims):
        claim_id = store.upsert_entity(
            direction,
            "claim",
            f"claim {problem}/{mechanism}/{facet}/{i}",
            source="extract",
        )
        store.occupy_cell(cell_id, claim_id)
    return cell_id


def test_dry_run_proposes_without_changing_cells(tmp_path: Path) -> None:
    store, direction = _build_store(tmp_path)
    _occupied_cell(
        store, direction, "paper-generation", "llm-agent-loop", "benchmark-eval"
    )
    _occupied_cell(store, direction, "paper-generation", "agent-loop", "benchmark-eval")
    llm = FakeLLM({"problem": {}, "mechanism": {"agent-loop": "llm-agent-loop"}})
    result = canonicalize_tags(store, direction, llm=llm)
    assert result["proposed"]["mechanism"] == {"agent-loop": "llm-agent-loop"}
    assert result["applied"] is False
    assert result["cells_merged"] == 0
    assert len(store.cells(direction)) == 2  # untouched


def test_apply_merges_cells_and_moves_occupants(tmp_path: Path) -> None:
    store, direction = _build_store(tmp_path)
    keep = _occupied_cell(
        store, direction, "paper-generation", "llm-agent-loop", "benchmark-eval", 2
    )
    _occupied_cell(
        store, direction, "paper-generation", "agent-loop", "benchmark-eval", 1
    )
    llm = FakeLLM({"problem": {}, "mechanism": {"agent-loop": "llm-agent-loop"}})
    result = canonicalize_tags(store, direction, llm=llm, apply=True)
    assert result["cells_merged"] == 1
    assert result["claims_moved"] == 1
    cells = store.cells(direction)
    assert len(cells) == 1
    assert cells[0]["mechanism"] == "llm-agent-loop"
    occupants = store.cell_occupants(keep)
    assert len(occupants) == 3
    # 3 occupants => strength recomputed to "strong"
    assert cells[0]["evidence_strength"] == "strong"
    assert store.get_meta(f"canonicalize:last_run:{direction}") is not None


def test_out_of_vocabulary_and_identity_proposals_are_dropped(tmp_path: Path) -> None:
    store, direction = _build_store(tmp_path)
    _occupied_cell(store, direction, "rigor-audit", "tree-search", "theoretical")
    _occupied_cell(store, direction, "rigor-audit", "tree-searching", "theoretical")
    llm = FakeLLM(
        {
            "problem": {},
            "mechanism": {
                "tree-searching": "tree-search",  # valid
                "made-up-tag": "tree-search",  # variant not in vocab
                "tree-search": "invented-canon",  # canonical not in vocab
            },
        }
    )
    result = canonicalize_tags(store, direction, llm=llm, apply=True)
    assert result["proposed"]["mechanism"] == {"tree-searching": "tree-search"}
    assert sorted(result["dropped"]["mechanism"]) == ["made-up-tag", "tree-search"]
    assert len(store.cells(direction)) == 1


def test_chain_mappings_resolve_to_final_canonical() -> None:
    vocabulary = {"a", "b", "c"}
    mapping, dropped = _validate_mapping({"a": "b", "b": "c"}, vocabulary)
    assert mapping == {"a": "c", "b": "c"}
    assert dropped == []


def test_single_tag_axis_makes_no_llm_call(tmp_path: Path) -> None:
    store, direction = _build_store(tmp_path)
    _occupied_cell(store, direction, "rigor-audit", "tree-search", "theoretical")
    llm = FakeLLM({"problem": {}, "mechanism": {}})
    result = canonicalize_tags(store, direction, llm=llm)
    assert llm.prompts == []
    assert result["proposed"] == {"problem": {}, "mechanism": {}}


def test_extraction_prompt_carries_known_tags(tmp_path: Path) -> None:
    """The extract batch must inject the existing vocabulary into its prompt."""
    from research_harness.panorama.extract import extract_claims

    store, direction = _build_store(tmp_path)
    _occupied_cell(
        store, direction, "paper-generation", "llm-agent-loop", "benchmark-eval"
    )
    abstract = (
        "Automated scientific discovery has advanced quickly in recent years. "
        "We present a system that generates full research papers end to end "
        "with an autonomous agent loop, evaluated on a reviewer benchmark "
        "with strong baselines and released code for reproducibility."
    )
    store.upsert_entity(
        direction,
        "paper",
        "Alpha Agent Paper",
        attrs={"abstract": abstract},
        pool_paper_id=101,
    )
    prompts: list[str] = []

    def fake_llm(prompt: str) -> str:
        prompts.append(prompt)
        return "[]"

    extract_claims(store, direction, llm=fake_llm)
    assert len(prompts) == 1
    assert "paper-generation" in prompts[0]
    assert "llm-agent-loop" in prompts[0]
