"""Tests for the panorama LLM claim-extraction batch (fake LLMs only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_harness.panorama.extract import (
    DEFAULT_PROMPT_TEMPLATE,
    extract_claims,
)
from research_harness.panorama.store import PanoramaStore

SLUG = "agentic-eval"

ABSTRACT_ALPHA = (
    "Automated scientific discovery has advanced quickly in recent years. "
    "We present a system that generates full research papers end to end "
    "with an autonomous agent loop. Across 51 generated manuscripts our "
    "pipeline improves acceptance-style scores by 18 percent over strong "
    "baselines on a reviewer benchmark. We release code and evaluation "
    "scripts to support reproducible research."
)

ABSTRACT_BETA = (
    "Large language model agents still hallucinate contributions when "
    "drafting manuscripts. We introduce a planning stage that decomposes "
    "paper generation into verifiable subtasks executed by an agent loop. "
    "On a benchmark of 200 drafting tasks the planner reduces fabricated "
    "citations by half relative to a single-pass baseline while keeping "
    "fluency unchanged across every evaluated domain."
)

ABSTRACT_GAMMA = (
    "Rigor auditing of machine learning papers is usually manual and slow. "
    "We prove that a tree-search procedure over review rubrics recovers "
    "every injected flaw class under mild assumptions on rubric coverage. "
    "Our analysis gives the first completeness guarantee for automated "
    "rigor audits and clarifies when searching deeper cannot help, with "
    "worked derivations for three canonical rubric families."
)


class FakeLLM:
    """Deterministic fake: routes by title marker found in the prompt."""

    model = "fake-model"

    def __init__(self, responses: dict[str, Any]):
        self._responses = responses
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        for marker, response in self._responses.items():
            if marker in prompt:
                if isinstance(response, str):
                    return response
                return json.dumps(response)
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")


def _claim(
    claim: str,
    problem: str,
    mechanism: str,
    facet: str,
    quote: str,
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "claim": claim,
        "problem": problem,
        "mechanism": mechanism,
        "evidence_facet": facet,
        "quote": quote,
        "confidence": confidence,
    }


ALPHA_CLAIM = _claim(
    "An autonomous agent loop can generate full research papers end to end.",
    "paper-generation",
    "llm-agent-loop",
    "benchmark-eval",
    "generates full research papers end to end with an autonomous agent loop",
    confidence=0.9,
)

# Quote differs from the abstract in case and internal whitespace only.
BETA_CLAIM = _claim(
    "Decomposing paper generation into verifiable subtasks halves fabricated "
    "citations.",
    "paper-generation",
    "llm-agent-loop",
    "benchmark-eval",
    "THE PLANNER  reduces fabricated citations by half",
    confidence=0.8,
)

GAMMA_CLAIM = _claim(
    "Tree search over review rubrics has a completeness guarantee for rigor audits.",
    "rigor-audit",
    "tree-search",
    "theoretical",
    "the first completeness guarantee for automated rigor audits",
    confidence=0.7,
)


def _build_store(tmp_path: Path) -> tuple[PanoramaStore, int]:
    store = PanoramaStore(tmp_path / "panorama")
    store.init()
    direction = store.get_or_create_direction(SLUG, "Agentic Evaluation")
    return store, direction


def _add_papers(store: PanoramaStore, direction: int) -> dict[str, int]:
    return {
        "alpha": store.upsert_entity(
            direction,
            "paper",
            "Alpha Agent Paper",
            attrs={"abstract": ABSTRACT_ALPHA},
            pool_paper_id=101,
        ),
        "beta": store.upsert_entity(
            direction,
            "paper",
            "Beta Agent Paper",
            summary=ABSTRACT_BETA,
            ext_ids={"arxiv": "2402.00002"},
        ),
        "gamma": store.upsert_entity(
            direction,
            "paper",
            "Gamma Theory Paper",
            attrs={"abstract": ABSTRACT_GAMMA},
        ),
    }


def _cell_by_key(
    store: PanoramaStore, direction: int, problem: str, mechanism: str, facet: str
) -> dict[str, Any]:
    for cell in store.cells(direction):
        if (cell["problem"], cell["mechanism"], cell["evidence_facet"]) == (
            problem,
            mechanism,
            facet,
        ):
            return cell
    raise AssertionError(f"cell not found: {problem} x {mechanism} x {facet}")


def test_happy_path_writes_claims_edges_anchors_and_cells(tmp_path):
    store, direction = _build_store(tmp_path)
    papers = _add_papers(store, direction)
    store.upsert_entity(
        direction, "paper", "Delta Short Paper", summary="Too short to extract."
    )
    fake = FakeLLM(
        {
            "Alpha Agent Paper": [ALPHA_CLAIM],
            "Beta Agent Paper": [BETA_CLAIM],
            "Gamma Theory Paper": [GAMMA_CLAIM],
        }
    )

    result = extract_claims(store, direction, llm=fake)

    assert result == {
        "papers_seen": 4,
        "papers_extracted": 3,
        "papers_skipped": 1,
        "claims_written": 3,
        "cells_touched": 2,
        "dropped_bad_quote": 0,
        "errors": [],
    }
    assert fake.calls == 3

    claims = store.entities(direction, "claim")
    assert len(claims) == 3
    by_summary = {c["summary"]: c for c in claims}
    for claim in claims:
        assert claim["source"] == "extract"
        assert claim["extractor_model"] == "fake-model"
    alpha_claim = by_summary[ALPHA_CLAIM["claim"]]
    assert alpha_claim["confidence"] == 0.9
    assert alpha_claim["name"] == ALPHA_CLAIM["claim"][:120]

    claim_edges = [e for e in store.edges(direction) if e["rel"] == "claims"]
    assert len(claim_edges) == 3
    edge_map = {e["src_id"]: e for e in claim_edges}
    assert edge_map[papers["alpha"]]["dst_id"] == alpha_claim["id"]
    assert edge_map[papers["alpha"]]["confidence"] == 0.9
    assert edge_map[papers["beta"]]["confidence"] == 0.8

    (alpha_anchor,) = store.anchors_for("entity", alpha_claim["id"])
    assert alpha_anchor["quote"] == ALPHA_CLAIM["quote"]
    assert alpha_anchor["summary"] == ALPHA_CLAIM["claim"]
    assert alpha_anchor["keywords"] == "paper-generation llm-agent-loop"
    assert alpha_anchor["source_ref"] == "pool:paper:101"
    beta_claim = by_summary[BETA_CLAIM["claim"]]
    (beta_anchor,) = store.anchors_for("entity", beta_claim["id"])
    assert beta_anchor["source_ref"] == "arxiv:2402.00002"
    gamma_claim = by_summary[GAMMA_CLAIM["claim"]]
    (gamma_anchor,) = store.anchors_for("entity", gamma_claim["id"])
    assert gamma_anchor["source_ref"] == f"entity:{papers['gamma']}"

    shared = _cell_by_key(
        store, direction, "paper-generation", "llm-agent-loop", "benchmark-eval"
    )
    assert shared["evidence_strength"] == "moderate"
    assert shared["status"] == "occupied"
    assert len(store.cell_occupants(shared["id"])) == 2
    solo = _cell_by_key(store, direction, "rigor-audit", "tree-search", "theoretical")
    assert solo["evidence_strength"] == "weak"
    assert solo["status"] == "occupied"

    assert store.get_meta(f"extract:last_run:{direction}") is not None


def test_cell_strength_escalates_to_strong_across_runs(tmp_path):
    store, direction = _build_store(tmp_path)
    _add_papers(store, direction)
    first = FakeLLM(
        {
            "Alpha Agent Paper": [ALPHA_CLAIM],
            "Beta Agent Paper": [BETA_CLAIM],
            "Gamma Theory Paper": [GAMMA_CLAIM],
        }
    )
    extract_claims(store, direction, llm=first)

    # A late-arriving paper lands in the already-moderate shared cell.
    store.upsert_entity(
        direction,
        "paper",
        "Epsilon Agent Paper",
        attrs={"abstract": ABSTRACT_ALPHA},
    )
    epsilon_claim = dict(ALPHA_CLAIM)
    epsilon_claim["claim"] = (
        "Reviewer-benchmark scores rise when an agent loop drafts papers."
    )
    second = FakeLLM({"Epsilon Agent Paper": [epsilon_claim]})

    result = extract_claims(store, direction, llm=second)

    assert second.calls == 1  # earlier papers skipped, no re-extraction
    assert result["papers_skipped"] == 3
    assert result["claims_written"] == 1
    shared = _cell_by_key(
        store, direction, "paper-generation", "llm-agent-loop", "benchmark-eval"
    )
    assert shared["evidence_strength"] == "strong"
    assert len(store.cell_occupants(shared["id"])) == 3


def test_malformed_json_records_error_and_continues(tmp_path):
    store, direction = _build_store(tmp_path)
    papers = _add_papers(store, direction)
    fake = FakeLLM(
        {
            "Alpha Agent Paper": "Sorry, I cannot produce structured output.",
            "Beta Agent Paper": [BETA_CLAIM],
            "Gamma Theory Paper": [GAMMA_CLAIM],
        }
    )

    result = extract_claims(store, direction, llm=fake)

    assert result["papers_extracted"] == 2
    assert result["claims_written"] == 2
    assert len(result["errors"]) == 1
    assert result["errors"][0]["paper_id"] == papers["alpha"]
    summaries = {c["summary"] for c in store.entities(direction, "claim")}
    assert BETA_CLAIM["claim"] in summaries
    assert GAMMA_CLAIM["claim"] in summaries


def test_quote_not_in_abstract_is_dropped(tmp_path):
    store, direction = _build_store(tmp_path)
    store.upsert_entity(
        direction, "paper", "Alpha Agent Paper", attrs={"abstract": ABSTRACT_ALPHA}
    )
    bad = dict(ALPHA_CLAIM)
    bad["claim"] = "A claim resting on an invented quotation."
    bad["quote"] = "this sentence never appears in the abstract"
    fake = FakeLLM({"Alpha Agent Paper": [ALPHA_CLAIM, bad]})

    result = extract_claims(store, direction, llm=fake)

    assert result["claims_written"] == 1
    assert result["dropped_bad_quote"] == 1
    assert result["errors"] == []
    (claim,) = store.entities(direction, "claim")
    assert claim["summary"] == ALPHA_CLAIM["claim"]


def test_only_missing_rerun_makes_zero_llm_calls(tmp_path):
    store, direction = _build_store(tmp_path)
    _add_papers(store, direction)
    responses = {
        "Alpha Agent Paper": [ALPHA_CLAIM],
        "Beta Agent Paper": [BETA_CLAIM],
        "Gamma Theory Paper": [GAMMA_CLAIM],
    }
    extract_claims(store, direction, llm=FakeLLM(responses))
    assert len(store.entities(direction, "claim")) == 3

    rerun = FakeLLM(responses)
    result = extract_claims(store, direction, llm=rerun)

    assert rerun.calls == 0
    assert result["papers_extracted"] == 0
    assert result["papers_skipped"] == 3
    assert result["claims_written"] == 0
    assert len(store.entities(direction, "claim")) == 3

    forced = FakeLLM(responses)
    forced_result = extract_claims(store, direction, llm=forced, only_missing=False)
    assert forced.calls == 3
    # upsert_entity dedupes identical claims, so nothing is duplicated.
    assert forced_result["claims_written"] == 3
    assert len(store.entities(direction, "claim")) == 3


def test_tag_normalization_and_facet_fallback(tmp_path):
    store, direction = _build_store(tmp_path)
    store.upsert_entity(
        direction, "paper", "Alpha Agent Paper", attrs={"abstract": ABSTRACT_ALPHA}
    )
    messy = _claim(
        "An autonomous agent loop can generate full research papers end to end.",
        "  Paper  Generation ",
        "LLM_Agent Loop",
        "Benchmark-Eval",
        ALPHA_CLAIM["quote"],
    )
    weird_facet = _claim(
        "Reviewer-style scores improve by 18 percent over strong baselines.",
        "x" * 60,  # over the 40-char tag cap
        "llm-agent-loop",
        "meta-analysis",  # not in the closed facet vocabulary
        "improves acceptance-style scores by 18 percent over strong baselines",
    )
    fake = FakeLLM({"Alpha Agent Paper": [messy, weird_facet]})

    result = extract_claims(store, direction, llm=fake)

    assert result["claims_written"] == 2
    normalized = _cell_by_key(
        store, direction, "paper-generation", "llm-agent-loop", "benchmark-eval"
    )
    assert normalized["status"] == "occupied"
    fallback = [c for c in store.cells(direction) if c["evidence_facet"] == "none"]
    assert len(fallback) == 1
    assert fallback[0]["problem"] == "x" * 40
    assert fallback[0]["mechanism"] == "llm-agent-loop"


def test_limit_caps_llm_calls_and_batch_is_resumable(tmp_path):
    store, direction = _build_store(tmp_path)
    _add_papers(store, direction)
    responses = {
        "Alpha Agent Paper": [ALPHA_CLAIM],
        "Beta Agent Paper": [BETA_CLAIM],
        "Gamma Theory Paper": [GAMMA_CLAIM],
    }
    first = FakeLLM(responses)

    result = extract_claims(store, direction, llm=first, limit=2)

    assert first.calls == 2
    assert result["papers_extracted"] == 2
    assert len(store.entities(direction, "claim")) == 2

    second = FakeLLM(responses)
    resumed = extract_claims(store, direction, llm=second)
    assert second.calls == 1  # only the remaining paper is extracted
    assert resumed["papers_extracted"] == 1
    assert len(store.entities(direction, "claim")) == 3


def test_max_claims_per_paper_truncates(tmp_path):
    store, direction = _build_store(tmp_path)
    store.upsert_entity(
        direction, "paper", "Alpha Agent Paper", attrs={"abstract": ABSTRACT_ALPHA}
    )
    variants = []
    for index in range(4):
        variant = dict(ALPHA_CLAIM)
        variant["claim"] = f"Distinct contribution-level claim number {index}."
        variants.append(variant)
    fake = FakeLLM({"Alpha Agent Paper": variants})

    result = extract_claims(store, direction, llm=fake, max_claims_per_paper=2)

    assert result["claims_written"] == 2
    assert len(store.entities(direction, "claim")) == 2


def test_prompt_template_is_exported_and_used(tmp_path):
    assert "{title}" in DEFAULT_PROMPT_TEMPLATE
    assert "{abstract}" in DEFAULT_PROMPT_TEMPLATE
    assert "{max_claims}" in DEFAULT_PROMPT_TEMPLATE

    store, direction = _build_store(tmp_path)
    store.upsert_entity(
        direction, "paper", "Alpha Agent Paper", attrs={"abstract": ABSTRACT_ALPHA}
    )
    fake = FakeLLM({"Alpha Agent Paper": [ALPHA_CLAIM]})
    extract_claims(store, direction, llm=fake, max_claims_per_paper=2)

    (prompt,) = fake.prompts
    assert "Alpha Agent Paper" in prompt
    assert ABSTRACT_ALPHA in prompt
    assert "at most 2 objects" in prompt
