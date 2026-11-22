from __future__ import annotations

import json


def _seed_topic(conn, topic_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO topics (id, name, description, status) VALUES (?, ?, ?, ?)",
        (
            topic_id,
            "eventgraph-urban-sports-consumption",
            "ArcGIS sports-event consumption spatiotemporal analysis",
            "active",
        ),
    )


def _seed_paper(
    conn,
    paper_id: int,
    title: str,
    *,
    topic_id: int = 1,
    status: str = "meta_only",
    relevance: str = "medium",
    year: int | None = 2026,
    venue: str = "Test Venue",
    doi: str | None = None,
    arxiv_id: str | None = None,
    url: str | None = None,
    pdf_path: str = "",
    abstract: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO papers
            (id, title, year, venue, doi, arxiv_id, url, pdf_path, status, abstract)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            title,
            year,
            venue,
            doi,
            arxiv_id,
            url,
            pdf_path,
            status,
            abstract,
        ),
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
        (paper_id, topic_id, relevance),
    )


def test_paper_pool_audit_excludes_topic39_style_noise(db, conn) -> None:
    from research_harness.paper_pool_audit import audit_topic_paper_pool

    _seed_topic(conn)
    _seed_paper(conn, 1, "", doi="10.test/empty")
    _seed_paper(
        conn,
        2,
        "Retro-Augmented Spatiotemporal Causal Decision Trees for Cellular Rejuvenation",
        doi="10.test/cellular",
    )
    _seed_paper(
        conn,
        3,
        "Transaction Fraud Detection Method Based on Event Temporal Graph Attention Network",
        doi="10.test/fraud",
    )
    _seed_paper(
        conn,
        4,
        "Visualizing urban mobility",
        url="https://example.test/visual-a",
    )
    _seed_paper(
        conn,
        5,
        "Visualizing urban mobility",
        url="https://example.test/visual-b",
    )
    _seed_paper(
        conn,
        6,
        "Causal spatiotemporal graph learning for sports event consumption",
        status="annotated",
        relevance="high",
        year=2025,
        venue="KDD",
        doi="10.test/core",
        pdf_path="/tmp/core.pdf",
        abstract="sports event consumption mobility GIS causal graph evaluation",
    )
    conn.commit()

    audit = audit_topic_paper_pool(db, topic_id=1)

    assert audit["schema_version"] == "rh.paper_pool_audit.v1"
    assert audit["counts"]["total_linked"] == 6
    assert audit["counts"]["meta_only"] == 5
    assert audit["counts"]["coverage_eligible"] == 1
    assert audit["counts"]["excluded_metadata_bad"] == 1
    assert audit["counts"]["excluded_noise"] == 2
    assert audit["counts"]["duplicate_title_records"] == 1

    noise_titles = {item["title"] for item in audit["examples"]["excluded_noise"]}
    assert any("Cellular Rejuvenation" in title for title in noise_titles)
    assert any("Fraud Detection" in title for title in noise_titles)
    assert audit["examples"]["excluded_metadata_bad"][0]["reason"] == "empty_title"
    duplicate_group = audit["examples"]["duplicate_title_groups"][0]
    assert duplicate_group["title"] == "Visualizing urban mobility"
    assert duplicate_group["paper_ids"] == [4, 5]

    role_status = audit["role_coverage"]
    assert role_status["causal_identification"]["covered"] is True
    assert role_status["spatiotemporal_graph_learning"]["covered"] is True
    assert role_status["sports_event_consumption"]["covered"] is True
    assert "dataset_source" in audit["missing_roles"]


def test_paper_pool_audit_is_json_safe(db, conn) -> None:
    from research_harness.paper_pool_audit import audit_topic_paper_pool

    _seed_topic(conn)
    _seed_paper(conn, 1, "ArcGIS hotspot baseline for urban sports events")
    conn.commit()

    payload = audit_topic_paper_pool(db, topic_id=1)

    assert json.loads(json.dumps(payload))["topic_id"] == 1


