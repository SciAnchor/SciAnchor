"""Deterministic invariant checks for stage gates.

These checks run BEFORE LLM-based gate evaluation and are:
- Fast (no LLM calls)
- Deterministic (same input = same output)
- Non-bypassable (even in autonomous mode)

Inspired by OpenAI's "enforce invariants mechanically, not through documentation."
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from research_harness.experiment.coverage_gate import evaluate_ablation_payload
from research_harness.storage.db import Database
from .models import (
    MIN_EVIDENCE_COVERAGE,
    MIN_FINAL_USABLE_SCREENED_PAPERS,
    MIN_GAP_COUNT,
)
from .stages import resolve_stage, stage_names_for_query

logger = logging.getLogger(__name__)


NON_BLOCKING_STALE_ARTIFACT_TYPES = frozenset(
    {
        "research_state_update",
        "handoff_report",
    }
)

WRITE_GATE_STAGES = frozenset({"write", "draft_preparation", "formal_review"})
BLOCKING_EVIDENCE_SUPPORT_STATUSES = frozenset({"unsupported", "contradicts"})
ARTIFACT_TRACE_REQUIRED_TYPES = frozenset({"publication_pack"})
ARTIFACT_TRACE_SOURCE_TYPES = frozenset(
    {
        "adversarial_resolution",
        "authorship_statement",
        "baseline_matrix",
        "claim_candidate_set",
        "direction_proposal",
        "draft_pack",
        "evidence_pack",
        "experiment_result",
        "figure_plan",
        "final_bundle",
        "final_integrity_report",
        "integrity_review_report",
        "process_summary",
        "re_review_report",
        "response_to_review",
        "review_bundle",
        "revision_package",
        "scholarly_review_report",
        "section_draft",
        "study_spec",
        "verified_registry",
    }
)
BASELINE_GOVERNANCE_STAGES = frozenset({"analyze", "propose"})
BASELINE_GOVERNANCE_ARTIFACT_TYPES = frozenset(
    {"baseline_matrix", "baseline_governance_report"}
)

# Figure-provider governance: a provider failure must degrade to a
# deterministic local figure plus a pending marker, never to a missing asset.
ILLUSTRATION_PENDING_MARKERS = ("ILLUSTRATION_PROVIDER_PENDING", "ILLUSTRATION_PENDING")
FIGURE_PROVIDER_FAILURE_TOKENS = ("FAILED", "ERROR", "UNAVAILABLE")

# ---------------------------------------------------------------------------
# Artifact schema definitions (per artifact_type)
#
# Each entry lists `required_fields` (canonical names). For each canonical
# name, `field_aliases` may list synonyms — if any alias is present and
# truthy, the canonical requirement is satisfied. This matches the actual
# writer output across the codebase, where multiple primitives evolved
# slightly different field names for the same concept.
# ---------------------------------------------------------------------------

ARTIFACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "topic_brief": {
        "required_fields": ["scope", "venue_target"],
        "field_aliases": {
            "scope": [
                "scope",
                "problem_statement",
                "topic_scope",
                "scope_definition",
                "research_scope",
                "research_direction",
            ],
            "venue_target": [
                "venue_target",
                "target_venue",
                "venue",
                "target_conference",
            ],
        },
        "description": "Topic framing output with scope and venue target",
    },
    "literature_map": {
        "required_fields": ["clusters"],
        "field_aliases": {
            "clusters": ["clusters", "cluster_summary", "groups", "themes"],
        },
        "description": "Clustered literature mapping",
    },
    "paper_pool_snapshot": {
        "required_fields": ["paper_count"],
        "field_aliases": {
            "paper_count": ["paper_count", "papers_total", "n_papers", "total_papers"],
        },
        "description": "Snapshot of paper pool state",
    },
    "evidence_pack": {
        "required_fields": ["claims"],
        "field_aliases": {
            "claims": ["claims", "systems", "evidence", "evidence_items", "claim_list"],
        },
        "description": "Extracted claims and evidence links",
    },
    "direction_proposal": {
        "required_fields": ["research_question"],
        "field_aliases": {
            "research_question": [
                "research_question",
                "directions",
                "proposals",
                "questions",
                "hypothesis",
            ],
        },
        "description": "Proposed research direction with question and hypothesis",
    },
    "baseline_matrix": {
        "required_fields": ["baselines", "coverage"],
        "field_aliases": {
            "baselines": ["baselines", "baseline_records", "baseline_methods"],
            "coverage": ["coverage", "baseline_coverage", "coverage_matrix"],
        },
        "description": "Structured baseline coverage and novelty governance matrix",
    },
    "adversarial_resolution": {
        "required_fields": ["outcome"],
        "field_aliases": {
            "outcome": ["outcome", "verdict", "resolution", "result"],
        },
        "description": "Result of adversarial review round",
    },
    "study_spec": {
        "required_fields": ["methodology"],
        "field_aliases": {
            "methodology": ["methodology", "method", "approach", "design"],
        },
        "description": "Experiment study design specification",
    },
    "experiment_result": {
        "required_fields": ["metrics"],
        "field_aliases": {
            "metrics": ["metrics", "results", "measurements", "scores"],
        },
        "description": "Experiment execution results with metrics",
    },
    "verified_registry": {
        "required_fields": ["whitelist_size"],
        "field_aliases": {
            "whitelist_size": ["whitelist_size", "verified_count", "registry_size"],
        },
        "description": "Verified number registry from experiment",
    },
    "draft_pack": {
        "required_fields": ["sections"],
        "field_aliases": {
            "sections": ["sections", "section_drafts", "draft_sections"],
        },
        "description": "Drafted paper sections",
    },
    "publication_pack": {
        "required_fields": ["components", "contract", "source_artifacts"],
        "field_aliases": {
            "components": ["components", "component_map", "slots"],
            "contract": ["contract", "publication_contract", "artifact_contract"],
            "source_artifacts": [
                "source_artifacts",
                "sources",
                "provenance_sources",
            ],
        },
        "description": "Evidence-bound publication package contract",
    },
    "research_state_update": {
        "required_fields": ["event_type"],
        "field_aliases": {
            "event_type": ["event_type", "event", "kind"],
        },
        "description": (
            "Durable feedback update with failures, fixes, contradictions, "
            "review feedback, evidence references, and next actions"
        ),
    },
}


def _has_required_field(
    payload: dict[str, Any],
    field: str,
    schema: dict[str, Any],
    raw_json: str = "",
) -> bool:
    """Return True if `payload` has `field` (or any of its declared aliases)
    set to a truthy value, either at the top level or nested anywhere in
    the payload structure (substring match on the raw JSON)."""
    aliases = schema.get("field_aliases", {}).get(field, [field])
    if field not in aliases:
        aliases = [field, *aliases]
    for key in aliases:
        if key in payload and payload[key]:
            return True
    # Fallback: detect the same canonical/alias keys nested anywhere
    # in the payload via raw substring match. This is cheaper than a
    # recursive walk and good enough for the "is the concept present
    # at all" question.
    if raw_json:
        for key in aliases:
            if f'"{key}"' in raw_json:
                return True
    return False


def _payload_has_paper_sourcing(payload_json: str) -> bool:
    """Cheap structural check: does the payload reference any paper IDs?

    Looks for the canonical sourcing keys at any depth via substring match
    on the raw JSON. Avoids a full json.loads + recursive walk for what
    is fundamentally an "is there any paper attribution at all" question.
    """
    if not payload_json:
        return False
    return (
        '"paper_id"' in payload_json
        or '"paper_ids"' in payload_json
        or '"source_paper_ids"' in payload_json
        or '"evidence_papers"' in payload_json
        or '"evidence_links"' in payload_json
        or '"citations"' in payload_json
    )


def _iter_evidence_link_records(value: Any):
    """Yield evidence-link-shaped dicts from nested artifact payloads."""
    if isinstance(value, dict):
        if "support_status" in value and (
            "claim_id" in value or "source_id" in value or "source_type" in value
        ):
            yield value
        for child in value.values():
            yield from _iter_evidence_link_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_evidence_link_records(child)


def _coerce_artifact_id(value: Any) -> int | None:
    """Return an artifact id from common artifact reference values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if text.isdigit():
        return int(text)

    import re

    for pattern in (
        r"^project_artifacts:(\d+)(?::|$)",
        r"^artifact:[^:]+:(\d+)(?::|$)",
        r"^artifact:(\d+)(?::|$)",
    ):
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


ARTIFACT_TRACE_CONTAINER_KEYS = frozenset(
    {
        "artifact_ref",
        "artifact_refs",
        "source_artifact",
        "source_artifacts",
        "source_refs",
        "trace",
        "artifact_trace",
        "provenance_sources",
    }
)
ARTIFACT_TRACE_DIRECT_KEYS = frozenset(
    {
        "source_artifact_id",
        "source_artifact_ids",
    }
)
ARTIFACT_TRACE_CONTEXT_ID_KEYS = frozenset(
    {
        "artifact_id",
        "source_artifact_id",
        "id",
        "ref",
        "artifact_ref",
    }
)


def _iter_payload_artifact_ref_ids(value: Any):
    """Yield artifact ids from source/reference-shaped payload fields."""
    if not isinstance(value, dict):
        return

    for key, child in value.items():
        if key in ARTIFACT_TRACE_DIRECT_KEYS:
            yield from _iter_trace_context_artifact_ref_ids(child)
            continue
        if key in ARTIFACT_TRACE_CONTAINER_KEYS:
            yield from _iter_trace_context_artifact_ref_ids(child)


