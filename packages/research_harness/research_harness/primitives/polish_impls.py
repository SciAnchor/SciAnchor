"""Final-draft polish (终稿打磨) — a first-class reviewer-style manuscript polish.

RH had the QA *pieces* (consistency_check, citation checks, section_review's
deterministic checks, venue_compliance_check) but no cohesive reviewer-style
polish pass. This orchestrates them plus a multi-angle reviewer critique into a
single prioritized-findings report with a submission-readiness verdict.

Anthropic patterns: orchestrator-workers (polish orchestrates reviewer angles +
QA primitives), parallelization (angles), evaluator-optimizer (review -> fix ->
re-check). Deterministic checks stay deterministic (no LLM).
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .exemplar_impls import (
    _chat,
    _json,
    _llm,
)  # reuse robust router+fallback LLM helper
from .registry import (
    MANUSCRIPT_POLISH_SPEC,
    MANUSCRIPT_REVIEW_SPEC,
    MANUSCRIPT_UNIFY_SPEC,
    register_primitive,
)
from .types import (
    ManuscriptPolishOutput,
    ManuscriptReviewOutput,
    ManuscriptUnifyOutput,
    ReviewFinding,
    UnifyChange,
)

_ANGLES = ["methods_stats", "domain", "editorial"]
_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}

_REVIEW_PROMPTS = {
    "methods_stats": (
        "You are a rigorous METHODS & STATISTICS reviewer for {venue}. Critique the manuscript "
        "for design rigour, leakage control, endpoint definitions, statistics/reporting "
        "completeness, and claim-evidence alignment (does every claim map to a result?)."
    ),
    "domain": (
        "You are a DOMAIN / subject-matter reviewer for {venue}. Critique the manuscript for "
        "correctness of domain concepts, validity of the framing and endpoints, over-claiming, "
        "and generalizability / real-world validity."
    ),
    "editorial": (
        "You are the HANDLING EDITOR for {venue}. Critique the manuscript for structure and flow, "
        "abstract quality, writing clarity vs over-claiming, figure/table callouts and legends, "
        "reference adequacy and ordering, internal consistency, and venue format compliance."
    ),
}

_REVIEW_TAIL = (
    "\nThe text may be a manuscript SOURCE (Markdown with image links, Markdown tables, and author "
    "placeholders like p1-p8). Do NOT raise findings about rendering/format artifacts — Markdown "
    "image syntax, tables shown as plain text, placeholder author names, or heading markup — those "
    "are handled by the build. Focus on scientific rigour, validity, structure, and content.\n"
    'Return ONLY JSON: {{"findings":[{{"severity":"high|medium|low","location":"section",'
    '"issue":"<specific problem>","fix":"<specific actionable fix>"}}]}}. Be specific and '
    "prioritized (most important first); no praise, no generic advice.\n\nManuscript:\n{manuscript}"
)


def _split_sections(text: str) -> dict[str, str]:
    parts = re.split(r"(?m)^##\s+(.+?)\s*$", text or "")
    secs: dict[str, str] = {}
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            name = (parts[i] or "").strip()[:40]
            body = (parts[i + 1] or "").strip()
            if name and body:
                secs[name] = body
    return secs or (
        {"manuscript": (text or "").strip()} if (text or "").strip() else {}
    )


def _sort_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    return sorted(findings, key=lambda f: _SEV_ORDER.get(f.severity, 1))


def _counts(findings: list[ReviewFinding]) -> tuple[int, int, int]:
    return (
        sum(f.severity == "high" for f in findings),
        sum(f.severity == "medium" for f in findings),
        sum(f.severity == "low" for f in findings),
    )


def _norm_sev(s: Any) -> str:
    s = str(s or "medium").lower().strip()
    return s if s in _SEV_ORDER else "medium"


def _field(obj: Any, *names: str, default: str = "") -> str:
    for n in names:
        v = getattr(obj, n, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(n)
        if v:
            return str(v)
    return default


@contextmanager
def _required_check(name: str):
    """Abort incomplete checks without exposing provider responses to callers."""
    try:
        yield
    except Exception as exc:
        raise RuntimeError(f"{name} did not complete") from exc


@register_primitive(MANUSCRIPT_REVIEW_SPEC)
def manuscript_review(
    *,
    db=None,
    topic_id=None,
    manuscript: str,
    angles=None,
    venue: str = "",
    _model: str | None = None,
    **_: Any,
) -> ManuscriptReviewOutput:
    """Multi-angle reviewer critique → prioritized, actionable findings."""
    text = str(manuscript or "")[:40000]
    v = venue or "a top journal"
    with _required_check("manuscript_review setup"):
        use_angles = list(angles or _ANGLES)
        if any(a not in _REVIEW_PROMPTS for a in use_angles):
            raise ValueError("unsupported review angle")
        llm = _llm(_model, "writing", "manuscript_review")
    findings: list[ReviewFinding] = []
    for angle in use_angles:
        prompt = (_REVIEW_PROMPTS[angle] + _REVIEW_TAIL).format(
            venue=v, manuscript=text
        )
        with _required_check(f"manuscript_review angle {angle}"):
            raw = _chat(llm, prompt).strip()
            fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
            # A repaired/truncated response cannot certify a completed review.
            j = json.loads(fenced.group(1) if fenced else raw)
            if not isinstance(j, dict) or not isinstance(j.get("findings"), list):
                raise ValueError("review response requires a findings list")
            for f in j["findings"]:
                if (
                    not isinstance(f, dict)
                    or any(
                        not isinstance(f.get(k), str)
                        for k in ("severity", "location", "issue", "fix")
                    )
                    or f["severity"].strip().lower() not in _SEV_ORDER
                    or not f["issue"].strip()
                ):
                    raise ValueError("invalid review finding")
                findings.append(
                    ReviewFinding(
                        angle=angle,
                        severity=_norm_sev(f["severity"]),
                        location=f["location"][:80],
                        issue=f["issue"][:500],
                        fix=f["fix"][:500],
                    )
                )
    findings = _sort_findings(findings)
    nh, nm, nl = _counts(findings)
    return ManuscriptReviewOutput(
        findings=findings,
        angles=use_angles,
        n_high=nh,
        n_medium=nm,
        n_low=nl,
        model_used=getattr(llm, "model", ""),
    )


def _deterministic_findings(secs: dict[str, str]) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    from research_harness.primitives.writing_impls import section_review

    for name, txt in secs.items():
        if not txt or len(txt) < 40:
            continue
        sr = section_review(section=name, content=str(txt))
        for c in getattr(sr, "deterministic_checks", []) or []:
            if getattr(c, "passed", True):
                continue
            out.append(
                ReviewFinding(
                    angle="deterministic",
                    severity="low",
                    location=name,
                    issue=f"{getattr(c, 'check_name', 'check')}: {getattr(c, 'details', '')}"[
                        :500
                    ],
                    fix="address the flagged writing-quality check",
                )
            )
    return out


def _consistency_findings(db, topic_id, secs, _model) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    from research_harness.execution.llm_primitives import consistency_check

    cc = consistency_check(
        db=db, topic_id=topic_id, sections=list(secs.values()), _model=_model
    )
    for iss in getattr(cc, "issues", []) or []:
        out.append(
            ReviewFinding(
                angle="consistency",
                severity=_norm_sev(_field(iss, "severity", default="medium")),
                location=_field(iss, "section", "location"),
                issue=_field(iss, "description", "issue", "message", default=str(iss))[
                    :500
                ],
                fix=_field(iss, "suggestion", "fix", "resolution")[:500],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Whole-manuscript unification (the "统稿" pass)
# ---------------------------------------------------------------------------

_UNIFY_PROMPT = """You are the final-pass editor of an academic manuscript for {venue}.
The sections below were drafted separately; your ONLY job is to make them read
as one paper written by one author. Perform exactly these edit categories:

1. seam — rewrite section openings/closings so each section follows from the
   previous one (real transitions, not "In this section we...").
2. terminology — one term per concept for the whole paper.{term_block}
3. dedup — remove content repeated across sections (keep the best placement,
   cut or compress the duplicates).
4. de_ai — replace true AI cliches (e.g. "delve into", "shed light on",
   "paving the way", "it is worth noting that", "plays a crucial role").
   Standard academic register is NOT a cliche — keep phrases like
   "the proposed method", "as shown in Table 2", "furthermore",
   "significantly", "approximately" where they are natural; just avoid using
   the same connective more than ~2 times per section.
5. rhythm — vary sentence length within paragraphs that read metronomic; merge
   choppy fragments; split run-ons.

HARD CONSTRAINTS (violating any of these voids the edit):
- Never add, remove, or alter any citation marker: \\cite{{...}}, [N], \\ref{{...}}.
- Never change any number, unit, metric value, or claim of fact.
- Never add new claims, results, or references.
- Keep every section heading exactly as-is, in the same order.
- Keep overall length within ±10% of the original.
- Edit only where one of the five categories applies; leave good prose alone.
{style_block}
Return the FULL edited manuscript as plain text (NOT JSON) between the markers:
<<<MANUSCRIPT>>>
...full text...
<<<END MANUSCRIPT>>>
Then the change log as JSON between:
<<<CHANGES>>>
{{"changes": [{{"location": "...", "category": "seam|terminology|dedup|de_ai|rhythm", "before": "<exact original snippet>", "after": "<edited snippet>", "reason": "..."}}]}}
<<<END CHANGES>>>

