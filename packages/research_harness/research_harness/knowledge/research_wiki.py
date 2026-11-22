"""Private Research Wiki Markdown materialization helpers.

This module intentionally stays dependency-free and RH-native. It projects the
existing Topic Knowledge read model into a local Markdown vault for inspection;
it does not change public MCP/CLI/HTTP surfaces or write RH storage rows.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from research_harness.storage.db import Database

from .topic_layer import get_latest_topic_knowledge_snapshot


WIKI_PAGE_SCHEMA_VERSION = "research_wiki_page.v1"
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class WikiLink:
    target: str
    label: str


@dataclass(frozen=True)
class ResearchWikiPage:
    relative_path: str
    title: str
    page_type: str
    frontmatter: dict[str, Any]
    body: str

    @property
    def markdown(self) -> str:
        return dump_frontmatter(self.frontmatter, self.body)


@dataclass(frozen=True)
class ResearchWikiExport:
    topic_id: int
    vault_path: Path
    pages: tuple[ResearchWikiPage, ...]
    graph: dict[str, list[str]]


@dataclass(frozen=True)
class _AtomRecord:
    id: int
    topic_id: int
    atom_type: str
    normalized_key: str
    label: str
    source_type: str
    source_id: str
    source_hash: str
    paper_id: int | None
    source_section: str
    snippet: str
    confidence: float
    description: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _EdgeRecord:
    edge_type: str
    from_atom_id: int
    to_atom_id: int
    confidence: float


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    """Render dependency-free JSON-valued Markdown frontmatter."""

    lines = ["---"]
    for key, value in metadata.items():
        lines.append(
            f"{key}: "
            f"{json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)}"
        )
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Parse the JSON-valued frontmatter emitted by ``dump_frontmatter``."""

    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown

    metadata: dict[str, Any] = {}
    raw_header = markdown[4:end]
    for line in raw_header.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        if not key:
            continue
        raw_value = value.strip()
        try:
            metadata[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            metadata[key] = raw_value
    return metadata, markdown[end + len("\n---\n") :]


def extract_wikilinks(markdown: str) -> list[WikiLink]:
    """Extract Obsidian-style wikilinks from Markdown content."""

    links: list[WikiLink] = []
    for match in _WIKILINK_RE.finditer(markdown):
        target = match.group(1).strip()
        label = (match.group(2) or _default_link_label(target)).strip()
        if target:
            links.append(WikiLink(target=target, label=label))
    return links


def materialize_research_wiki_vault(
    db: Database,
    topic_id: int,
    *,
    vault_path: str | Path,
    focus: str = "",
    max_papers: int | None = None,
    require_current: bool = True,
) -> ResearchWikiExport:
    """Write a private Research Wiki vault from the latest Topic Knowledge snapshot."""

    export = build_research_wiki_export(
        db,
        topic_id,
        vault_path=vault_path,
        focus=focus,
        max_papers=max_papers,
        require_current=require_current,
    )
    path = Path(vault_path)
    path.mkdir(parents=True, exist_ok=True)
    for page in export.pages:
        page_path = path / page.relative_path
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page.markdown, encoding="utf-8")

    return ResearchWikiExport(
        topic_id=export.topic_id,
        vault_path=path,
        pages=export.pages,
        graph=export.graph,
    )


def build_research_wiki_export(
    db: Database,
    topic_id: int,
    *,
    vault_path: str | Path = "",
    focus: str = "",
    max_papers: int | None = None,
    require_current: bool = True,
) -> ResearchWikiExport:
    """Build a private Research Wiki export in memory without writing files."""

    snapshot = get_latest_topic_knowledge_snapshot(
        db,
        topic_id,
        focus=focus,
        max_papers=max_papers,
        require_current=require_current,
    )
    if snapshot is None:
        raise ValueError(f"no current topic knowledge snapshot for topic {topic_id}")

    conn = db.connect()
    try:
        papers = _load_topic_papers(conn, topic_id)
        atoms = _load_semantic_atoms(conn, topic_id)
        edges = _load_semantic_edges(conn, topic_id)
    finally:
        conn.close()

    path = Path(vault_path)
    pages = _build_pages(
        topic_id=topic_id,
        snapshot_artifact_id=snapshot.artifact_id,
        snapshot_source_hash=snapshot.source_hash,
        paper_source_hashes=_paper_source_hashes(snapshot.source_manifest),
        papers=papers,
        atoms=atoms,
        edges=edges,
    )
    graph = build_research_wiki_graph(pages)
    return ResearchWikiExport(
        topic_id=topic_id,
        vault_path=path,
        pages=tuple(pages),
        graph=graph,
    )


