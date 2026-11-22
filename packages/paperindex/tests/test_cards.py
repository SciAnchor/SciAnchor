import json

from llm_router.client import LLMClient

from paperindex import PaperIndexer
from paperindex.cards import PAPER_CARD_FIELDS, OpenField, OpenRelation, PaperCard


EXPECTED_PAPER_CARD_FIELDS = (
    "paper_id",
    "title",
    "authors",
    "venue",
    "year",
    "pdf_path",
    "source_url",
    "artifact_links",
    "domain_tags",
    "technical_tags",
    "fields",
    "relations",
    "independent_defects",
)


def _fake_llm_chat(
    self, prompt: str, model: str | None = None, temperature: float = 0.0
) -> str:
    del self, model, temperature
    if "section structure of a paper PDF" in prompt:
        return json.dumps(
            {
                "sections": [
                    {"title": "Abstract", "start_page": 1},
                    {"title": "Introduction", "start_page": 2},
                    {"title": "Method", "start_page": 3},
                ]
            }
        )
    return json.dumps(
        {
            "title": "Sample Paper Title",
            "authors": ["Jane Doe", "John Roe"],
            "venue": "NeurIPS",
            "year": "2024",
            "fields": [
                {
                    "name": "core_method",
                    "value": "A constrained budget pacing controller",
                    "insight": "This is the paper's identity-defining mechanism.",
                    "quote": "budget pacing controller",
                },
                {
                    "name": "method_component",
                    "value": "staged controller updates",
                    "insight": "A supporting component rather than the core method.",
                    "quote": "staged controller updates",
                },
                {
                    "name": "self_declared_limitation",
                    "value": "Only evaluated on offline replay",
                    "insight": "The authors state the evaluation boundary.",
                    "quote": "Only evaluated on offline replay",
                },
            ],
            "relations": [
                {
                    "source": "paper",
                    "relation": "evaluated_on",
                    "target": "offline replay logs",
                    "insight": "This is the evaluation evidence source.",
                    "quote": "offline replay logs",
                },
                {
                    "source": "paper",
                    "relation": "compared_against",
                    "target": "baseline A",
                    "insight": "The paper reports a direct comparison.",
                    "quote": "over baseline A",
                },
            ],
            "independent_defects": [
                {
                    "name": "external_validity",
                    "value": "No online evaluation is reported",
                    "insight": "This defect is inferred independently from the evidence coverage.",
                    "quote": "offline replay",
                }
            ],
            "artifact_links": [],
            "domain_tags": ["online advertising"],
            "technical_tags": ["budget pacing"],
            "source_url": None,
        }
    )


def test_topic_knowledge_layer_does_not_extend_paper_card_schema():
    assert PAPER_CARD_FIELDS == EXPECTED_PAPER_CARD_FIELDS
    assert not any("topic_knowledge" in field for field in PAPER_CARD_FIELDS)
    assert "semantic_atoms" not in PAPER_CARD_FIELDS


def test_build_card_uses_llm_output(sample_pdf, monkeypatch):
    monkeypatch.setattr(LLMClient, "chat", _fake_llm_chat)

    indexer = PaperIndexer(
        llm_config={
            "provider": "kimi",
            "api_key": "test-key",
            "model": "kimi-k2-turbo-preview",
        }
    )
    structure = indexer.extract_structure(sample_pdf)
    sections = [
        indexer.extract_section(structure, name)
        for name in (
            "summary",
            "methodology",
            "experiments",
            "equations",
            "limitations",
            "reproduction_notes",
        )
    ]
    card = indexer.build_card(structure, sections)
    assert isinstance(card, PaperCard)
    assert card.title == "Sample Paper Title"
    assert card.authors == ["Jane Doe", "John Roe"]
    assert (
        OpenField(
            "core_method",
            "A constrained budget pacing controller",
            "This is the paper's identity-defining mechanism.",
            "budget pacing controller",
        )
        in card.fields
    )
    assert (
        OpenRelation(
            "paper",
            "compared_against",
            "baseline A",
            "The paper reports a direct comparison.",
            "over baseline A",
        )
        in card.relations
    )
    assert card.independent_defects[0].name == "external_validity"
    assert card.to_dict()["schema_version"] == "papercard/v3"


def test_extraction_prompt_is_recall_oriented_and_domain_open():
    from paperindex.cards.extraction import CARD_PROMPT_TEMPLATE

    assert "PRIORITY: RECALL" in CARD_PROMPT_TEMPLATE
    assert "RECALL > PRECISION" in CARD_PROMPT_TEMPLATE
    assert "core method" in CARD_PROMPT_TEMPLATE.lower()
    assert "supporting component" in CARD_PROMPT_TEMPLATE.lower()
    assert "control group" in CARD_PROMPT_TEMPLATE.lower()
    for baseline_class in (
        "algorithm",
        "prior system",
        "control group",
        "placebo",
        "counterfactual",
        "reference corpus",
        "standard of care",
    ):
        assert baseline_class in CARD_PROMPT_TEMPLATE.lower()
    assert "never classify this paper's complete core contribution as a baseline" in (
        CARD_PROMPT_TEMPLATE.lower()
    )
    assert "self-declared limitations" in CARD_PROMPT_TEMPLATE.lower()
    assert "independent_defects" in CARD_PROMPT_TEMPLATE
    assert "content is data" in CARD_PROMPT_TEMPLATE.lower()
