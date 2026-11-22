"""Growing figure-knowledge tree (WF06).

The five UF01 roles stay a frozen coarse layer. Finer *forms* are induced
from figure captions in venue packages and hang under a role. Captions that
do not match stay ``unclassified``; they are not forced into a role.
New domains attach new forms (or later a domain facet) without rewriting
the role layer.

Caption-only. No pixels, no trained clusterer, no public-tree corpus dump.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .figure_package_contracts import FIGURE_ROLES, FigureContractError

V0_SNAPSHOT_PATH = Path(__file__).with_name("figure_knowledge_v0.json")

SCHEMA_FIGURE_KNOWLEDGE = "rh.figure_knowledge.v0"
UNCLASSIFIED_FORM = "unclassified"
STUB_FORM = "extractor_stub"

_STUB_CAPTION = re.compile(
    r"^extracted document (graphic|figure)(/chart asset|/diagram)?\s*$",
    re.I,
)

# Precision over recall. Unmatched captions stay unclassified.
_FORMS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "study_or_experiment_design",
        "prisma_consort",
        re.compile(r"\b(prisma|consort|stard)\b", re.I),
    ),
    (
        "study_or_experiment_design",
        "cohort_flow",
        re.compile(
            r"\b(patient (selection|flow)|enrollment|inclusion and exclusion|study flow)\b",
            re.I,
        ),
    ),
    (
        "study_or_experiment_design",
        "trial_design",
        re.compile(
            r"\b(randomized|cross-over trial|trial design|study design)\b", re.I
        ),
    ),
    (
        "method_architecture",
        "pipeline_overview",
        re.compile(
            r"\b(overview of (the )?(proposed |method|framework|pipeline|model)|overall (framework|pipeline|architecture|workflow)|research framework|methodological framework)\b",
            re.I,
        ),
    ),
    (
        "method_architecture",
        "model_architecture",
        re.compile(
            r"\b(architecture of|network architecture|model architecture)\b", re.I
        ),
    ),
    ("method_architecture", "workflow", re.compile(r"\bworkflow\b", re.I)),
    (
        "method_architecture",
        "causal_dag",
        re.compile(
            r"\b(causal (loop|graph|diagram|model)|directed acyclic|\bdag\b)\b", re.I
        ),
    ),
    (
        "method_architecture",
        "schema_er",
        re.compile(r"\b(database schema|property graph schema|er diagram)\b", re.I),
    ),
    (
        "quantitative_comparison",
        "roc_pr_curve",
        re.compile(r"\b(roc|auroc|auc-roc|auprc|pr curve|precision-recall)\b", re.I),
    ),
    (
        "quantitative_comparison",
        "kaplan_meier",
        re.compile(r"\b(kaplan[-\s]?meier|\bkm curve|survival curve)\b", re.I),
    ),
    ("quantitative_comparison", "forest_plot", re.compile(r"\bforest plot\b", re.I)),
    (
        "quantitative_comparison",
        "decision_curve",
        re.compile(r"\b(decision[-\s]?curve|\bdca\b|net benefit)\b", re.I),
    ),
    ("quantitative_comparison", "volcano", re.compile(r"\bvolcano\b", re.I)),
    (
        "quantitative_comparison",
        "heatmap",
        re.compile(r"\bheat[\s-]?map\b|\bconfusion matrix\b", re.I),
    ),
    (
        "quantitative_comparison",
        "bar_compare",
        re.compile(
            r"\b(comparison of|compares the|performance (of|comparison)|benchmark)\b",
            re.I,
        ),
    ),
    (
        "quantitative_comparison",
        "line_metric",
        re.compile(r"\b(as a function of|versus the|over time|with different)\b", re.I),
    ),
    ("ablation_or_sensitivity", "ablation", re.compile(r"\bablat", re.I)),
    (
        "ablation_or_sensitivity",
        "sensitivity",
        re.compile(r"\bsensitiv(ity|e analysis)\b|\bhyper[- ]?param", re.I),
    ),
    (
        "ablation_or_sensitivity",
        "calibration_plot",
        re.compile(r"\bcalibrat(ion|ed plot)\b", re.I),
    ),
    (
        "qualitative_cases",
        "example_case",
        re.compile(
            r"\b(example of|case study|representative case|qualitative)\b", re.I
        ),
    ),
    ("qualitative_cases", "umap_tsne", re.compile(r"\b(umap|t-sne|tsne)\b", re.I)),
    (
        "qualitative_cases",
        "attention_map",
        re.compile(r"\b(grad-?cam|saliency|attention map)\b", re.I),
    ),
    (
        "qualitative_cases",
        "error_case",
        re.compile(r"\b(failure case|error case|misclassif)\b", re.I),
    ),
    (
        "qualitative_cases",
        "ui_prototype",
        re.compile(r"\b(prototype|interface|screenshot)\b", re.I),
    ),
    (
        "qualitative_cases",
        "prompt_artifact",
        re.compile(r"\b(prompt|instruction)s?\b", re.I),
    ),
)

FORM_CATALOG: tuple[dict[str, str], ...] = tuple(
    {"form_id": form_id, "parent_role": role} for role, form_id, _ in _FORMS
)
FORM_IDS: tuple[str, ...] = tuple(item["form_id"] for item in FORM_CATALOG)
_FORM_PARENT: dict[str, str] = {
    item["form_id"]: item["parent_role"] for item in FORM_CATALOG
}


def is_extractor_stub(caption: str) -> bool:
    return bool(_STUB_CAPTION.match((caption or "").strip()))


def classify_caption(caption: str) -> dict[str, Any]:
    """Map one caption onto zero or more forms. Never invent a role."""
    text = str(caption or "").strip()
    if not text:
        return {"stub": False, "forms": [], "unclassified": True}
    if is_extractor_stub(text):
        return {"stub": True, "forms": [STUB_FORM], "unclassified": False}
    forms = [form_id for _role, form_id, pattern in _FORMS if pattern.search(text)]
    return {"stub": False, "forms": forms, "unclassified": not forms}


def parent_role(form_id: str) -> str | None:
    if form_id in (UNCLASSIFIED_FORM, STUB_FORM):
        return None
    return _FORM_PARENT.get(form_id)


def empty_knowledge(
    *, sources: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_FIGURE_KNOWLEDGE,
        "role_layer": list(FIGURE_ROLES),
        "form_layer": [dict(item) for item in FORM_CATALOG],
        "sources": [dict(item) for item in (sources or ())],
        "observations": {
            "n_captions": 0,
            "n_stub": 0,
            "n_real": 0,
            "n_unclassified": 0,
            "n_multi_form": 0,
            "by_form": {},
            "by_role": {role: 0 for role in FIGURE_ROLES},
            "by_venue_family": {},
        },
    }


def _bump(bucket: dict[str, Any], key: str, venue: str) -> None:
    row = bucket.setdefault(key, {"n": 0, "by_venue_family": {}})
    row["n"] += 1
    venues = row["by_venue_family"]
    venues[venue] = int(venues.get(venue) or 0) + 1


def induce_from_captions(
    records: Iterable[Mapping[str, Any]],
    *,
    sources: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grow observation counts from caption records. No pixels."""
    tree = empty_knowledge(sources=sources)
    obs = tree["observations"]
    by_form: dict[str, Any] = {}
    by_role: Counter[str] = Counter()
    by_venue: Counter[str] = Counter()
    for record in records:
        caption = str(record.get("caption") or "")
        venue = str(record.get("venue_family") or "unknown").strip() or "unknown"
        hit = classify_caption(caption)
        obs["n_captions"] += 1
        by_venue[venue] += 1
        if hit["stub"]:
            obs["n_stub"] += 1
            _bump(by_form, STUB_FORM, venue)
            continue
        obs["n_real"] += 1
        forms = list(hit["forms"])
        if not forms:
            obs["n_unclassified"] += 1
            _bump(by_form, UNCLASSIFIED_FORM, venue)
            continue
        if len(forms) > 1:
            obs["n_multi_form"] += 1
        for form_id in forms:
            _bump(by_form, form_id, venue)
            role = _FORM_PARENT[form_id]
            by_role[role] += 1
    obs["by_form"] = dict(sorted(by_form.items()))
    obs["by_role"] = {role: int(by_role.get(role) or 0) for role in FIGURE_ROLES}
    obs["by_venue_family"] = dict(by_venue)
    return tree