Manuscript:
{manuscript}"""

_CITE_RE = re.compile(
    r"\\cite[tp]?\*?(?:\[[^\]]*\])?\{([^}]*)\}|\[(\d+(?:\s*[,–-]\s*\d+)*)\]"
)
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)+(?![\w.])|(?<![\w.])\d+(?:\.\d+)?%")
# Non-LaTeX evidence identifiers (narrative reviews, bilingual/Chinese drafts):
# \cite{} is absent there, so the citation gate above is a no-op. These are the
# load-bearing references in that register — PMID/PMCID/RH-pool/arXiv ids.
_ID_RE = re.compile(
    r"PMID\s*(\d+)|PMCID\s*(\d+)|(?:^|[^A-Za-z])RH\s+(\d+)|arXiv:\s*(\S+)",
    re.IGNORECASE,
)


def _citation_multiset(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in _CITE_RE.finditer(text or ""):
        key = (m.group(1) or m.group(2) or "").replace(" ", "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _identifier_multiset(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in _ID_RE.finditer(text or ""):
        key = next((g for g in m.groups() if g), "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _unify_gate(original: str, unified: str) -> dict[str, Any]:
    """Deterministic preservation gate for the unify pass."""
    issues: list[str] = []
    if _citation_multiset(original) != _citation_multiset(unified):
        issues.append("citation markers changed")
    if _identifier_multiset(original) != _identifier_multiset(unified):
        issues.append("evidence identifiers changed (PMID/RH/arXiv)")
    missing_numbers = sorted(
        set(_NUM_RE.findall(original)) - set(_NUM_RE.findall(unified))
    )
    if missing_numbers:
        issues.append(f"numbers lost: {missing_numbers[:5]}")
    o_len, u_len = len(original), len(unified)
    if o_len and not (0.8 * o_len <= u_len <= 1.15 * o_len):
        issues.append(f"length drift {u_len / o_len:.2f}x outside [0.80, 1.15]")
    o_heads = re.findall(
        r"(?m)^(#{1,3}\s+.+|\\(?:sub)*section\*?\{[^}]*\})\s*$", original
    )
    u_heads = re.findall(
        r"(?m)^(#{1,3}\s+.+|\\(?:sub)*section\*?\{[^}]*\})\s*$", unified
    )
    if o_heads != u_heads:
        issues.append("section headings changed")
    return {"passed": not issues, "issues": issues}


@register_primitive(MANUSCRIPT_UNIFY_SPEC)
def manuscript_unify(
    *,
    db=None,
    topic_id=None,
    manuscript: str,
    term_registry=None,
    style_card: str = "",
    venue: str = "",
    _model: str | None = None,
    **_: Any,
) -> ManuscriptUnifyOutput:
    """Whole-manuscript unification: seams, terminology, dedup, de-AI, rhythm.

    Runs once on the writing tier with the FULL manuscript in context (the
    per-section loop structurally cannot see whole-paper readability). Prose is
    returned as plain text — never wrapped in JSON — and a deterministic gate
    rejects any rewrite that loses citations, numbers, or headings.
    """
    original = str(manuscript or "").strip()
    if not original:
        return ManuscriptUnifyOutput(unified_text="", status="no_change")

    term_lines = [
        f"  - {t.get('term')}: {str(t.get('definition', ''))[:120]}"
        for t in (term_registry or [])
        if isinstance(t, dict) and t.get("term")
    ]
    term_block = (
        " Use these registry terms VERBATIM everywhere (no synonyms):\n"
        + "\n".join(term_lines)
        if term_lines
        else ""
    )
    style_block = (
        "\nStyle card (form only — imitate structure/register, never wording):\n"
        + style_card.strip()[:2000]
        + "\n"
        if style_card.strip()
        else ""
    )

    llm = _llm(_model, "writing", "manuscript_unify")
    raw = _chat(
        llm,
        _UNIFY_PROMPT.format(
            venue=venue or "a top venue",
            term_block=term_block,
            style_block=style_block,
            manuscript=original[:180000],
        ),
    )

    m_text = re.search(
        r"<<<MANUSCRIPT>>>\s*(.*?)\s*<<<END MANUSCRIPT>>>", raw, re.DOTALL
    )
    unified = m_text.group(1).strip() if m_text else ""
    changes: list[UnifyChange] = []
    m_changes = re.search(r"<<<CHANGES>>>\s*(.*?)\s*<<<END CHANGES>>>", raw, re.DOTALL)
    if m_changes:
        try:
            payload = _json(m_changes.group(1), "manuscript_unify")
            for c in payload.get("changes") or []:
                if isinstance(c, dict):
                    changes.append(
                        UnifyChange(
                            location=str(c.get("location", ""))[:120],
                            category=str(c.get("category", ""))[:20],
                            before=str(c.get("before", ""))[:500],
                            after=str(c.get("after", ""))[:500],
                            reason=str(c.get("reason", ""))[:300],
                        )
                    )
        except Exception:
            pass

    if not unified:
        return ManuscriptUnifyOutput(
            unified_text=original,
            status="gate_failed",
            gate={"passed": False, "issues": ["no manuscript block in model output"]},
            model_used=getattr(llm, "model", ""),
        )
    if unified == original:
        return ManuscriptUnifyOutput(
            unified_text=original,
            status="no_change",
            gate={"passed": True, "issues": []},
            model_used=getattr(llm, "model", ""),
        )

    gate = _unify_gate(original, unified)
    if not gate["passed"]:
        return ManuscriptUnifyOutput(
            unified_text=original,
            changes=changes,
            status="gate_failed",
            gate=gate,
            model_used=getattr(llm, "model", ""),
        )
    return ManuscriptUnifyOutput(
        unified_text=unified,
        changes=changes,
        status="unified",
        gate=gate,
        model_used=getattr(llm, "model", ""),
    )


# ---------------------------------------------------------------------------
# Source-fidelity grep audit (XCI05 / R1+R2) — deterministic, no LLM
# ---------------------------------------------------------------------------

_BACKTICK_RE = re.compile(r"`([^`\n]{1,200})`")
_FUNC_CALL_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?:\((?P<args>[^)]*)\))?$"
)
_KW_DEFAULT_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>[^,]+)")
_PATHISH_RE = re.compile(
    r"^(?:\.\./|\.\./|/|[A-Za-z0-9_.-]+/)"  # relative, parent, or absolute path lead-in
    r"[A-Za-z0-9_./\-]*"
    r"(?:\.(?:py|md|tex|json|yaml|yml|toml|txt|sh))?$"
)


def _literal_or_raw(token: str) -> Any:
    raw = token.strip()
    if not raw:
        return raw
    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw


def _defaults_match(stated: Any, actual: Any) -> bool:
    if stated == actual:
        return True
    # tolerate "0.5" vs 0.5 and True/False spellings from prose
    try:
        if float(stated) == float(actual):  # type: ignore[arg-type]
            return True
    except Exception:
        pass
    return str(stated).strip() == str(actual).strip()


def _iter_python_files(root: Path) -> list[Path]:
    out: list[Path] = []
    skip = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
    }
    for path in root.rglob("*.py"):
        if any(part in skip for part in path.parts):
            continue
        out.append(path)
    return out


def _index_functions(
    root: Path,
) -> dict[str, list[tuple[Path, ast.AsyncFunctionDef | ast.FunctionDef]]]:
    index: dict[str, list[tuple[Path, Any]]] = {}
    for path in _iter_python_files(root):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                index.setdefault(node.name, []).append((path, node))
    return index


def _function_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    """Map kw-capable parameter name -> default value (AST literal or raw dump)."""
    args = node.args
    defaults: dict[str, Any] = {}
    # positional-or-keyword defaults align to the end of args.args
    pos = list(args.args)
    pos_defaults = list(args.defaults)
    if pos_defaults:
        for name_node, default_node in zip(pos[-len(pos_defaults) :], pos_defaults):
            try:
                defaults[name_node.arg] = ast.literal_eval(default_node)
            except Exception:
                defaults[name_node.arg] = ast.dump(default_node)
    for name_node, default_node in zip(args.kwonlyargs, args.kw_defaults):
        if default_node is None:
            continue
        try:
            defaults[name_node.arg] = ast.literal_eval(default_node)
        except Exception:
            defaults[name_node.arg] = ast.dump(default_node)
    return defaults


def _safe_resolve(root: Path, claimed: str) -> tuple[Path | None, str]:
    """Resolve claimed path under root. Returns (path_or_None, error)."""
    raw = claimed.strip().strip("'\"")
    if not raw or raw.startswith(("http://", "https://", "s3://")):
        return None, "not_a_workspace_path"
    candidate = Path(raw)
    try:
        if candidate.is_absolute():
            resolved = candidate.resolve()
            root_resolved = root.resolve()
            if root_resolved != resolved and root_resolved not in resolved.parents:
                return None, "path_escapes_workspace"
        else:
            resolved = (root / candidate).resolve()
            root_resolved = root.resolve()
            if root_resolved != resolved and root_resolved not in resolved.parents:
                return None, "path_escapes_workspace"
    except Exception as exc:  # noqa: BLE001
        return None, f"path_unresolvable:{type(exc).__name__}"
    return resolved, ""


def _citation_keys_in_text(text: str) -> set[str]:
    keys: set[str] = set()
    for m in _CITE_RE.finditer(text or ""):
        blob = (m.group(1) or m.group(2) or "").replace(" ", "")
        if not blob:
            continue
        # numeric ranges like 1-3 / 1,2 stay as one marker token for allow-lists
        # that use the same form; split comma-separated latex keys.
        if m.group(1) is not None:
            for part in blob.split(","):
                part = part.strip()
                if part:
                    keys.add(part)
        else:
            keys.add(blob)
    return keys


def source_fidelity_audit(
    *,
    manuscript: str,
    workspace_root: str | Path | None = None,
    composition_contract: Mapping[str, Any] | None = None,
) -> list[ReviewFinding]:
    """Deterministic R1/R2 audit. Empty input / no root+contract → no findings."""
    text = str(manuscript or "")
    findings: list[ReviewFinding] = []

    root: Path | None = None
    if workspace_root not in (None, ""):
        try:
            root = Path(str(workspace_root)).expanduser().resolve()
        except Exception:
            findings.append(
                ReviewFinding(
                    angle="source_fidelity",
                    severity="high",
                    location="workspace_root",
                    issue=f"workspace_root is unresolvable: {workspace_root!r}",
                    fix="pass an existing directory path as workspace_root",
                )
            )
            root = None
        else:
            if not root.is_dir():
                findings.append(
                    ReviewFinding(
                        angle="source_fidelity",
                        severity="high",
                        location="workspace_root",
                        issue=f"workspace_root is not a directory: {root}",
                        fix="point workspace_root at the project checkout",
                    )
                )
                root = None

    if root is not None:
        fn_index = _index_functions(root)
        for m in _BACKTICK_RE.finditer(text):
            token = (m.group(1) or "").strip()
            if not token or " " in token and not _FUNC_CALL_RE.match(token):
                # multi-word prose in backticks is not a claim we audit
                if _PATHISH_RE.search(token) is None and not _FUNC_CALL_RE.match(token):
                    continue
            # path claims
            if _PATHISH_RE.search(token) and not _FUNC_CALL_RE.match(token):
                resolved, err = _safe_resolve(root, token)
                if err == "path_escapes_workspace":
                    findings.append(
                        ReviewFinding(
                            angle="source_fidelity",
                            severity="high",
                            location="path",
                            issue=f"claimed path escapes workspace: `{token}`",
                            fix="cite only paths inside the workspace root",
                        )
                    )
                elif err or resolved is None or not resolved.exists():
                    findings.append(
                        ReviewFinding(
                            angle="source_fidelity",
                            severity="high",
                            location="path",
                            issue=f"claimed path does not resolve in workspace: `{token}`",
                            fix="fix the path or remove the claim",
                        )
                    )
                continue
            # function / default claims
            cm = _FUNC_CALL_RE.match(token)
            if not cm:
                continue
            name = cm.group("name")
            args = (cm.group("args") or "").strip()
            hits = fn_index.get(name) or []
            if not hits:
                findings.append(
                    ReviewFinding(
                        angle="source_fidelity",
                        severity="high",
                        location="function",
                        issue=f"function `{name}` is mentioned but not found in workspace source",
                        fix="implement the function or remove the claim",
                    )
                )
                continue
            if not args or "=" not in args:
                continue
            stated: dict[str, Any] = {}
            for km in _KW_DEFAULT_RE.finditer(args):
                stated[km.group("key")] = _literal_or_raw(km.group("val"))
            if not stated:
                findings.append(
                    ReviewFinding(
                        angle="source_fidelity",
                        severity="medium",
                        location="function",
                        issue=f"could not parse parameter defaults in `{token}`",
                        fix="state defaults as name=literal (e.g. foo(bar=1))",
                    )
                )
                continue
            # any overload/definition whose defaults cover the stated keys wins
            matched = False
            mismatch_detail = ""
            for _path, node in hits:
                defaults = _function_defaults(node)
                ok = True
                for key, val in stated.items():
                    if key not in defaults:
                        ok = False
                        mismatch_detail = (
                            f"`{name}` has no parameter default for `{key}`"
                        )
                        break
                    if not _defaults_match(val, defaults[key]):
                        ok = False
                        mismatch_detail = (
                            f"`{name}({key}=...)` claimed {val!r} but source default is "
                            f"{defaults[key]!r}"
                        )
                        break
                if ok:
                    matched = True
                    break
            if not matched:
                findings.append(
                    ReviewFinding(
                        angle="source_fidelity",
                        severity="high",
                        location="function",
                        issue=mismatch_detail
                        or f"defaults in `{token}` do not match source",
                        fix="align the prose default with the callable signature",
                    )
                )

    # R2 bidirectional citation discipline
    contract = (
        composition_contract if isinstance(composition_contract, Mapping) else None
    )
    if contract:
        allowed_raw = contract.get("allowed_citation_keys")
        required_raw = contract.get("required_citation_keys")
        allowed = (
            {str(x).strip() for x in (allowed_raw or []) if str(x).strip()}
            if allowed_raw is not None
            else None
        )
        required = (
            {str(x).strip() for x in (required_raw or []) if str(x).strip()}
            if required_raw is not None
            else set()
        )
        body_keys = _citation_keys_in_text(text)
        if allowed is not None:
            for key in sorted(body_keys - allowed):
                findings.append(
                    ReviewFinding(
                        angle="source_fidelity",
                        severity="high",
                        location="citation",
                        issue=f"citation `{key}` is not in the composition contract allow-list",
                        fix="remove the cite or add the paper to the composition contract",
                    )
                )
        for key in sorted(required - body_keys):
            findings.append(
                ReviewFinding(
                    angle="source_fidelity",
                    severity="high",
                    location="citation",
                    issue=f"required citation `{key}` is missing from the manuscript body",
                    fix="cite the required paper in the body",
                )
            )

    return _sort_findings(findings)


# ---------------------------------------------------------------------------
# Gated destyle surgery (tier 2): the LLM proposes, the invariant gate disposes
# ---------------------------------------------------------------------------
# Not yet a registered primitive: promoted after the destyle-loop experiment
# (experiments/destyle-loop/) shows a stable counterbalanced win.

_DESTYLE_STRATEGY = {
    "sentence_len_cv": (
        "Only edit if the window has two or more consecutive sentences over "
        "25 words. Split at a semicolon or ', and/but/so' coordination; keep "
        "colons that introduce elaborations. NEVER detach a relative, "
        "purpose, or participial clause from its head. Give the punchiest "
        "INDEPENDENT claim its own SHORT sentence. Never pad."
    ),
    "midband_share": (
        "Vary sentence length: split or tighten so one key claim lands as a "
        "very short sentence. Never pad."
    ),
    "connective_cadence": (
        "Remove the leading connective and let the logic carry, or fold the "
        "sentence into the previous one."
    ),
    "negative_parallelism": "Recast without the 'not just X but Y' frame.",
    "opener_repetition": (
        "Vary the opening ONLY if the window offers a natural alternative "
        "subject or fronted phrase. NEVER invert into a cleft ('X is what Y "
        "reports'). If no natural variant exists, omit this window."
    ),
    "clause_stacking": (
        "Split into two sentences ONLY at a colon, semicolon, coordination, "
        "or em-dash; never detach a subordinate clause from its head."
    ),
    "closer_habit": (
        "If the FINAL sentence only restates content already in the "
        "paragraph, delete it; otherwise recast it without the summary "
        "formula. Keep the rest of the paragraph verbatim."
    ),
    "em_dash_per_1k": (
        "Replace the em-dash parenthetical with parentheses, commas, or a "
        "separate sentence. If the pronoun reference becomes unclear, repeat "
        "the noun it refers to (it is in the window)."
    ),
    "lexical_rotation": (
        "The NOTE names the document's canonical term and the rotated "
        "synonym(s) in this sentence. If the synonym refers to the SAME "
        "thing or action as the canonical term, replace it with the "
        "canonical term (matching inflection); published papers repeat "
        "their terms. If it genuinely names something different, omit this "
        "window. Change nothing else."
    ),
    "rule_of_three": (
        "Break the 'A, B, and C' drumbeat while keeping every item: give "
        "one item its own clause or pair two and set one apart. Split into "
        "a new sentence ONLY at a colon, semicolon, coordination, or "
        "em-dash. Never drop, add, or reorder facts; if no natural recast "
        "exists, omit this window."
    ),
}
# a failed axis licenses surgery on flags of these axes
_AXIS_TO_FLAG = {
    "initial_connective_ratio": "connective_cadence",
    "consecutive_connective_openers": "connective_cadence",
    "midband_share": "sentence_len_cv",
    "subord_per_sent": "clause_stacking",
}

_DESTYLE_PROMPT_HEAD = (
    "You are a precision copy editor removing AI-flavoured rhythm from an "
    "academic manuscript. Below are numbered text windows, each tagged with "
    "its defect and an edit strategy. Rewrite each window under these HARD "
    "RULES:\n"
    "- Use ONLY words already present in that window (inflection changes allowed).\n"
    "- Never add, remove, or alter numbers, citations, or identifiers.\n"
    "- Never delete or add negations (not/no/never...), hedges "
    "(may/suggest/approximately...), quantifiers (all/only/most...), or modals.\n"
    "- Never add facts, claims, or content words from outside the window.\n"
    "- The rewrite must not exceed ~110% of the window length; prefer shorter.\n"
    "- At most ONE new sentence boundary per window.\n"
    "- Prefer the SMALLEST change that fixes the defect; when in doubt, omit "
    "the window entirely — an unedited window costs nothing, a stilted edit "
    "costs a reviewer.\n"
    'Return ONLY JSON: {"edits":[{"id":<window number>,"candidates":["<rewrite '
    'A>","<optional rewrite B>","<optional rewrite C>"]}]}\n\n'
)

_SELECT_PROMPT = (
    "Original passage:\n<<<%s>>>\n\nGate-approved rewrites:\n%s\n"
    "Which rewrite reads most natural and cohesive to a careful human editor? "
    "If NONE reads better than the original, answer 0. Reply with ONE digit only."
)


def manuscript_destyle(
    *,
    manuscript: str,
    max_rounds: int = 2,
    max_windows: int = 12,
    _model: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Fingerprint-targeted, gate-checked style surgery. Content cannot drift:
    every LLM edit must pass ``content_invariant`` or it is vetoed."""
    from research_harness._workflow.execution.style_fingerprint import (
        DESTYLE_RHS_WORDS,
        content_invariant,
        destyle_deterministic,
        style_fingerprint,
    )

    det = destyle_deterministic(str(manuscript or ""))
    text = det.text
    applied: list[dict[str, str]] = [
        {"axis": "deterministic", "change": c} for c in det.changes
    ]
    vetoed: list[dict[str, Any]] = []
    fp0 = style_fingerprint(text)
    llm = _llm(_model, "writing", "manuscript_destyle")
    for _round in range(max_rounds):
        fp = style_fingerprint(text)
        licensed = {a.axis for a in fp.failed_axes}
        licensed |= {_AXIS_TO_FLAG[a] for a in licensed & _AXIS_TO_FLAG.keys()}
        # r1: STRICT licensing — papers/axes inside their band are not touched
        # (r0: always-on sentence_len_cv surgery lost badly on healthy papers)
        windows: list[Any] = []  # StyleFlag objects
        seen: set[str] = set()
        for f in fp.flags:
            w = f.full
            if f.axis not in licensed or not w or w in seen:
                continue
            if text.count(w) != 1 or _DESTYLE_STRATEGY.get(f.axis) is None:
                continue
            seen.add(w)
            windows.append(f)
            if len(windows) >= max_windows:
                break
        if not windows:
            break
        blob = "\n\n".join(
            f"WINDOW {i} [defect: {f.axis}] strategy: {_DESTYLE_STRATEGY[f.axis]}"
            + (
                f"\nNOTE: {f.detail}"
                if f.axis == "lexical_rotation" and f.detail
                else ""
            )
            + f"\n<<<{f.full}>>>"
            for i, f in enumerate(windows)
        )
        try:
            j = _json(_chat(llm, _DESTYLE_PROMPT_HEAD + blob), "manuscript_destyle")
        except Exception:
            break
        n_applied = 0
        selector = _llm(None, "light", "destyle_select")
        for e in j.get("edits") or []:
            if not isinstance(e, dict):
                continue
            i = e.get("id")
            cands = e.get("candidates")
            if cands is None and e.get("after"):
                cands = [e.get("after")]
            cands = [str(c).strip() for c in (cands or []) if str(c).strip()]
            if not isinstance(i, int) or not (0 <= i < len(windows)):
                continue
            flg = windows[i]
            ax, w = flg.axis, flg.full
            if text.count(w) != 1:
                continue
            survivors = []
            for c in cands:
                if c == w:
                    continue
                gate = content_invariant(
                    w,
                    c,
                    extra_allowed=DESTYLE_RHS_WORDS + flg.extra_allowed,
                    extra_deletable=flg.extra_deletable,
                )
                if gate["passed"]:
                    survivors.append(c)
                else:
                    vetoed.append(
                        {"axis": ax, "issues": gate["issues"], "before": w[:120]}
                    )
            if not survivors:
                continue
            after = survivors[0]
            if len(survivors) > 1:
                # best-of-N: a light judge picks, and may reject all (0)
                menu = "\n".join(f"{k + 1}. <<<{c}>>>" for k, c in enumerate(survivors))
                try:
                    pick = re.search(r"\d", _chat(selector, _SELECT_PROMPT % (w, menu)))
                    n = int(pick.group(0)) if pick else 1
                except Exception:
                    n = 1
                if n == 0:
                    continue
                after = survivors[min(n, len(survivors)) - 1]
            text = text.replace(w, after)
            applied.append({"axis": ax, "before": w[:160], "after": after[:160]})
            n_applied += 1
        if not n_applied:
            break
    fp1 = style_fingerprint(text)
    return {
        "text": text,
        "applied": applied,
        "vetoed": vetoed,
        "failed_axes_before": [a.axis for a in fp0.failed_axes],
        "failed_axes_after": [a.axis for a in fp1.failed_axes],
        "flags_before": len(fp0.flags),
        "flags_after": len(fp1.flags),
        "model_used": getattr(llm, "model", ""),
    }


