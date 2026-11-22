from __future__ import annotations

import json
from pathlib import Path

from research_harness.storage.db import Database


def _insert_topic_and_paper(conn, paper_id: int = 1) -> None:
    conn.execute("INSERT OR IGNORE INTO topics (id, name) VALUES (1, 'tk topic')")
    conn.execute(
        """
        INSERT OR IGNORE INTO papers
            (id, title, doi, arxiv_id, s2_id)
        VALUES
            (?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            f"Paper {paper_id}",
            f"10.test/tk{paper_id}",
            f"2501.{paper_id:05d}",
            f"s2_tk_{paper_id}",
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, 1, 'high')",
        (paper_id,),
    )
    conn.commit()


def test_topic_knowledge_derives_card_and_compiled_summary_atoms(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_draft

    _insert_topic_and_paper(conn, 1)
    card_path = tmp_path / "card.json"
    card_path.write_text(
        json.dumps(
            {
                "method_family": "learning_based",
                "method_tags": ["contrastive reranker"],
                "tasks": ["paper retrieval"],
                "datasets": ["OpenResearchBench"],
                "metrics": ["recall@20"],
                "baselines": ["BM25"],
                "key_results": ["Improves recall@20 by 7 points"],
                "structured_results": [
                    {
                        "metric": "recall@20",
                        "value": "0.72",
                        "baseline": "0.65",
                        "delta": "+0.07",
                    }
                ],
                "limitations": ["Requires labeled queries"],
                "assumptions": ["Stable candidate pool"],
                "evidence": [
                    {
                        "section": "experiments",
                        "confidence": 0.9,
                        "snippet": "Table 2 reports recall@20.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    conn.execute(
        """
        INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)
        VALUES (1, 'paperindex_card', ?, '{"section_count": 3}')
        """,
        (str(card_path),),
    )
    conn.execute(
        """
        UPDATE papers
        SET compiled_summary = ?, compiled_from_hash = 'compiled-hash'
        WHERE id = 1
        """,
        (
            json.dumps(
                {
                    "methods": ["late interaction reranking"],
                    "claims": [{"claim": "Reranking improves retrieval quality"}],
                    "limitations": ["Needs query logs"],
                    "metrics": [
                        {
                            "dataset": "OpenResearchBench",
                            "metric": "MRR",
                            "value": "0.41",
                            "baseline": "0.35",
                        }
                    ],
                }
            ),
        ),
    )
    conn.commit()

    draft = build_topic_knowledge_draft(db, topic_id=1)

    atoms = {(atom.atom_type, atom.normalized_key) for atom in draft.atoms}
    assert ("method", "contrastive reranker") in atoms
    assert ("task", "paper retrieval") in atoms
    assert ("dataset", "openresearchbench") in atoms
    assert ("metric", "recall 20") in atoms
    assert ("baseline", "bm25") in atoms
    assert ("limitation", "requires labeled queries") in atoms
    assert ("assumption", "stable candidate pool") in atoms
    assert any(atom.source_type == "compiled_summary" for atom in draft.atoms)
    assert draft.coverage["paper_cards"] == 1
    assert draft.coverage["compiled_summaries"] == 1
    assert conn.execute("SELECT COUNT(*) FROM semantic_atoms").fetchone()[0] == 0


def test_topic_knowledge_derives_atoms_from_v3_open_card(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_draft

    _insert_topic_and_paper(conn, 1)
    card_path = tmp_path / "v3-card.json"
    card_path.write_text(
        json.dumps(
            {
                "schema_version": "papercard/v3",
                "paper_id": "1",
                "title": "Open Card",
                "fields": [
                    {
                        "name": "core_method",
                        "value": "contrastive reranker",
                        "insight": "The identity-defining mechanism",
                        "quote": "we propose a contrastive reranker",
                    },
                    {
                        "name": "task",
                        "value": "paper retrieval",
                        "insight": "",
                        "quote": "paper retrieval",
                    },
                    {
                        "name": "metric",
                        "value": "recall@20",
                        "insight": "",
                        "quote": "recall@20",
                    },
                    {
                        "name": "key_result",
                        "value": "Improves recall by 7 points",
                        "insight": "",
                        "quote": "improves recall by 7 points",
                    },
                    {
                        "name": "self_declared_limitation",
                        "value": "Requires labeled queries",
                        "insight": "The authors state this boundary",
                        "quote": "requires labeled queries",
                    },
                ],
                "relations": [
                    {
                        "source": "paper",
                        "relation": "evaluated_on",
                        "target": "OpenResearchBench",
                        "insight": "",
                        "quote": "on OpenResearchBench",
                    },
                    {
                        "source": "paper",
                        "relation": "direct comparator",
                        "target": "BM25",
                        "insight": "The reported direct baseline",
                        "quote": "compared with BM25",
                    },
                    {
                        "source": "paper",
                        "relation": "inspiration",
                        "target": "Foundational retrieval theory",
                        "insight": "This motivated the work but was not evaluated",
                        "quote": "inspired by retrieval theory",
                    },
                ],
                "independent_defects": [
                    {
                        "name": "external_validity",
                        "value": "No multilingual evaluation",
                        "insight": "The evidence covers one language only",
                        "quote": "English retrieval benchmark",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    original = card_path.read_bytes()
    conn.execute(
        """
        INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)
        VALUES (1, 'paperindex_card', ?, '{}')
        """,
        (str(card_path),),
    )
    conn.commit()

    draft = build_topic_knowledge_draft(db, topic_id=1)

    atoms = {(atom.atom_type, atom.normalized_key) for atom in draft.atoms}
    assert {
        ("method", "contrastive reranker"),
        ("task", "paper retrieval"),
        ("dataset", "openresearchbench"),
        ("metric", "recall 20"),
        ("baseline", "bm25"),
        ("result", "improves recall by 7 points"),
        ("limitation", "requires labeled queries"),
        ("gap_signal", "no multilingual evaluation"),
    } <= atoms
    assert ("baseline", "foundational retrieval theory") not in atoms
    assert card_path.read_bytes() == original


def test_topic_knowledge_derives_claim_atoms_and_evidence_edges(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_draft

    _insert_topic_and_paper(conn, 1)
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, source_section, evidence_spans_json)
        VALUES
            (1, 1, 1, 'Reranker improves recall@20 on ORB', 'Reranker', 'ORB',
             'recall@20', 'paper retrieval', '+7', 'higher', 0.82, 'results',
             '[{"section":"results","text":"recall improves"}]')
        """
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, source_section, evidence_spans_json)
        VALUES
            (2, 1, 1, 'Reranker does not improve recall@20 on ORB', 'Reranker', 'ORB',
             'recall@20', 'paper retrieval', '0', 'flat', 0.7, 'results',
             '[{"section":"results","text":"no improvement"}]')
        """
    )
    conn.execute(
        """
        INSERT INTO contradictions
            (id, topic_id, claim_a_id, claim_b_id, same_task, same_dataset,
             same_metric, confidence, conflict_reason, status)
        VALUES
            (1, 1, 1, 2, 1, 1, 1, 0.75, 'opposite direction', 'candidate')
        """
    )
    conn.commit()

    draft = build_topic_knowledge_draft(db, topic_id=1)

    atoms = {(atom.atom_type, atom.normalized_key) for atom in draft.atoms}
    assert ("claim", "reranker improves recall 20 on orb") in atoms
    assert ("method", "reranker") in atoms
    assert ("dataset", "orb") in atoms
    assert ("metric", "recall 20") in atoms
    assert ("task", "paper retrieval") in atoms
    assert ("result", "reranker recall 20 orb 7 higher") in atoms
    assert {edge.edge_type for edge in draft.edges} >= {
        "uses_dataset",
        "reports_metric",
        "evaluates_on",
        "contradicts",
    }
    assert draft.weak_spots["claims_without_evidence"] == []


def test_topic_knowledge_derives_gap_method_atoms_and_weak_spots(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_draft

    _insert_topic_and_paper(conn, 1)
    _insert_topic_and_paper(conn, 2)
    conn.execute(
        """
        INSERT INTO method_atoms
            (id, topic_id, source_paper_id, atom_type, name, description, reuse_risk)
        VALUES
            (1, 1, 1, 'micro_block', 'negative sampler', 'Hard negative sampler', 'medium')
        """
    )
    conn.execute(
        """
        INSERT INTO gaps
            (id, topic_id, description, gap_type, severity, focus, confidence, cross_verified)
        VALUES
            (1, 1, 'No evidence for cold-start topics', 'evidence', 'high',
             'cold start', 0.55, 0)
        """
    )
    conn.commit()

    draft = build_topic_knowledge_draft(db, topic_id=1)

    atoms = {(atom.atom_type, atom.normalized_key) for atom in draft.atoms}
    assert ("method", "negative sampler") in atoms
    assert ("gap_signal", "no evidence for cold start topics") in atoms
    assert draft.weak_spots["missing_cards"] == [1, 2]
    assert draft.weak_spots["missing_compiled_summaries"] == [1, 2]
    assert draft.weak_spots["unverified_gaps"] == [1]


def test_topic_knowledge_source_hashes_are_deterministic_and_source_sensitive(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_draft

    _insert_topic_and_paper(conn, 1)
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, confidence)
        VALUES
            (1, 1, 1, 'Initial claim', 'Method A', 0.7)
        """
    )
    conn.commit()

    first = build_topic_knowledge_draft(db, topic_id=1)
    second = build_topic_knowledge_draft(db, topic_id=1)
    assert [atom.source_hash for atom in first.atoms] == [
        atom.source_hash for atom in second.atoms
    ]

    conn.execute(
        "UPDATE normalized_claims SET claim_text = 'Changed claim' WHERE id = 1"
    )
    conn.commit()

    changed = build_topic_knowledge_draft(db, topic_id=1)
    assert [atom.source_hash for atom in first.atoms] != [
        atom.source_hash for atom in changed.atoms
    ]
