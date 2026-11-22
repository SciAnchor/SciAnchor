"""PanoramaStore: L1 access layer for the Domain Panorama KB.

The store owns one directory (default `<rh-state>/panorama/`):

    L0/   raw snapshots (server-side; laptop copies are partial)
    L1/panorama.db   this store
    L2/vault/        regenerable markdown views (written by views.py)

Papers are never duplicated as truth: `pool_paper_id` + external ids point back
to the RH pool DB, which stays the true source for paper metadata.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import (
    EDGE_RELS,
    ENTITY_KINDS,
    VERDICT_SCOPE_KINDS,
    apply_schema,
)

_ENV_ROOT = "RH_PANORAMA_DIR"


def default_panorama_root(db_path: Path | str | None = None) -> Path:
    """Resolve the panorama root: env override, else sibling of the RH DB."""
    env = os.environ.get(_ENV_ROOT)
    if env:
        return Path(env).expanduser()
    if db_path is not None:
        return Path(db_path).expanduser().resolve().parent / "panorama"
    from .._core.config import GLOBAL_DB_PATH

    return GLOBAL_DB_PATH.parent / "panorama"


def _dumps(obj: Any) -> str:
    return json.dumps(obj or {}, ensure_ascii=False, sort_keys=True)


def _utc_now() -> str:
    """Now, in the same format SQLite's ``datetime('now')`` produces.

    Verdict expiry is compared as a string against `valid_until`, which SQLite
    wrote, so both sides must use the same shape.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for key in ("attrs_json", "ext_ids_json", "evidence_json"):
        if key in out and isinstance(out[key], str):
            try:
                out[key[: -len("_json")]] = json.loads(out[key])
            except ValueError:
                out[key[: -len("_json")]] = {}
            del out[key]
    return out