def build_research_wiki_graph(
    pages: tuple[ResearchWikiPage, ...] | list[ResearchWikiPage],
) -> dict[str, list[str]]:
    """Build a deterministic page-link graph from rendered wikilinks."""

    available = {page.relative_path for page in pages}
    graph: dict[str, list[str]] = {}
    for page in pages:
        targets = {
            _normalize_link_target(link.target)
            for link in extract_wikilinks(page.body)
            if _normalize_link_target(link.target) in available
            and _normalize_link_target(link.target) != page.relative_path
        }
        graph[page.relative_path] = sorted(targets)
    return graph


def _build_pages(
    *,
    topic_id: int,
    snapshot_artifact_id: int,
    snapshot_source_hash: str,
    paper_source_hashes: dict[int, str],
    papers: dict[int, str],
    atoms: list[_AtomRecord],
    edges: list[_EdgeRecord],
) -> list[ResearchWikiPage]:
    atom_page_paths = {atom.id: _atom_page_path(atom) for atom in atoms}
    atoms_by_page: dict[str, list[_AtomRecord]] = {}
    for atom in atoms:
        atoms_by_page.setdefault(atom_page_paths[atom.id], []).append(atom)

    neighbor_ids = _semantic_neighbors(edges)
    pages: list[ResearchWikiPage] = []
    pages.extend(
        _source_pages(topic_id, papers, paper_source_hashes, atoms, atom_page_paths)
    )
    for relative_path, page_atoms in sorted(atoms_by_page.items()):
        primary = sorted(page_atoms, key=lambda atom: (atom.atom_type, atom.id))[0]
        pages.append(
            _atom_page(
                topic_id=topic_id,
                relative_path=relative_path,
                primary=primary,
                atoms=page_atoms,
                atom_page_paths=atom_page_paths,
                neighbor_ids=neighbor_ids,
                atom_by_id={atom.id: atom for atom in atoms},
            )
        )
    pages.append(
        _thesis_page(
            topic_id=topic_id,
            snapshot_artifact_id=snapshot_artifact_id,
            snapshot_source_hash=snapshot_source_hash,
            papers=papers,
            atoms=atoms,
        )
    )
    return sorted(pages, key=lambda page: page.relative_path)


