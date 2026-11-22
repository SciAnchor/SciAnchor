"""Local asset loaders for retrieve-then-rerank (exemplars + figures).

IDX03/W4 and W5 online path only — no ANN, no offline worker.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..storage.db import Database
from .rerank import retrieve_then_rerank

logger = logging.getLogger(__name__)


def _form_text(form: dict[str, Any] | None, summary: str = "") -> str:
    """Flatten form JSON into ranking text (FORM keys, not source prose)."""
    parts: list[str] = []
    if summary:
        parts.append(str(summary))
    if not isinstance(form, dict):
        return " ".join(parts)

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                parts.append(str(k).replace("_", " "))
                walk(v, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for item in obj[:24]:
                walk(item, depth + 1)
        elif obj is not None and str(obj).strip():
            parts.append(str(obj)[:200])

    walk(form)
    return " ".join(parts)


def upsert_exemplar_units(
    db: Database,
    *,
    topic_id: int,
    units: list[Any],
) -> int:
    """Persist curated exemplar units. Returns rows written."""
    if not topic_id or not units:
        return 0
    conn = db.connect()
    written = 0
    try:
        for u in units:
            if isinstance(u, dict):
                unit_type = str(u.get("unit_type", "") or "")
                source_paper_id = int(u.get("source_paper_id", 0) or 0)
                source_title = str(u.get("source_title", "") or "")
                venue = str(u.get("venue", "") or "")
                venue_tier = str(u.get("venue_tier", "") or "")
                quality = float(u.get("quality", 0) or 0)
                form = u.get("form") if isinstance(u.get("form"), dict) else {}
                summary = str(u.get("summary", "") or "")
            else:
                unit_type = str(getattr(u, "unit_type", "") or "")
                source_paper_id = int(getattr(u, "source_paper_id", 0) or 0)
                source_title = str(getattr(u, "source_title", "") or "")
                venue = str(getattr(u, "venue", "") or "")
                venue_tier = str(getattr(u, "venue_tier", "") or "")
                quality = float(getattr(u, "quality", 0) or 0)
                form = getattr(u, "form", None)
                form = form if isinstance(form, dict) else {}
                summary = str(getattr(u, "summary", "") or "")
            if not unit_type:
                continue
            conn.execute(
                """
                INSERT INTO exemplar_units
                    (topic_id, unit_type, source_paper_id, source_title,
                     venue, venue_tier, quality, form_json, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id, unit_type, source_paper_id) DO UPDATE SET
                    source_title=excluded.source_title,
                    venue=excluded.venue,
                    venue_tier=excluded.venue_tier,
                    quality=excluded.quality,
                    form_json=excluded.form_json,
                    summary=excluded.summary,
                    created_at=datetime('now')
                """,
                (
                    int(topic_id),
                    unit_type,
                    source_paper_id,
                    source_title,
                    venue,
                    venue_tier,
                    quality,
                    json.dumps(form, ensure_ascii=False),
                    summary[:500],
                ),
            )
            written += 1
        conn.commit()
    except Exception as exc:
        logger.debug("exemplar_units upsert skipped: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        conn.close()
    return written


def load_exemplar_unit_rows(
    db: Database,
    *,
    topic_id: int | None,
    unit_type: str,
    min_quality: float = 0.0,
) -> list[dict[str, Any]]:
    """Load exemplar_units rows for a topic/type (empty if table missing)."""
    if topic_id is None or not unit_type:
        return []
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, topic_id, unit_type, source_paper_id, source_title,
                   venue, venue_tier, quality, form_json, summary
            FROM exemplar_units
            WHERE topic_id = ? AND unit_type = ? AND quality >= ?
            ORDER BY quality DESC, id ASC
            """,
            (int(topic_id), str(unit_type), float(min_quality)),
        ).fetchall()
    except Exception as exc:
        logger.debug("exemplar_units load skipped: %s", exc)
        return []
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        form_raw = r["form_json"] if "form_json" in r.keys() else "{}"
        try:
            form = json.loads(form_raw or "{}")
        except Exception:
            form = {}
        if not isinstance(form, dict):
            form = {}
        out.append(
            {
                "id": int(r["id"]),
                "topic_id": int(r["topic_id"]),
                "unit_type": str(r["unit_type"] or ""),
                "source_paper_id": int(r["source_paper_id"] or 0),
                "source_title": str(r["source_title"] or ""),
                "venue": str(r["venue"] or ""),
                "venue_tier": str(r["venue_tier"] or ""),
                "quality": float(r["quality"] or 0),
                "form": form,
                "summary": str(r["summary"] or ""),
            }
        )
    return out