def _iter_trace_context_artifact_ref_ids(value: Any):
    artifact_id = _coerce_artifact_id(value)
    if artifact_id is not None:
        yield artifact_id
        return

    if isinstance(value, dict):
        for key, child in value.items():
            if key in ARTIFACT_TRACE_CONTEXT_ID_KEYS:
                artifact_id = _coerce_artifact_id(child)
                if artifact_id is not None:
                    yield artifact_id
                continue
            yield from _iter_trace_context_artifact_ref_ids(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_trace_context_artifact_ref_ids(child)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _final_bundle_has_interim_boundary(payload: dict[str, Any]) -> bool:
    boundary = payload.get("interim_boundary")
    return (
        payload.get("is_interim") is True
        and str(payload.get("finality_status") or "") == "interim_ready"
        and isinstance(boundary, dict)
        and bool(str(boundary.get("statement") or "").strip())
    )


_BIB_KEY_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_THEBIBLIOGRAPHY_RE = re.compile(r"\\begin\{thebibliography\}")
_BIB_FIELD_NAME_RE = re.compile(r"([A-Za-z][\w-]*)\s*=\s*")
_BIB_AUTHORED_ENTRY_TYPES = frozenset(
    {
        "article",
        "inproceedings",
        "incollection",
        "inbook",
        "book",
        "phdthesis",
        "mastersthesis",
        "techreport",
    }
)


def _split_bib_entries(bib_text: str) -> list[tuple[str, str, str]]:
    """Split BibTeX source into (entry_type, key, body) triples.

    Brace-aware and best effort: malformed input yields fewer entries rather
    than raising, because this feeds an advisory write-gate lint.
    """
    entries: list[tuple[str, str, str]] = []
    index = 0
    length = len(bib_text)
    while index < length:
        at = bib_text.find("@", index)
        if at == -1:
            break
        brace = bib_text.find("{", at)
        if brace == -1:
            break
        entry_type = bib_text[at + 1 : brace].strip().lower()
        comma = bib_text.find(",", brace)
        if comma == -1:
            break
        key = bib_text[brace + 1 : comma].strip()
        depth = 1
        cursor = comma + 1
        while cursor < length and depth > 0:
            char = bib_text[cursor]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            cursor += 1
        body = bib_text[comma + 1 : cursor - 1]
        if entry_type not in {"comment", "preamble", "string"} and key:
            entries.append((entry_type, key, body))
        index = cursor
    return entries


def _bib_fields(body: str) -> dict[str, str]:
    """Extract field name -> value pairs from one entry body (brace-aware)."""
    fields: dict[str, str] = {}
    for match in _BIB_FIELD_NAME_RE.finditer(body):
        name = match.group(1).lower()
        cursor = match.end()
        if cursor >= len(body):
            continue
        char = body[cursor]
        if char == "{":
            depth = 1
            end = cursor + 1
            while end < len(body) and depth > 0:
                if body[end] == "{":
                    depth += 1
                elif body[end] == "}":
                    depth -= 1
                end += 1
            value = body[cursor + 1 : end - 1]
        elif char == '"':
            closing = body.find('"', cursor + 1)
            value = body[cursor + 1 : closing] if closing != -1 else ""
        else:
            end = cursor
            while end < len(body) and body[end] not in ",\n":
                end += 1
            value = body[cursor:end]
        fields.setdefault(name, value.strip())
    return fields


def bibliography_hygiene_findings(
    bib_text: str = "", tex_text: str = ""
) -> list[dict[str, Any]]:
    """Deterministic bibliography lint for the write gate.

    Catches the defect classes that shipped in the 2026-07-02 EventGraph
    final PDF (backlog Q3): authorless entries, journal names paired with
    arXiv DOIs, citation keys whose embedded year contradicts the year
    field, and hand-written thebibliography environments.
    """
    findings: list[dict[str, Any]] = []
    for entry_type, key, body in _split_bib_entries(bib_text or ""):
        fields = _bib_fields(body)
        if (
            entry_type in _BIB_AUTHORED_ENTRY_TYPES
            and not fields.get("author")
            and not fields.get("editor")
        ):
            findings.append(
                {
                    "code": "authorless_entry",
                    "entry": key,
                    "message": (f"bibliography entry '{key}' has no author or editor"),
                }
            )
        doi = fields.get("doi", "").lower()
        journal = fields.get("journal", "")
        if (
            journal
            and ("arxiv" in doi or "10.48550" in doi)
            and "arxiv" not in journal.lower()
        ):
            findings.append(
                {
                    "code": "journal_with_arxiv_doi",
                    "entry": key,
                    "message": (
                        f"bibliography entry '{key}' pairs journal '{journal}' "
                        "with an arXiv DOI; cite the journal version or drop "
                        "the journal field"
                    ),
                }
            )
        year = fields.get("year", "").strip()
        key_year = _BIB_KEY_YEAR_RE.search(key)
        if key_year and year.isdigit() and key_year.group(0) != year:
            findings.append(
                {
                    "code": "key_year_mismatch",
                    "entry": key,
                    "message": (
                        f"bibliography key '{key}' embeds year "
                        f"{key_year.group(0)} but the year field says {year}"
                    ),
                }
            )
    if tex_text and _THEBIBLIOGRAPHY_RE.search(tex_text):
        findings.append(
            {
                "code": "handwritten_thebibliography",
                "entry": "",
                "message": (
                    "manuscript uses a hand-written thebibliography "
                    "environment; prefer bibtex/natbib so entries stay "
                    "machine-verifiable"
                ),
            }
        )
    return findings


def _illustration_provenance_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path, record in _iter_dict_records(payload):
        requires_illustration = any(
            _truthy(record.get(key))
            for key in (
                "illustration_required",
                "requires_illustration",
                "illustration_expected",
            )
        )
        route = str(
            record.get("provider_route")
            or record.get("route")
            or record.get("provenance_route")
            or ""
        )
        status = str(
            record.get("illustration_status") or record.get("generation_status") or ""
        )
        deterministic = (
            "deterministic_local" in route or "deterministic_local" in status
        )
        pending = any(marker in status for marker in ILLUSTRATION_PENDING_MARKERS)
        if requires_illustration and deterministic and not pending:
            findings.append(
                {
                    "message": (
                        "Illustration-required figure provenance uses deterministic "
                        "local fallback instead of a real provider or pending marker"
                    ),
                    "metadata": {"path": path, "route": route, "status": status},
                }
            )
    return findings


def _iter_dict_records(value: Any, path: str = "$"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _iter_dict_records(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_dict_records(child, f"{path}[{index}]")


def _writing_mode_is_dream(payload: dict[str, Any]) -> bool:
    mode = str(payload.get("writing_mode") or payload.get("mode") or "").lower()
    return "dream" in mode or "advisor_ideal" in mode


# Demo smoke artifacts are valid deliverables only inside a demo run. These
# payload stamps come from the auto-runner's demo seed-pool path.
DEMO_SCOPE_MARKERS = frozenset(
    {
        "paper_production_demo_pdf_smoke",
        "demo_pdf_smoke",
        "demo_limited_seed_pool",
    }
)
_DEMO_SCOPE_PAYLOAD_KEYS = (
    "automation_scope",
    "readiness_scope",
    "evidence_boundary",
    "publication_pack_status",
)


def _payload_demo_scope_marker(payload: dict[str, Any]) -> str:
    for key in _DEMO_SCOPE_PAYLOAD_KEYS:
        value = str(payload.get(key) or "")
        if value in DEMO_SCOPE_MARKERS:
            return f"{key}={value}"
    return ""


def _illustration_generation_ready() -> bool:
    """Best-effort probe for a configured illustration backend."""
    try:
        from research_harness.integrations.figure_image_provider import (
            figure_image_generation_ready,
        )

        return bool(figure_image_generation_ready())
    except Exception:  # noqa: BLE001 - readiness probe must never break gating
        return False


def figure_pending_provider_ready_findings(
    payload: dict[str, Any], *, provider_ready: bool | None = None
) -> list[dict[str, Any]]:
    """Locate ILLUSTRATION_PENDING markers that are no longer acceptable.

    The pending marker is the sanctioned degraded state only while no real
    figure provider is configured. Once a provider route is ready, a pending
    fallback must block instead of shipping silently.
    """
    ready = (
        _illustration_generation_ready() if provider_ready is None else provider_ready
    )
    if not ready:
        return []
    findings: list[dict[str, Any]] = []
    for path, record in _iter_dict_records(payload):
        for key, value in record.items():
            values: list[str]
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, list):
                values = [item for item in value if isinstance(item, str)]
            else:
                continue
            for text in values:
                upper = text.upper()
                if any(marker in upper for marker in ILLUSTRATION_PENDING_MARKERS):
                    findings.append({"path": f"{path}.{key}", "status": text})
                    break
    return findings


#: Figure routes that produce publication-grade output. An ad-hoc plotting
#: script bypasses the discipline style profiles (palette, ticks, panel
#: letters, error bars) and reliably ships default-matplotlib figures — the
#: defect this gate exists to stop, repeatedly observed on real bundles.
APPROVED_FIGURE_ROUTES = (
    "rh_experiment_figures_renderer",
    "figure_suite_render",
    "renderer_completed",
    "illustration",
    "provider_completed",
    "owner_supplied_placeholder",
    "owner_supplied_pending",
    "external_asset",
    "deterministic_local",
    # RH's own deterministic LaTeX/TikZ route (records -> figure, no hand
    # authoring) is legitimate; only hand-written plots are the defect.
    "tikz_local",
    "latex_local",
    "latex",
)
#: Routes that are explicitly NOT acceptable, named so the message can say why.
_ADHOC_FIGURE_ROUTE_RE = re.compile(
    r"(?:ad[-_ ]?hoc|custom[-_ ]?(?:script|plot)|matplotlib[-_ ]?script"
    r"|python[-_ ]?script|one[-_ ]?off|manual[-_ ]?plot|hand[-_ ]?(?:written|made)"
    r"|handmade)",
    re.IGNORECASE,
)


def figure_route_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag figures produced outside the approved rendering routes.

    Nature-grade output is a property of the renderer, not of the author's
    intent: a one-off plotting script silently drops the discipline palette,
    tick discipline, panel letters and error bars that the style profiles
    apply. Declaring such a route is therefore a finding, not a neutral fact.
    """
    findings: list[dict[str, Any]] = []
    for path, record in _iter_dict_records(payload):
        route = " ".join(
            str(record.get(key) or "")
            for key in ("figure_provider", "provider", "generation_status", "route")
        ).strip()
        if not route:
            continue
        if _ADHOC_FIGURE_ROUTE_RE.search(route) or not any(
            approved in route.lower() for approved in APPROVED_FIGURE_ROUTES
        ):
            findings.append(
                {
                    "message": (
                        f"figure route {route!r} is not an approved rendering "
                        "route: render result figures through RH's "
                        "experiment_figures renderer with the discipline style "
                        "profile (palette, ticks, panel letters, error bars), "
                        "not an ad-hoc plotting script"
                    ),
                    "metadata": {"path": path, "route": route},
                }
            )
    return findings


#: TeX reports a too-wide box as "Overfull \hbox (Npt too wide)". Small
#: prose overflows are typographically routine; a table or figure spilling
#: past the text block is a basic defect that must never reach a reviewer.
_OVERFULL_HBOX_RE = re.compile(r"Overfull \\hbox \(([0-9.]+)pt too wide\)")
OVERFULL_HBOX_PT_LIMIT = 20.0


def latex_layout_findings(
    log_text: str, limit_pt: float = OVERFULL_HBOX_PT_LIMIT
) -> list[dict[str, Any]]:
    """Overflowing boxes in a compiled manuscript log, worst first."""
    widths = sorted(
        (float(m.group(1)) for m in _OVERFULL_HBOX_RE.finditer(log_text or "")),
        reverse=True,
    )
    over = [w for w in widths if w >= limit_pt]
    if not over:
        return []
    return [
        {
            "message": (
                f"{len(over)} box(es) overflow the text block by >= {limit_pt}pt "
                f"(worst {over[0]:.1f}pt): a table or float is spilling past the "
                "margin. Wrap wide tables in \\resizebox, shorten the column "
                "set, or set \\emergencystretch; do not ship an overflowing "
                "layout"
            ),
            "metadata": {"overfull_pt": over[:5], "total_overfull": len(widths)},
        }
    ]


def _has_figure_provenance_record(payload: dict[str, Any]) -> bool:
    """True when any nested record declares how a figure was produced.

    The silent-bypass case this supports: a bundle whose figures were made by
    an untracked script has figure_count > 0 and no record at all — no marker
    for any gate to see. Absence of provenance must be detectable.
    """
    for _path, record in _iter_dict_records(payload):
        if any(
            str(record.get(key) or "").strip()
            for key in ("generation_status", "illustration_status", "figure_provider")
        ):
            return True
    return False


def _figure_provider_failure_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag figure records where a provider failure ended in no asset at all.

    The accepted degraded state is a deterministic local figure plus a
    pending marker; a missing figure is never an acceptable failure state.
    """
    findings: list[dict[str, Any]] = []
    for path, record in _iter_dict_records(payload):
        status = str(
            record.get("generation_status") or record.get("illustration_status") or ""
        )
        upper = status.upper()
        failed = any(token in upper for token in FIGURE_PROVIDER_FAILURE_TOKENS)
        pending = any(marker in upper for marker in ILLUSTRATION_PENDING_MARKERS)
        completed = status == "provider_completed"
        if completed and _truthy(record.get("fallback")):
            findings.append(
                {
                    "message": (
                        "Illustration figure reports provider_completed while its "
                        "selected render is an intermediate fallback"
                    ),
                    "metadata": {
                        "path": path,
                        "status": status,
                        "fallback": True,
                        "selected_stage_key": str(
                            record.get("selected_stage_key") or ""
                        ),
                    },
                }
            )
        if not failed and not pending:
            continue
        asset = ""
        for key in (
            "output_path",
            "fallback_asset_path",
            "local_fallback_path",
            "asset_path",
        ):
            value = str(record.get(key) or "").strip()
            if value and value.lower() != "none":
                asset = value
                break
        if not asset:
            findings.append(
                {
                    "message": (
                        "Figure provider failure at "
                        f"{path} left no figure asset: record a deterministic "
                        "local fallback figure plus an ILLUSTRATION_PENDING "
                        "marker instead of shipping without the figure"
                    ),
                    "metadata": {"path": path, "status": status},
                }
            )
    return findings


def _resolve_recorded_path(raw: Any) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, path]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


_FIGURE_ENV_RE = re.compile(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", re.DOTALL)
_GRAPHIC_CONTENT_RE = re.compile(
    r"\\includegraphics\b|\\begin\{tikzpicture\}|\\begin\{pgfpicture\}"
)
_INCLUDEGRAPHICS_PATH_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_APPENDIX_RE = re.compile(
    r"\\appendix\b|\\begin\{appendices\}|\\section\*?\{Appendix", re.IGNORECASE
)
_TABULAR_BLOCK_RE = re.compile(
    r"\\begin\{tabular[x*]?\}(.*?)\\end\{tabular[x*]?\}", re.DOTALL
)
_DECIMAL_NUMBER_RE = re.compile(r"\d+\.\d+")


def _tex_includegraphics_names(tex_source: str) -> set[str]:
    """Basenames and stems of ``\\includegraphics`` paths in TeX."""
    names: set[str] = set()
    for match in _INCLUDEGRAPHICS_PATH_RE.finditer(tex_source or ""):
        raw = str(match.group(1) or "").strip()
        if not raw:
            continue
        base = Path(raw).name
        if base:
            names.add(base)
            stem = Path(base).stem
            if stem:
                names.add(stem)
    return names


def _routed_figure_names(payload: dict[str, Any]) -> set[str]:
    """Basenames produced by a routed figure tool payload."""
    names: set[str] = set()
    for _path, record in _iter_dict_records(payload):
        for key in ("path", "filename"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                base = Path(value).name
                names.add(base)
                if Path(base).stem:
                    names.add(Path(base).stem)
        paths = record.get("paths")
        if isinstance(paths, dict):
            for value in paths.values():
                if isinstance(value, str) and value.strip():
                    base = Path(value).name
                    names.add(base)
                    if Path(base).stem:
                        names.add(Path(base).stem)
    return names


def _plan_missing_draw_fields(payload: dict[str, Any]) -> list[str]:
    spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else payload
    if not isinstance(spec, dict):
        spec = {}
    missing: list[str] = []
    venue = str(spec.get("target_venue") or payload.get("target_venue") or "").strip()
    if not venue:
        missing.append("target_venue")
    grammar = (
        spec.get("venue_figure_grammar")
        or spec.get("result_plot_policy")
        or payload.get("venue_figure_grammar")
        or payload.get("result_plot_policy")
    )
    if not (isinstance(grammar, dict) and grammar):
        missing.append("venue_figure_grammar")
    modules = spec.get("figure_modules") or payload.get("figure_modules")
    if not (isinstance(modules, dict) and modules):
        missing.append("figure_modules")
    return missing


def _tex_figure_count(tex_source: str) -> int:
    """Count figures that render real graphic content.

    Counting only ``\\includegraphics`` scored legitimate TikZ/PGF figures
    as zero; counting bare figure environments would let caption-only fbox
    placeholders satisfy the visual floor. So: a figure environment counts
    when it contains graphic content, and standalone graphics outside any
    figure environment count individually.
    """
    graphical_envs = sum(
        1
        for match in _FIGURE_ENV_RE.finditer(tex_source)
        if _GRAPHIC_CONTENT_RE.search(match.group(0))
    )
    outside_envs = _FIGURE_ENV_RE.sub("", tex_source)
    return graphical_envs + len(_GRAPHIC_CONTENT_RE.findall(outside_envs))


# Narrative figure cross-reference measurement (2026-08-08 postmortem).
#
# A manuscript shipped with six ``\label{fig:...}`` declarations and ZERO
# ``\ref{fig:...}`` citations in the body: the figures existed as assets but
# the prose never pointed at any of them. The build report counted only
# graphic assets, so "6" was read as "six figures are referenced" — false.
# Asset count and narrative-reference count are therefore reported as
# SEPARATE numbers. These are pure metrics: no invariant, no threshold, no
# pass/fail decision reads them.
_LABEL_DECL_RE = re.compile(r"\\label\s*\{([^}]*)\}")
_FIGURE_LABEL_PREFIX_RE = re.compile(r"^fig(?:ure)?:", re.IGNORECASE)
# \ref, \autoref, \cref, \Cref — starred variants and padding tolerated.
# Anchoring on the backslash keeps ``\autoref`` from matching the ``ref``
# branch, and the required brace keeps ``\crefrange`` from matching at all.
_FIGURE_REF_RE = re.compile(r"\\(?:ref|autoref|cref|Cref)\*?\s*\{([^}]*)\}")


def _brace_keys(raw: str) -> list[str]:
    """Split a reference argument into keys (``\\cref{fig:a,fig:b}``)."""
    return [key.strip() for key in raw.split(",") if key.strip()]


def _tex_figure_label_keys(tex_source: str) -> set[str]:
    """Distinct ``\\label{fig:...}`` keys declared anywhere in the source.

    Label identity is case-sensitive (LaTeX treats ``fig:A`` and ``fig:a`` as
    different labels); only the ``fig:``/``figure:`` prefix test is
    case-insensitive.
    """
    return {
        key
        for key in (m.group(1).strip() for m in _LABEL_DECL_RE.finditer(tex_source))
        if _FIGURE_LABEL_PREFIX_RE.match(key)
    }


def _tex_narrative_reference_keys(tex_source: str) -> set[str]:
    """Distinct reference keys cited from OUTSIDE every figure environment.

    A ``\\ref`` inside the figure float itself (typically a caption
    cross-linking a sibling panel) is markup, not prose narration, so the
    figure environments are removed before scanning.
    """
    narrative = _FIGURE_ENV_RE.sub(" ", tex_source)
    keys: set[str] = set()
    for match in _FIGURE_REF_RE.finditer(narrative):
        keys.update(_brace_keys(match.group(1)))
    return keys


# BUG-018: method details deferred to "per the provided rules" / "按提供的规则"
# instead of concrete thresholds/hyperparameters. Conservative, domain-agnostic
# — only matches phrases that stand in for a value, not ordinary cross-refs.
_METHODS_PLACEHOLDER_RE = re.compile(
    r"(?:按|根据|依据)[^。\n]{0,6}(?:提供|给定)的?(?:规则|配置|参数|设置|阈值|超参)"
    r"|(?:per|using|following|as per)\s+the\s+provided\s+"
    r"(?:rules?|configuration|thresholds?|hyper-?parameters?|settings?)",
    re.IGNORECASE,
)


def _tex_content_metrics(tex_source: str) -> dict[str, Any]:
    numeric_tables = sum(
        1
        for match in _TABULAR_BLOCK_RE.finditer(tex_source)
        if len(_DECIMAL_NUMBER_RE.findall(match.group(1))) >= 3
    )
    placeholder_hits = _METHODS_PLACEHOLDER_RE.findall(tex_source)
    figure_labels = _tex_figure_label_keys(tex_source)
    narrated_labels = figure_labels & _tex_narrative_reference_keys(tex_source)
    return {
        # Asset count — unchanged semantics, and deliberately NOT the same
        # number as the narrative-reference count below.
        "figure_count": _tex_figure_count(tex_source),
        "numeric_result_table_count": numeric_tables,
        "appendix_present": bool(_APPENDIX_RE.search(tex_source)),
        "placeholder_phrase_count": len(placeholder_hits),
        "placeholder_examples": sorted({h.strip() for h in placeholder_hits})[:5],
        "figure_label_count": len(figure_labels),
        "figure_narrative_reference_count": len(narrated_labels),
        "unreferenced_figure_labels": sorted(figure_labels - narrated_labels),
    }


_AAAI_OFFICIAL_STYLE_RE = re.compile(
    r"\\documentclass(?:\[[^\]]*\])?\{aaai|\\usepackage(?:\[[^\]]*\])?\{aaai"
)
_A4PAPER_RE = re.compile(r"\ba4paper\b")
_LETTERPAPER_RE = re.compile(r"\bletterpaper\b")
_TWOCOLUMN_RE = re.compile(r"\\twocolumn\b|\\documentclass\[[^\]]*twocolumn")


def venue_template_findings(
    target_venue: str,
    tex_source: str,
    tex_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Deterministic venue/template mismatch findings for one TeX source.

    Only venue families with hard layout requirements are enforced. For an
    AAAI target the acceptable states are the official aaai class/style
    (including a bundled aaai*.sty/.cls next to the TeX) or RH's letterpaper
    two-column AAAI draft template. An a4paper or single-column article body
    for an AAAI target is exactly the incident regression this gate stops.
    Shared by the write-gate invariant check and commit_manuscript_version.
    """
    venue = str(target_venue or "").strip().lower()
    if "aaai" not in venue:
        return []
    if _AAAI_OFFICIAL_STYLE_RE.search(tex_source):
        return []
    if tex_dir is not None:
        try:
            if any(tex_dir.glob("aaai*.sty")) or any(tex_dir.glob("aaai*.cls")):
                return []
        except OSError:
            pass
    findings: list[dict[str, Any]] = []
    if _A4PAPER_RE.search(tex_source) or not _LETTERPAPER_RE.search(tex_source):
        findings.append(
            {
                "check": "venue_template_compliance",
                "severity": "high",
                "message": (
                    f"target venue {target_venue!r} requires AAAI letterpaper "
                    "layout, but the TeX source uses neither the official "
                    "aaai class/style nor a letterpaper geometry; use the "
                    "official AAAI kit or RH's aaai draft template"
                ),
            }
        )
    if not _TWOCOLUMN_RE.search(tex_source):
        findings.append(
            {
                "check": "venue_template_compliance",
                "severity": "high",
                "message": (
                    f"target venue {target_venue!r} requires a two-column "
                    "AAAI layout, but the TeX source is single-column; use "
                    "the official AAAI kit or RH's aaai draft template"
                ),
            }
        )
    return findings


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "required"}
    return bool(value)


def _normalized_strings(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _baseline_id(record: dict[str, Any], fallback: int) -> str:
    for key in ("baseline_id", "id", "name"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return f"baseline:{fallback}"


def _baseline_family(record: dict[str, Any]) -> str:
    for key in ("method_family", "baseline_family", "family"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _baseline_facets(record: dict[str, Any]) -> list[str]:
    facets: list[str] = []
    for key in ("facets", "survey_facets", "covered_facets"):
        facets.extend(_normalized_strings(record.get(key)))
    for key in ("facet", "survey_facet", "evaluation_facet"):
        value = str(record.get(key) or "").strip()
        if value:
            facets.append(value)
    return list(dict.fromkeys(facets))


def _direction_claims_strong_novelty(payload: dict[str, Any]) -> bool:
    decision = payload.get("novelty_decision")
    if isinstance(decision, dict):
        verdict = str(decision.get("verdict") or "").strip().lower()
        if verdict in {"novel", "strong_novelty"}:
            return True

    texts: list[str] = []
    for key in (
        "novelty_claim",
        "novelty_statement",
        "contribution",
        "contribution_claim",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            texts.append(value)
    combined = " ".join(texts).lower()
    if not combined:
        return False
    if any(token in combined for token in ("incremental", "extension", "extends")):
        return False
    return "novel" in combined or "first" in combined


def _baseline_matrix_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("baselines")
    if not isinstance(raw, list):
        raw = payload.get("baseline_records")
    return [item for item in _as_list(raw) if isinstance(item, dict)]


def _baseline_close_prior_ids(
    payload: dict[str, Any], baseline_records: list[dict[str, Any]]
) -> list[str]:
    ids: list[str] = []
    decision = payload.get("novelty_decision")
    if isinstance(decision, dict):
        ids.extend(_normalized_strings(decision.get("close_prior_baseline_ids")))
        ids.extend(_normalized_strings(decision.get("close_prior_ids")))

    for index, record in enumerate(baseline_records):
        relation = str(record.get("relationship_to_proposal") or "").strip().lower()
        if relation in {"close_prior", "too_similar", "overlaps", "duplicate"}:
            ids.append(_baseline_id(record, index))
    return list(dict.fromkeys(ids))


def _baseline_novelty_verdict(payload: dict[str, Any]) -> str:
    decision = payload.get("novelty_decision")
    if isinstance(decision, dict):
        return str(decision.get("verdict") or "").strip().lower()
    return str(payload.get("novelty_verdict") or "").strip().lower()


def _analyze_gate_would_need_expansion(conn: Any, topic_id: int, stage: str) -> bool:
    if resolve_stage(stage) != "analyze":
        return False

    stage_names = stage_names_for_query(stage)
    placeholders = ",".join("?" * len(stage_names))
    gap_row = conn.execute(
        f"""
        SELECT payload_json FROM project_artifacts
        WHERE topic_id = ? AND stage IN ({placeholders})
              AND artifact_type IN ('gap_detect', 'gap_analysis')
              AND status = 'active'
        ORDER BY version DESC LIMIT 1
        """,
        (topic_id, *stage_names),
    ).fetchone()
    if gap_row is not None:
        try:
            payload = json.loads(gap_row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        gaps = payload.get("gaps", [])
        if isinstance(gaps, list) and len(gaps) < MIN_GAP_COUNT:
            return True

    ev_row = conn.execute(
        """
        SELECT payload_json FROM project_artifacts
        WHERE topic_id = ? AND artifact_type = 'evidence_trace_report'
              AND status = 'active'
        ORDER BY version DESC LIMIT 1
        """,
        (topic_id,),
    ).fetchone()
    if ev_row is not None:
        try:
            payload = json.loads(ev_row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        coverage = float(payload.get("coverage_ratio", 0.0) or 0.0)
        if coverage < MIN_EVIDENCE_COVERAGE:
            return True

    return False


def _baseline_governance_is_linked_to_proposal(
    conn: Any,
    *,
    proposal_id: int,
    baseline_id: int,
    proposal_payload: dict[str, Any],
    baseline_payload: dict[str, Any],
) -> bool:
    if baseline_id >= proposal_id:
        return True

    edge = conn.execute(
        """
        SELECT 1
        FROM artifact_dependencies
        WHERE (from_artifact_id = ? AND to_artifact_id = ?)
           OR (from_artifact_id = ? AND to_artifact_id = ?)
        LIMIT 1
        """,
        (baseline_id, proposal_id, proposal_id, baseline_id),
    ).fetchone()
    if edge is not None:
        return True

    proposal_refs = set(_iter_payload_artifact_ref_ids(proposal_payload))
    baseline_refs = set(_iter_payload_artifact_ref_ids(baseline_payload))
    return baseline_id in proposal_refs or proposal_id in baseline_refs


class InvariantChecker:
    """Runs deterministic pre-checks before gate evaluation."""

    def __init__(self, db: Database):
        self._db = db

    def check_all(self, topic_id: int, stage: str) -> list[InvariantViolation]:
        """Run all invariant checks for a stage. Returns list of violations."""
        violations: list[InvariantViolation] = []
        violations.extend(self.check_run_contract(topic_id, stage))
        violations.extend(self.check_artifact_schemas(topic_id, stage))
        violations.extend(self.check_no_stale_artifacts(topic_id, stage))
        violations.extend(self.check_provenance_linkage(topic_id, stage))
        violations.extend(self.check_artifact_trace_linkage(topic_id, stage))
        violations.extend(self.check_baseline_governance(topic_id, stage))
        violations.extend(self.check_unsupported_evidence_links(topic_id, stage))
        violations.extend(self.check_section_citations(topic_id, stage))
        violations.extend(
            self.check_citation_sentence_evidence_coverage(topic_id, stage)
        )
        violations.extend(self.check_final_publication_boundaries(topic_id, stage))
        violations.extend(self.check_dream_firewall(topic_id, stage))
        violations.extend(self.check_bibliography_hygiene(topic_id, stage))
        violations.extend(self.check_venue_template_compliance(topic_id, stage))
        violations.extend(self.check_figure_provider_fallback(topic_id, stage))
        violations.extend(self.check_figure_provider_pending_readiness(topic_id, stage))
        violations.extend(self.check_demo_scope_boundary(topic_id, stage))
        violations.extend(self.check_experiment_execution_evidence(topic_id, stage))
        violations.extend(self.check_figure_contract_gate(topic_id, stage))
        violations.extend(self.check_exemplar_writing_gate(topic_id, stage))
        return violations

    # run_contract entries with enforcement="gate" must name a check that
    # actually exists — a contract claiming gate enforcement without a gate is
    # exactly the "instruction lives only in conversation" failure this
    # artifact type replaces. Extend this map when a new gate lands.
    RUN_CONTRACT_ENFORCEABLE_KEYS: dict[str, str] = {
        "figures_referenced_in_text": "figure_narrative_reference",
        "figure_provider_declared": "figure_provider_provenance",
    }
    RUN_CONTRACT_ENFORCEMENT_LEVELS = ("gate", "measured", "advisory")

    def check_run_contract(self, topic_id: int, stage: str) -> list[InvariantViolation]:
        """Validate the topic's run_contract artifact (user run requirements).

        A run_contract entry is ``{key, requirement, enforcement}``. The check
        keeps contracts honest: unknown enforcement levels and gate-declared
        entries with no backing gate are violations. Entries at ``measured``
        or ``advisory`` are legitimate — the point is that the boundary of
        what is actually enforced stays explicit (same principle as the
        disclosure checker's "what this does not check" output).
        """
        found = self._latest_active_payload(topic_id, "run_contract")
        if found is None:
            return []
        artifact_id, payload = found
        violations: list[InvariantViolation] = []
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            return [
                InvariantViolation(
                    check="run_contract_schema",
                    severity="high",
                    message=(
                        f"run_contract {artifact_id} has no entries list; "
                        "record entries as {key, requirement, enforcement}"
                    ),
                    artifact_id=artifact_id,
                )
            ]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            enforcement = str(entry.get("enforcement") or "").strip().lower()
            if enforcement not in self.RUN_CONTRACT_ENFORCEMENT_LEVELS:
                violations.append(
                    InvariantViolation(
                        check="run_contract_schema",
                        severity="high",
                        message=(
                            f"run_contract {artifact_id} entry {key!r} has "
                            f"enforcement {enforcement!r}; use one of "
                            f"{'/'.join(self.RUN_CONTRACT_ENFORCEMENT_LEVELS)}"
                        ),
                        artifact_id=artifact_id,
                    )
                )
                continue
            if enforcement == "gate" and key not in self.RUN_CONTRACT_ENFORCEABLE_KEYS:
                violations.append(
                    InvariantViolation(
                        check="run_contract_unenforceable_gate",
                        severity="high",
                        message=(
                            f"run_contract {artifact_id} entry {key!r} "
                            "declares gate enforcement but no gate exists "
                            "for it; implement the gate first or record the "
                            "entry as measured/advisory — a contract must "
                            "not claim enforcement it does not have"
                        ),
                        artifact_id=artifact_id,
                    )
                )
        return violations

    def _latest_active_payload(
        self, topic_id: int, artifact_type: str
    ) -> tuple[int, dict[str, Any]] | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT id, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = ? AND status = 'active'
                ORDER BY version DESC, id DESC LIMIT 1
                """,
                (topic_id, artifact_type),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        return int(row["id"]), payload

    def _has_kept_experiment_runs(self, topic_id: int) -> bool:
        conn = self._db.connect()
        try:
            try:
                row = conn.execute(
                    "SELECT 1 FROM experiment_runs WHERE topic_id = ? AND kept = 1 "
                    "LIMIT 1",
                    (topic_id,),
                ).fetchone()
            except Exception:  # noqa: BLE001 - legacy DBs may lack the table
                return False
            return row is not None
        finally:
            conn.close()

    def check_bibliography_hygiene(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Advisory bibliography lint on the active final bundle (backlog Q3).

        Reads the recorded .bib (and TeX for hand-written thebibliography
        environments) and reports authorless entries, journal+arXiv-DOI
        pairings, and key/year mismatches. Medium severity: surfaced in gate
        diagnostics without blocking, since bib style varies by venue.
        """
        if stage not in WRITE_GATE_STAGES:
            return []
        found = self._latest_active_payload(topic_id, "final_bundle")
        if found is None:
            return []
        artifact_id, payload = found
        files = payload.get("files")
        files = files if isinstance(files, dict) else {}
        bib_path = _resolve_recorded_path(files.get("bib") or payload.get("bib_path"))
        tex_path = _resolve_recorded_path(files.get("tex") or payload.get("tex_path"))
        bib_text = ""
        tex_text = ""
        try:
            if bib_path is not None:
                bib_text = bib_path.read_text(encoding="utf-8", errors="replace")
            if tex_path is not None:
                tex_text = tex_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        if not bib_text and not tex_text:
            return []
        return [
            InvariantViolation(
                check="bibliography_hygiene",
                severity="medium",
                message=finding["message"],
                artifact_id=artifact_id,
                metadata={"code": finding["code"], "entry": finding["entry"]},
            )
            for finding in bibliography_hygiene_findings(bib_text, tex_text)
        ]

    def check_exemplar_writing_gate(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Write gate: a manuscript must be anchored to target-venue exemplars.

        Default ON — set ``RESEARCH_HARNESS_EAG_WRITE_GATE=0`` to disable.
        EAG is what carries venue register into the draft; without it the
        prompts fall back to a generic conference template and the manuscript
        opens in the wrong voice (an npj abstract starting "We introduce ..."
        is the canonical symptom). Before 2026-08-17 that fall-back was
        silent: EAG participated in figure planning only, so a topic could
        pass the write gate with no exemplar anchor at all. Drafting still
        must not hard-fail deep in a run, so the gate fires at the write
        stage, where importing exemplars is still cheap.
        """
        if os.environ.get("RESEARCH_HARNESS_EAG_WRITE_GATE", "1").strip() == "0":
            return []
        if stage not in WRITE_GATE_STAGES:
            return []
        for artifact_type in (
            "exemplar_plan_intro_arc",
            "exemplar_plan_abstract_arc",
            "exemplar_curate",
        ):
            if self._latest_active_payload(topic_id, artifact_type) is not None:
                return []
        return [
            InvariantViolation(
                check="exemplar_writing_gate",
                severity="high",
                message=(
                    "Topic reaches the write gate with no active EAG exemplar "
                    "anchor (no intro/abstract arc plan, no curated exemplar "
                    "set). Section prompts would fall back to the generic "
                    "template and lose target-venue register. Run "
                    "`rh exemplar import` / `rh exemplar plan` for the target "
                    "venue, or disable RESEARCH_HARNESS_EAG_WRITE_GATE."
                ),
            )
        ]

    def check_figure_contract_gate(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Write/finalize gate for the whole-paper figure contract.

        Default ON — set ``RESEARCH_HARNESS_FIGURE_CONTRACT_GATE=0`` to disable.
        Survey/position papers without experiment goals/results skip the plan
        requirement. Any ``\\includegraphics`` in the committed TeX must still
        resolve to a routed-module product (figure_suite_render / figure_generate).
        """
        if os.environ.get("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1").strip() == "0":
            return []
        if stage not in WRITE_GATE_STAGES:
            return []
        violations: list[InvariantViolation] = []
        if self._topic_has_experiment_basis(topic_id):
            found = self._latest_active_payload(topic_id, "figure_suite_plan")
            if found is None:
                violations.append(
                    InvariantViolation(
                        check="figure_contract_gate",
                        severity="high",
                        message=(
                            "Topic has experiment goals/results but no figure_suite_plan. "
                            "Plan the paper's figure suite (rh exemplar figure-plan) before "
                            "the write gate, or disable "
                            "RESEARCH_HARNESS_FIGURE_CONTRACT_GATE."
                        ),
                    )
                )
            else:
                artifact_id, payload = found
                coverage = payload.get("matrix_coverage")
                coverage = coverage if isinstance(coverage, dict) else {}
                unfeedable = coverage.get("unfeedable_panels") or []
                unfed = coverage.get("unfed_experiments") or []
                if coverage.get("verdict") == "gaps_found" and (unfeedable or unfed):
                    violations.append(
                        InvariantViolation(
                            check="figure_contract_gate",
                            severity="high",
                            message=(
                                f"figure_suite_plan has unresolved coverage gaps "
                                f"({len(unfeedable)} panel(s) without data, {len(unfed)} "
                                "experiment(s) with no figure). Reconcile against results "
                                "(rh exemplar figure-plan --reuse-plan) before the write gate."
                            ),
                            artifact_id=artifact_id,
                            metadata={
                                "unfeedable_panels": len(unfeedable),
                                "unfed_experiments": len(unfed),
                            },
                        )
                    )
                missing = _plan_missing_draw_fields(payload)
                if missing:
                    violations.append(
                        InvariantViolation(
                            check="figure_contract_gate",
                            severity="high",
                            message=(
                                "figure_suite_plan is missing pre-draw fields "
                                f"({', '.join(missing)}): target_venue, "
                                "venue_figure_grammar, and figure_modules are "
                                "required before pixels."
                            ),
                            artifact_id=artifact_id,
                            metadata={"missing": missing},
                        )
                    )
        violations.extend(self._includegraphics_route_violations(topic_id))
        return violations

    def _includegraphics_route_violations(
        self, topic_id: int
    ) -> list[InvariantViolation]:
        """Every ``\\includegraphics`` must map to a routed-module product."""
        found = self._latest_active_payload(topic_id, "final_bundle")
        if found is None:
            return []
        artifact_id, payload = found
        files = payload.get("files")
        files = files if isinstance(files, dict) else {}
        tex_ref = (
            files.get("tex") if isinstance(files, dict) else None
        ) or payload.get("tex_path")
        tex_path = _resolve_recorded_path(tex_ref)
        if tex_path is None:
            return []
        try:
            tex_source = tex_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        included = _tex_includegraphics_names(tex_source)
        if not included:
            return []
        routed: set[str] = set()
        for artifact_type in (
            "figure_suite_render",
            "figure_asset_pack",
            "figure_generate",
        ):
            recorded = self._latest_active_payload(topic_id, artifact_type)
            if recorded is None:
                continue
            routed.update(_routed_figure_names(recorded[1]))
        unmatched = sorted(
            name
            for name in included
            if name not in routed and Path(name).stem not in routed
        )
        if not unmatched:
            return []
        return [
            InvariantViolation(
                check="figure_contract_gate",
                severity="high",
                message=(
                    "final_bundle \\includegraphics paths are not routed-module "
                    f"products ({unmatched[:5]}). Draw through figure_suite_render "
                    "or figure_generate; ad-hoc / Claude-drawn files do not pass."
                ),
                artifact_id=artifact_id,
                metadata={"unmatched": unmatched[:8], "routed_count": len(routed)},
            )
        ]

    def _topic_has_experiment_basis(self, topic_id: int) -> bool:
        """True when the topic has experiment_result/baseline_matrix artifacts or
        an active goal_pool — i.e. something a result-figure suite would plot."""
        conn = self._db.connect()
        try:
            has_artifact = conn.execute(
                "SELECT 1 FROM project_artifacts WHERE topic_id = ? "
                "AND artifact_type IN ('experiment_result', 'baseline_matrix') "
                "AND status = 'active' LIMIT 1",
                (topic_id,),
            ).fetchone()
            if has_artifact is not None:
                return True
            try:
                has_goal = conn.execute(
                    "SELECT 1 FROM goal_pool WHERE topic_id = ? AND status = 'active' LIMIT 1",
                    (topic_id,),
                ).fetchone()
                return has_goal is not None
            except Exception:
                return False
        except Exception:
            return False
        finally:
            conn.close()

    def check_dream_firewall(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Refuse dream-marked final bundles on the formal RH path.

        A final_bundle whose writing mode is dream blocks the write gate; the
        same findings also block commit_manuscript_version.
        """
        if stage not in WRITE_GATE_STAGES:
            return []
        found = self._latest_active_payload(topic_id, "final_bundle")
        if found is None:
            return []
        artifact_id, payload = found
        return self.dream_firewall_findings(artifact_id, payload)

    @staticmethod
    def dream_firewall_findings(
        artifact_id: int, payload: dict[str, Any]
    ) -> list[InvariantViolation]:
        """Firewall findings for one final_bundle payload.

        Shared by the write-gate invariant check and by
        commit_manuscript_version, so a hand-committed dream bundle is
        refused the same way as a pipeline-generated one. It always fails
        closed.
        """
        if not _writing_mode_is_dream(payload):
            return []
        return [
            InvariantViolation(
                check="dream_firewall",
                severity="critical",
                message=(
                    f"final_bundle {artifact_id} is dream-marked: the formal "
                    "RH path refuses dream bundles at the commit and write gates"
                ),
                artifact_id=artifact_id,
            )
        ]

    def check_venue_template_compliance(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Block write gates when the final bundle ignores the venue template.

        The original incident shipped an a4paper single-column article for an
        AAAI target: skill docs promised the venue template but nothing
        enforced it against the committed TeX.
        """
        if stage not in WRITE_GATE_STAGES:
            return []
        venue = self._topic_target_venue(topic_id)
        if not venue:
            return []
        found = self._latest_active_payload(topic_id, "final_bundle")
        if found is None:
            return []
        artifact_id, payload = found
        files = payload.get("files")
        tex_ref = (
            files.get("tex") if isinstance(files, dict) else None
        ) or payload.get("tex_path")
        tex_path = _resolve_recorded_path(tex_ref)
        if tex_path is None:
            return []
        try:
            tex_source = tex_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [
            InvariantViolation(
                check=finding["check"],
                severity=finding["severity"],
                message=finding["message"],
                artifact_id=artifact_id,
            )
            for finding in venue_template_findings(venue, tex_source, tex_path.parent)
        ]

    def _topic_target_venue(self, topic_id: int) -> str:
        conn = self._db.connect()
        try:
            try:
                row = conn.execute(
                    "SELECT target_venue FROM topics WHERE id = ?",
                    (topic_id,),
                ).fetchone()
            except Exception:  # noqa: BLE001 - legacy DBs may lack the column
                return ""
        finally:
            conn.close()
        if row is None:
            return ""
        return str(row["target_venue"] or "").strip()

    def check_figure_provider_fallback(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Block write gates when a figure-provider failure shipped no asset."""
        violations: list[InvariantViolation] = []
        if stage not in WRITE_GATE_STAGES:
            return violations

        found = self._latest_active_payload(topic_id, "figure_plan")
        if found is None:
            return violations
        artifact_id, payload = found
        for finding in _figure_provider_failure_findings(payload):
            violations.append(
                InvariantViolation(
                    check="figure_fallback_policy",
                    severity="high",
                    message=finding["message"],
                    artifact_id=artifact_id,
                    metadata=finding["metadata"],
                )
            )
        return violations

    def check_demo_scope_boundary(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Demo smoke artifacts must not satisfy a non-demo run's gate.

        A demo run stamps its outputs (readiness_scope=demo_pdf_smoke,
        evidence_boundary=demo_limited_seed_pool, ...). If a later formal run
        still has those artifacts active, its gates would otherwise evaluate
        to pass on smoke output — the leak that shipped a demo PDF as a
        formal deliverable.
        """
        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            run_row = conn.execute(
                "SELECT mode FROM orchestrator_runs WHERE topic_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (topic_id,),
            ).fetchone()
            run_mode = str(run_row["mode"] or "") if run_row is not None else ""
            if not run_mode or run_mode == "demo":
                return violations
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND stage = ? AND status = 'active'
                """,
                (topic_id, stage),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            marker = _payload_demo_scope_marker(payload)
            if marker:
                violations.append(
                    InvariantViolation(
                        check="demo_scope_boundary",
                        severity="high",
                        message=(
                            f"{row['artifact_type']} {row['id']} is a demo "
                            f"smoke artifact ({marker}) but the current run "
                            f"mode is {run_mode}: regenerate it under the "
                            "formal pipeline instead of reusing demo output"
                        ),
                        artifact_id=int(row["id"]),
                    )
                )
        return violations

    def check_figure_provider_pending_readiness(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Escalate pending figure fallbacks once a real provider is ready.

        A deterministic local figure plus an ILLUSTRATION_PENDING marker is the
        accepted degraded state only while no provider route is configured.
        With a ready provider, the marker means figure_generate was skipped,
        so the write gate must block instead of shipping the fallback.
        """
        violations: list[InvariantViolation] = []
        if stage not in WRITE_GATE_STAGES:
            return violations
        if not _illustration_generation_ready():
            return violations
        for artifact_type in (
            "figure_plan",
            "final_bundle",
            "final_bundle_quality_report",
        ):
            found = self._latest_active_payload(topic_id, artifact_type)
            if found is None:
                continue
            artifact_id, payload = found
            for finding in figure_pending_provider_ready_findings(
                payload, provider_ready=True
            ):
                violations.append(
                    InvariantViolation(
                        check="figure_provider_pending_with_ready_provider",
                        severity="high",
                        message=(
                            f"{artifact_type} {artifact_id} still carries a "
                            "ILLUSTRATION_PENDING fallback marker but an "
                            "illustration backend is configured: "
                            "generate the real figure via figure_generate "
                            "instead of shipping the deterministic fallback"
                        ),
                        artifact_id=artifact_id,
                        metadata=finding,
                    )
                )
        return violations

    def check_experiment_execution_evidence(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Require observed execution evidence at the experiment gate: a result
        without observed logs, or planned-only code that never ran, must not
        advance to write."""
        violations: list[InvariantViolation] = []
        if resolve_stage(stage) != "experiment":
            return violations

        result_found = self._latest_active_payload(topic_id, "experiment_result")
        if result_found is not None:
            artifact_id, payload = result_found
            result_status = str(payload.get("result_status") or "").lower()
            observed_logs = _as_list(payload.get("observed_experiment_logs"))
            observed = (
                bool(observed_logs)
                or "observed" in result_status
                or self._has_kept_experiment_runs(topic_id)
            )
            if not observed:
                violations.append(
                    InvariantViolation(
                        check="experiment_execution_evidence",
                        severity="high",
                        message=(
                            f"experiment_result {artifact_id} has no observed "
                            "experiment logs: run the experiments before advancing"
                        ),
                        artifact_id=artifact_id,
                    )
                )

            gate = evaluate_ablation_payload(payload)
            if gate is not None:
                if gate["verdict"] != "pass":
                    violations.append(
                        InvariantViolation(
                            check="ablation_coverage_and_variance",
                            severity="high",
                            message=(
                                f"experiment_result {artifact_id} has "
                                f"{gate['verdict']} ablation evidence: "
                                f"{', '.join(gate.get('blockers', [])) or 'variance unclear'}"
                            ),
                            artifact_id=artifact_id,
                            metadata=gate,
                        )
                    )

        code_found = self._latest_active_payload(topic_id, "experiment_code")
        if code_found is not None:
            artifact_id, payload = code_found
            status = str(payload.get("status") or "").lower()
            planned_only = "planned" in status or "not_executed" in status
            if planned_only and not self._has_kept_experiment_runs(topic_id):
                violations.append(
                    InvariantViolation(
                        check="experiment_execution_evidence",
                        severity="high",
                        message=(
                            f"experiment_code {artifact_id} records status "
                            f"'{payload.get('status')}' with no execution: "
                            "execute the experiment code before advancing"
                        ),
                        artifact_id=artifact_id,
                    )
                )
        return violations

    def check_artifact_schemas(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Validate that artifact payloads match their type schemas.

        Scoped to artifacts whose stage resolves to the queried V2 stage —
        otherwise one bad artifact would surface a violation on every
        stage node in the UI.
        """
        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json, title, stage
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                if row["artifact_type"] in NON_BLOCKING_STALE_ARTIFACT_TYPES:
                    continue
                if resolve_stage(row["stage"] or "") != stage:
                    continue
                artifact_type = row["artifact_type"]
                schema = ARTIFACT_SCHEMAS.get(artifact_type)
                if schema is None:
                    continue  # No schema defined = no validation

                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    violations.append(
                        InvariantViolation(
                            check="artifact_schema",
                            severity="critical",
                            message=f"Artifact {row['id']} ({artifact_type}) has invalid JSON payload",
                            artifact_id=row["id"],
                        )
                    )
                    continue

                raw_json = row["payload_json"] or ""
                for field in schema.get("required_fields", []):
                    if not _has_required_field(payload, field, schema, raw_json):
                        violations.append(
                            InvariantViolation(
                                check="artifact_schema",
                                severity="medium",
                                message=(
                                    f"Artifact {row['id']} ({artifact_type}) missing "
                                    f"required field '{field}'"
                                ),
                                artifact_id=row["id"],
                            )
                        )
        finally:
            conn.close()

        return violations

    def check_no_stale_artifacts(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Verify no stale artifacts are being counted for gate evaluation.

        Scoped to the queried V2 stage so legacy stale artifacts only
        surface on their own stage node, not every node in the timeline.
        """
        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, stale, stale_reason, stage
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active' AND stale = 1
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                if row["artifact_type"] in NON_BLOCKING_STALE_ARTIFACT_TYPES:
                    continue
                if resolve_stage(row["stage"] or "") != stage:
                    continue
                violations.append(
                    InvariantViolation(
                        check="stale_artifact",
                        severity="high",
                        message=(
                            f"Artifact {row['id']} ({row['artifact_type']}) is stale: "
                            f"{row['stale_reason'] or 'no reason given'}"
                        ),
                        artifact_id=row["id"],
                        metadata={
                            "artifact_type": row["artifact_type"],
                            "stage": row["stage"] or "",
                            "stale_reason": row["stale_reason"] or "",
                        },
                    )
                )
        finally:
            conn.close()

        return violations

    def check_provenance_linkage(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Check that critical artifacts have provenance records.

        Accepts either of two evidence forms: a linked
        `provenance_record_id`, OR a payload that carries paper-level
        sourcing (e.g. `paper_id`/`paper_ids`/`source_paper_ids`).
        Legacy artifacts produced before provenance linkage was wired
        often embed paper IDs directly; flagging them as missing
        provenance is a false positive.
        """
        violations: list[InvariantViolation] = []
        critical_types = frozenset(
            {
                "evidence_pack",
                "direction_proposal",
                "experiment_result",
                "draft_pack",
                "adversarial_resolution",
            }
        )

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, provenance_record_id, stage, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type IN ({})
                """.format(",".join("?" * len(critical_types))),
                (topic_id, *critical_types),
            ).fetchall()

            for row in rows:
                if resolve_stage(row["stage"] or "") != stage:
                    continue
                if row["provenance_record_id"]:
                    continue
                if _payload_has_paper_sourcing(row["payload_json"] or ""):
                    continue
                violations.append(
                    InvariantViolation(
                        check="provenance_linkage",
                        severity="medium",
                        message=(
                            f"Critical artifact {row['id']} ({row['artifact_type']}) "
                            "has no provenance record"
                        ),
                        artifact_id=row["id"],
                    )
                )
        finally:
            conn.close()

        return violations

    def check_artifact_trace_linkage(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Require derived artifacts to preserve an artifact-level source trace.

        A valid trace is either a persisted dependency edge in
        ``artifact_dependencies`` or a payload reference to another artifact in
        the same topic. Paper IDs and provenance records answer different
        questions; this check ensures object-level artifact lineage is replayable.
        """
        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, stage, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type IN ({})
                """.format(",".join("?" * len(ARTIFACT_TRACE_REQUIRED_TYPES))),
                (topic_id, *ARTIFACT_TRACE_REQUIRED_TYPES),
            ).fetchall()

            for row in rows:
                if resolve_stage(row["stage"] or "") != stage:
                    continue

                source_placeholders = ",".join("?" * len(ARTIFACT_TRACE_SOURCE_TYPES))
                dependency_count = conn.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM artifact_dependencies dep
                    JOIN project_artifacts src ON src.id = dep.from_artifact_id
                    WHERE dep.to_artifact_id = ?
                      AND src.topic_id = ?
                      AND src.status = 'active'
                      AND COALESCE(src.stale, 0) = 0
                      AND src.artifact_type IN ({source_placeholders})
                    """,
                    (row["id"], topic_id, *sorted(ARTIFACT_TRACE_SOURCE_TYPES)),
                ).fetchone()["count"]
                if dependency_count:
                    continue

                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    payload = {}

                ref_ids = sorted(set(_iter_payload_artifact_ref_ids(payload)))
                valid_ref_ids = self._valid_same_topic_artifact_ref_ids(
                    conn, topic_id, row["id"], ref_ids
                )
                invalid_ref_ids = sorted(set(ref_ids) - set(valid_ref_ids))
                if valid_ref_ids and not invalid_ref_ids:
                    continue

                violations.append(
                    InvariantViolation(
                        check="artifact_trace_linkage",
                        severity="high",
                        message=(
                            f"Artifact {row['id']} ({row['artifact_type']}) has no "
                            "replayable source artifact trace"
                        ),
                        artifact_id=row["id"],
                        metadata={
                            "artifact_type": row["artifact_type"],
                            "stage": row["stage"] or "",
                            "payload_artifact_ref_ids": ref_ids,
                            "valid_payload_artifact_ref_ids": valid_ref_ids,
                            "invalid_payload_artifact_ref_ids": invalid_ref_ids,
                            "dependency_count": int(dependency_count or 0),
                        },
                    )
                )
        finally:
            conn.close()

        return violations

    @staticmethod
    def _valid_same_topic_artifact_ref_ids(
        conn: Any,
        topic_id: int,
        artifact_id: int,
        ref_ids: list[int],
    ) -> list[int]:
        if not ref_ids:
            return []

        placeholders = ",".join("?" * len(ref_ids))
        source_placeholders = ",".join("?" * len(ARTIFACT_TRACE_SOURCE_TYPES))
        rows = conn.execute(
            f"""
            SELECT id
            FROM project_artifacts
            WHERE topic_id = ?
              AND id != ?
              AND status = 'active'
              AND COALESCE(stale, 0) = 0
              AND artifact_type IN ({source_placeholders})
              AND id IN ({placeholders})
            ORDER BY id
            """,
            (
                topic_id,
                artifact_id,
                *sorted(ARTIFACT_TRACE_SOURCE_TYPES),
                *ref_ids,
            ),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def check_baseline_governance(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Validate baseline coverage and novelty governance before promotion."""
        resolved_stage = resolve_stage(stage)
        if resolved_stage not in BASELINE_GOVERNANCE_STAGES:
            return []

        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            proposal_row = conn.execute(
                """
                SELECT id, payload_json
                FROM project_artifacts
                WHERE topic_id = ?
                  AND status = 'active'
                  AND artifact_type = 'direction_proposal'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if proposal_row is None:
                return violations

            try:
                proposal_payload = json.loads(proposal_row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                proposal_payload = {}
            if not isinstance(proposal_payload, dict):
                proposal_payload = {}
            claims_novelty = _direction_claims_strong_novelty(proposal_payload)

            baseline_row = conn.execute(
                """
                SELECT id, artifact_type, payload_json, stale, stale_reason, stage
                FROM project_artifacts
                WHERE topic_id = ?
                  AND status = 'active'
                  AND artifact_type IN ({})
                ORDER BY
                  CASE artifact_type
                    WHEN 'baseline_matrix' THEN 0
                    WHEN 'baseline_governance_report' THEN 1
                    ELSE 2
                  END,
                  id DESC
                LIMIT 1
                """.format(",".join("?" * len(BASELINE_GOVERNANCE_ARTIFACT_TYPES))),
                (topic_id, *BASELINE_GOVERNANCE_ARTIFACT_TYPES),
            ).fetchone()
            if baseline_row is None:
                if _analyze_gate_would_need_expansion(conn, topic_id, stage):
                    return violations
                message = (
                    "Direction proposal is missing a baseline_matrix/baseline "
                    "governance artifact"
                )
                if claims_novelty:
                    message = (
                        "Direction proposal makes a novelty claim without "
                        "a baseline_matrix/baseline governance artifact"
                    )
                violations.append(
                    InvariantViolation(
                        check="baseline_governance_missing",
                        severity="high",
                        message=message,
                        artifact_id=proposal_row["id"],
                        metadata={
                            "direction_proposal_artifact_id": proposal_row["id"],
                            "required_artifact_types": sorted(
                                BASELINE_GOVERNANCE_ARTIFACT_TYPES
                            ),
                            "claims_novelty": claims_novelty,
                        },
                    )
                )
                return violations

            try:
                baseline_payload = json.loads(baseline_row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                baseline_payload = {}
            if not isinstance(baseline_payload, dict):
                baseline_payload = {}

            records = _baseline_matrix_records(baseline_payload)
            if not _baseline_governance_is_linked_to_proposal(
                conn,
                proposal_id=int(proposal_row["id"]),
                baseline_id=int(baseline_row["id"]),
                proposal_payload=proposal_payload,
                baseline_payload=baseline_payload,
            ):
                violations.append(
                    InvariantViolation(
                        check="baseline_governance_unlinked",
                        severity="high",
                        message=(
                            f"Baseline governance artifact {baseline_row['id']} "
                            f"precedes direction proposal {proposal_row['id']} "
                            "without an artifact dependency or payload trace"
                        ),
                        artifact_id=baseline_row["id"],
                        metadata={
                            "baseline_artifact_id": baseline_row["id"],
                            "direction_proposal_artifact_id": proposal_row["id"],
                        },
                    )
                )

            if bool(baseline_row["stale"]):
                violations.append(
                    InvariantViolation(
                        check="stale_baseline_governance",
                        severity="high",
                        message=(
                            f"Baseline governance artifact {baseline_row['id']} "
                            "is stale and must be recomputed before proposal review"
                        ),
                        artifact_id=baseline_row["id"],
                        metadata={
                            "baseline_artifact_id": baseline_row["id"],
                            "artifact_type": baseline_row["artifact_type"],
                            "stage": baseline_row["stage"] or "",
                            "stale_reason": baseline_row["stale_reason"] or "",
                        },
                    )
                )

            if claims_novelty and not records:
                violations.append(
                    InvariantViolation(
                        check="baseline_governance_missing",
                        severity="high",
                        message=(
                            f"Baseline governance artifact {baseline_row['id']} "
                            "has no baseline records for a novelty-claiming proposal"
                        ),
                        artifact_id=baseline_row["id"],
                        metadata={
                            "direction_proposal_artifact_id": proposal_row["id"],
                            "baseline_artifact_id": baseline_row["id"],
                        },
                    )
                )

            coverage = baseline_payload.get("coverage")
            if isinstance(coverage, dict):
                required = set(_normalized_strings(coverage.get("required_families")))
                covered = set(_normalized_strings(coverage.get("covered_families")))
                if required and not covered:
                    covered = {
                        family
                        for family in (_baseline_family(record) for record in records)
                        if family
                    }
                missing = sorted(required - covered)
                if missing:
                    violations.append(
                        InvariantViolation(
                            check="baseline_coverage_incomplete",
                            severity="high",
                            message=(
                                "Baseline matrix is missing required method "
                                f"family coverage: {', '.join(missing)}"
                            ),
                            artifact_id=baseline_row["id"],
                            metadata={
                                "baseline_artifact_id": baseline_row["id"],
                                "required_families": sorted(required),
                                "covered_families": sorted(covered),
                                "missing_families": missing,
                            },
                        )
                    )

                required_facets = set(
                    _normalized_strings(coverage.get("required_facets"))
                )
                covered_facets = set(
                    _normalized_strings(coverage.get("covered_facets"))
                )
                if required_facets and not covered_facets:
                    covered_facets = {
                        facet
                        for record in records
                        for facet in _baseline_facets(record)
                        if facet
                    }
                missing_facets = sorted(required_facets - covered_facets)
                if missing_facets:
                    violations.append(
                        InvariantViolation(
                            check="baseline_coverage_incomplete",
                            severity="high",
                            message=(
                                "Baseline matrix is missing required survey "
                                f"facet coverage: {', '.join(missing_facets)}"
                            ),
                            artifact_id=baseline_row["id"],
                            metadata={
                                "baseline_artifact_id": baseline_row["id"],
                                "required_facets": sorted(required_facets),
                                "covered_facets": sorted(covered_facets),
                                "missing_facets": missing_facets,
                            },
                        )
                    )

            stale_ids = [
                _baseline_id(record, index)
                for index, record in enumerate(records)
                if bool(record.get("stale"))
                or str(record.get("reliability_state") or "").lower() == "stale"
                or str(record.get("status") or "").lower() == "stale"
            ]
            if stale_ids:
                violations.append(
                    InvariantViolation(
                        check="stale_baseline_record",
                        severity="high",
                        message=(
                            "Baseline matrix contains stale baseline records: "
                            f"{', '.join(stale_ids)}"
                        ),
                        artifact_id=baseline_row["id"],
                        metadata={
                            "baseline_artifact_id": baseline_row["id"],
                            "stale_baseline_ids": stale_ids,
                        },
                    )
                )

            novelty_verdict = _baseline_novelty_verdict(baseline_payload)
            close_prior_ids = _baseline_close_prior_ids(baseline_payload, records)
            if claims_novelty and (
                close_prior_ids
                or novelty_verdict
                in {"too_similar", "not_novel", "false_novelty", "duplicate"}
            ):
                violations.append(
                    InvariantViolation(
                        check="false_novelty_claim",
                        severity="high",
                        message=(
                            "Direction proposal claims novelty despite close prior "
                            "baseline evidence"
                        ),
                        artifact_id=proposal_row["id"],
                        metadata={
                            "direction_proposal_artifact_id": proposal_row["id"],
                            "baseline_artifact_id": baseline_row["id"],
                            "novelty_verdict": novelty_verdict,
                            "close_prior_baseline_ids": close_prior_ids,
                        },
                    )
                )
        finally:
            conn.close()

        return violations

    def check_citation_sentence_evidence_coverage(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """v2 Step 3.3: every sentence with a citation marker in a draft
        section MUST have at least one matching EvidenceMapping entry in
        the artifact's ``evidence_map`` sidecar.

        This replaces v1's imprecise "70% non-boilerplate coverage" metric
        with a deterministic rule: citation presence in prose is testable
        by regex, and EvidenceMapping is a structured sidecar list.
        """
        violations: list[InvariantViolation] = []
        if stage not in ("write", "draft_preparation", "formal_review"):
            return violations

        import re

        cite_rx = re.compile(r"\\cite[pt]?\{|\[\d+\]|\(\w+,\s*\d{4}\)")

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type = 'draft_pack'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue

                evidence_map = payload.get("evidence_map") or []
                covered_indices_by_section: dict[str, set[int]] = {}
                if isinstance(evidence_map, list):
                    for em in evidence_map:
                        if not isinstance(em, dict):
                            continue
                        sec = str(em.get("section", "")).strip() or "_"
                        idx = em.get("sentence_index")
                        if isinstance(idx, int):
                            covered_indices_by_section.setdefault(sec, set()).add(idx)

                sections = payload.get("sections", {})
                for section_name, content in sections.items():
                    if not isinstance(content, str):
                        continue
                    if section_name in ("abstract", "conclusion", "acknowledgments"):
                        continue
                    # Lightweight sentence split matching _extract_evidence_map.
                    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\\\[\(])", content)
                    covered = covered_indices_by_section.get(section_name)
                    # Fallback: maybe the writer emitted evidence_map without
                    # section tags — treat any entry as covering any index.
                    if covered is None:
                        covered = covered_indices_by_section.get("_", set())
                    missing: list[int] = []
                    for idx, sent in enumerate(parts):
                        if cite_rx.search(sent) and idx not in covered:
                            missing.append(idx)
                    if missing:
                        violations.append(
                            InvariantViolation(
                                check="citation_sentence_evidence_coverage",
                                severity="medium",
                                message=(
                                    f"Section '{section_name}' in draft_pack has "
                                    f"{len(missing)} citation-marked sentence(s) "
                                    f"without EvidenceMapping entries "
                                    f"(sentence indices: {missing[:5]})"
                                ),
                                artifact_id=row["id"],
                            )
                        )
        finally:
            conn.close()

        return violations

    def check_final_publication_boundaries(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        violations: list[InvariantViolation] = []
        if stage not in WRITE_GATE_STAGES:
            return violations

        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT id, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'final_bundle'
                      AND status = 'active'
                ORDER BY version DESC, id DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return violations

        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            return violations
        if not isinstance(payload, dict):
            return violations

        evidence = payload.get("reference_pool_evidence")
        finality_status = str(payload.get("finality_status") or "")
        if not isinstance(evidence, dict) and not finality_status:
            return violations
        if isinstance(evidence, dict):
            reference_passed = evidence.get("passed") is True
            usable = int(evidence.get("usable_screened_paper_count") or 0)
            minimum = int(
                evidence.get("minimum_required") or MIN_FINAL_USABLE_SCREENED_PAPERS
            )
        else:
            reference_passed = False
            usable = 0
            minimum = MIN_FINAL_USABLE_SCREENED_PAPERS

        interim_ok = _final_bundle_has_interim_boundary(payload)
        if finality_status == "final_ready" and not reference_passed:
            violations.append(
                InvariantViolation(
                    check="final_reference_pool_gate",
                    severity="high",
                    message=(
                        "final_bundle claims final_ready but has "
                        f"{usable} usable screened paper(s), below the threshold "
                        f"of {minimum}"
                    ),
                    artifact_id=int(row["id"]),
                    metadata={
                        "finality_status": finality_status,
                        "usable_screened_paper_count": usable,
                        "minimum_required": minimum,
                    },
                )
            )
        if not reference_passed and finality_status not in {"interim_ready", "blocked"}:
            violations.append(
                InvariantViolation(
                    check="final_reference_pool_gate",
                    severity="high",
                    message=(
                        "final_bundle is below the final reference-pool threshold "
                        "but is not explicitly marked interim"
                    ),
                    artifact_id=int(row["id"]),
                    metadata={"finality_status": finality_status or "unset"},
                )
            )
        if finality_status == "interim_ready" and not interim_ok:
            violations.append(
                InvariantViolation(
                    check="interim_boundary_gate",
                    severity="high",
                    message="interim final_bundle is missing required boundary metadata",
                    artifact_id=int(row["id"]),
                    metadata={"finality_status": finality_status},
                )
            )

        for finding in _illustration_provenance_findings(payload):
            violations.append(
                InvariantViolation(
                    check="illustration_provenance_gate",
                    severity="high",
                    message=finding["message"],
                    artifact_id=int(row["id"]),
                    metadata=finding["metadata"],
                )
            )
        return violations

    def check_unsupported_evidence_links(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Block write-stage progression when evidence links are unsupported.

        Evidence links may live in an ``evidence_links`` artifact or inside an
        ``evidence_pack``. The check intentionally ignores artifact stage
        because analyze-stage evidence is what write-stage drafting consumes.
        """
        violations: list[InvariantViolation] = []
        if stage not in WRITE_GATE_STAGES:
            return violations

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type IN ('evidence_links', 'evidence_pack')
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue

                for link in _iter_evidence_link_records(payload):
                    status = str(link.get("support_status") or "").lower()
                    if status not in BLOCKING_EVIDENCE_SUPPORT_STATUSES:
                        continue
                    claim_id = str(link.get("claim_id") or "unknown_claim")
                    source_id = str(link.get("source_id") or "unknown_source")
                    link_key = "|".join(
                        (
                            claim_id,
                            str(link.get("source_type") or ""),
                            source_id,
                            status,
                        )
                    )
                    violations.append(
                        InvariantViolation(
                            check="unsupported_evidence_link",
                            severity="high",
                            message=(
                                f"Evidence link for claim '{claim_id}' has "
                                f"blocking support_status='{status}' from "
                                f"source '{source_id}'"
                            ),
                            artifact_id=row["id"],
                            metadata={
                                "artifact_type": row["artifact_type"],
                                "claim_id": claim_id,
                                "source_id": source_id,
                                "source_type": str(link.get("source_type") or ""),
                                "support_status": status,
                                "link_key": link_key,
                                "evidence_span": link.get("evidence_span") or {},
                                "citation_candidate": link.get("citation_candidate")
                                or {},
                            },
                        )
                    )
        finally:
            conn.close()

        return violations

    def check_section_citations(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Check that draft sections contain citation markers."""
        violations: list[InvariantViolation] = []
        if stage not in ("write", "draft_preparation", "formal_review"):
            return violations

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type = 'draft_pack'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue

                sections = payload.get("sections", {})
                for section_name, content in sections.items():
                    if section_name in ("abstract", "conclusion", "acknowledgments"):
                        continue  # These sections may not need citations
                    if isinstance(content, str) and len(content) > 200:
                        # Check for citation markers: \cite{}, [N], (Author, Year)
                        import re

                        has_cite = bool(
                            re.search(
                                r"\\cite\{|[\[\(]\d+[\]\)]|\(\w+,\s*\d{4}\)", content
                            )
                        )
                        if not has_cite:
                            violations.append(
                                InvariantViolation(
                                    check="section_citations",
                                    severity="medium",
                                    message=(
                                        f"Section '{section_name}' in draft_pack "
                                        f"({len(content)} chars) has no citation markers"
                                    ),
                                    artifact_id=row["id"],
                                )
                            )
        finally:
            conn.close()

        return violations


class InvariantViolation:
    """A single invariant check failure."""

    __slots__ = ("check", "severity", "message", "artifact_id", "metadata")

    def __init__(
        self,
        check: str,
        severity: str,
        message: str,
        artifact_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.check = check
        self.severity = severity  # critical|high|medium|low
        self.message = message
        self.artifact_id = artifact_id
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return f"InvariantViolation({self.severity}: {self.message})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "artifact_id": self.artifact_id,
            "metadata": self.metadata,
        }


def is_blocking(violation: InvariantViolation) -> bool:
    """Check if a violation should block gate progression."""
    return violation.severity in ("critical", "high")
