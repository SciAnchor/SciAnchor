"""IDX01 slice: retrieve-then-rerank shared primitive + D4 embed-all gate."""

from __future__ import annotations

import math

import pytest

from research_harness.embeddings.service import EmbeddingResult
from research_harness.memory import recall_similar_runs
from research_harness.primitives import impls as impls_mod
from research_harness.retrieval import retrieve_then_rerank
from research_harness.storage.db import Database


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EMBEDDING_PROVIDER", "fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "rerank.db")
    database.migrate()
    return database


def _patch_embed(monkeypatch, mapping):
    """mapping: substring -> unit vector; query uses key '__query__'."""

    def fake_embed_texts(_db, texts, **_kwargs):
        vectors = []
        for i, text in enumerate(texts):
            if i == 0:
                vectors.append(_norm(mapping["__query__"]))
                continue
            chosen = mapping.get("__default__")
            for key, vec in mapping.items():
                if key.startswith("__"):
                    continue
                if key.lower() in text.lower():
                    chosen = vec
                    break
            vectors.append(_norm(chosen))
        return EmbeddingResult(
            provider="fake",
            model="fake-v1",
            vectors=vectors,
            dim=len(vectors[0]),
            cache_hits=0,
            cache_misses=len(texts),
        )

    # retrieve_then_rerank does a late import from research_harness.embeddings
    monkeypatch.setattr(
        "research_harness.embeddings.embed_texts",
        fake_embed_texts,
    )


def test_retrieve_then_rerank_empty_query(db):
    assert retrieve_then_rerank(db, "", [("1", "hello")]) == []


def test_retrieve_then_rerank_lexical_fallback_without_embeddings(db):
    hits = retrieve_then_rerank(
        db,
        "graph neural network molecules",
        [
            ("a", "graph neural networks for molecules"),
            ("b", "large language model evaluation"),
        ],
        use_embeddings=False,
    )
    assert hits and hits[0].doc_id == "a"
    assert hits[0].embed_score == 0.0


def test_retrieve_then_rerank_embed_all_recovers_zero_lexical(db, monkeypatch):
    """Semantic twin with no token overlap still ranks when N is small (D4)."""
    _patch_embed(
        monkeypatch,
        {
            "__query__": [1.0, 0.0, 0.0],
            "partial correlation": [0.99, 0.1, 0.0],
            "__default__": [0.0, 0.0, 1.0],
        },
    )
    hits = retrieve_then_rerank(
        db,
        "conditional dependence gating across channels",
        [
            ("twin", "partial correlation channel collapse remedy"),
            ("noise", "unrelated baking recipes and pastry dough"),
        ],
        top_k=2,
        use_embeddings=True,
        embed_all_max=64,
        shortlist_k=1,  # pure lexical shortlist would keep only one doc
    )
    assert hits[0].doc_id == "twin"
    assert hits[0].embed_score > hits[1].embed_score


def test_workflow_memory_semantic_near_miss_not_gated(db, monkeypatch):
    _patch_embed(
        monkeypatch,
        {
            "__query__": [1.0, 0.0, 0.0],
            "partial correlation": [0.99, 0.05, 0.0],
            "__default__": [0.0, 0.0, 1.0],
        },
    )
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, status, created_at) VALUES (?,?,?,?)",
            (
                "partial correlation channel collapse",
                "remedy for multivariate forecasting",
                "active",
                "2026-03-01",
            ),
        )
        t_sem = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO topics (name, description, status, created_at) VALUES (?,?,?,?)",
            (
                "pastry dough lamination",
                "baking recipes and flour hydration",
                "active",
                "2026-03-01",
            ),
        )
        t_noise = int(cur.lastrowid)
        for tid in (t_sem, t_noise):
            conn.execute(
                "INSERT INTO projects (id, topic_id, name, description) VALUES (?,?,?,?)",
                (tid, tid, "stub", "stub"),
            )
            conn.execute(
                """
                INSERT INTO provenance_records
                (primitive, category, started_at, finished_at, backend,
                 topic_id, stage, input_hash, output_hash, cost_usd, success)
                VALUES ('t','a','2026-03-01','2026-03-01','local',?,'a','h','h',0.0,1)
                """,
                (tid,),
            )
        conn.commit()
    finally:
        conn.close()

    hits = recall_similar_runs(
        db,
        "conditional dependence gating across sensor channels",
        min_age_days=0,
        max_age_days=None,
        use_embeddings=True,
    )
    assert hits, "expected semantic hit"
    assert hits[0].topic_id == t_sem


