from __future__ import annotations

import json

from paperindex.cards.schema import PAPER_CARD_FIELDS, PaperCard
from research_harness.primitives.registry import PAPER_INGEST_SPEC
from research_harness.storage.db import Database


EXPECTED_PAPER_CARD_FIELDS: tuple[str, ...] = (
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

EXPECTED_PAPER_INGEST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "topic_id": {"type": "integer"},
        "relevance": {"type": "string", "enum": ["high", "medium", "low"]},
        "url": {"type": "string"},
    },
    "required": ["source"],
}


def test_topic_knowledge_layer_does_not_extend_paper_card_schema() -> None:
    assert PAPER_CARD_FIELDS == EXPECTED_PAPER_CARD_FIELDS

    payload = PaperCard.from_dict(
        {
            "schema_version": "papercard/v3",
            "paper_id": "paper-1",
            "title": "Guarded Card",
            "fields": [],
            "relations": [],
            "independent_defects": [],
        }
    ).to_dict()

    assert tuple(key for key in payload if key != "schema_version") == (
        EXPECTED_PAPER_CARD_FIELDS
    )
    assert "topic_knowledge_snapshot" not in payload
    assert "semantic_atoms" not in payload
    assert "semantic_edges" not in payload


def test_topic_knowledge_snapshot_reads_mixed_cards_without_rewriting_them(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    legacy_path = tmp_path / "legacy-card.json"
    legacy_payload = {
        "paper_id": "1",
        "title": "Legacy Card",
        "method_family": "learning_based",
        "datasets": ["ORB"],
        "baselines": ["BM25"],
    }
    legacy_json = json.dumps(legacy_payload, ensure_ascii=False, sort_keys=True)
    legacy_path.write_text(legacy_json, encoding="utf-8")
    v3_path = tmp_path / "v3-card.json"
    v3_payload = {
        "schema_version": "papercard/v3",
        "paper_id": "2",
        "title": "Open Card",
        "fields": [
            {
                "name": "core_method",
                "value": "hybrid retrieval",
                "insight": "",
                "quote": "hybrid retrieval",
            }
        ],
        "relations": [
            {
                "source": "paper",
                "relation": "evaluated_on",
                "target": "Multilingual ORB",
                "insight": "",
                "quote": "Multilingual ORB",
            }
        ],
        "independent_defects": [],
    }
    v3_json = json.dumps(v3_payload, ensure_ascii=False, sort_keys=True)
    v3_path.write_text(v3_json, encoding="utf-8")

    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'guard topic')")
    conn.executemany(
        "INSERT INTO papers (id, title) VALUES (?, ?)",
        [(1, "Legacy Card"), (2, "Open Card")],
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
    )
    conn.executemany(
        """
        INSERT INTO paper_artifacts (id, paper_id, artifact_type, path, metadata)
        VALUES (?, ?, 'paperindex_card', ?, '{}')
        """,
        [(1, 1, str(legacy_path)), (2, 2, str(v3_path))],
    )
    conn.commit()

    result = build_topic_knowledge_snapshot(db, topic_id=1)

    assert result.artifact_id > 0
    assert result.payload["coverage"]["paper_cards"] == 2
    assert result.payload["covered"]["methods"] == [
        "hybrid retrieval",
        "learning_based",
    ]
    assert result.payload["covered"]["datasets"] == ["Multilingual ORB", "ORB"]
    assert result.payload["covered"]["baselines"] == ["BM25"]
    assert legacy_path.read_text(encoding="utf-8") == legacy_json
    assert v3_path.read_text(encoding="utf-8") == v3_json


def test_topic_knowledge_layer_does_not_change_paper_ingest_contract() -> None:
    assert PAPER_INGEST_SPEC.name == "paper_ingest"
    assert PAPER_INGEST_SPEC.category.name == "RETRIEVAL"
    assert PAPER_INGEST_SPEC.input_schema == EXPECTED_PAPER_INGEST_SCHEMA
    assert PAPER_INGEST_SPEC.output_type == "PaperIngestOutput"
    assert PAPER_INGEST_SPEC.requires_llm is False
    assert PAPER_INGEST_SPEC.idempotent is True

    schema_text = json.dumps(PAPER_INGEST_SPEC.input_schema, sort_keys=True)
    assert "topic_knowledge" not in schema_text
    assert "topic_knowledge_snapshot" not in schema_text