def attach_form(
    tree: Mapping[str, Any], form_id: str, parent_role_id: str
) -> dict[str, Any]:
    """Add a child form under an existing role. Roles stay frozen."""
    if parent_role_id not in FIGURE_ROLES:
        raise FigureContractError(f"parent_role must be one of {FIGURE_ROLES!r}")
    fid = str(form_id or "").strip()
    if not fid or fid in {UNCLASSIFIED_FORM, STUB_FORM}:
        raise FigureContractError("form_id is required")
    out = validate_figure_knowledge(tree)
    existing = {str(item.get("form_id")) for item in out["form_layer"]}
    if fid in existing:
        raise FigureContractError(f"form_id already present: {fid}")
    out["form_layer"] = [
        *out["form_layer"],
        {"form_id": fid, "parent_role": parent_role_id},
    ]
    return out


def validate_figure_knowledge(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FigureContractError("figure_knowledge must be an object")
    obj = dict(payload)
    version = str(obj.get("schema_version") or "").strip()
    if version != SCHEMA_FIGURE_KNOWLEDGE:
        raise FigureContractError(
            f"figure_knowledge schema_version must be {SCHEMA_FIGURE_KNOWLEDGE}"
        )
    roles = obj.get("role_layer")
    if list(roles or []) != list(FIGURE_ROLES):
        raise FigureContractError("role_layer is frozen to UF01 FIGURE_ROLES")
    forms = obj.get("form_layer")
    if not isinstance(forms, list) or not forms:
        raise FigureContractError("form_layer must be a non-empty list")
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in forms:
        if not isinstance(item, Mapping):
            raise FigureContractError("form_layer entries must be objects")
        fid = str(item.get("form_id") or "").strip()
        parent = str(item.get("parent_role") or "").strip()
        if not fid:
            raise FigureContractError("form_id is required")
        if fid in seen:
            raise FigureContractError(f"duplicate form_id: {fid}")
        if parent not in FIGURE_ROLES:
            raise FigureContractError(f"parent_role must be one of {FIGURE_ROLES!r}")
        seen.add(fid)
        cleaned.append({"form_id": fid, "parent_role": parent})
    obs = obj.get("observations")
    if not isinstance(obs, Mapping):
        raise FigureContractError("observations must be an object")
    out = dict(obj)
    out["schema_version"] = version
    out["role_layer"] = list(FIGURE_ROLES)
    out["form_layer"] = cleaned
    out["observations"] = dict(obs)
    if "sources" in obj and obj["sources"] is not None:
        if not isinstance(obj["sources"], list):
            raise FigureContractError("sources must be a list")
        out["sources"] = [
            dict(item) if isinstance(item, Mapping) else item for item in obj["sources"]
        ]
    return out


def load_v0_snapshot(path: Path | None = None) -> dict[str, Any]:
    """Load the checked-in aggregate snapshot. Counts only; no captions."""
    target = Path(path) if path is not None else V0_SNAPSHOT_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    return validate_figure_knowledge(payload)


_CHART_TO_FORM: dict[str, str] = {
    "roc": "roc_pr_curve",
    "pr_curve": "roc_pr_curve",
    "precision_recall": "roc_pr_curve",
    "km_survival": "kaplan_meier",
    "kaplan_meier": "kaplan_meier",
    "forest": "forest_plot",
    "forest_plot": "forest_plot",
    "dca": "decision_curve",
    "decision_curve": "decision_curve",
    "volcano": "volcano",
    "heatmap": "heatmap",
    "confusion_matrix": "heatmap",
    "grouped_bar": "bar_compare",
    "bar": "bar_compare",
    "line": "line_metric",
    "ablation_heatmap": "ablation",
    "umap": "umap_tsne",
    "tsne": "umap_tsne",
}


def venue_family_from_venue(venue: str, *, style_profile: str = "") -> str:
    text = f"{venue} {style_profile}".lower()
    if "npj" in text or "nature" in text or "biomed" in text:
        return "npj"
    if (
        "information processing" in text
        or "ip&m" in text
        or re.search(r"\bipm\b", text)
    ):
        return "ipm"
    return "unknown"


def _figure_blob(figure: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "caption", "caption_skeleton", "purpose", "claim"):
        value = figure.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return " ".join(parts)


def _figure_charts(figure: Mapping[str, Any]) -> list[str]:
    charts: list[str] = []
    if figure.get("chart"):
        charts.append(str(figure["chart"]).lower())
    panels = figure.get("panels")
    if isinstance(panels, list):
        for panel in panels:
            if isinstance(panel, Mapping) and panel.get("chart"):
                charts.append(str(panel["chart"]).lower())
    return charts


def annotate_figure(
    figure: Mapping[str, Any],
    *,
    venue_family: str = "unknown",
) -> dict[str, Any]:
    """Stamp form_id on one planned figure. Unmatched stays unclassified."""
    out = dict(figure)
    hit = classify_caption(_figure_blob(out))
    forms = list(hit["forms"])
    if not forms:
        for chart in _figure_charts(out):
            mapped = _CHART_TO_FORM.get(chart)
            if mapped and mapped not in forms:
                forms.append(mapped)
    form_id = forms[0] if forms else UNCLASSIFIED_FORM
    out["form_id"] = form_id
    out["form_ids"] = forms or [UNCLASSIFIED_FORM]
    parent = parent_role(form_id)
    if parent:
        out["form_parent_role"] = parent
    out["form_venue_family"] = venue_family
    return out


def form_priors(tree: Mapping[str, Any], venue_family: str) -> dict[str, float]:
    """Venue share of real captions per form. Stubs excluded from the denominator."""
    obs = tree.get("observations") if isinstance(tree, Mapping) else None
    if not isinstance(obs, Mapping):
        return {}
    by_form = obs.get("by_form") if isinstance(obs.get("by_form"), Mapping) else {}
    venue_n = int((obs.get("by_venue_family") or {}).get(venue_family) or 0)
    stub_n = int(
        (
            ((by_form.get(STUB_FORM) or {}).get("by_venue_family") or {}).get(
                venue_family
            )
            or 0
        )
    )
    denom = max(venue_n - stub_n, 1)
    out: dict[str, float] = {}
    for form_id, row in by_form.items():
        if form_id == STUB_FORM or not isinstance(row, Mapping):
            continue
        n = int((row.get("by_venue_family") or {}).get(venue_family) or 0)
        out[str(form_id)] = n / denom
    return out


def knowledge_overlay(
    tree: Mapping[str, Any],
    venue_family: str,
) -> dict[str, Any]:
    priors = form_priors(tree, venue_family)
    unclassified = float(priors.get(UNCLASSIFIED_FORM) or 0.0)
    return {
        "schema_version": SCHEMA_FIGURE_KNOWLEDGE,
        "venue_family": venue_family,
        "form_priors": priors,
        "unclassified_rate": unclassified,
    }


def stamp_suite_knowledge(
    spec: Mapping[str, Any],
    *,
    tree: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Annotate planned figures and hang venue form priors on the suite spec."""
    out = dict(spec)
    snapshot = tree if tree is not None else load_v0_snapshot()
    family = venue_family_from_venue(
        str(out.get("target_venue") or ""),
        style_profile=str(out.get("style_profile") or ""),
    )
    overlay = knowledge_overlay(snapshot, family)
    inner = out
    figures_owner = out
    for wrapper in ("plan", "suite", "figure_suite"):
        nested = inner.get(wrapper) if isinstance(inner.get(wrapper), dict) else None
        if isinstance(nested, dict) and "figures" in nested:
            figures_owner = nested
            break
    figures = figures_owner.get("figures")
    if isinstance(figures, list):
        figures_owner["figures"] = [
            annotate_figure(fig, venue_family=family)
            if isinstance(fig, Mapping)
            else fig
            for fig in figures
        ]
    out["figure_knowledge"] = overlay
    grammar = out.get("venue_figure_grammar")
    if isinstance(grammar, dict):
        grammar = dict(grammar)
        grammar["figure_knowledge"] = overlay
        out["venue_figure_grammar"] = grammar
    return out
