"""Manuscript claim-logic tree (EAG-Ladder batch 2, content side).

``logic_tree_build`` turns the topic's paper plan + extracted claims into a
claim tree: core claim -> supporting claims -> evidence leaves anchored to
topic papers. Each node carries a per-section obligation, so SECTION_LOOP
drafting can be conditioned jointly on (form contract, logic obligations) —
the form x logic factorization: EAG contracts say HOW a section reads,
the tree says WHAT it must establish.

Deterministic helpers (`obligations_for_section`, `render_obligations_block`)
are pure so the writing checks and the A/B harness can reuse them without a
model.
"""

from __future__ import annotations

import json
from typing import Any

from .exemplar_impls import _chat, _json, _llm
from .registry import LOGIC_TREE_BUILD_SPEC, register_primitive
from .types import LogicTreeNode, LogicTreeOutput

_SECTIONS = (
    "introduction",
    "related_work",
    "method",
    "experiments",
    "results",
    "limitations",
    "conclusion",
    "abstract",
)

_TREE_PROMPT = (
    "Build the CLAIM-LOGIC TREE for this manuscript. The root is the paper's ONE core "
    "claim; children are the supporting claims that must hold for the parent to hold; "
    "leaves cite the evidence papers (by the integer ids given) that support them.\n"
    "Every node gets: a one-sentence claim, the prose section that must establish it "
    "(one of: {sections}), and a one-sentence OBLIGATION describing what the text must "
    "do for that node (state / derive / measure / defend).\n"
    "Manuscript content and contributions:\n{target}\n\n"
    "Evidence papers (id: title):\n{papers}\n\n"
    'Return ONLY JSON: {{"tree":{{"root_id":"n1","nodes":[{{"node_id":"n1",'
    '"claim":"...","parent_id":"","section_hint":"...",'
    '"evidence_paper_ids":[],"obligation":"..."}}]}}}}. At most {max_nodes} nodes; '
    "every non-root node's parent_id must exist; section_hint must be one of the given "
    "sections; use evidence ids ONLY from the list (empty list when none applies)."
)


def _topic_papers(db, topic_id: int, limit: int = 40) -> list[tuple[int, str]]:
    if db is None or topic_id is None:
        return []
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title FROM papers p
            JOIN topic_papers tp ON tp.paper_id = p.id
            WHERE tp.topic_id = ? ORDER BY p.citation_count DESC NULLS LAST
            LIMIT ?
            """,
            (topic_id, limit),
        ).fetchall()
        return [(int(r[0]), str(r[1])[:140]) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _plan_target(db, topic_id: int) -> str:
    if db is None or topic_id is None:
        return ""
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json FROM project_artifacts
            WHERE topic_id = ? AND artifact_type IN ('PAPER_PLAN', 'paper_plan')
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    try:
        plan = json.loads(row[0])
    except (TypeError, ValueError):
        return ""
    if not isinstance(plan, dict):
        return ""
    keep = {
        key: plan.get(key)
        for key in (
            "title",
            "core_claim",
            "contributions",
            "research_question",
            "hypotheses",
            "method_summary",
            "claims",
        )
        if plan.get(key)
    }
    return json.dumps(keep, ensure_ascii=False)[:3500]


@register_primitive(LOGIC_TREE_BUILD_SPEC)
def logic_tree_build(
    *,
    db=None,
    topic_id=None,
    target_content: str = "",
    max_nodes: int = 18,
    _model: str | None = None,
    **_: Any,
) -> LogicTreeOutput:
    """Build the claim tree from the plan/claims; validated deterministically."""
    target = str(target_content or "").strip() or _plan_target(db, topic_id)
    if not target:
        return LogicTreeOutput()
    papers = _topic_papers(db, topic_id)
    listing = "\n".join(f"{pid}: {title}" for pid, title in papers) or "(none)"
    valid_ids = {pid for pid, _ in papers}

    client = _llm(_model, "medium", "logic_tree_build")
    try:
        parsed = _json(
            _chat(
                client,
                _TREE_PROMPT.format(
                    sections="|".join(_SECTIONS),
                    target=target[:3500],
                    papers=listing[:4000],
                    max_nodes=int(max_nodes),
                ),
            ),
            "logic_tree_build",
        )
    except Exception:
        return LogicTreeOutput(model_used=getattr(client, "model", ""))

    tree = parsed.get("tree") if isinstance(parsed.get("tree"), dict) else parsed
    raw_nodes = tree.get("nodes") if isinstance(tree, dict) else None
    if not isinstance(raw_nodes, list):
        return LogicTreeOutput(model_used=getattr(client, "model", ""))

    nodes: list[LogicTreeNode] = []
    seen_ids: set[str] = set()
    for raw in raw_nodes[: max(1, int(max_nodes))]:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("node_id") or "").strip()
        claim = str(raw.get("claim") or "").strip()
        if not node_id or not claim or node_id in seen_ids:
            continue
        section = str(raw.get("section_hint") or "").strip().lower()
        if section not in _SECTIONS:
            section = ""
        evidence = [
            int(pid)
            for pid in (raw.get("evidence_paper_ids") or [])
            if isinstance(pid, (int, float)) and int(pid) in valid_ids
        ]
        nodes.append(
            LogicTreeNode(
                node_id=node_id,
                claim=claim[:400],
                parent_id=str(raw.get("parent_id") or "").strip(),
                section_hint=section,
                evidence_paper_ids=evidence,
                obligation=str(raw.get("obligation") or "").strip()[:300],
            )
        )
        seen_ids.add(node_id)

    # Deterministic validation: drop nodes whose parent does not exist.
    nodes = [n for n in nodes if not n.parent_id or n.parent_id in seen_ids]
    root_id = str(tree.get("root_id") or "").strip() if isinstance(tree, dict) else ""
    roots = [n for n in nodes if not n.parent_id]
    if root_id not in seen_ids:
        root_id = roots[0].node_id if roots else ""
    sections_covered = sorted({n.section_hint for n in nodes if n.section_hint})
    return LogicTreeOutput(
        nodes=nodes,
        root_id=root_id,
        n_nodes=len(nodes),
        sections_covered=sections_covered,
        model_used=getattr(client, "model", ""),
    )


# --------------------------------------------------------------------------- #
# Deterministic consumers (no LLM)                                            #
# --------------------------------------------------------------------------- #


def obligations_for_section(
    tree_payload: dict[str, Any], section: str
) -> list[dict[str, Any]]:
    """Nodes this section must establish, from a recorded logic_tree payload."""
    section = str(section or "").strip().lower()
    out: list[dict[str, Any]] = []
    for node in tree_payload.get("nodes") or []:
        if isinstance(node, dict) and str(node.get("section_hint") or "") == section:
            out.append(node)
    return out


def render_obligations_block(obligations: list[dict[str, Any]]) -> str:
    """Prompt block: what THIS section must establish (content side)."""
    if not obligations:
        return ""
    lines = ["LOGIC OBLIGATIONS (this section must establish, in substance):"]
    for i, node in enumerate(obligations, 1):
        claim = str(node.get("claim") or "").strip()
        obligation = str(node.get("obligation") or "").strip()
        evidence = node.get("evidence_paper_ids") or []
        suffix = f" [evidence papers: {evidence}]" if evidence else ""
        lines.append(f"{i}. {claim} — {obligation}{suffix}")
    lines.append("Cover EVERY obligation above; do not invent claims outside them.")
    return "\n".join(lines)