@register_primitive(MANUSCRIPT_POLISH_SPEC)
def manuscript_polish(
    *,
    db=None,
    topic_id=None,
    manuscript: str,
    sections=None,
    venue: str = "",
    run_consistency: bool = True,
    run_deterministic: bool = True,
    workspace_root: str | None = None,
    composition_contract: Mapping[str, Any] | None = None,
    ablation_payload: Mapping[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> ManuscriptPolishOutput:
    """Orchestrated final-draft polish: reviewer critique + deterministic + consistency
    checks -> prioritized findings + submission-readiness verdict."""
    text = str(manuscript or "")
    secs = (
        sections if isinstance(sections, dict) and sections else _split_sections(text)
    )
    checks_run = ["manuscript_review"]
    rev = manuscript_review(
        db=db, topic_id=topic_id, manuscript=text, venue=venue, _model=_model
    )
    findings = list(rev.findings)
    if run_deterministic and secs:
        with _required_check("manuscript_polish section_review(deterministic)"):
            findings += _deterministic_findings(secs)
        checks_run.append("section_review(deterministic)")
        with _required_check("manuscript_polish style_fingerprint"):
            from research_harness._workflow.execution.style_fingerprint import (
                style_fingerprint_findings,
            )

            findings += style_fingerprint_findings(text)
        checks_run.append("style_fingerprint")
        # finish_rulebook_v0.1 P0: case-trace / typed-appendix surface signals
        with _required_check("manuscript_polish finish_form_contract"):
            from research_harness._workflow.execution.finish_form_contract import (
                finish_form_findings,
            )

            ff = [
                ReviewFinding(
                    angle=str(row.get("angle") or "finish_form"),
                    severity=_norm_sev(row.get("severity") or "medium"),
                    location=str(row.get("location") or ""),
                    issue=str(row.get("issue") or "")[:500],
                    fix=str(row.get("fix") or "")[:500],
                )
                for row in finish_form_findings(text)
            ]
        checks_run.append("finish_form_contract")
        findings += ff
        # Structured ablation contract (coverage_gate) when caller supplies payload
        if ablation_payload:
            with _required_check("manuscript_polish ablation_contract"):
                from research_harness._workflow.execution.finish_form_contract import (
                    ablation_contract_findings,
                )

                ab_ff = [
                    ReviewFinding(
                        angle=str(row.get("angle") or "finish_form"),
                        severity=_norm_sev(row.get("severity") or "medium"),
                        location=str(row.get("location") or ""),
                        issue=str(row.get("issue") or "")[:500],
                        fix=str(row.get("fix") or "")[:500],
                    )
                    for row in ablation_contract_findings(ablation_payload)
                ]
            checks_run.append("ablation_contract")
            findings += ab_ff
    if run_consistency and db is not None and topic_id is not None and secs:
        with _required_check("manuscript_polish consistency_check"):
            findings += _consistency_findings(db, topic_id, secs, _model)
        checks_run.append("consistency_check")
    if workspace_root or composition_contract:
        with _required_check("manuscript_polish source_fidelity_audit"):
            findings += source_fidelity_audit(
                manuscript=text,
                workspace_root=workspace_root,
                composition_contract=composition_contract,
            )
        checks_run.append("source_fidelity_audit")
    findings = _sort_findings(findings)
    nh, nm, nl = _counts(findings)
    readiness = "blocked" if nh else ("needs_revision" if nm else "ready")
    summary = (
        f"{nh} high, {nm} medium, {nl} low findings across {len(checks_run)} checks "
        f"-> submission_readiness={readiness}"
    )
    return ManuscriptPolishOutput(
        findings=findings,
        submission_readiness=readiness,
        n_high=nh,
        n_medium=nm,
        n_low=nl,
        checks_run=checks_run,
        summary=summary,
        model_used=rev.model_used,
    )