def _source_pages(
    topic_id: int,
    papers: dict[int, str],
    paper_source_hashes: dict[int, str],
    atoms: list[_AtomRecord],
    atom_page_paths: dict[int, str],
) -> list[ResearchWikiPage]:
    pages: list[ResearchWikiPage] = []
    atoms_by_paper: dict[int, list[_AtomRecord]] = {}
    atoms_by_section: dict[tuple[int, str], list[_AtomRecord]] = {}
    for atom in atoms:
        if atom.paper_id is None:
            continue
        atoms_by_paper.setdefault(atom.paper_id, []).append(atom)
        section = atom.source_section or "paper"
        atoms_by_section.setdefault((atom.paper_id, section), []).append(atom)

    for paper_id, title in sorted(papers.items()):
        paper_atoms = atoms_by_paper.get(paper_id, [])
        section_links = [
            _wiki_link(
                f"sources/paper-{paper_id}/{slugify(section)}.md",
                section,
            )
            for section in sorted(
                {atom.source_section or "paper" for atom in paper_atoms},
                key=str.lower,
            )
        ]
        atom_links = _dedupe_sorted_links(
            _wiki_link(atom_page_paths[atom.id], atom.label) for atom in paper_atoms
        )
        body = _body(
            title,
            [
                ("Sections", section_links),
                ("Linked Pages", atom_links),
            ],
        )
        pages.append(
            ResearchWikiPage(
                relative_path=f"sources/paper-{paper_id}.md",
                title=title,
                page_type="source",
                frontmatter=_frontmatter(
                    topic_id=topic_id,
                    page_type="source",
                    title=title,
                    sources=[
                        _source_ref(
                            paper_id=paper_id,
                            source_type="paper",
                            source_id=paper_id,
                            source_hash=paper_source_hashes.get(paper_id, ""),
                            section_anchor="",
                            evidence_snippet=title,
                        )
                    ],
                ),
                body=body,
            )
        )

    for (paper_id, section), section_atoms in sorted(
        atoms_by_section.items(), key=lambda item: (item[0][0], item[0][1].lower())
    ):
        title = f"{papers.get(paper_id, f'Paper {paper_id}')} / {section}"
        atom_links = _dedupe_sorted_links(
            _wiki_link(atom_page_paths[atom.id], atom.label) for atom in section_atoms
        )
        pages.append(
            ResearchWikiPage(
                relative_path=f"sources/paper-{paper_id}/{slugify(section)}.md",
                title=title,
                page_type="source_section",
                frontmatter=_frontmatter(
                    topic_id=topic_id,
                    page_type="source_section",
                    title=title,
                    sources=[_atom_source_ref(atom) for atom in section_atoms],
                ),
                body=_body(title, [("Linked Pages", atom_links)]),
            )
        )
    return pages


def _atom_page(
    *,
    topic_id: int,
    relative_path: str,
    primary: _AtomRecord,
    atoms: list[_AtomRecord],
    atom_page_paths: dict[int, str],
    neighbor_ids: dict[int, set[int]],
    atom_by_id: dict[int, _AtomRecord],
) -> ResearchWikiPage:
    page_type = _page_type(primary.atom_type)
    related_links = _dedupe_sorted_links(
        _wiki_link(atom_page_paths[neighbor_id], atom_by_id[neighbor_id].label)
        for atom in atoms
        for neighbor_id in neighbor_ids.get(atom.id, set())
        if neighbor_id in atom_page_paths
        and atom_page_paths[neighbor_id] != relative_path
    )
    source_links = _source_links(atoms) if page_type == "finding" else []
    sections = [
        ("Evidence", _evidence_lines(atoms, link_sources=page_type == "finding")),
        ("Related", related_links),
    ]
    if source_links:
        sections.append(("Source Anchors", source_links))
    return ResearchWikiPage(
        relative_path=relative_path,
        title=primary.label,
        page_type=page_type,
        frontmatter=_frontmatter(
            topic_id=topic_id,
            page_type=page_type,
            title=primary.label,
            aliases=sorted(
                {atom.label for atom in atoms if atom.label != primary.label}
            ),
            sources=[_atom_source_ref(atom) for atom in atoms],
        ),
        body=_body(primary.label, sections),
    )


def _thesis_page(
    *,
    topic_id: int,
    snapshot_artifact_id: int,
    snapshot_source_hash: str,
    papers: dict[int, str],
    atoms: list[_AtomRecord],
) -> ResearchWikiPage:
    finding_links = _dedupe_sorted_links(
        _wiki_link(_atom_page_path(atom), atom.label)
        for atom in atoms
        if _page_type(atom.atom_type) == "finding"
    )
    source_links = _dedupe_sorted_links(
        _wiki_link(f"sources/paper-{paper_id}.md", title)
        for paper_id, title in papers.items()
    )
    title = f"Topic {topic_id} thesis"
    return ResearchWikiPage(
        relative_path=f"thesis/topic-{topic_id}.md",
        title=title,
        page_type="thesis",
        frontmatter=_frontmatter(
            topic_id=topic_id,
            page_type="thesis",
            title=title,
            sources=[
                _source_ref(
                    paper_id=None,
                    source_type="topic_knowledge_snapshot",
                    source_id=snapshot_artifact_id,
                    source_hash=snapshot_source_hash,
                    section_anchor="",
                    evidence_snippet="topic_knowledge_snapshot",
                )
            ],
        ),
        body=_body(
            title,
            [
                ("Source Papers", source_links),
                ("Findings", finding_links),
            ],
        ),
    )


