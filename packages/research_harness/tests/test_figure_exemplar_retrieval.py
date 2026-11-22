"""UF04 exemplar retrieval: rights, structure-over-topic, venue, diversity."""

from __future__ import annotations

from research_harness.visualization.figure_exemplar_retrieval import (
    retrieve_figure_exemplars,
)
from research_harness.visualization.figure_package_contracts import (
    SCHEMA_FIGURE_OPPORTUNITY,
    validate_reference_record,
)

IPM = "Information Processing & Management"
NPJ = "npj Digital Medicine"


def _opp(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_OPPORTUNITY,
        "opportunity_id": "opp:quantitative_comparison",
        "role": "quantitative_comparison",
        "reader_question": "How do the methods compare on the reported metrics?",
        "claim": "Named methods are compared on shared metrics.",
        "evidence_boundary": "evidence_backed",
        "priority": "high",
        "information_topology": "grouped_comparison",
    }
    payload.update(overrides)
    return payload


def _unit(reference_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "reference_id": reference_id,
        "paper_id": f"paper-{reference_id}",
        "figure_id": f"fig:{reference_id}",
        "figure_role": "quantitative_comparison",
        "information_topology": "grouped_comparison",
        "evidence_grammar": "evidence_backed",
        "venue_profile": IPM,
        "topic": "crowdfunding",
        "rights_status": "display_allowed",
        "quality": 0.8,
        "publication_year": 2024,
        "verification_status": "verified",
        "caption": f"secret caption {reference_id}",
        "image_path": f"/private/{reference_id}.png",
    }
    payload.update(overrides)
    return payload


def test_unknown_rights_are_excluded() -> None:
    result = retrieve_figure_exemplars(
        opportunity=_opp(),
        units=[
            _unit("ok"),
            _unit("bad", rights_status="unknown", paper_id="paper-bad"),
        ],
        target_venue=IPM,
        top_k=3,
    )
    ids = [r["reference_id"] for r in result["ranked"]]
    assert "ok" in ids
    assert "bad" not in ids
    assert any(e["reference_id"] == "bad" for e in result["excluded"])


def test_structure_over_topic_wins() -> None:
    result = retrieve_figure_exemplars(
        opportunity=_opp(),
        units=[
            _unit(
                "same-topic-wrong-form",
                figure_role="method_architecture",
                information_topology="pipeline_stages",
                topic="crowdfunding",
                quality=1.0,
            ),
            _unit(
                "other-topic-same-form",
                topic="radiology-triage",
                venue_profile=NPJ,
                quality=0.6,
            ),
        ],
        target_venue=IPM,
        topic="crowdfunding",
        top_k=2,
    )
    assert result["ranked"][0]["reference_id"] == "other-topic-same-form"


def test_venue_tie_break() -> None:
    result = retrieve_figure_exemplars(
        opportunity=_opp(),
        units=[
            _unit("npj-form", venue_profile=NPJ, paper_id="p-npj"),
            _unit("ipm-form", venue_profile=IPM, paper_id="p-ipm"),
        ],
        target_venue=IPM,
        top_k=2,
    )
    assert result["ranked"][0]["reference_id"] == "ipm-form"
    assert result["ranked"][1]["reference_id"] == "npj-form"


def test_diverse_top_k_prefers_distinct_papers() -> None:
    result = retrieve_figure_exemplars(
        opportunity=_opp(),
        units=[
            _unit("a1", paper_id="paper-a", quality=0.99),
            _unit("a2", paper_id="paper-a", quality=0.98),
            _unit("b1", paper_id="paper-b", quality=0.7),
            _unit("c1", paper_id="paper-c", quality=0.69),
        ],
        target_venue=IPM,
        top_k=3,
    )
    papers = [r["paper_id"] for r in result["ranked"]]
    assert len(set(papers)) == 3


def test_ranking_is_stable() -> None:
    units = [
        _unit("z", quality=0.7, paper_id="pz"),
        _unit("a", quality=0.7, paper_id="pa"),
        _unit("m", quality=0.7, paper_id="pm"),
    ]
    first = retrieve_figure_exemplars(opportunity=_opp(), units=units, target_venue=IPM)
    second = retrieve_figure_exemplars(
        opportunity=_opp(), units=units, target_venue=IPM
    )
    assert [r["reference_id"] for r in first["ranked"]] == [
        r["reference_id"] for r in second["ranked"]
    ]


def test_missing_topology_degrades_without_failing() -> None:
    result = retrieve_figure_exemplars(
        opportunity=_opp(information_topology=""),
        units=[_unit("ok", information_topology="grouped_comparison")],
        target_venue=IPM,
        top_k=1,
    )
    assert result["ranked"]
    assert result["ranked"][0]["reference_id"] == "ok"


def test_internal_retrieval_does_not_leak_source_content() -> None:
    result = retrieve_figure_exemplars(
        opportunity=_opp(),
        units=[
            _unit(
                "hidden",
                rights_status="internal_retrieval",
                caption="do not leak this caption",
                image_path="/secret/fig.png",
            )
        ],
        target_venue=IPM,
        top_k=1,
    )
    rec = result["ranked"][0]
    validate_reference_record(rec)
    assert rec["rights_status"] == "internal_retrieval"
    assert "caption" not in rec
    assert "image_path" not in rec
    blob = str(rec)
    assert "do not leak this caption" not in blob
    assert "/secret/fig.png" not in blob
    assert "source_claims" in rec["not_transferable"]