def rank_exemplar_rows(
    db: Database,
    *,
    query: str,
    rows: list[dict[str, Any]],
    top_k: int = 3,
    use_embeddings: bool = True,
) -> list[dict[str, Any]]:
    """Rank exemplar rows by FORM text via retrieve-then-rerank."""
    if not rows or top_k <= 0:
        return []
    if len(rows) <= top_k and not query.strip():
        return sorted(rows, key=lambda r: -float(r.get("quality") or 0))[:top_k]

    documents = []
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        doc_id = str(r.get("id") or r.get("source_paper_id") or len(by_id))
        text = _form_text(r.get("form"), str(r.get("summary") or ""))
        # quality as prior so high-gated units stay preferred when ties
        by_id[doc_id] = r
        documents.append((doc_id, text, {"quality": float(r.get("quality") or 0)}))

    prior = {doc_id: float(meta.get("quality") or 0) for doc_id, _, meta in documents}
    ranked = retrieve_then_rerank(
        db,
        query or "exemplar form",
        documents,
        top_k=top_k,
        shortlist_k=max(top_k * 4, 16),
        use_embeddings=use_embeddings,
        embed_weight=0.55,
        prior_scores=prior,
        prior_weight=0.25,
    )
    out: list[dict[str, Any]] = []
    for hit in ranked:
        row = by_id.get(hit.doc_id)
        if row is not None:
            enriched = dict(row)
            enriched["rank_score"] = float(hit.score)
            out.append(enriched)
    if len(out) < top_k:
        seen = {r.get("id") for r in out}
        for r in sorted(rows, key=lambda x: -float(x.get("quality") or 0)):
            if r.get("id") in seen:
                continue
            out.append(r)
            if len(out) >= top_k:
                break
    return out[:top_k]


@dataclass(frozen=True)
class FigureHit:
    figure_id: int
    paper_id: int
    figure_number: int
    caption: str
    interpretation: str
    figure_type: str
    quality_score: float | None
    score: float
    paper_title: str = ""


def search_extracted_figures(
    db: Database,
    *,
    query: str,
    topic_id: int | None = None,
    paper_id: int | None = None,
    figure_type: str = "",
    top_k: int = 10,
    use_embeddings: bool = True,
) -> list[FigureHit]:
    """Retrieve figures by caption+interpretation text (local pool only)."""
    query = (query or "").strip()
    if not query or top_k <= 0:
        return []

    clauses: list[str] = []
    params: list[Any] = []
    if paper_id is not None:
        clauses.append("ef.paper_id = ?")
        params.append(int(paper_id))
    if topic_id is not None:
        clauses.append(
            "ef.paper_id IN (SELECT paper_id FROM paper_topics WHERE topic_id = ?)"
        )
        params.append(int(topic_id))
    if figure_type:
        clauses.append("LOWER(COALESCE(ef.figure_type, '')) LIKE ?")
        params.append(f"%{figure_type.lower()}%")

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT ef.id, ef.paper_id, ef.figure_number, ef.caption, ef.interpretation,
               ef.figure_type, ef.quality_score, p.title AS paper_title
        FROM extracted_figures ef
        LEFT JOIN papers p ON p.id = ef.paper_id
        {where}
        ORDER BY ef.id ASC
        LIMIT 500
    """
    conn = db.connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as exc:
        logger.debug("extracted_figures search skipped: %s", exc)
        return []
    finally:
        conn.close()

    if not rows:
        return []

    documents = []
    by_id: dict[str, Any] = {}
    prior: dict[str, float] = {}
    for r in rows:
        doc_id = str(r["id"])
        caption = str(r["caption"] or "")
        interp = str(r["interpretation"] or "")
        ftype = str(r["figure_type"] or "")
        text = " ".join(part for part in (caption, interp, ftype) if part)
        qs = r["quality_score"] if "quality_score" in r.keys() else None
        try:
            qsf = float(qs) if qs is not None else 0.0
        except (TypeError, ValueError):
            qsf = 0.0
        by_id[doc_id] = r
        prior[doc_id] = qsf
        documents.append((doc_id, text, {"quality_score": qsf}))

    ranked = retrieve_then_rerank(
        db,
        query,
        documents,
        top_k=top_k,
        shortlist_k=max(top_k * 5, 32),
        use_embeddings=use_embeddings,
        embed_weight=0.6,
        prior_scores=prior if any(prior.values()) else None,
        prior_weight=0.15 if any(prior.values()) else 0.0,
    )
    hits: list[FigureHit] = []
    for hit in ranked:
        r = by_id.get(hit.doc_id)
        if r is None:
            continue
        qs = r["quality_score"] if "quality_score" in r.keys() else None
        try:
            qsf = float(qs) if qs is not None else None
        except (TypeError, ValueError):
            qsf = None
        hits.append(
            FigureHit(
                figure_id=int(r["id"]),
                paper_id=int(r["paper_id"] or 0),
                figure_number=int(r["figure_number"] or 0),
                caption=str(r["caption"] or ""),
                interpretation=str(r["interpretation"] or ""),
                figure_type=str(r["figure_type"] or ""),
                quality_score=qsf,
                score=float(hit.score),
                paper_title=str(r["paper_title"] or ""),
            )
        )
    return hits