def test_local_paper_search_embed_rerank_backend_label(db):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, abstract, year, venue) VALUES (?,?,?,?)",
            (
                "Partial Correlation Gating for Multivariate Forecasts",
                "channel collapse remedy via conditional dependence",
                2025,
                "ICLR",
            ),
        )
        conn.execute(
            "INSERT INTO papers (title, abstract, year, venue) VALUES (?,?,?,?)",
            (
                "Sourdough hydration study",
                "baking flour water ratios",
                2024,
                "Kitchen",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    out = impls_mod.paper_search(
        db=db,
        query="conditional dependence channel gating",
        local_only=True,
        max_results=5,
        local_embed_rerank=True,
    )
    assert "embed_rerank" in out.retrieval_backend
    assert out.papers


def test_exemplar_units_upsert_and_rank(db, monkeypatch):
    from research_harness.retrieval import (
        load_exemplar_unit_rows,
        rank_exemplar_rows,
        upsert_exemplar_units,
    )

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, status, created_at) VALUES (?,?,?,?)",
            ("eag-topic", "t", "active", "2026-03-01"),
        )
        conn.commit()
        topic_id = 1
    finally:
        conn.close()

    units = [
        {
            "unit_type": "intro_arc",
            "source_paper_id": 11,
            "source_title": "Partial Correlation Gating",
            "venue": "ICLR",
            "venue_tier": "A",
            "quality": 9.0,
            "form": {
                "moves": [
                    {
                        "move": "gap",
                        "gist": "channel collapse under multivariate forecast",
                    },
                    {"move": "this-work", "gist": "conditional dependence gating"},
                ]
            },
            "summary": "gap then contribution via partial correlation",
        },
        {
            "unit_type": "intro_arc",
            "source_paper_id": 22,
            "source_title": "Pastry Lamination",
            "venue": "Kitchen",
            "venue_tier": "?",
            "quality": 8.5,
            "form": {
                "moves": [
                    {"move": "establish-importance", "gist": "butter layers"},
                    {"move": "this-work", "gist": "fold counts"},
                ]
            },
            "summary": "baking dough hydration",
        },
    ]
    n = upsert_exemplar_units(db, topic_id=topic_id, units=units)
    assert n == 2
    rows = load_exemplar_unit_rows(db, topic_id=topic_id, unit_type="intro_arc")
    assert len(rows) == 2

    _patch_embed(
        monkeypatch,
        {
            "__query__": [1.0, 0.0, 0.0],
            "conditional dependence": [0.99, 0.05, 0.0],
            "partial correlation": [0.98, 0.1, 0.0],
            "channel collapse": [0.97, 0.1, 0.0],
            "__default__": [0.0, 0.0, 1.0],
        },
    )
    ranked = rank_exemplar_rows(
        db,
        query="conditional dependence gating across channels",
        rows=rows,
        top_k=1,
        use_embeddings=True,
    )
    assert ranked and ranked[0]["source_paper_id"] == 11


def test_exemplar_retrieve_loads_table_without_units(db, monkeypatch):
    from research_harness.primitives.exemplar_impls import exemplar_retrieve
    from research_harness.retrieval import upsert_exemplar_units

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, status, created_at) VALUES (?,?,?,?)",
            ("eag-load", "t", "active", "2026-03-01"),
        )
        conn.commit()
    finally:
        conn.close()

    upsert_exemplar_units(
        db,
        topic_id=1,
        units=[
            {
                "unit_type": "skeleton",
                "source_paper_id": 7,
                "source_title": "Dependence Gating Architecture",
                "venue": "NeurIPS",
                "venue_tier": "A",
                "quality": 8.0,
                "form": {
                    "sections": [
                        {"name": "method", "role": "mechanism", "key_moves": ["gate"]}
                    ]
                },
                "summary": "conditional dependence sections",
            },
            {
                "unit_type": "skeleton",
                "source_paper_id": 8,
                "source_title": "Bread Crumb Topology",
                "venue": "Kitchen",
                "venue_tier": "?",
                "quality": 9.5,
                "form": {
                    "sections": [
                        {"name": "bake", "role": "heat", "key_moves": ["crumb"]}
                    ]
                },
                "summary": "oven temperature curves",
            },
            {
                "unit_type": "skeleton",
                "source_paper_id": 9,
                "source_title": "Noise Paper",
                "venue": "X",
                "venue_tier": "?",
                "quality": 7.0,
                "form": {"sections": [{"name": "misc", "role": "other"}]},
                "summary": "unrelated filler",
            },
            {
                "unit_type": "skeleton",
                "source_paper_id": 10,
                "source_title": "More Noise",
                "venue": "Y",
                "venue_tier": "?",
                "quality": 7.1,
                "form": {"sections": [{"name": "misc2", "role": "other"}]},
                "summary": "still unrelated",
            },
        ],
    )
    _patch_embed(
        monkeypatch,
        {
            "__query__": [1.0, 0.0, 0.0],
            "conditional dependence": [0.99, 0.0, 0.0],
            "Dependence Gating": [0.98, 0.05, 0.0],
            "__default__": [0.0, 1.0, 0.0],
        },
    )

    def boom(*_a, **_k):
        raise RuntimeError("no llm")

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls._llm",
        boom,
    )
    out = exemplar_retrieve(
        db=db,
        topic_id=1,
        unit_type="skeleton",
        target_content="conditional dependence gating method section",
        top_k=1,
        use_embed_rank=True,
    )
    assert out.ranked
    assert out.ranked[0].source_paper_id == 7
    assert "embed" in out.rationale