class PanoramaStore:
    """SQLite-backed L1 store. One instance per panorama root directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self.db_path = self.root / "L1" / "panorama.db"
        self.vault_dir = self.root / "L2" / "vault"
        self.l0_dir = self.root / "L0"

    # -- lifecycle ---------------------------------------------------------

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.l0_dir.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            apply_schema(conn)
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # -- directions --------------------------------------------------------

    def get_or_create_direction(
        self,
        slug: str,
        title: str,
        *,
        description: str = "",
        rh_domain_id: int | None = None,
    ) -> int:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT id FROM directions WHERE slug = ?", (slug,)
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO directions (slug, title, description, rh_domain_id) "
                "VALUES (?, ?, ?, ?)",
                (slug, title, description, rh_domain_id),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def direction(self, slug: str) -> dict[str, Any] | None:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT * FROM directions WHERE slug = ?", (slug,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # -- entities ----------------------------------------------------------

    def upsert_entity(
        self,
        direction_id: int,
        kind: str,
        name: str,
        *,
        summary: str = "",
        attrs: dict[str, Any] | None = None,
        ext_ids: dict[str, str] | None = None,
        pool_paper_id: int | None = None,
        source: str = "",
        extractor_model: str = "",
        confidence: float | None = None,
    ) -> int:
        """Insert or merge an entity.

        Dedup order: any matching external id (scheme, value) → existing row;
        else (direction, kind, name). On merge, ext_ids/attrs are unioned and a
        longer summary wins; existing non-empty fields are never blanked.
        """
        if kind not in ENTITY_KINDS:
            raise ValueError(f"unknown entity kind: {kind}")
        name = name.strip()
        if not name:
            raise ValueError("entity name must be non-empty")
        ext_ids = {k: str(v) for k, v in (ext_ids or {}).items() if v}
        conn = self.connect()
        try:
            entity_id: int | None = None
            for scheme, value in ext_ids.items():
                row = conn.execute(
                    "SELECT e.id FROM entity_ext_ids x JOIN entities e "
                    "ON e.id = x.entity_id "
                    "WHERE x.scheme = ? AND x.value = ? AND e.direction_id = ?",
                    (scheme, value, direction_id),
                ).fetchone()
                if row is not None:
                    entity_id = int(row["id"])
                    break
            if entity_id is None:
                row = conn.execute(
                    "SELECT id FROM entities WHERE direction_id = ? AND kind = ? "
                    "AND name = ?",
                    (direction_id, kind, name),
                ).fetchone()
                if row is not None:
                    entity_id = int(row["id"])

            if entity_id is None:
                cur = conn.execute(
                    "INSERT INTO entities (direction_id, kind, name, summary, "
                    "attrs_json, ext_ids_json, pool_paper_id, source, "
                    "extractor_model, confidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        direction_id,
                        kind,
                        name,
                        summary,
                        _dumps(attrs),
                        _dumps(ext_ids),
                        pool_paper_id,
                        source,
                        extractor_model,
                        confidence,
                    ),
                )
                entity_id = int(cur.lastrowid)
            else:
                row = conn.execute(
                    "SELECT summary, attrs_json, ext_ids_json, pool_paper_id "
                    "FROM entities WHERE id = ?",
                    (entity_id,),
                ).fetchone()
                merged_attrs = {}
                merged_ext = {}
                try:
                    merged_attrs = json.loads(row["attrs_json"]) or {}
                    merged_ext = json.loads(row["ext_ids_json"]) or {}
                except ValueError:
                    pass
                merged_attrs.update(attrs or {})
                merged_ext.update(ext_ids)
                new_summary = (
                    summary
                    if len(summary) > len(row["summary"] or "")
                    else row["summary"]
                )
                conn.execute(
                    "UPDATE entities SET summary = ?, attrs_json = ?, "
                    "ext_ids_json = ?, pool_paper_id = COALESCE(?, pool_paper_id), "
                    "updated_at = datetime('now') WHERE id = ?",
                    (
                        new_summary,
                        _dumps(merged_attrs),
                        _dumps(merged_ext),
                        pool_paper_id,
                        entity_id,
                    ),
                )
            for scheme, value in ext_ids.items():
                conn.execute(
                    "INSERT OR IGNORE INTO entity_ext_ids (entity_id, scheme, value) "
                    "VALUES (?, ?, ?)",
                    (entity_id, scheme, value),
                )
            conn.commit()
            return entity_id
        finally:
            conn.close()

    def entities(
        self, direction_id: int, kind: str | None = None
    ) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            if kind is None:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE direction_id = ? ORDER BY id",
                    (direction_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE direction_id = ? AND kind = ? "
                    "ORDER BY id",
                    (direction_id, kind),
                ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def entity(self, entity_id: int) -> dict[str, Any] | None:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    # -- edges -------------------------------------------------------------

    def add_edge(
        self,
        direction_id: int,
        src_id: int,
        dst_id: int,
        rel: str,
        *,
        event_at: str | None = None,
        valid_until: str | None = None,
        attrs: dict[str, Any] | None = None,
        confidence: float | None = None,
        dedupe: bool = True,
    ) -> int:
        if rel not in EDGE_RELS:
            raise ValueError(f"unknown edge rel: {rel}")
        conn = self.connect()
        try:
            if dedupe:
                row = conn.execute(
                    "SELECT id FROM edges WHERE src_id = ? AND dst_id = ? "
                    "AND rel = ? AND valid_until IS NULL",
                    (src_id, dst_id, rel),
                ).fetchone()
                if row is not None:
                    return int(row["id"])
            cur = conn.execute(
                "INSERT INTO edges (direction_id, src_id, dst_id, rel, event_at, "
                "valid_until, attrs_json, confidence) VALUES (?,?,?,?,?,?,?,?)",
                (
                    direction_id,
                    src_id,
                    dst_id,
                    rel,
                    event_at,
                    valid_until,
                    _dumps(attrs),
                    confidence,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def expire_edge(self, edge_id: int, *, invalidated_by: int | None = None) -> None:
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE edges SET valid_until = datetime('now'), "
                "invalidated_by = ? WHERE id = ? AND valid_until IS NULL",
                (invalidated_by, edge_id),
            )
            conn.commit()
        finally:
            conn.close()

    def edges_for(self, entity_id: int, *, live_only: bool = True) -> list[dict]:
        conn = self.connect()
        try:
            sql = "SELECT * FROM edges WHERE (src_id = ? OR dst_id = ?)"
            if live_only:
                sql += " AND valid_until IS NULL"
            rows = conn.execute(sql, (entity_id, entity_id)).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # -- anchors -----------------------------------------------------------

    def add_anchor(
        self,
        target_kind: str,
        target_id: int,
        *,
        keywords: str = "",
        summary: str = "",
        insight: str = "",
        quote: str = "",
        source_ref: str = "",
        fetched_at: str | None = None,
    ) -> int:
        if target_kind not in ("entity", "edge", "cell", "verdict"):
            raise ValueError(f"unknown anchor target kind: {target_kind}")
        conn = self.connect()
        try:
            cur = conn.execute(
                "INSERT INTO anchors (target_kind, target_id, keywords, summary, "
                "insight, quote, source_ref, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    target_kind,
                    target_id,
                    keywords,
                    summary,
                    insight,
                    quote,
                    source_ref,
                    fetched_at,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def anchors_for(self, target_kind: str, target_id: int) -> list[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM anchors WHERE target_kind = ? AND target_id = ?",
                (target_kind, target_id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -- territory map -----------------------------------------------------

    def upsert_cell(
        self,
        direction_id: int,
        problem: str,
        mechanism: str,
        evidence_facet: str = "",
        *,
        evidence_strength: str | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> int:
        conn = self.connect()
        try:
            conn.execute(
                "INSERT INTO territory_cells (direction_id, problem, mechanism, "
                "evidence_facet) VALUES (?,?,?,?) "
                "ON CONFLICT(direction_id, problem, mechanism, evidence_facet) "
                "DO NOTHING",
                (direction_id, problem, mechanism, evidence_facet),
            )
            row = conn.execute(
                "SELECT id FROM territory_cells WHERE direction_id = ? "
                "AND problem = ? AND mechanism = ? AND evidence_facet = ?",
                (direction_id, problem, mechanism, evidence_facet),
            ).fetchone()
            cell_id = int(row["id"])
            sets, params = [], []
            if evidence_strength is not None:
                sets.append("evidence_strength = ?")
                params.append(evidence_strength)
            if status is not None:
                sets.append("status = ?")
                params.append(status)
            if notes is not None:
                sets.append("notes = ?")
                params.append(notes)
            if sets:
                params.append(cell_id)
                conn.execute(
                    f"UPDATE territory_cells SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
            conn.commit()
            return cell_id
        finally:
            conn.close()

    def occupy_cell(self, cell_id: int, entity_id: int, role: str = "occupies") -> None:
        conn = self.connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cell_claims (cell_id, entity_id, role) "
                "VALUES (?,?,?)",
                (cell_id, entity_id, role),
            )
            conn.execute(
                "UPDATE territory_cells SET status = CASE WHEN status = 'unknown' "
                "THEN 'occupied' ELSE status END WHERE id = ?",
                (cell_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def cells(self, direction_id: int, status: str | None = None) -> list[dict]:
        conn = self.connect()
        try:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM territory_cells WHERE direction_id = ? "
                    "ORDER BY problem, mechanism",
                    (direction_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM territory_cells WHERE direction_id = ? "
                    "AND status = ? ORDER BY problem, mechanism",
                    (direction_id, status),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def cell_occupants(self, cell_id: int) -> list[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT e.*, c.role FROM cell_claims c JOIN entities e "
                "ON e.id = c.entity_id WHERE c.cell_id = ? ORDER BY e.id",
                (cell_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def merge_cell_into(self, src_cell_id: int, dst_cell_id: int) -> int:
        """Move all occupants of ``src`` into ``dst`` and delete ``src``.

        Returns the number of occupant links moved. Both cells must exist and
        belong to the same direction; a deleted source row cannot leave a
        phantom empty cell behind (which would read as a false gap).
        """
        if src_cell_id == dst_cell_id:
            raise ValueError("merge_cell_into requires two distinct cells")
        conn = self.connect()
        try:
            cells = {
                int(r["id"]): r
                for r in conn.execute(
                    "SELECT * FROM territory_cells WHERE id IN (?, ?)",
                    (src_cell_id, dst_cell_id),
                ).fetchall()
            }
            if src_cell_id not in cells or dst_cell_id not in cells:
                raise ValueError("merge_cell_into: unknown cell id")
            if cells[src_cell_id]["direction_id"] != cells[dst_cell_id]["direction_id"]:
                raise ValueError(
                    "merge_cell_into: cells belong to different directions"
                )
            moved = conn.execute(
                "SELECT COUNT(*) AS n FROM cell_claims WHERE cell_id = ?",
                (src_cell_id,),
            ).fetchone()["n"]
            conn.execute(
                "INSERT OR REPLACE INTO cell_claims (cell_id, entity_id, role) "
                "SELECT ?, entity_id, role FROM cell_claims WHERE cell_id = ?",
                (dst_cell_id, src_cell_id),
            )
            conn.execute("DELETE FROM cell_claims WHERE cell_id = ?", (src_cell_id,))
            conn.execute("DELETE FROM territory_cells WHERE id = ?", (src_cell_id,))
            conn.execute(
                "UPDATE territory_cells SET status = CASE WHEN status = 'unknown' "
                "THEN 'occupied' ELSE status END WHERE id = ?",
                (dst_cell_id,),
            )
            conn.commit()
            return int(moved)
        finally:
            conn.close()

    # -- verdicts (gap_ground_verify write-back) ---------------------------

    def record_verdict(
        self,
        direction_id: int,
        claim_text: str,
        verdict: str,
        *,
        cell_id: int | None = None,
        tool: str = "gap_ground_verify",
        evidence: dict[str, Any] | None = None,
        scope_kind: str = "unscoped",
        scope_ref: str = "",
        evidence_snapshot_id: str = "",
        ttl_days: int | None = None,
        revival_triggers: list[str] | None = None,
        source_hash: str = "",
    ) -> int:
        """Record a verdict. Unscoped writes are diagnostic-only by default.

        A verdict only becomes `active` — that is, only becomes something
        ranking and promotion may consult — when the caller says what it is
        about (`scope_kind` + `scope_ref`). Omitting that is not an error, but
        the row is stored as `legacy_unscoped` / `diagnostic_only`, because a
        judgement with no recorded scope cannot be re-checked later and must not
        silently keep influencing decisions.
        """
        if scope_kind not in VERDICT_SCOPE_KINDS:
            raise ValueError(
                f"scope_kind must be one of {VERDICT_SCOPE_KINDS}, got {scope_kind!r}"
            )
        if scope_kind == "unscoped" and cell_id is not None:
            # A `gap_ground_verify` write-back against a territory cell already
            # has a real scope: that cell. Infer it rather than quarantining a
            # correctly-scoped verdict for not spelling it out.
            scope_kind, scope_ref = "cell", f"cell:{cell_id}"
        scoped = scope_kind != "unscoped" and bool(scope_ref.strip())
        if scope_kind != "unscoped" and not scope_ref.strip():
            raise ValueError(
                f"scope_kind={scope_kind!r} requires a non-empty scope_ref"
            )
        scope_status = "scoped" if scoped else "legacy_unscoped"
        eligibility = "active" if scoped else "diagnostic_only"
        quarantine_reason = (
            "" if scoped else "written without a scope; not eligible for ranking"
        )
        conn = self.connect()
        try:
            cur = conn.execute(
                "INSERT INTO verdicts (direction_id, cell_id, claim_text, verdict, "
                "tool, evidence_json, scope_kind, scope_ref, scope_status, "
                "eligibility, quarantine_reason, evidence_snapshot_id, valid_until, "
                "revival_triggers_json, source_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,"
                + ("datetime('now', ?)" if ttl_days is not None else "?")
                + ",?,?)",
                (
                    direction_id,
                    cell_id,
                    claim_text,
                    verdict,
                    tool,
                    _dumps(evidence),
                    scope_kind,
                    scope_ref,
                    scope_status,
                    eligibility,
                    quarantine_reason,
                    evidence_snapshot_id,
                    # `{:+d}` so a negative TTL yields "-1 days", which SQLite
                    # parses; "+-1 days" would silently produce NULL.
                    f"{int(ttl_days):+d} days" if ttl_days is not None else None,
                    _dumps(revival_triggers or []),
                    source_hash,
                ),
            )
            if cell_id is not None:
                conn.execute(
                    "UPDATE territory_cells SET last_verified_at = datetime('now') "
                    "WHERE id = ?",
                    (cell_id,),
                )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def verdicts(self, direction_id: int) -> list[dict]:
        """Every verdict row, including quarantined and expired ones.

        This is the raw audit accessor. Anything that ranks, promotes, or
        renders should use :meth:`active_verdicts` instead — see
        :meth:`effective_eligibility` for why a row that says `active` in the
        column may still not be.
        """
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM verdicts WHERE direction_id = ? ORDER BY decided_at",
                (direction_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def effective_eligibility(verdict: dict[str, Any]) -> str:
        """Eligibility after applying expiry and supersession.

        The stored column is not the whole answer: a scoped, active verdict
        stops being usable once it is past `valid_until` or has been superseded.
        Computing it at read time means an expired verdict cannot keep counting
        just because no writer happened to run.
        """
        if verdict.get("superseded_by"):
            return "diagnostic_only"
        stored = verdict.get("eligibility") or "diagnostic_only"
        if stored != "active":
            return stored
        valid_until = verdict.get("valid_until")
        if valid_until and str(valid_until) < _utc_now():
            return "diagnostic_only"
        return "active"

    def active_verdicts(self, direction_id: int) -> list[dict]:
        """Verdicts that may influence ranking and promotion. Deny by default."""
        return [
            verdict
            for verdict in self.verdicts(direction_id)
            if self.effective_eligibility(verdict) == "active"
        ]

    def supersede_verdict(self, verdict_id: int, replacement_id: int) -> None:
        """Point an old verdict at the one that replaced it.

        Append-only: the superseded row keeps its text and evidence so the
        history stays auditable, it simply stops being live.
        """
        if verdict_id == replacement_id:
            raise ValueError("a verdict cannot supersede itself")
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE verdicts SET superseded_by = ? WHERE id = ?",
                (replacement_id, verdict_id),
            )
            conn.commit()
        finally:
            conn.close()

    def quarantine_verdict(self, verdict_id: int, reason: str) -> None:
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE verdicts SET eligibility = 'quarantined', "
                "quarantine_reason = ? WHERE id = ?",
                (reason, verdict_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -- search / stats ----------------------------------------------------

    def search(
        self,
        direction_id: int,
        query: str,
        *,
        kinds: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """FTS5 keyword search over entity name+summary; LIKE fallback."""
        conn = self.connect()
        try:
            try:
                rows = conn.execute(
                    "SELECT e.*, bm25(entities_fts) AS score FROM entities_fts f "
                    "JOIN entities e ON e.id = f.rowid "
                    "WHERE entities_fts MATCH ? AND e.direction_id = ? "
                    "ORDER BY score LIMIT ?",
                    (query, direction_id, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query}%"
                rows = conn.execute(
                    "SELECT e.*, 0.0 AS score FROM entities e "
                    "WHERE e.direction_id = ? AND (e.name LIKE ? OR e.summary LIKE ?) "
                    "LIMIT ?",
                    (direction_id, like, like, limit),
                ).fetchall()
            out = [_row_to_dict(r) for r in rows]
            if kinds:
                out = [e for e in out if e["kind"] in kinds]
            return out
        finally:
            conn.close()

    def stats(self, direction_id: int) -> dict[str, Any]:
        conn = self.connect()
        try:
            by_kind = {
                r["kind"]: r["n"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) AS n FROM entities "
                    "WHERE direction_id = ? GROUP BY kind",
                    (direction_id,),
                ).fetchall()
            }
            edges = conn.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE direction_id = ? "
                "AND valid_until IS NULL",
                (direction_id,),
            ).fetchone()["n"]
            cells = conn.execute(
                "SELECT status, COUNT(*) AS n FROM territory_cells "
                "WHERE direction_id = ? GROUP BY status",
                (direction_id,),
            ).fetchall()
            verdicts = conn.execute(
                "SELECT COUNT(*) AS n FROM verdicts WHERE direction_id = ?",
                (direction_id,),
            ).fetchone()["n"]
            anchors = conn.execute("SELECT COUNT(*) AS n FROM anchors").fetchone()["n"]
            return {
                "entities_by_kind": by_kind,
                "entities_total": sum(by_kind.values()),
                "live_edges": edges,
                "cells_by_status": {r["status"]: r["n"] for r in cells},
                "verdicts": verdicts,
                "anchors": anchors,
            }
        finally:
            conn.close()

    # -- harvest (capture-recapture substrate) -----------------------------

    def record_harvest_run(
        self,
        direction_id: int,
        source: str,
        query: str,
        hits: list[dict[str, Any]],
        *,
        round_no: int = 1,
        attrs: dict[str, Any] | None = None,
    ) -> int:
        """Persist one harvest query and its hits.

        Each hit: {"identity": canonical id string (e.g. "arxiv:2408.06292" or
        "title:<normhash>"), "scheme": ..., "title": ...,
        "matched_entity_id": optional, "relevance": optional}.
        new_count counts identities never seen in any earlier run for this
        direction (the marginal-discovery numerator).
        """
        conn = self.connect()
        try:
            seen = {
                r["identity"]
                for r in conn.execute(
                    "SELECT DISTINCT h.identity FROM harvest_hits h "
                    "JOIN harvest_runs r ON r.id = h.run_id "
                    "WHERE r.direction_id = ?",
                    (direction_id,),
                ).fetchall()
            }
            new_count = len({h["identity"] for h in hits} - seen)
            cur = conn.execute(
                "INSERT INTO harvest_runs (direction_id, source, query, round, "
                "finished_at, result_count, new_count, attrs_json) "
                "VALUES (?,?,?,?,datetime('now'),?,?,?)",
                (
                    direction_id,
                    source,
                    query,
                    round_no,
                    len(hits),
                    new_count,
                    _dumps(attrs),
                ),
            )
            run_id = int(cur.lastrowid)
            for hit in hits:
                conn.execute(
                    "INSERT OR IGNORE INTO harvest_hits (run_id, identity, scheme, "
                    "title, matched_entity_id, relevance) VALUES (?,?,?,?,?,?)",
                    (
                        run_id,
                        hit["identity"],
                        hit.get("scheme", ""),
                        hit.get("title", ""),
                        hit.get("matched_entity_id"),
                        hit.get("relevance"),
                    ),
                )
            conn.commit()
            return run_id
        finally:
            conn.close()

    def capture_matrix(self, direction_id: int) -> dict[str, set[str]]:
        """identity -> set of sources that captured it (for Chao estimators)."""
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT h.identity, r.source FROM harvest_hits h "
                "JOIN harvest_runs r ON r.id = h.run_id WHERE r.direction_id = ?",
                (direction_id,),
            ).fetchall()
            matrix: dict[str, set[str]] = {}
            for row in rows:
                matrix.setdefault(row["identity"], set()).add(row["source"])
            return matrix
        finally:
            conn.close()

    def harvest_runs(self, direction_id: int) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM harvest_runs WHERE direction_id = ? ORDER BY id",
                (direction_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def edges(self, direction_id: int, *, live_only: bool = True) -> list[dict]:
        """All edges for a direction (direction-level listing)."""
        conn = self.connect()
        try:
            sql = "SELECT * FROM edges WHERE direction_id = ?"
            if live_only:
                sql += " AND valid_until IS NULL"
            rows = conn.execute(sql, (direction_id,)).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # -- meta --------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        conn = self.connect()
        try:
            conn.execute(
                "INSERT INTO panorama_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    def get_meta(self, key: str) -> str | None:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT value FROM panorama_meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()