def test_paper_pool_audit_ignores_screened_out_metadata_and_noise(db, conn) -> None:
    from research_harness.paper_pool_audit import audit_topic_paper_pool

    _seed_topic(conn)
    _seed_paper(conn, 1, "", doi="10.test/empty")
    _seed_paper(
        conn,
        2,
        "Infectious Diseases as Socio-Spatial Processes",
        doi="10.test/noise",
    )
    conn.execute(
        """
        UPDATE paper_topics
        SET screening_status = 'screened_out',
            relevance = 'low',
            evidence_role = 'excluded_noise'
        WHERE topic_id = 1
        """
    )
    conn.commit()

    audit = audit_topic_paper_pool(db, topic_id=1)

    assert audit["counts"]["excluded_metadata_bad"] == 0
    assert audit["counts"]["excluded_noise"] == 0
    assert audit["examples"]["excluded_metadata_bad"] == []
    assert audit["examples"]["excluded_noise"] == []


def test_paper_pool_audit_uses_social_science_observational_roles(db, conn) -> None:
    from research_harness.paper_pool_audit import audit_topic_paper_pool

    _seed_topic(conn)
    _seed_paper(
        conn,
        1,
        "POI dataset for urban sports event consumption",
        status="annotated",
        relevance="high",
        year=2024,
        doi="10.test/dataset",
        pdf_path="/tmp/dataset.pdf",
        abstract="point of interest transaction mobility record",
    )
    _seed_paper(
        conn,
        2,
        "ArcGIS hotspot and Moran spatial statistics for sports tourism",
        status="annotated",
        relevance="high",
        year=2024,
        doi="10.test/gis",
        pdf_path="/tmp/gis.pdf",
        abstract="arcgis hotspot moran kernel density",
    )
    _seed_paper(
        conn,
        3,
        "Difference-in-differences evidence on major sport event impacts",
        status="annotated",
        relevance="high",
        year=2024,
        doi="10.test/causal",
        pdf_path="/tmp/causal.pdf",
        abstract="difference-in-differences placebo treatment effect",
    )
    _seed_paper(
        conn,
        4,
        "Spectator sports event consumption and urban economic impact",
        status="annotated",
        relevance="high",
        year=2024,
        doi="10.test/consumption",
        pdf_path="/tmp/consumption.pdf",
        abstract="sports event consumption economic impact",
    )
    _seed_paper(
        conn,
        5,
        "Benchmark protocol for urban spatial consumption models",
        status="annotated",
        relevance="high",
        year=2024,
        doi="10.test/evaluation",
        pdf_path="/tmp/evaluation.pdf",
        abstract="baseline evaluation metric protocol",
    )
    conn.commit()

    audit = audit_topic_paper_pool(
        db,
        topic_id=1,
        required_roles=(
            "dataset_source",
            "gis_spatial_statistics",
            "causal_identification",
            "sports_event_consumption",
            "baseline_evaluation",
        ),
    )

    assert "spatiotemporal_graph_learning" not in audit["role_coverage"]
    assert audit["missing_roles"] == []


def test_paper_pool_audit_counts_explicit_evidence_role_assignments(db, conn) -> None:
    """A screened-in paper assigned an evidence_role counts toward role
    coverage even when its title/abstract lack the gate keywords."""
    from research_harness.paper_pool_audit import audit_topic_paper_pool

    _seed_topic(conn)
    _seed_paper(
        conn,
        1,
        "Urban policy evaluation without gate keywords",
        status="annotated",
        relevance="high",
        year=2024,
        doi="10.test/assigned",
        pdf_path="/tmp/assigned.pdf",
        abstract="a study of city programmes",
    )
    conn.execute(
        """
        UPDATE paper_topics
        SET screening_status = 'screened_in', manuscript_eligible = 1,
            evidence_role = 'causal_identification'
        WHERE topic_id = 1 AND paper_id = 1
        """
    )
    conn.commit()

    audit = audit_topic_paper_pool(
        db, topic_id=1, required_roles=("causal_identification",)
    )

    assert audit["role_coverage"]["causal_identification"]["covered"] is True
    assert audit["missing_roles"] == []