def test_search_extracted_figures_caption_embed(db, monkeypatch):
    from research_harness.retrieval import search_extracted_figures

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, abstract, year, venue) VALUES (?,?,?,?)",
            ("Gating Paper", "abs", 2025, "ICLR"),
        )
        conn.execute(
            "INSERT INTO papers (title, abstract, year, venue) VALUES (?,?,?,?)",
            ("Bake Paper", "abs", 2024, "Kitchen"),
        )
        # quality_score column from migration 078
        conn.execute(
            """
            INSERT INTO extracted_figures
                (paper_id, figure_number, caption, interpretation, figure_type, quality_score)
            VALUES (?,?,?,?,?,?)
            """,
            (
                1,
                1,
                "Partial correlation gate heatmaps across channels",
                "shows channel collapse remedy under conditional dependence",
                "heatmap",
                8.0,
            ),
        )
        conn.execute(
            """
            INSERT INTO extracted_figures
                (paper_id, figure_number, caption, interpretation, figure_type, quality_score)
            VALUES (?,?,?,?,?,?)
            """,
            (
                2,
                1,
                "Sourdough crumb cross-section photos",
                "baking hydration outcomes",
                "photo",
                9.0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    _patch_embed(
        monkeypatch,
        {
            "__query__": [1.0, 0.0, 0.0],
            "Partial correlation": [0.99, 0.05, 0.0],
            "conditional dependence": [0.98, 0.05, 0.0],
            "channel collapse": [0.97, 0.1, 0.0],
            "__default__": [0.0, 0.0, 1.0],
        },
    )
    hits = search_extracted_figures(
        db,
        query="conditional dependence channel gating heatmap",
        top_k=1,
        use_embeddings=True,
    )
    assert hits and hits[0].paper_id == 1
    assert hits[0].figure_type == "heatmap"


def test_degraded_embeddings_do_not_reorder(db, monkeypatch):
    """Substituted fake vectors must not steer the ranking.

    When the real provider fails, ``embed_texts`` returns hash-noise vectors
    with ``degraded=True``. Blending those at ``embed_weight`` silently
    randomizes the order, so rerank must drop the dense signal and rank on
    lexical evidence alone.
    """

    def degraded_embed_texts(_db, texts, **_kwargs):
        # Vectors that would put the lexically-irrelevant doc first if used.
        vectors = [_norm([1.0, 0.0])]
        for text in texts[1:]:
            vectors.append(
                _norm([0.0, 1.0]) if "molecules" in text else _norm([1.0, 0.0])
            )
        return EmbeddingResult(
            provider="fake",
            model="fake-v1",
            vectors=vectors,
            dim=2,
            errors=["openai error: 503"],
            degraded=True,
        )

    monkeypatch.setattr("research_harness.embeddings.embed_texts", degraded_embed_texts)
    hits = retrieve_then_rerank(
        db,
        "graph neural network molecules",
        [
            ("relevant", "graph neural networks for molecules"),
            ("noise", "unrelated baking recipes and pastry dough"),
        ],
        top_k=2,
        use_embeddings=True,
        embed_all_max=64,
    )
    assert hits[0].doc_id == "relevant"
    assert all(h.embed_score == 0.0 for h in hits)
