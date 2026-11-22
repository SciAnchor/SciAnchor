"""BUG-012: cross-species / cross-model validation evidence detection."""

from __future__ import annotations

from research_harness.experiment.organism_gate import (
    cross_species_evidence_findings,
    detect_organisms,
)
from research_harness.storage.db import Database


def test_detect_organisms_word_boundaries():
    assert detect_organisms("A study of human peripheral blood") == {"human"}
    assert detect_organisms("mouse vein wall model (C57BL/6)") == {"mouse"}
    assert (
        detect_organisms("we generate iterated ratings") == set()
    )  # no false rat/human
    assert "human" in detect_organisms("patients with acute DVT")


def _seed(db: Database) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, expected_organism) VALUES (?, ?, ?)",
            ("dvt-topic", "human DVT single-cell", "human"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO papers (id, title, abstract) VALUES (?, ?, ?)",
            (1, "Acute DVT peripheral blood", "human patients with venous thrombosis"),
        )
        conn.execute(
            "INSERT INTO papers (id, title, abstract) VALUES (?, ?, ?)",
            (2, "Vein wall remodeling", "murine mouse model of venous thrombus"),
        )
        for pid in (1, 2):
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'high')",
                (pid, topic_id),
            )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def test_cross_species_findings_flag_offspecies_paper(db):
    topic_id = _seed(db)
    findings = cross_species_evidence_findings(db, topic_id)
    assert len(findings) == 1
    assert findings[0]["paper_id"] == 2
    assert findings[0]["detected_organisms"] == ["mouse"]
    assert findings[0]["expected_organism"] == "human"


def test_cross_species_findings_are_opt_in(db):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES ('no-organism', 'x')"
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO papers (id, title, abstract) VALUES (9, 'mouse study', 'murine')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (9, ?, 'high')",
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()
    # No declared expected_organism -> check does not fire.
    assert cross_species_evidence_findings(db, topic_id) == []
