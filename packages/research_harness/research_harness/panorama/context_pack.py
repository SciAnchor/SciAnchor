"""Context packs: one self-contained markdown string for agent prompts.

Deterministic projection of one direction's panorama L1 store (plan §3, L2):
direction header, compact territory-map table, frontier digest, then entity
digests by kind (papers last, most-recently-updated first). The pack is capped
at ``max_chars`` by trimming paper entries first, then dataset entries, then a
hard tail cut; a final note records any truncation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema import ENTITY_KINDS
from .store import PanoramaStore
from .views import (
    cell_label,
    classify_cells,
    generated_header_block,
    live_direction_edges,
    one_line,
    sorted_cells,
    sorted_verdicts,
    utc_timestamp,
)

__all__ = ["build_context_pack", "write_context_pack"]

#: Digest order: every non-paper kind in schema order, papers last.
_DIGEST_KIND_ORDER = tuple(
    [kind for kind in ENTITY_KINDS if kind != "paper"] + ["paper"]
)

_EXT_ID_PREFERENCE = ("arxiv", "doi", "github", "openalex", "url")

_LATEST_VERDICT_LIMIT = 10


def _md_cell(value: str) -> str:
    text = " ".join((value or "").split()).replace("|", "\\|")
    return text or "—"


def _key_ext_id(ext_ids: dict[str, str]) -> str:
    if not ext_ids:
        return ""
    for scheme in _EXT_ID_PREFERENCE:
        if scheme in ext_ids:
            return f"{scheme}:{ext_ids[scheme]}"
    scheme = sorted(ext_ids)[0]
    return f"{scheme}:{ext_ids[scheme]}"


def _entity_entry(entity: dict[str, Any]) -> str:
    entry = f"- **{entity['name']}**"
    summary = one_line(entity.get("summary") or "", 240)
    if summary:
        entry += f" — {summary}"
    key = _key_ext_id(entity.get("ext_ids") or {})
    if key:
        entry += f" [{key}]"
    return entry


def build_context_pack(
    store: PanoramaStore, direction_slug: str, *, max_chars: int = 80_000
) -> str:
    """Build the direction's context pack as one markdown string (≤ max_chars)."""
    direction = store.direction(direction_slug)
    if direction is None:
        raise ValueError(f"unknown panorama direction: {direction_slug!r}")
    direction_id = int(direction["id"])

    stats = store.stats(direction_id)
    entities = store.entities(direction_id)
    entity_by_id = {e["id"]: e for e in entities}
    edges = live_direction_edges(store, direction_id, entities)
    cells = sorted_cells(store, direction_id)
    occupants_by_cell = {c["id"]: store.cell_occupants(c["id"]) for c in cells}
    verdicts = sorted_verdicts(store, direction_id)

    head = [f"# Context pack — {direction['title']} ({direction['slug']})", ""]
    description = (direction.get("description") or "").strip()
    if description:
        head += [one_line(description, 500), ""]
    head.append(
        f"Stats: {stats['entities_total']} entities, {stats['live_edges']} "
        f"live edges, {len(cells)} territory cells, {stats['verdicts']} verdicts."
    )

    territory = ["## Territory map", ""]
    if cells:
        territory += [
            "| Problem | Mechanism | Facet | Status | Strength "
            "| Last verified | Occupants |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for cell in cells:
            occupants = "; ".join(occ["name"] for occ in occupants_by_cell[cell["id"]])
            territory.append(
                f"| {_md_cell(cell['problem'])} "
                f"| {_md_cell(cell['mechanism'])} "
                f"| {_md_cell(cell['evidence_facet'])} "
                f"| {_md_cell(cell['status'])} "
                f"| {_md_cell(cell['evidence_strength'])} "
                f"| {_md_cell(cell['last_verified_at'] or 'never')} "
                f"| {_md_cell(occupants)} |"
            )
    else:
        territory.append("_No territory cells recorded._")

    open_cells, weak_cells, contested_cells = classify_cells(cells)
    frontier = ["## Frontier digest"]

    def digest_bucket(title: str, bucket: list[dict[str, Any]]) -> None:
        frontier.extend(["", f"### {title}", ""])
        if not bucket:
            frontier.append("_None._")
            return
        for cell in bucket:
            line = f"- {cell_label(cell)} (strength: {cell['evidence_strength']})"
            names = "; ".join(occ["name"] for occ in occupants_by_cell[cell["id"]])
            if names:
                line += f" — occupants: {names}"
            frontier.append(line)

    digest_bucket("Open cells", open_cells)
    digest_bucket("Weak-evidence cells", weak_cells)
    digest_bucket("Contested cells", contested_cells)

    frontier.extend(["", "### Latest verdicts", ""])
    latest = list(reversed(verdicts))[:_LATEST_VERDICT_LIMIT]
    if latest:
        for verdict in latest:
            frontier.append(
                f"- [{verdict['verdict']}] {one_line(verdict['claim_text'], 240)} "
                f"({verdict['tool']}, {verdict['decided_at']})"
            )
    else:
        frontier.append("_None._")

    contradictions = [e for e in edges if e["rel"] == "contradicts"]
    if contradictions:
        frontier.extend(["", "### Live contradictions", ""])
        for edge in contradictions:
            src = entity_by_id.get(edge["src_id"])
            dst = entity_by_id.get(edge["dst_id"])
            src_name = src["name"] if src else f"entity #{edge['src_id']}"
            dst_name = dst["name"] if dst else f"entity #{edge['dst_id']}"
            frontier.append(f"- {src_name} contradicts {dst_name}")

    kind_entries: dict[str, list[str]] = {}
    for kind in _DIGEST_KIND_ORDER:
        kind_entities = sorted(
            (e for e in entities if e["kind"] == kind),
            key=lambda e: (e["updated_at"], e["id"]),
            reverse=True,
        )
        if kind_entities:
            kind_entries[kind] = [_entity_entry(e) for e in kind_entities]

    n_papers = len(kind_entries.get("paper", []))
    n_datasets = len(kind_entries.get("dataset", []))

    def render(paper_keep: int, dataset_keep: int) -> str:
        sections = [head, territory, frontier]
        entity_lines = ["## Entities"]
        for kind, entries in kind_entries.items():
            keep = entries
            if kind == "paper":
                keep = entries[:paper_keep]
            elif kind == "dataset":
                keep = entries[:dataset_keep]
            if not keep:
                continue
            entity_lines += ["", f"### {kind}", ""] + keep
        if len(entity_lines) > 1:
            sections.append(entity_lines)
        return "\n\n".join("\n".join(block) for block in sections) + "\n"

    text = render(n_papers, n_datasets)
    if len(text) <= max_chars:
        return text

    paper_keep, dataset_keep = n_papers, n_datasets
    body = text
    note = ""
    while True:
        body = render(paper_keep, dataset_keep)
        note = (
            f"_Truncated to fit {max_chars} chars: kept {paper_keep}/{n_papers} "
            f"paper entries and {dataset_keep}/{n_datasets} dataset entries._"
        )
        candidate = f"{body}\n{note}\n"
        if len(candidate) <= max_chars:
            return candidate
        if paper_keep > 0:
            paper_keep -= 1
        elif dataset_keep > 0:
            dataset_keep -= 1
        else:
            break

    note = (
        f"_Truncated to fit {max_chars} chars: dropped all {n_papers} paper "
        f"and {n_datasets} dataset entries; tail cut._"
    )
    keep = max(max_chars - len(note) - 2, 0)
    result = body[:keep].rstrip("\n") + "\n" + note + "\n"
    return result[:max_chars] if len(result) > max_chars else result


def write_context_pack(store: PanoramaStore, direction_slug: str, **kw: Any) -> Path:
    """Write the context pack to ``vault_dir/context-pack.md`` and return the path."""
    content = build_context_pack(store, direction_slug, **kw)
    header = generated_header_block(direction_slug, utc_timestamp())
    store.vault_dir.mkdir(parents=True, exist_ok=True)
    path = store.vault_dir / "context-pack.md"
    path.write_text(header + "\n" + content, encoding="utf-8")
    return path
