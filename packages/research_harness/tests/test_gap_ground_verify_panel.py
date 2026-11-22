"""Tests for the NOV02 opt-in judge arm (gap_ground_verify judge_mode="panel").

LLM layer is stubbed by monkeypatching _get_client/_client_chat (same pattern
as test_adversarial_review); retrieval is stubbed at primitives.impls.
Calibration evidence behind the arm: docs/innovation-kb/evidence/
calibration-baseline-2026-08-10.md and calibration-sciverse-arm-2026-08-12.md
(retrieved pre-emptors were 100% under-convicted to partially_occupied).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pytest

from research_harness.execution import llm_primitives
from research_harness._workflow.execution import prompts
from research_harness.execution.llm_primitives import (
    _coerce_narrowness,
    _merge_panel_judgements,
    gap_ground_verify,
)
from research_harness.storage.db import Database


@dataclass
class _Paper:
    title: str = "Killer Paper"
    abstract: str = "Does exactly the gap."
    snippet: str = ""
    year: int = 2026
    venue: str = "ICLR"
    arxiv_id: str = "2604.00001"
    doi: str = ""
    relevance_score: float = 1.0


@dataclass
class _SearchResult:
    papers: list = field(default_factory=lambda: [_Paper()])


class _FakeClient:
    model = "fake-judge"


def _vote(verdict: str, **over) -> dict:
    base = {
        "verdict": verdict,
        "grounded_confidence": 0.6,
        "reason": f"{verdict} because",
        "coverage_note": "bounded by retrieval",
        "occupying": [
            {"title": "Killer Paper", "verdict": "overlaps", "evidence": "q"}
        ],
        "narrowness": {"Killer Paper": "covers core mechanism; residual tiny"},
    }
    base.update(over)
    return base


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    return db


@pytest.fixture
def stubbed_retrieval(monkeypatch):
    import research_harness.primitives.impls as impls

    monkeypatch.setattr(
        impls, "paper_search", lambda **kwargs: _SearchResult(), raising=True
    )
    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: _FakeClient())


def _route_chat(monkeypatch, judge_responses: list[dict]):
    """Stub _client_chat: decompose -> no extra queries; judges -> queue.

    Returns the list of judge prompts seen, in call order.
    """
    judge_prompts: list[str] = []
    queue = list(judge_responses)

    def fake_chat(client, prompt: str) -> str:
        if '"queries"' in prompt:
            return json.dumps({"queries": []})
        judge_prompts.append(prompt)
        return json.dumps(queue.pop(0))

    monkeypatch.setattr(llm_primitives, "_client_chat", fake_chat)
    return judge_prompts


# --- single mode: regression, no behavior change -------------------------


def test_single_mode_one_judge_call_and_empty_new_fields(
    db, stubbed_retrieval, monkeypatch
):
    prompts_seen = _route_chat(monkeypatch, [_vote("partially_occupied")])

    out = gap_ground_verify(db=db, topic_id=1, gap="no prior work does X")

    assert len(prompts_seen) == 1  # exactly one judge call, as before
    assert "Your judging perspective" not in prompts_seen[0]
    assert out.verdict == "partially_occupied"
    assert out.judge_votes == []
    # single prompt never asks for narrowness -> additive field stays empty
    assert out.narrowness == {}


# --- panel mode: one judge per perspective, aggregation, new fields ------


def test_panel_mode_one_judge_per_perspective_and_majority_occupied(
    db, stubbed_retrieval, monkeypatch
):
    prompts_seen = _route_chat(
        monkeypatch,
        [
            _vote("occupied"),
            _vote("occupied"),
            _vote("partially_occupied"),
            _vote("open"),
        ],
    )

    out = gap_ground_verify(
        db=db, topic_id=1, gap="no prior work does X", judge_mode="panel"
    )

    assert len(prompts_seen) == len(prompts.GAP_JUDGE_PERSPECTIVES)
    perspectives = [
        re.search(r"Your judging perspective: (\w+)", p).group(1) for p in prompts_seen
    ]
    assert perspectives == list(prompts.GAP_JUDGE_PERSPECTIVES)
    # every panel prompt carries a decision rule
    assert all("DECISION RULE" in p for p in prompts_seen)
    assert out.verdict == "occupied"
    assert [v["perspective"] for v in out.judge_votes] == perspectives
    assert all(v["reason"] for v in out.judge_votes)
    assert out.narrowness == {"Killer Paper": "covers core mechanism; residual tiny"}
    # occupying merged + deduped across the judges
    assert len(out.occupying) == 1
    assert out.occupying[0].title == "Killer Paper"


def test_residual_depth_seat_asks_what_must_be_built_not_what_is_unclaimed():
    """The other three seats score a gap higher the narrower its residual is, which is
    the axis a journal's contribution seat scores in the opposite direction. This seat
    exists to ask the reverse question, so its prompt must not inherit the default rule
    that files residual reasoning away from the verdict."""
    shared = prompts.gap_ground_verify_panel_prompt("gap", "candidates", "narrowness")
    residual = prompts.gap_ground_verify_panel_prompt(
        "gap", "candidates", "residual_depth"
    )

    assert "residual variants belong to a separate residual analysis" in shared
    assert "residual variants belong to a separate residual analysis" not in residual
    assert "overrides the verdict glossary" in residual
    for built in (
        "must be learned",
        "must be solved for",
        "no closed form",
        "proof obligation",
    ):
        assert built in residual


# --- aggregation rule branches (pure) ------------------------------------


def _judgements(*verdicts: str) -> list[tuple[str, dict]]:
    names = ["coverage", "mechanism_equivalence", "narrowness"]
    return [(names[i], _vote(v)) for i, v in enumerate(verdicts)]


def test_aggregate_two_occupied_votes_win():
    merged, votes = _merge_panel_judgements(
        _judgements("occupied", "partially_occupied", "occupied")
    )
    assert merged["verdict"] == "occupied"
    assert len(votes) == 3


def test_aggregate_any_partial_without_majority_is_partial():
    merged, _ = _merge_panel_judgements(
        _judgements("occupied", "partially_occupied", "open")
    )
    assert merged["verdict"] == "partially_occupied"


def test_aggregate_all_open_is_open():
    merged, _ = _merge_panel_judgements(_judgements("open", "open", "open"))
    assert merged["verdict"] == "open"


def test_aggregate_mixed_without_partial_falls_back_to_inconclusive():
    merged, _ = _merge_panel_judgements(_judgements("occupied", "open", "inconclusive"))
    assert merged["verdict"] == "inconclusive"


def test_merge_keeps_strongest_occupying_verdict_and_mean_confidence():
    a = _vote(
        "occupied",
        grounded_confidence=0.9,
        occupying=[{"title": "Killer Paper", "verdict": "overlaps", "evidence": "x"}],
    )
    b = _vote(
        "occupied",
        grounded_confidence=0.3,
        occupying=[{"title": "Killer Paper", "verdict": "preempts", "evidence": "y"}],
    )
    merged, _ = _merge_panel_judgements([("coverage", a), ("narrowness", b)])
    assert merged["verdict"] == "occupied"
    assert merged["grounded_confidence"] == pytest.approx(0.6)
    assert merged["occupying"] == [
        {"title": "Killer Paper", "verdict": "preempts", "evidence": "y"}
    ]


def test_coerce_narrowness_accepts_dict_and_list_shapes():
    assert _coerce_narrowness({"T": " note "}) == {"T": "note"}
    assert _coerce_narrowness(
        [{"title": "T", "narrowness": "note"}, {"title": "", "narrowness": "x"}]
    ) == {"T": "note"}
    assert _coerce_narrowness("garbage") == {}
    assert _coerce_narrowness(None) == {}


# --- registry + CLI opt-in wiring ----------------------------------------


def test_registry_spec_exposes_optional_judge_mode_enum():
    from research_harness.primitives.registry import get_primitive_spec

    spec = get_primitive_spec("gap_ground_verify")
    prop = spec.input_schema["properties"]["judge_mode"]
    assert prop["enum"] == ["single", "panel"]
    assert prop["default"] == "single"
    assert "judge_mode" not in spec.input_schema["required"]


def test_calibrate_cli_passes_judge_mode_through(runner, tmp_path, monkeypatch):
    from research_harness import execution as execution_pkg
    from research_harness._workflow.execution import tracked as tracked_mod
    from research_harness.cli import main
    from research_harness.primitives.types import (
        GapGroundVerifyOutput,
        PrimitiveResult,
    )

    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "c1",
                        "gap": "no prior work does X",
                        "truth": "occupied",
                        "preemptors": [
                            {"title": "Killer Paper", "arxiv_id": "2604.00001"}
                        ],
                        "judged_at": "2026-08-02",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    seen_kwargs: list[dict] = []

    class _FakeTracked:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, primitive, **kwargs):
            seen_kwargs.append(kwargs)
            return PrimitiveResult(
                primitive=primitive,
                success=True,
                output=GapGroundVerifyOutput(
                    gap=kwargs["gap"],
                    verdict="occupied",
                    judge_votes=[
                        {
                            "perspective": "coverage",
                            "verdict": "occupied",
                            "reason": "r",
                        }
                    ],
                    narrowness={"Killer Paper": "tiny residual"},
                ),
            )

    monkeypatch.setattr(execution_pkg, "create_backend", lambda *a, **k: object())
    monkeypatch.setattr(tracked_mod, "TrackedBackend", _FakeTracked)

    out_path = tmp_path / "report.json"
    result = runner.invoke(
        main,
        [
            "panorama",
            "calibrate",
            str(fixture),
            "--topic",
            "1",
            "--budgets",
            "5",
            "--judge-mode",
            "panel",
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen_kwargs and seen_kwargs[0]["judge_mode"] == "panel"
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["judge_mode"] == "panel"
    record = report["curve"][0]["records"][0]
    assert record["judge_votes"][0]["perspective"] == "coverage"
    assert record["narrowness"] == {"Killer Paper": "tiny residual"}

    # default stays single — production replay behavior unchanged
    seen_kwargs.clear()
    result = runner.invoke(
        main,
        ["panorama", "calibrate", str(fixture), "--topic", "1", "--budgets", "5"],
    )
    assert result.exit_code == 0, result.output
    assert seen_kwargs and seen_kwargs[0]["judge_mode"] == "single"


def test_provider_errors_force_open_to_inconclusive(db, monkeypatch):
    """E1 on gap path: silent provider failure must not yield a positive open."""
    import research_harness.primitives.impls as impls

    @dataclass
    class _ErrResult:
        papers: list = field(default_factory=lambda: [_Paper()])
        provider_errors: list[str] = field(
            default_factory=lambda: ["openalex: Rate limit exceeded", "s2: 429"]
        )
        providers_queried: list[str] = field(default_factory=lambda: ["arxiv"])
        provider: str = "multi"

    monkeypatch.setattr(impls, "paper_search", lambda **kwargs: _ErrResult())
    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: _FakeClient())
    _route_chat(monkeypatch, [_vote("open")])

    out = gap_ground_verify(db=db, topic_id=1, gap="no prior work does X")
    assert out.verdict == "inconclusive"
    assert "Provider/source failure" in out.coverage_note
    assert "openalex" in out.coverage_note
    assert "Index lag" in out.coverage_note


def test_empty_synonym_family_noted_on_no_candidates(db, monkeypatch):
    """E5: zero-hit query families must be named, not silently read as vacancy."""
    import research_harness.primitives.impls as impls

    @dataclass
    class _EmptyResult:
        papers: list = field(default_factory=list)
        provider_errors: list[str] = field(default_factory=list)
        providers_queried: list[str] = field(default_factory=lambda: ["arxiv"])
        provider: str = "arxiv"

    seen_queries: list[str] = []
    seen_allowlists: list = []

    def fake_search(**kwargs):
        seen_queries.append(str(kwargs.get("query") or ""))
        seen_allowlists.append(kwargs.get("provider_allowlist"))
        return _EmptyResult()

    monkeypatch.setattr(impls, "paper_search", fake_search)
    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: _FakeClient())

    # Decompose returns two families; both empty after paper_search stub.
    def fake_chat(client, prompt: str) -> str:
        if '"queries"' in prompt:
            return json.dumps({"queries": ["ask for help budget", "expert calls"]})
        raise AssertionError("judge must not run when no candidates")

    monkeypatch.setattr(llm_primitives, "_client_chat", fake_chat)
    out = gap_ground_verify(
        db=db, topic_id=1, gap="function allocation under automation transparency"
    )
    assert out.verdict == "inconclusive"
    assert "Synonym-family zero-hit" in out.coverage_note
    assert (
        "Domain-index route" in out.coverage_note
        or "primary index" in out.coverage_note
    )
    # E5 expand: lexicon alternates must be searched, not only decompose output.
    assert any("escalation rate" in q or "query budget" in q for q in seen_queries)
    # E4 pin: human_factors domain pins crossref/pubmed (known suite providers).
    assert any(
        isinstance(a, list) and "crossref" in a and "pubmed" in a
        for a in seen_allowlists
    )


def test_e10_rejects_webfetch_numeric_occupying(db, stubbed_retrieval, monkeypatch):
    """E10: occupying rows with numeric claims + bad method are dropped."""

    def fake_chat(client, prompt: str) -> str:
        if '"queries"' in prompt:
            return json.dumps({"queries": []})
        return json.dumps(
            {
                "verdict": "occupied",
                "grounded_confidence": 0.8,
                "reason": "numeric preemptor",
                "coverage_note": "ok",
                "occupying": [
                    {
                        "title": "Killer Paper",
                        "verdict": "preempts",
                        "evidence": "n=100",
                        "n": 100,
                        "method": "webfetch",
                    },
                    {
                        "title": "Killer Paper",
                        "verdict": "overlaps",
                        "evidence": "mechanism",
                    },
                ],
            }
        )

    monkeypatch.setattr(llm_primitives, "_client_chat", fake_chat)
    out = gap_ground_verify(db=db, topic_id=1, gap="no prior work does X")
    assert len(out.occupying) == 1
    assert out.occupying[0].evidence == "mechanism"
    assert "E10" in out.coverage_note


def test_a_paragraph_claim_is_not_sent_to_an_index_as_a_query(db, monkeypatch):
    """A claim's own sentence is not a query, and a provider that rejects it voids the verdict.

    The raw gap is appended as a capture round so the decomposer cannot alias
    away the claim's canonical terms. For a one-line gap that works. For a
    refined novelty statement it sends four hundred characters of prose to every
    index: OpenReview answers 400, and one provider error is enough to turn an
    open verdict inconclusive, so no long-form claim can ever be verified.
    """
    import research_harness.primitives.impls as impls

    @dataclass
    class _Result:
        papers: list = field(default_factory=list)
        provider_errors: list[str] = field(default_factory=list)
        providers_queried: list[str] = field(default_factory=lambda: ["arxiv"])
        provider: str = "arxiv"

    seen: list[str] = []

    def fake_search(**kwargs):
        seen.append(str(kwargs.get("query") or ""))
        return _Result()

    monkeypatch.setattr(impls, "paper_search", fake_search)
    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(
        llm_primitives,
        "_client_chat",
        lambda client, prompt: json.dumps({"queries": ["nested missingness ranking"]}),
    )

    paragraph = (
        "Unlike complete-case change scoring, logistics that assume observed later "
        "timepoints, late-concat radiomics, pretreatment encoders that cannot run on a "
        "public clinical table, and a shared mask-token ranker, this method identifies "
        "pretreatment rank-order under nested missingness by mapping each observation "
        "pattern to a distinct low-rank ranking head and by penalizing pairwise order "
        "disagreements along nested masks so later measurements cannot rewrite the "
        "pretreatment order it reports."
    )
    gap_ground_verify(db=db, topic_id=1, gap=paragraph)

    assert seen, "the decomposed queries must still be searched"
    assert paragraph not in seen
    assert all(len(query) <= 240 for query in seen)


def test_a_source_that_lost_one_query_still_answered(db, monkeypatch):
    """a0113 (2026-09-27): Semantic Scholar lost one capture query to an SSL EOF and
    answered the others, while arXiv answered none. Only arXiv is down."""
    import research_harness.primitives.impls as impls

    @dataclass
    class _Result:
        provider_errors: list[str]
        papers: list = field(default_factory=lambda: [_Paper()])
        providers_queried: list[str] = field(
            default_factory=lambda: ["arxiv", "crossref", "semantic_scholar"]
        )
        provider: str = "multi"

    calls: list[str] = []

    def fake_search(**kwargs):
        calls.append(str(kwargs.get("query") or ""))
        errors = ["arxiv: HTTP Error 429: Unknown Error"]
        if len(calls) == 1:
            errors.append(
                "semantic_scholar: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>"
            )
        return _Result(provider_errors=errors)

    def fake_chat(client, prompt: str) -> str:
        if '"queries"' in prompt:
            return json.dumps({"queries": ["prior art alpha", "prior art beta"]})
        return json.dumps(_vote("open"))

    monkeypatch.setattr(impls, "paper_search", fake_search)
    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(llm_primitives, "_client_chat", fake_chat)

    out = gap_ground_verify(db=db, topic_id=1, gap="no prior work does X")

    assert len(calls) >= 2
    assert set(out.providers_answered) == {"crossref", "semantic_scholar"}