def _frontmatter(
    *,
    topic_id: int,
    page_type: str,
    title: str,
    sources: list[dict[str, Any]],
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": WIKI_PAGE_SCHEMA_VERSION,
        "topic_id": topic_id,
        "page_type": page_type,
        "title": title,
    }
    if aliases:
        metadata["aliases"] = aliases
    metadata["sources"] = _dedupe_sources(sources)
    return metadata


def _body(title: str, sections: list[tuple[str, list[str]]]) -> str:
    lines = [f"# {title}", ""]
    for section_title, items in sections:
        lines.extend([f"## {section_title}", ""])
        if not items:
            lines.extend(["- none", ""])
            continue
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _evidence_lines(atoms: list[_AtomRecord], *, link_sources: bool) -> list[str]:
    lines: list[str] = []
    for atom in sorted(atoms, key=lambda item: (item.source_type, item.source_id)):
        snippet = atom.snippet or atom.label
        if link_sources and atom.paper_id is not None and atom.source_section:
            source = _wiki_link(
                f"sources/paper-{atom.paper_id}/{slugify(atom.source_section)}.md",
                atom.source_section,
            )
            lines.append(f"{snippet} ({source})")
            continue
        lines.append(snippet)
    return lines


def _source_links(atoms: list[_AtomRecord]) -> list[str]:
    return _dedupe_sorted_links(
        _wiki_link(
            f"sources/paper-{atom.paper_id}/{slugify(atom.source_section)}.md",
            atom.source_section,
        )
        for atom in atoms
        if atom.paper_id is not None and atom.source_section
    )


def _atom_source_ref(atom: _AtomRecord) -> dict[str, Any]:
    return _source_ref(
        paper_id=atom.paper_id,
        source_type=atom.source_type,
        source_id=atom.source_id,
        source_hash=atom.source_hash,
        section_anchor=atom.source_section,
        evidence_snippet=atom.snippet or atom.label,
    )


def _source_ref(
    *,
    paper_id: int | None,
    source_type: str,
    source_id: str | int,
    source_hash: str,
    section_anchor: str,
    evidence_snippet: str,
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "source_type": source_type,
        "source_id": str(source_id),
        "source_hash": source_hash,
        "section_anchor": section_anchor,
        "evidence_snippet": evidence_snippet,
    }


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for source in sources:
        key = (
            source.get("paper_id"),
            source.get("source_type"),
            source.get("source_id"),
            source.get("source_hash"),
            source.get("section_anchor"),
            source.get("evidence_snippet"),
        )
        by_key.setdefault(key, dict(source))
    return [
        by_key[key] for key in sorted(by_key, key=lambda item: tuple(map(str, item)))
    ]


def _paper_source_hashes(source_manifest: dict[str, Any]) -> dict[int, str]:
    hashes: dict[int, str] = {}
    for source in source_manifest.get("sources") or []:
        if not isinstance(source, dict) or source.get("source_type") != "paper":
            continue
        paper_id = source.get("paper_id") or source.get("source_id")
        if paper_id is None:
            continue
        try:
            hashes[int(paper_id)] = str(source.get("source_hash") or "")
        except (TypeError, ValueError):
            continue
    return hashes


def _semantic_neighbors(edges: list[_EdgeRecord]) -> dict[int, set[int]]:
    neighbors: dict[int, set[int]] = {}
    for edge in edges:
        neighbors.setdefault(edge.from_atom_id, set()).add(edge.to_atom_id)
        neighbors.setdefault(edge.to_atom_id, set()).add(edge.from_atom_id)
    return neighbors


def _atom_page_path(atom: _AtomRecord) -> str:
    directory = _page_directory(atom.atom_type)
    return f"{directory}/{slugify(atom.label)}.md"


