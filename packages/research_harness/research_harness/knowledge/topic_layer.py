"""Deterministic Topic Knowledge Layer v1 helpers.

This module is private runtime plumbing. It reads existing structured RH rows
to derive semantic atoms/edges, persists the private derived read model and
snapshot artifact, and does not register a public tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from paperindex.cards.schema import PaperCard
from research_harness.storage.db import Database


EXTRACTOR_VERSION = "topic_knowledge_v1"
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SemanticAtom:
    topic_id: int
    atom_type: str
    normalized_key: str
    label: str
    source_type: str
    source_id: str
    source_hash: str
    paper_id: int | None = None
    source_section: str = ""
    snippet: str = ""
    confidence: float = 0.0
    description: str = ""
    extractor_version: str = EXTRACTOR_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def atom_key(self) -> str:
        return "|".join(
            (
                str(self.topic_id),
                self.atom_type,
                self.normalized_key,
                self.source_type,
                self.source_id,
            )
        )


@dataclass(frozen=True)
class SemanticEdge:
    topic_id: int
    edge_type: str
    from_atom_key: str
    to_atom_key: str
    source_type: str
    source_id: str
    source_hash: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def edge_key(self) -> str:
        return "|".join(
            (
                str(self.topic_id),
                self.edge_type,
                self.from_atom_key,
                self.to_atom_key,
                self.source_type,
                self.source_id,
            )
        )


@dataclass(frozen=True)
class TopicKnowledgeDraft:
    topic_id: int
    paper_ids: tuple[int, ...]
    source_records: tuple[dict[str, Any], ...]
    atoms: tuple[SemanticAtom, ...]
    edges: tuple[SemanticEdge, ...]
    coverage: dict[str, int]
    weak_spots: dict[str, list[Any]]


@dataclass(frozen=True)
class TopicKnowledgeSnapshotResult:
    topic_id: int
    artifact_id: int
    snapshot_id: int
    source_hash: str
    snapshot_version: str
    payload: dict[str, Any]
    reused: bool = False


@dataclass(frozen=True)
class TopicKnowledgeSnapshot:
    topic_id: int
    artifact_id: int
    snapshot_id: int
    source_hash: str
    current_source_hash: str
    snapshot_version: str
    payload: dict[str, Any]
    source_manifest: dict[str, Any]
    coverage: dict[str, Any]
    is_current: bool


@dataclass(frozen=True)
class TopicKnowledgeEvidenceMapExport:
    topic_id: int
    path: Path
    snapshot: TopicKnowledgeSnapshot
    markdown: str


def build_topic_knowledge_draft(
    db: Database,
    topic_id: int,
    *,
    focus: str = "",
    max_papers: int | None = None,
    include_stale: bool = False,
) -> TopicKnowledgeDraft:
    """Build a read-only topic knowledge draft from existing structured rows."""

    del include_stale  # Stale filtering applies to future persisted snapshots.
    conn = db.connect()
    try:
        papers = _topic_papers(conn, topic_id, max_papers=max_papers)
        paper_ids = [int(row["id"]) for row in papers]
        paper_id_set = set(paper_ids)
        cards = _paper_cards(conn, paper_ids)
        claims = _normalized_claims(conn, topic_id, paper_id_set)
        gaps = _gaps(conn, topic_id, focus=focus)
        method_atoms = _method_atoms(conn, topic_id, paper_id_set)
        taxonomy_nodes = _taxonomy_nodes(conn, topic_id)
        contradictions = _contradictions(conn, topic_id)

        atom_builder = _AtomBuilder(topic_id=topic_id)
        edge_builder = _EdgeBuilder(topic_id=topic_id)

        _derive_from_cards(atom_builder, cards)
        _derive_from_compiled_summaries(atom_builder, papers)
        _derive_from_claims(atom_builder, edge_builder, claims)
        _derive_from_gaps(atom_builder, gaps)
        _derive_from_method_atoms(atom_builder, method_atoms)
        _derive_from_taxonomy(atom_builder, taxonomy_nodes)
        _derive_from_contradictions(edge_builder, atom_builder, contradictions)

        atoms = tuple(atom_builder.atoms())
        edges = tuple(edge_builder.edges())
        weak_spots = _weak_spots(
            papers=papers,
            cards=cards,
            claims=claims,
            gaps=gaps,
            atoms=atoms,
        )
        coverage = {
            "topic_papers": len(papers),
            "paper_cards": len(cards),
            "annotations": _annotation_count(conn, paper_ids),
            "compiled_summaries": sum(
                1 for row in papers if _text(row["compiled_summary"])
            ),
            "normalized_claims": len(claims),
            "gaps": len(gaps),
            "contradictions": len(contradictions),
            "taxonomy_nodes": len(taxonomy_nodes),
            "method_atoms": len(method_atoms),
            "semantic_atoms": len(atoms),
            "semantic_edges": len(edges),
        }
        return TopicKnowledgeDraft(
            topic_id=topic_id,
            paper_ids=tuple(paper_ids),
            source_records=_source_records(
                papers=papers,
                cards=cards,
                claims=claims,
                gaps=gaps,
                method_atoms=method_atoms,
                taxonomy_nodes=taxonomy_nodes,
                contradictions=contradictions,
            ),
            atoms=atoms,
            edges=edges,
            coverage=coverage,
            weak_spots=weak_spots,
        )
    finally:
        conn.close()


def build_topic_knowledge_snapshot(
    db: Database,
    topic_id: int,
    *,
    focus: str = "",
    max_papers: int | None = None,
    include_stale: bool = False,
    snapshot_version: str = EXTRACTOR_VERSION,
) -> TopicKnowledgeSnapshotResult:
    """Persist a private topic knowledge snapshot artifact and metadata."""

    draft = build_topic_knowledge_draft(
        db,
        topic_id,
        focus=focus,
        max_papers=max_papers,
        include_stale=include_stale,
    )
    source_manifest = _source_manifest(
        draft,
        focus=focus,
        max_papers=max_papers,
    )
    source_hash = _source_hash(source_manifest)

    conn = db.connect()
    try:
        active = _active_snapshot(conn, topic_id)
        if (
            active is not None
            and active["source_hash"] == source_hash
            and active["snapshot_version"] == snapshot_version
        ):
            payload = _json_obj(active["payload_json"]) or {}
            return TopicKnowledgeSnapshotResult(
                topic_id=topic_id,
                artifact_id=int(active["artifact_id"]),
                snapshot_id=int(active["snapshot_id"]),
                source_hash=source_hash,
                snapshot_version=snapshot_version,
                payload=payload,
                reused=True,
            )

        now = _utc_now()
        if active is not None and active["source_hash"] == source_hash:
            _mark_active_snapshots(
                conn,
                topic_id=topic_id,
                status="superseded",
                reason="topic knowledge snapshot superseded by newer snapshot version",
            )
        elif active is not None:
            _mark_active_snapshots(
                conn,
                topic_id=topic_id,
                status="stale",
                reason="topic knowledge sources changed",
            )

        _replace_semantic_read_model(conn, draft)
        payload = _snapshot_payload(
            draft,
            source_manifest=source_manifest,
            source_hash=source_hash,
            snapshot_version=snapshot_version,
            generated_at=now,
        )
        existing = _snapshot_by_source_version(
            conn,
            topic_id=topic_id,
            source_hash=source_hash,
            snapshot_version=snapshot_version,
        )
        if existing is not None:
            _reactivate_snapshot(
                conn,
                snapshot=existing,
                payload=payload,
                source_manifest=source_manifest,
                coverage=draft.coverage,
                source_hash=source_hash,
                snapshot_version=snapshot_version,
            )
            conn.commit()
            return TopicKnowledgeSnapshotResult(
                topic_id=topic_id,
                artifact_id=int(existing["artifact_id"]),
                snapshot_id=int(existing["snapshot_id"]),
                source_hash=source_hash,
                snapshot_version=snapshot_version,
                payload=payload,
                reused=True,
            )

        artifact_id = _insert_snapshot_artifact(
            conn,
            topic_id=topic_id,
            payload=payload,
            source_manifest=source_manifest,
            source_hash=source_hash,
            snapshot_version=snapshot_version,
        )
        cursor = conn.execute(
            """
            INSERT INTO topic_knowledge_snapshots
                (topic_id, artifact_id, status, snapshot_version, source_hash,
                 source_manifest_json, coverage_json)
            VALUES
                (?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                topic_id,
                artifact_id,
                snapshot_version,
                source_hash,
                _stable_json(source_manifest),
                _stable_json(draft.coverage),
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        conn.commit()
        return TopicKnowledgeSnapshotResult(
            topic_id=topic_id,
            artifact_id=artifact_id,
            snapshot_id=snapshot_id,
            source_hash=source_hash,
            snapshot_version=snapshot_version,
            payload=payload,
            reused=False,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_latest_topic_knowledge_snapshot(
    db: Database,
    topic_id: int,
    *,
    focus: str = "",
    max_papers: int | None = None,
    require_current: bool = True,
) -> TopicKnowledgeSnapshot | None:
    """Read the latest active private snapshot, optionally requiring freshness."""

    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT tks.id AS snapshot_id, tks.topic_id, tks.artifact_id,
                   tks.source_hash, tks.snapshot_version,
                   tks.source_manifest_json, tks.coverage_json,
                   pa.payload_json
            FROM topic_knowledge_snapshots tks
            JOIN project_artifacts pa ON pa.id = tks.artifact_id
            WHERE tks.topic_id = ?
              AND tks.status = 'active'
              AND pa.artifact_type = 'topic_knowledge_snapshot'
              AND pa.status = 'active'
              AND pa.stale = 0
            ORDER BY tks.created_at DESC, tks.id DESC
            LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    current_source_hash = _current_topic_knowledge_source_hash(
        db,
        topic_id,
        focus=focus,
        max_papers=max_papers,
    )
    source_hash = str(row["source_hash"] or "")
    is_current = source_hash == current_source_hash
    if require_current and not is_current:
        return None

    payload = _json_obj(row["payload_json"]) or {}
    source_manifest = _json_obj(row["source_manifest_json"]) or payload.get(
        "source_manifest"
    )
    coverage = _json_obj(row["coverage_json"]) or payload.get("coverage")
    return TopicKnowledgeSnapshot(
        topic_id=int(row["topic_id"]),
        artifact_id=int(row["artifact_id"]),
        snapshot_id=int(row["snapshot_id"]),
        source_hash=source_hash,
        current_source_hash=current_source_hash,
        snapshot_version=str(row["snapshot_version"] or ""),
        payload=payload if isinstance(payload, dict) else {},
        source_manifest=source_manifest if isinstance(source_manifest, dict) else {},
        coverage=coverage if isinstance(coverage, dict) else {},
        is_current=is_current,
    )


def summarize_topic_knowledge_snapshot(
    db: Database,
    topic_id: int,
    *,
    focus: str = "",
    max_papers: int | None = None,
) -> dict[str, Any]:
    """Return a private status/advisory summary for latest snapshot consumption."""

    snapshot = get_latest_topic_knowledge_snapshot(
        db,
        topic_id,
        focus=focus,
        max_papers=max_papers,
        require_current=False,
    )
    if snapshot is None:
        return {"status": "missing", "topic_id": topic_id}

    payload = snapshot.payload
    summary = {
        "status": "current" if snapshot.is_current else "outdated",
        "topic_id": snapshot.topic_id,
        "artifact_id": snapshot.artifact_id,
        "snapshot_id": snapshot.snapshot_id,
        "source_hash": snapshot.source_hash,
        "snapshot_version": snapshot.snapshot_version,
        "coverage": payload.get("coverage") or snapshot.coverage,
        "weak_spots": payload.get("weak_spots") or {},
        "next_actions": payload.get("next_actions") or [],
    }
    if not snapshot.is_current:
        summary["current_source_hash"] = snapshot.current_source_hash
    return summary


def render_topic_knowledge_evidence_map_markdown(
    snapshot: TopicKnowledgeSnapshot,
) -> str:
    """Render a private topic knowledge snapshot as evidence-map markdown."""

    payload = snapshot.payload
    covered = payload.get("covered") if isinstance(payload.get("covered"), dict) else {}
    weak_spots = (
        payload.get("weak_spots") if isinstance(payload.get("weak_spots"), dict) else {}
    )
    lines = [
        "# Topic Knowledge Evidence Map",
        "",
        f"- Topic id: {snapshot.topic_id}",
        f"- Snapshot artifact id: {snapshot.artifact_id}",
        f"- Snapshot id: {snapshot.snapshot_id}",
        f"- Snapshot version: `{snapshot.snapshot_version}`",
        f"- Source hash: `{snapshot.source_hash}`",
        f"- Current: {'yes' if snapshot.is_current else 'no'}",
    ]
    generated_at = _text(payload.get("generated_at"))
    if generated_at:
        lines.append(f"- Generated at: {generated_at}")

    _append_mapping_section(
        lines, "Coverage", payload.get("coverage") or snapshot.coverage
    )
    _append_list_section(lines, "Papers", covered.get("papers") or [])
    _append_list_section(lines, "Methods", covered.get("methods") or [])
    _append_list_section(lines, "Datasets", covered.get("datasets") or [])
    _append_list_section(lines, "Metrics", covered.get("metrics") or [])
    _append_list_section(lines, "Baselines", covered.get("baselines") or [])
    _append_list_section(lines, "Claims", covered.get("claims") or [])
    _append_list_section(lines, "Gaps", covered.get("gaps") or [])
    _append_mapping_section(lines, "Weak Spots", weak_spots)
    _append_research_state(lines, payload.get("research_state") or {})
    _append_list_section(lines, "Next Actions", payload.get("next_actions") or [])
    return "\n".join(lines).rstrip() + "\n"


def export_topic_knowledge_evidence_map_markdown(
    db: Database,
    topic_id: int,
    *,
    topic_workspace_path: str | Path,
    filename: str = "topic-knowledge-snapshot.md",
    focus: str = "",
    max_papers: int | None = None,
    require_current: bool = True,
) -> TopicKnowledgeEvidenceMapExport | None:
    """Write the current private snapshot under a topic workspace evidence map."""

    snapshot = get_latest_topic_knowledge_snapshot(
        db,
        topic_id,
        focus=focus,
        max_papers=max_papers,
        require_current=require_current,
    )
    if snapshot is None:
        return None

    safe_filename = Path(filename or "topic-knowledge-snapshot.md").name
    output_path = (
        Path(topic_workspace_path).expanduser() / "02-evidence-map" / safe_filename
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_topic_knowledge_evidence_map_markdown(snapshot)
    output_path.write_text(markdown, encoding="utf-8")
    return TopicKnowledgeEvidenceMapExport(
        topic_id=topic_id,
        path=output_path,
        snapshot=snapshot,
        markdown=markdown,
    )


def _current_topic_knowledge_source_hash(
    db: Database,
    topic_id: int,
    *,
    focus: str,
    max_papers: int | None,
) -> str:
    draft = build_topic_knowledge_draft(
        db,
        topic_id,
        focus=focus,
        max_papers=max_papers,
    )
    source_manifest = _source_manifest(
        draft,
        focus=focus,
        max_papers=max_papers,
    )
    return _source_hash(source_manifest)


def _append_mapping_section(
    lines: list[str],
    title: str,
    mapping: Any,
) -> None:
    lines.extend(["", f"## {title}", ""])
    if not isinstance(mapping, dict) or not mapping:
        lines.append("- none")
        return
    for key in sorted(mapping, key=str):
        value = mapping[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"- {key}: none")
                continue
            lines.append(f"- {key}:")
            for item in value:
                lines.append(f"  - {_markdown_item(item)}")
            continue
        lines.append(f"- {key}: {_markdown_item(value)}")


def _append_list_section(lines: list[str], title: str, values: Any) -> None:
    lines.extend(["", f"## {title}", ""])
    if not isinstance(values, list) or not values:
        lines.append("- none")
        return
    for value in values:
        lines.append(f"- {_markdown_item(value)}")


def _append_research_state(lines: list[str], state: Any) -> None:
    lines.extend(["", "## Research State", ""])
    if not isinstance(state, dict) or not state:
        lines.append("- none")
        return
    for key in sorted(state, key=str):
        value = state[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"- {key}: none")
                continue
            lines.append(f"- {key}:")
            for item in value:
                lines.append(f"  - {_markdown_item(item)}")
            continue
        if isinstance(value, dict):
            lines.append(f"- {key}:")
            for sub_key in sorted(value, key=str):
                lines.append(f"  - {sub_key}: {_markdown_item(value[sub_key])}")
            continue
        lines.append(f"- {key}: {_markdown_item(value)}")


def _markdown_item(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return _stable_json(value)
    text = _text(value).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip() or "none"


class _AtomBuilder:
    def __init__(self, *, topic_id: int):
        self._topic_id = topic_id
        self._atoms: dict[str, SemanticAtom] = {}

    def add(
        self,
        *,
        atom_type: str,
        label: str,
        source_type: str,
        source_id: str | int,
        source_hash: str,
        paper_id: int | None = None,
        source_section: str = "",
        snippet: str = "",
        confidence: float = 0.0,
        description: str = "",
        normalized_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SemanticAtom | None:
        clean_label = _text(label)
        key = normalized_key or _normalize_key(clean_label)
        if not key:
            return None
        atom = SemanticAtom(
            topic_id=self._topic_id,
            atom_type=atom_type,
            normalized_key=key,
            label=clean_label,
            source_type=source_type,
            source_id=str(source_id),
            paper_id=paper_id,
            source_section=source_section,
            snippet=_text(snippet)[:500],
            confidence=float(confidence or 0.0),
            description=_text(description),
            source_hash=source_hash,
            metadata=dict(metadata or {}),
        )
        self._atoms.setdefault(atom.atom_key, atom)
        return self._atoms[atom.atom_key]

    def get(self, atom_key: str) -> SemanticAtom | None:
        return self._atoms.get(atom_key)

    def atoms(self) -> list[SemanticAtom]:
        return list(self._atoms.values())


class _EdgeBuilder:
    def __init__(self, *, topic_id: int):
        self._topic_id = topic_id
        self._edges: dict[str, SemanticEdge] = {}

    def add(
        self,
        *,
        edge_type: str,
        from_atom: SemanticAtom | None,
        to_atom: SemanticAtom | None,
        source_type: str,
        source_id: str | int,
        source_hash: str,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if from_atom is None or to_atom is None:
            return
        edge = SemanticEdge(
            topic_id=self._topic_id,
            edge_type=edge_type,
            from_atom_key=from_atom.atom_key,
            to_atom_key=to_atom.atom_key,
            source_type=source_type,
            source_id=str(source_id),
            confidence=float(confidence or 0.0),
            source_hash=source_hash,
            metadata=dict(metadata or {}),
        )
        self._edges.setdefault(edge.edge_key, edge)

    def edges(self) -> list[SemanticEdge]:
        return list(self._edges.values())


def _replace_semantic_read_model(
    conn: sqlite3.Connection,
    draft: TopicKnowledgeDraft,
) -> None:
    conn.execute("DELETE FROM semantic_edges WHERE topic_id = ?", (draft.topic_id,))
    conn.execute(
        "DELETE FROM semantic_atoms WHERE topic_id = ? AND extractor_version = ?",
        (draft.topic_id, EXTRACTOR_VERSION),
    )
    atom_ids: dict[str, int] = {}
    for atom in draft.atoms:
        cursor = conn.execute(
            """
            INSERT INTO semantic_atoms
                (topic_id, atom_type, normalized_key, label, description,
                 source_type, source_id, paper_id, source_section, snippet,
                 confidence, source_hash, extractor_version, metadata_json)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                atom.topic_id,
                atom.atom_type,
                atom.normalized_key,
                atom.label,
                atom.description,
                atom.source_type,
                atom.source_id,
                atom.paper_id,
                atom.source_section,
                atom.snippet,
                atom.confidence,
                atom.source_hash,
                atom.extractor_version,
                _stable_json(atom.metadata),
            ),
        )
        atom_ids[atom.atom_key] = int(cursor.lastrowid)

    for edge in draft.edges:
        from_id = atom_ids.get(edge.from_atom_key)
        to_id = atom_ids.get(edge.to_atom_key)
        if from_id is None or to_id is None:
            continue
        conn.execute(
            """
            INSERT INTO semantic_edges
                (topic_id, edge_type, from_atom_id, to_atom_id, source_type,
                 source_id, confidence, source_hash, metadata_json)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge.topic_id,
                edge.edge_type,
                from_id,
                to_id,
                edge.source_type,
                edge.source_id,
                edge.confidence,
                edge.source_hash,
                _stable_json(edge.metadata),
            ),
        )


def _active_snapshot(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT tks.id AS snapshot_id, tks.artifact_id, tks.source_hash,
               tks.snapshot_version, pa.payload_json
        FROM topic_knowledge_snapshots tks
        JOIN project_artifacts pa ON pa.id = tks.artifact_id
        WHERE tks.topic_id = ?
          AND tks.status = 'active'
          AND pa.status = 'active'
          AND pa.stale = 0
        ORDER BY tks.created_at DESC, tks.id DESC
        LIMIT 1
        """,
        (topic_id,),
    ).fetchone()


def _snapshot_by_source_version(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    source_hash: str,
    snapshot_version: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT tks.id AS snapshot_id, tks.artifact_id, pa.payload_json
        FROM topic_knowledge_snapshots tks
        JOIN project_artifacts pa ON pa.id = tks.artifact_id
        WHERE tks.topic_id = ?
          AND tks.source_hash = ?
          AND tks.snapshot_version = ?
        ORDER BY tks.created_at DESC, tks.id DESC
        LIMIT 1
        """,
        (topic_id, source_hash, snapshot_version),
    ).fetchone()


def _mark_active_snapshots(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    status: str,
    reason: str,
) -> None:
    rows = conn.execute(
        """
        SELECT artifact_id
        FROM topic_knowledge_snapshots
        WHERE topic_id = ? AND status = 'active'
        """,
        (topic_id,),
    ).fetchall()
    artifact_ids = [int(row["artifact_id"]) for row in rows]
    conn.execute(
        """
        UPDATE topic_knowledge_snapshots
        SET status = ?, updated_at = datetime('now')
        WHERE topic_id = ? AND status = 'active'
        """,
        (status, topic_id),
    )
    if not artifact_ids:
        return
    placeholders = ",".join("?" for _ in artifact_ids)
    conn.execute(
        f"""
        UPDATE project_artifacts
        SET status = ?, stale = 1, stale_reason = ?, updated_at = datetime('now')
        WHERE id IN ({placeholders})
        """,
        [status, reason, *artifact_ids],
    )


def _reactivate_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot: sqlite3.Row,
    payload: dict[str, Any],
    source_manifest: dict[str, Any],
    coverage: dict[str, int],
    source_hash: str,
    snapshot_version: str,
) -> None:
    artifact_id = int(snapshot["artifact_id"])
    conn.execute(
        """
        UPDATE project_artifacts
        SET status = 'active',
            stale = 0,
            stale_reason = NULL,
            payload_json = ?,
            metadata_json = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            _stable_json(payload),
            _stable_json(
                {
                    "source_hash": source_hash,
                    "snapshot_version": snapshot_version,
                    "source_manifest": source_manifest,
                }
            ),
            artifact_id,
        ),
    )
    conn.execute(
        """
        UPDATE topic_knowledge_snapshots
        SET status = 'active',
            source_manifest_json = ?,
            coverage_json = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            _stable_json(source_manifest),
            _stable_json(coverage),
            int(snapshot["snapshot_id"]),
        ),
    )


def _insert_snapshot_artifact(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    payload: dict[str, Any],
    source_manifest: dict[str, Any],
    source_hash: str,
    snapshot_version: str,
) -> int:
    version = int(
        conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'topic_knowledge_snapshot'
            """,
            (topic_id,),
        ).fetchone()[0]
    )
    project_id = _project_id_for_topic(conn, topic_id)
    cursor = conn.execute(
        """
        INSERT INTO project_artifacts
            (project_id, topic_id, stage, artifact_type, status, version, title,
             payload_json, metadata_json)
        VALUES
            (?, ?, 'analysis', 'topic_knowledge_snapshot', 'active', ?, ?, ?, ?)
        """,
        (
            project_id,
            topic_id,
            version,
            f"Topic knowledge snapshot v{version}",
            _stable_json(payload),
            _stable_json(
                {
                    "source_hash": source_hash,
                    "snapshot_version": snapshot_version,
                    "source_manifest": source_manifest,
                }
            ),
        ),
    )
    return int(cursor.lastrowid)


def _project_id_for_topic(conn: sqlite3.Connection, topic_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
        (topic_id,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _source_manifest(
    draft: TopicKnowledgeDraft,
    *,
    focus: str,
    max_papers: int | None,
) -> dict[str, Any]:
    source_counts: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in draft.source_records:
        source_type = str(record.get("source_type") or "")
        source_id = str(record.get("source_id") or "")
        source_hash = str(record.get("source_hash") or "")
        if not source_type or not source_id or not source_hash:
            continue
        key = (source_type, source_id, source_hash)
        source_counts.setdefault(
            key,
            {
                "source_type": source_type,
                "source_id": source_id,
                "source_hash": source_hash,
                "paper_id": record.get("paper_id"),
                "atom_count": 0,
                "edge_count": 0,
            },
        )
    for atom in draft.atoms:
        key = (atom.source_type, atom.source_id, atom.source_hash)
        source_counts.setdefault(
            key,
            {
                "source_type": atom.source_type,
                "source_id": atom.source_id,
                "source_hash": atom.source_hash,
                "paper_id": atom.paper_id,
                "atom_count": 0,
                "edge_count": 0,
            },
        )["atom_count"] += 1
    for edge in draft.edges:
        key = (edge.source_type, edge.source_id, edge.source_hash)
        source_counts.setdefault(
            key,
            {
                "source_type": edge.source_type,
                "source_id": edge.source_id,
                "source_hash": edge.source_hash,
                "paper_id": None,
                "atom_count": 0,
                "edge_count": 0,
            },
        )["edge_count"] += 1

    return {
        "schema_version": "topic_knowledge_source_manifest.v1",
        "extractor_version": EXTRACTOR_VERSION,
        "topic_id": draft.topic_id,
        "focus": focus,
        "max_papers": max_papers,
        "paper_ids": list(draft.paper_ids),
        "coverage": draft.coverage,
        "weak_spots": draft.weak_spots,
        "sources": sorted(
            source_counts.values(),
            key=lambda item: (
                str(item["source_type"]),
                str(item["source_id"]),
                str(item["source_hash"]),
            ),
        ),
    }


def _snapshot_payload(
    draft: TopicKnowledgeDraft,
    *,
    source_manifest: dict[str, Any],
    source_hash: str,
    snapshot_version: str,
    generated_at: str,
) -> dict[str, Any]:
    covered = _covered(draft, source_manifest)
    research_state = _research_state(draft, covered)
    return {
        "schema_version": "topic_knowledge_snapshot.v1",
        "snapshot_version": snapshot_version,
        "topic_id": draft.topic_id,
        "generated_at": generated_at,
        "source_hash": source_hash,
        "source_manifest": source_manifest,
        "coverage": draft.coverage,
        "covered": covered,
        "weak_spots": draft.weak_spots,
        "research_state": research_state,
        "next_actions": _next_actions(draft, covered),
    }


def _covered(
    draft: TopicKnowledgeDraft,
    source_manifest: dict[str, Any],
) -> dict[str, Any]:
    by_type: dict[str, list[str]] = {}
    for atom in draft.atoms:
        by_type.setdefault(atom.atom_type, [])
        if atom.label and atom.label not in by_type[atom.atom_type]:
            by_type[atom.atom_type].append(atom.label)
    for values in by_type.values():
        values.sort(key=str.lower)
    return {
        "papers": list(source_manifest.get("paper_ids") or []),
        "methods": by_type.get("method", []),
        "datasets": by_type.get("dataset", []),
        "metrics": by_type.get("metric", []),
        "baselines": by_type.get("baseline", []),
        "claims": by_type.get("claim", []),
        "gaps": by_type.get("gap_signal", []),
    }


def _research_state(
    draft: TopicKnowledgeDraft,
    covered: dict[str, Any],
) -> dict[str, Any]:
    high_confidence_claims = sorted(
        {
            atom.label
            for atom in draft.atoms
            if atom.atom_type == "claim" and atom.confidence >= 0.75
        },
        key=str.lower,
    )
    conflicts = [
        {
            "source_id": edge.source_id,
            "confidence": edge.confidence,
        }
        for edge in draft.edges
        if edge.edge_type == "contradicts"
    ]
    return {
        "high_confidence_claims": high_confidence_claims,
        "open_gaps": covered.get("gaps", []),
        "conflicts": conflicts,
        "baseline_readiness": {
            "has_baselines": bool(covered.get("baselines")),
            "has_metrics": bool(covered.get("metrics")),
            "has_datasets": bool(covered.get("datasets")),
        },
        "evidence_matrix_summary": {
            "claim_count": len(covered.get("claims", [])),
            "edge_count": len(draft.edges),
        },
        "method_map_summary": {
            "method_count": len(covered.get("methods", [])),
            "dataset_count": len(covered.get("datasets", [])),
            "metric_count": len(covered.get("metrics", [])),
        },
    }


def _next_actions(
    draft: TopicKnowledgeDraft,
    covered: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    weak = draft.weak_spots
    if weak.get("missing_cards") or weak.get("missing_compiled_summaries"):
        actions.append("paper_summarize")
    if weak.get("claims_without_evidence") or not covered.get("claims"):
        actions.append("claim_extract")
    if weak.get("unverified_gaps") or not covered.get("gaps"):
        actions.append("gap_detect")
    if not covered.get("baselines"):
        actions.append("baseline_identify")
    if covered.get("claims"):
        actions.append("evidence_matrix")
    return actions


def _derive_from_cards(builder: _AtomBuilder, cards: list[dict[str, Any]]) -> None:
    for item in cards:
        card = item["card"]
        source_hash = item["source_hash"]
        paper_id = item["paper_id"]
        source_id = item["artifact_id"]
        confidence = item["confidence"]

        fields = _open_card_fields(card)
        relations = _open_card_relations(card)

        _add_many(
            builder,
            "method",
            [
                card.get("method_family"),
                *card.get("method_tags", []),
                *_named_open_values(
                    fields,
                    "core_method",
                    "method",
                    "method_family",
                    "method_summary",
                    "method_tag",
                    "method_tags",
                ),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="method",
            confidence=confidence,
        )
        _add_many(
            builder,
            "task",
            [*card.get("tasks", []), *_named_open_values(fields, "task", "tasks")],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="tasks",
            confidence=confidence,
        )
        _add_many(
            builder,
            "dataset",
            [
                *card.get("datasets", []),
                *_relation_targets(
                    relations,
                    "dataset",
                    "evaluated_on",
                    "uses_dataset",
                ),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="datasets",
            confidence=confidence,
        )
        _add_many(
            builder,
            "metric",
            [
                *card.get("metrics", []),
                *_named_open_values(fields, "metric", "metrics"),
                *_relation_targets(relations, "measured_by", "reports_metric"),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="metrics",
            confidence=confidence,
        )
        _add_many(
            builder,
            "baseline",
            [
                *card.get("baselines", []),
                *_relation_targets(
                    relations,
                    "compared_against",
                    "direct_comparator",
                ),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="baselines",
            confidence=confidence,
        )
        _add_many(
            builder,
            "result",
            [
                *card.get("key_results", []),
                *_named_open_values(
                    fields, "key_result", "key_results", "result", "results"
                ),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="key_results",
            confidence=confidence,
        )
        _add_many(
            builder,
            "limitation",
            [
                *card.get("limitations", []),
                *_named_open_values(fields, "self_declared_limitation"),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="limitations",
            confidence=confidence,
        )
        _add_many(
            builder,
            "assumption",
            [
                *card.get("assumptions", []),
                *_named_open_values(fields, "assumption", "assumptions"),
            ],
            source_type="paperindex_card",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="assumptions",
            confidence=confidence,
        )
        for result in _iter_values(card.get("structured_results", [])):
            if not isinstance(result, dict):
                continue
            label = " ".join(
                _text(result.get(key))
                for key in ("metric", "value", "baseline", "delta")
                if _text(result.get(key))
            )
            builder.add(
                atom_type="result",
                label=label,
                source_type="paperindex_card",
                source_id=source_id,
                paper_id=paper_id,
                source_section="structured_results",
                snippet=label,
                confidence=confidence,
                source_hash=source_hash,
                metadata={"structured_result": result},
            )
        for defect in _open_card_items(card.get("independent_defects")):
            value = _text(defect.get("value"))
            builder.add(
                atom_type="gap_signal",
                label=value,
                source_type="paperindex_card",
                source_id=source_id,
                paper_id=paper_id,
                source_section="independent_defects",
                snippet=_text(defect.get("quote")) or value,
                description=_text(defect.get("insight")),
                confidence=confidence,
                source_hash=source_hash,
                metadata={"defect_name": _text(defect.get("name"))},
            )


def _open_card_fields(card: dict[str, Any]) -> list[dict[str, Any]]:
    return _open_card_items(card.get("fields"))


def _open_card_relations(card: dict[str, Any]) -> list[dict[str, Any]]:
    return _open_card_items(card.get("relations"))


def _open_card_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in _iter_values(value) if isinstance(item, dict)]


def _named_open_values(fields: list[dict[str, Any]], *names: str) -> list[str]:
    accepted = {_normalize_key(name) for name in names}
    return [
        _text(item.get("value"))
        for item in fields
        if _normalize_key(item.get("name")) in accepted and _text(item.get("value"))
    ]


def _relation_targets(
    relations: list[dict[str, Any]], *relation_names: str
) -> list[str]:
    accepted = {_normalize_key(name) for name in relation_names}
    return [
        _text(item.get("target"))
        for item in relations
        if _normalize_key(item.get("relation")) in accepted
        and _text(item.get("target"))
    ]


def _derive_from_compiled_summaries(
    builder: _AtomBuilder,
    papers: list[sqlite3.Row],
) -> None:
    for row in papers:
        raw = _text(row["compiled_summary"])
        if not raw:
            continue
        compiled = _json_obj(raw)
        if not isinstance(compiled, dict):
            continue
        paper_id = int(row["id"])
        source_payload = {
            "paper_id": paper_id,
            "compiled_summary": compiled,
            "compiled_from_hash": row["compiled_from_hash"],
        }
        source_hash = _source_hash(source_payload)
        source_id = f"paper:{paper_id}:compiled_summary"
        _add_many(
            builder,
            "method",
            compiled.get("methods", []),
            source_type="compiled_summary",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="methods",
            confidence=0.65,
        )
        for claim in _iter_values(compiled.get("claims", [])):
            label = claim.get("claim") if isinstance(claim, dict) else claim
            builder.add(
                atom_type="claim",
                label=_text(label),
                source_type="compiled_summary",
                source_id=source_id,
                paper_id=paper_id,
                source_section="claims",
                snippet=_text(label),
                confidence=0.65,
                source_hash=source_hash,
            )
        _add_many(
            builder,
            "limitation",
            compiled.get("limitations", []),
            source_type="compiled_summary",
            source_id=source_id,
            source_hash=source_hash,
            paper_id=paper_id,
            source_section="limitations",
            confidence=0.6,
        )
        for metric in _iter_values(compiled.get("metrics", [])):
            if not isinstance(metric, dict):
                continue
            dataset = builder.add(
                atom_type="dataset",
                label=_text(metric.get("dataset")),
                source_type="compiled_summary",
                source_id=source_id,
                paper_id=paper_id,
                source_section="metrics.dataset",
                confidence=0.6,
                source_hash=source_hash,
                metadata={"metric": metric},
            )
            metric_atom = builder.add(
                atom_type="metric",
                label=_text(metric.get("metric")),
                source_type="compiled_summary",
                source_id=source_id,
                paper_id=paper_id,
                source_section="metrics.metric",
                confidence=0.6,
                source_hash=source_hash,
                metadata={"metric": metric},
            )
            baseline = builder.add(
                atom_type="baseline",
                label=_text(metric.get("baseline")),
                source_type="compiled_summary",
                source_id=source_id,
                paper_id=paper_id,
                source_section="metrics.baseline",
                confidence=0.55,
                source_hash=source_hash,
                metadata={"metric": metric},
            )
            result_label = " ".join(
                _text(metric.get(key))
                for key in ("dataset", "metric", "value", "baseline")
                if _text(metric.get(key))
            )
            result = builder.add(
                atom_type="result",
                label=result_label,
                source_type="compiled_summary",
                source_id=source_id,
                paper_id=paper_id,
                source_section="metrics",
                confidence=0.6,
                source_hash=source_hash,
                metadata={"metric": metric},
            )
            del dataset, metric_atom, baseline, result


def _derive_from_claims(
    builder: _AtomBuilder,
    edges: _EdgeBuilder,
    claims: list[sqlite3.Row],
) -> None:
    for row in claims:
        source = _row_dict(row)
        source_hash = _source_hash(source)
        source_id = row["id"]
        paper_id = int(row["paper_id"])
        confidence = float(row["confidence"] or 0.0)
        claim = builder.add(
            atom_type="claim",
            label=row["claim_text"],
            source_type="normalized_claims",
            source_id=source_id,
            paper_id=paper_id,
            source_section=_text(row["source_section"]) or "claim_text",
            snippet=row["claim_text"],
            confidence=confidence,
            source_hash=source_hash,
            metadata={"modality": row["modality"]},
        )
        method = builder.add(
            atom_type="method",
            label=row["method"],
            source_type="normalized_claims",
            source_id=source_id,
            paper_id=paper_id,
            source_section="method",
            confidence=confidence,
            source_hash=source_hash,
        )
        dataset = builder.add(
            atom_type="dataset",
            label=row["dataset"],
            source_type="normalized_claims",
            source_id=source_id,
            paper_id=paper_id,
            source_section="dataset",
            confidence=confidence,
            source_hash=source_hash,
        )
        metric = builder.add(
            atom_type="metric",
            label=row["metric"],
            source_type="normalized_claims",
            source_id=source_id,
            paper_id=paper_id,
            source_section="metric",
            confidence=confidence,
            source_hash=source_hash,
        )
        task_label = _text(row["task_canonical"]) or _text(row["task"])
        task = builder.add(
            atom_type="task",
            label=task_label,
            source_type="normalized_claims",
            source_id=source_id,
            paper_id=paper_id,
            source_section="task",
            confidence=confidence,
            source_hash=source_hash,
        )
        if _text(row["value"]):
            result_label = " ".join(
                value
                for value in (
                    _text(row["method"]),
                    _text(row["metric"]),
                    _text(row["dataset"]),
                    _text(row["value"]),
                    _text(row["direction"]),
                )
                if value
            )
            builder.add(
                atom_type="result",
                label=result_label,
                source_type="normalized_claims",
                source_id=source_id,
                paper_id=paper_id,
                source_section="value",
                confidence=confidence,
                source_hash=source_hash,
                metadata={"direction": row["direction"]},
            )
        edges.add(
            edge_type="uses_dataset",
            from_atom=claim,
            to_atom=dataset,
            source_type="normalized_claims",
            source_id=source_id,
            confidence=confidence,
            source_hash=source_hash,
        )
        edges.add(
            edge_type="reports_metric",
            from_atom=claim,
            to_atom=metric,
            source_type="normalized_claims",
            source_id=source_id,
            confidence=confidence,
            source_hash=source_hash,
        )
        edges.add(
            edge_type="evaluates_on",
            from_atom=claim or method,
            to_atom=task,
            source_type="normalized_claims",
            source_id=source_id,
            confidence=confidence,
            source_hash=source_hash,
        )


def _derive_from_gaps(builder: _AtomBuilder, gaps: list[sqlite3.Row]) -> None:
    for row in gaps:
        source = _row_dict(row)
        source_hash = _source_hash(source)
        builder.add(
            atom_type="gap_signal",
            label=row["description"],
            source_type="gaps",
            source_id=row["id"],
            source_section=_text(row["gap_type"]) or "description",
            snippet=row["description"],
            confidence=float(row["confidence"] or 0.0),
            source_hash=source_hash,
            metadata={
                "severity": row["severity"],
                "focus": row["focus"],
                "cross_verified": bool(row["cross_verified"]),
                "cross_check_runs": row["cross_check_runs"],
                "related_paper_ids": row["related_paper_ids"],
            },
        )


def _derive_from_method_atoms(
    builder: _AtomBuilder,
    method_atoms: list[sqlite3.Row],
) -> None:
    for row in method_atoms:
        source = _row_dict(row)
        source_hash = _source_hash(source)
        builder.add(
            atom_type="method",
            label=row["name"],
            source_type="method_atoms",
            source_id=row["id"],
            paper_id=int(row["source_paper_id"]),
            source_section="name",
            snippet=row["description"],
            description=row["description"],
            confidence=0.75,
            source_hash=source_hash,
            metadata={
                "source_atom_type": row["atom_type"],
                "deps": _json_obj(row["deps"]) or [],
                "reported_gain": row["reported_gain"],
                "reuse_risk": row["reuse_risk"],
            },
        )


def _derive_from_taxonomy(
    builder: _AtomBuilder,
    taxonomy_nodes: list[sqlite3.Row],
) -> None:
    for row in taxonomy_nodes:
        source = _row_dict(row)
        source_hash = _source_hash(source)
        builder.add(
            atom_type="doc_signal",
            label=row["name"],
            source_type="taxonomy_nodes",
            source_id=row["id"],
            source_section="name",
            snippet=row["description"],
            description=row["description"],
            confidence=0.5,
            source_hash=source_hash,
            metadata={"parent_id": row["parent_id"], "aliases": row["aliases"]},
        )


def _derive_from_contradictions(
    edges: _EdgeBuilder,
    atoms: _AtomBuilder,
    contradictions: list[sqlite3.Row],
) -> None:
    for row in contradictions:
        source = _row_dict(row)
        source_hash = _source_hash(source)
        claim_a_key = _atom_key(
            topic_id=int(row["topic_id"]),
            atom_type="claim",
            normalized_key=_normalize_key(row["claim_a_text"]),
            source_type="normalized_claims",
            source_id=row["claim_a_id"],
        )
        claim_b_key = _atom_key(
            topic_id=int(row["topic_id"]),
            atom_type="claim",
            normalized_key=_normalize_key(row["claim_b_text"]),
            source_type="normalized_claims",
            source_id=row["claim_b_id"],
        )
        edges.add(
            edge_type="contradicts",
            from_atom=atoms.get(claim_a_key),
            to_atom=atoms.get(claim_b_key),
            source_type="contradictions",
            source_id=row["id"],
            confidence=float(row["confidence"] or 0.0),
            source_hash=source_hash,
            metadata={"status": row["status"], "reason": row["conflict_reason"]},
        )


def _add_many(
    builder: _AtomBuilder,
    atom_type: str,
    values: Any,
    *,
    source_type: str,
    source_id: str | int,
    source_hash: str,
    paper_id: int | None,
    source_section: str,
    confidence: float,
) -> None:
    for value in _iter_values(values):
        builder.add(
            atom_type=atom_type,
            label=_text(value),
            source_type=source_type,
            source_id=source_id,
            paper_id=paper_id,
            source_section=source_section,
            snippet=_text(value),
            confidence=confidence,
            source_hash=source_hash,
        )


def _iter_values(values: Any) -> list[Any]:
    if values in (None, ""):
        return []
    if isinstance(values, (list, tuple, set)):
        return list(values)
    return [values]


def _source_records(
    *,
    papers: list[sqlite3.Row],
    cards: list[dict[str, Any]],
    claims: list[sqlite3.Row],
    gaps: list[sqlite3.Row],
    method_atoms: list[sqlite3.Row],
    taxonomy_nodes: list[sqlite3.Row],
    contradictions: list[sqlite3.Row],
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for row in papers:
        paper_id = int(row["id"])
        records.append(
            {
                "source_type": "paper",
                "source_id": str(paper_id),
                "paper_id": paper_id,
                "source_hash": _source_hash(_row_dict(row)),
            }
        )
    for item in cards:
        records.append(
            {
                "source_type": "paperindex_card",
                "source_id": str(item["artifact_id"]),
                "paper_id": int(item["paper_id"]),
                "source_hash": str(item["source_hash"]),
            }
        )
    for row in claims:
        records.append(
            {
                "source_type": "normalized_claims",
                "source_id": str(row["id"]),
                "paper_id": int(row["paper_id"]),
                "source_hash": _source_hash(_row_dict(row)),
            }
        )
    for row in gaps:
        records.append(
            {
                "source_type": "gaps",
                "source_id": str(row["id"]),
                "paper_id": None,
                "source_hash": _source_hash(_row_dict(row)),
            }
        )
    for row in method_atoms:
        records.append(
            {
                "source_type": "method_atoms",
                "source_id": str(row["id"]),
                "paper_id": int(row["source_paper_id"]),
                "source_hash": _source_hash(_row_dict(row)),
            }
        )
    for row in taxonomy_nodes:
        records.append(
            {
                "source_type": "taxonomy_nodes",
                "source_id": str(row["id"]),
                "paper_id": None,
                "source_hash": _source_hash(_row_dict(row)),
            }
        )
    for row in contradictions:
        records.append(
            {
                "source_type": "contradictions",
                "source_id": str(row["id"]),
                "paper_id": None,
                "source_hash": _source_hash(_row_dict(row)),
            }
        )
    return tuple(records)


def _topic_papers(
    conn: sqlite3.Connection,
    topic_id: int,
    *,
    max_papers: int | None,
) -> list[sqlite3.Row]:
    limit_sql = "" if max_papers is None else " LIMIT ?"
    params: list[Any] = [topic_id]
    if max_papers is not None:
        params.append(max(0, int(max_papers)))
    return conn.execute(
        f"""
        SELECT p.id, p.title, p.compiled_summary, p.compiled_from_hash
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        WHERE pt.topic_id = ?
        ORDER BY p.id
        {limit_sql}
        """,
        params,
    ).fetchall()


def _paper_cards(
    conn: sqlite3.Connection, paper_ids: list[int]
) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"""
        SELECT id, paper_id, path, metadata
        FROM paper_artifacts
        WHERE artifact_type = 'paperindex_card'
          AND paper_id IN ({placeholders})
        ORDER BY paper_id, id
        """,
        paper_ids,
    ).fetchall()
    cards: list[dict[str, Any]] = []
    for row in rows:
        payload = _read_card_payload(row["path"])
        if payload is None:
            continue
        parsed_card = PaperCard.from_dict(payload)
        card = (
            parsed_card.to_dict()
            if payload.get("schema_version") == "papercard/v3"
            else dict(payload)
        )
        source_payload = {
            "artifact": _row_dict(row),
            "metadata": _json_obj(row["metadata"]) or {},
            "card": card,
        }
        evidence = card.get("evidence") or []
        confidence = max(
            [float(item.get("confidence") or 0.0) for item in evidence] or [0.7]
        )
        cards.append(
            {
                "artifact_id": int(row["id"]),
                "paper_id": int(row["paper_id"]),
                "card": card,
                "source_hash": _source_hash(source_payload),
                "confidence": confidence,
            }
        )
    return cards


def _normalized_claims(
    conn: sqlite3.Connection,
    topic_id: int,
    paper_ids: set[int],
) -> list[sqlite3.Row]:
    params: list[Any] = [topic_id]
    paper_filter = ""
    if paper_ids:
        paper_filter = f" AND paper_id IN ({','.join('?' for _ in paper_ids)})"
        params.extend(sorted(paper_ids))
    return conn.execute(
        f"""
        SELECT id, topic_id, paper_id, claim_text, method, dataset, metric, task,
               value, direction, confidence, source_section, task_canonical,
               modality, evidence_spans_json
        FROM normalized_claims
        WHERE topic_id = ?{paper_filter}
        ORDER BY id
        """,
        params,
    ).fetchall()


def _gaps(conn: sqlite3.Connection, topic_id: int, *, focus: str) -> list[sqlite3.Row]:
    params: list[Any] = [topic_id]
    focus_filter = ""
    if focus:
        focus_filter = " AND (focus = ? OR focus = '')"
        params.append(focus)
    return conn.execute(
        f"""
        SELECT id, topic_id, description, gap_type, severity, related_paper_ids,
               focus, confidence, cross_verified, cross_check_runs
        FROM gaps
        WHERE topic_id = ?{focus_filter}
        ORDER BY id
        """,
        params,
    ).fetchall()


def _method_atoms(
    conn: sqlite3.Connection,
    topic_id: int,
    paper_ids: set[int],
) -> list[sqlite3.Row]:
    params: list[Any] = [topic_id]
    paper_filter = ""
    if paper_ids:
        paper_filter = f" AND source_paper_id IN ({','.join('?' for _ in paper_ids)})"
        params.extend(sorted(paper_ids))
    return conn.execute(
        f"""
        SELECT id, topic_id, source_paper_id, atom_type, name, description, deps,
               reported_gain, reuse_risk, created_at
        FROM method_atoms
        WHERE topic_id = ?{paper_filter}
        ORDER BY id
        """,
        params,
    ).fetchall()


def _taxonomy_nodes(conn: sqlite3.Connection, topic_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, topic_id, name, parent_id, description, aliases
        FROM taxonomy_nodes
        WHERE topic_id = ?
        ORDER BY id
        """,
        (topic_id,),
    ).fetchall()


def _contradictions(conn: sqlite3.Connection, topic_id: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT c.id, c.topic_id, c.claim_a_id, c.claim_b_id, c.same_task,
               c.same_dataset, c.same_metric, c.confidence, c.conflict_reason,
               c.status, ca.claim_text AS claim_a_text, cb.claim_text AS claim_b_text
        FROM contradictions c
        LEFT JOIN normalized_claims ca ON ca.id = c.claim_a_id
        LEFT JOIN normalized_claims cb ON cb.id = c.claim_b_id
        WHERE c.topic_id = ?
        ORDER BY c.id
        """,
        (topic_id,),
    ).fetchall()
    return rows


def _annotation_count(conn: sqlite3.Connection, paper_ids: list[int]) -> int:
    if not paper_ids:
        return 0
    placeholders = ",".join("?" for _ in paper_ids)
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM paper_annotations WHERE paper_id IN ({placeholders})",
            paper_ids,
        ).fetchone()[0]
    )


def _weak_spots(
    *,
    papers: list[sqlite3.Row],
    cards: list[dict[str, Any]],
    claims: list[sqlite3.Row],
    gaps: list[sqlite3.Row],
    atoms: tuple[SemanticAtom, ...],
) -> dict[str, list[Any]]:
    card_paper_ids = {int(item["paper_id"]) for item in cards}
    missing_cards = [
        int(row["id"]) for row in papers if int(row["id"]) not in card_paper_ids
    ]
    missing_compiled = [
        int(row["id"]) for row in papers if not _text(row["compiled_summary"])
    ]
    claims_without_evidence = [
        int(row["id"]) for row in claims if not _json_obj(row["evidence_spans_json"])
    ]
    unverified_gaps = [
        int(row["id"]) for row in gaps if not int(row["cross_verified"] or 0)
    ]
    return {
        "missing_cards": missing_cards,
        "missing_compiled_summaries": missing_compiled,
        "claims_without_evidence": claims_without_evidence,
        "low_confidence_atoms": [
            atom.atom_key for atom in atoms if atom.confidence < 0.5
        ],
        "unverified_gaps": unverified_gaps,
    }


def _read_card_payload(path_value: str) -> dict[str, Any] | None:
    path = Path(path_value)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _source_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_obj(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return None


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _normalize_key(value: str) -> str:
    return _NON_WORD_RE.sub(" ", _text(value).lower()).strip()


def _atom_key(
    *,
    topic_id: int,
    atom_type: str,
    normalized_key: str,
    source_type: str,
    source_id: str | int,
) -> str:
    return "|".join(
        (str(topic_id), atom_type, normalized_key, source_type, str(source_id))
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
