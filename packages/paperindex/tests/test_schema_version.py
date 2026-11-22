import pytest

from paperindex.cards.schema import (
    PAPER_CARD_FIELDS,
    PAPER_CARD_SCHEMA_VERSION,
    SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS,
    OpenField,
    OpenRelation,
    PaperCard,
    PaperCardSchemaError,
)


def test_current_version_is_supported():
    assert PAPER_CARD_SCHEMA_VERSION == "papercard/v3"
    assert PAPER_CARD_SCHEMA_VERSION in SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS
    assert "papercard/v2" in SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS


def test_stamped_payload_round_trips():
    payload = PaperCard(
        title="T",
        fields=[OpenField("core_method", "M", "why M matters", "we propose M")],
        relations=[
            OpenRelation(
                "M", "compared_against", "control", "fair comparison", "versus control"
            )
        ],
        independent_defects=[
            OpenField(
                "coverage_gap",
                "No subgroup analysis",
                "may hide heterogeneity",
                "overall cohort",
            )
        ],
    ).to_dict()
    card = PaperCard.from_dict(payload)
    assert card.to_dict() == payload


def test_unstamped_payload_is_legacy_accepted():
    card = PaperCard.from_dict(
        {
            "title": "legacy",
            "core_idea": "A",
            "limitations": ["Authors report L"],
            "datasets": ["cohort X"],
            "baselines": ["standard of care"],
        }
    )

    assert card.title == "legacy"
    assert OpenField("core_idea", "A") in card.fields
    assert OpenField("self_declared_limitation", "Authors report L") in card.fields
    assert OpenRelation("paper", "evaluated_on", "cohort X") in card.relations
    assert (
        OpenRelation("paper", "compared_against", "standard of care") in card.relations
    )
    assert card.independent_defects == []


def test_stamped_v2_payload_is_legacy_accepted():
    card = PaperCard.from_dict(
        {"schema_version": "papercard/v2", "method_summary": "legacy method"}
    )

    assert OpenField("method_summary", "legacy method") in card.fields


def test_v3_payload_rejects_legacy_content_keys_instead_of_dropping_them():
    with pytest.raises(PaperCardSchemaError, match="unexpected fields"):
        PaperCard.from_dict(
            {
                "schema_version": "papercard/v3",
                "fields": [],
                "relations": [],
                "independent_defects": [],
                "key_results": ["would otherwise be lost"],
            }
        )


def test_unstamped_open_named_key_is_still_legacy():
    card = PaperCard.from_dict({"fields": ["legacy field named fields"]})

    assert card.fields == [OpenField("fields", "legacy field named fields")]


def test_v3_fields_feed_legacy_owner_search_properties():
    card = PaperCard(
        fields=[
            OpenField("core_method", "identity mechanism"),
            OpenField("method_component", "supporting module"),
            OpenField("result", "improved outcome"),
            OpenField("results", "replicated outcome"),
            OpenField("self_declared_limitation", "single site"),
        ]
    )

    assert card.core_idea == "identity mechanism"
    assert card.method_summary == "supporting module"
    assert card.key_results == ["improved outcome", "replicated outcome"]
    assert card.limitations == ["single site"]


def test_unsupported_version_rejected():
    with pytest.raises(PaperCardSchemaError):
        PaperCard.from_dict({"schema_version": "papercard/v999"})


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"authors": "Alice"},
        {"schema_version": "papercard/v3", "fields": "x"},
        {
            "schema_version": "papercard/v3",
            "fields": [{"name": ["not text"], "value": "x"}],
        },
        {"schema_version": "papercard/v3", "relations": ["x"]},
        {"schema_version": "papercard/v3", "independent_defects": ["x"]},
    ],
)
def test_malformed_boundary_types_fail_closed(payload):
    with pytest.raises(PaperCardSchemaError):
        PaperCard.from_dict(payload)


def test_schema_version_not_a_card_field():
    # The stamp lives in persisted payloads, not in the field contract —
    # keeps PAPER_CARD_FIELDS stable for downstream field guards.
    assert "schema_version" not in PAPER_CARD_FIELDS
    assert PAPER_CARD_FIELDS[-3:] == ("fields", "relations", "independent_defects")