def _page_directory(atom_type: str) -> str:
    if atom_type in {"method", "baseline"}:
        return "methodology"
    if atom_type in {"claim", "result", "limitation", "gap_signal"}:
        return "findings"
    return "concepts"


def _page_type(atom_type: str) -> str:
    if atom_type in {"method", "baseline"}:
        return "methodology"
    if atom_type in {"claim", "result", "limitation", "gap_signal"}:
        return "finding"
    return "concept"


def _wiki_link(relative_path: str, label: str) -> str:
    target = relative_path[:-3] if relative_path.endswith(".md") else relative_path
    return f"[[{target}|{label}]]"


def _dedupe_sorted_links(links: Any) -> list[str]:
    return sorted({str(link) for link in links if str(link)}, key=str.lower)


def _normalize_link_target(target: str) -> str:
    path = target.split("#", 1)[0].strip()
    if not path:
        return ""
    return path if path.endswith(".md") else f"{path}.md"


def _default_link_label(target: str) -> str:
    clean = target.split("#", 1)[0].rstrip("/")
    if not clean:
        return target
    return clean.rsplit("/", 1)[-1]


def slugify(value: Any) -> str:
    text = str(value or "").lower().replace("@", "-")
    slug = _NON_SLUG_RE.sub("-", text).strip("-")
    return slug or "untitled"


def _load_topic_papers(conn: sqlite3.Connection, topic_id: int) -> dict[int, str]:
    rows = conn.execute(
        """
        SELECT p.id, p.title
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        WHERE pt.topic_id = ?
        ORDER BY p.id
        """,
        (topic_id,),
    ).fetchall()
    return {int(row["id"]): str(row["title"] or f"Paper {row['id']}") for row in rows}


def _load_semantic_atoms(conn: sqlite3.Connection, topic_id: int) -> list[_AtomRecord]:
    rows = conn.execute(
        """
        SELECT id, topic_id, atom_type, normalized_key, label, description,
               source_type, source_id, paper_id, source_section, snippet,
               confidence, source_hash, metadata_json
        FROM semantic_atoms
        WHERE topic_id = ?
        ORDER BY atom_type, normalized_key, source_type, source_id, id
        """,
        (topic_id,),
    ).fetchall()
    return [
        _AtomRecord(
            id=int(row["id"]),
            topic_id=int(row["topic_id"]),
            atom_type=str(row["atom_type"] or ""),
            normalized_key=str(row["normalized_key"] or ""),
            label=str(row["label"] or ""),
            description=str(row["description"] or ""),
            source_type=str(row["source_type"] or ""),
            source_id=str(row["source_id"] or ""),
            source_hash=str(row["source_hash"] or ""),
            paper_id=int(row["paper_id"]) if row["paper_id"] is not None else None,
            source_section=str(row["source_section"] or ""),
            snippet=str(row["snippet"] or ""),
            confidence=float(row["confidence"] or 0.0),
            metadata=_json_obj(row["metadata_json"]) or {},
        )
        for row in rows
    ]


def _load_semantic_edges(conn: sqlite3.Connection, topic_id: int) -> list[_EdgeRecord]:
    rows = conn.execute(
        """
        SELECT edge_type, from_atom_id, to_atom_id, confidence
        FROM semantic_edges
        WHERE topic_id = ?
        ORDER BY edge_type, from_atom_id, to_atom_id, id
        """,
        (topic_id,),
    ).fetchall()
    return [
        _EdgeRecord(
            edge_type=str(row["edge_type"] or ""),
            from_atom_id=int(row["from_atom_id"]),
            to_atom_id=int(row["to_atom_id"]),
            confidence=float(row["confidence"] or 0.0),
        )
        for row in rows
    ]


def _json_obj(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return None


from .research_wiki_validation import (  # noqa: E402,F401
    ResearchWikiValidationIssue,
    ResearchWikiValidationReport,
    render_research_wiki_validation_report_markdown,
    validate_research_wiki_export,
)
