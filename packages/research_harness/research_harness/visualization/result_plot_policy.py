"""Deterministic venue and evidence policy for experiment/result plots.

This module is deliberately independent from the Matplotlib renderer.  It maps
venue, discipline, study, and record-schema signals onto an immutable plotting
policy; renderers and planners consume the same resolution and record it in
provenance.  It never handles generative architecture or method figures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_STYLE_PROFILES: set[str] = {
    "stem_conference",
    "nature_family",
    "social_humanities",
    "biomed_omics",
}


@dataclass(frozen=True)
class ResultPlotPolicy:
    """One immutable venue-family plotting contract."""

    policy_id: str
    venue_family: str
    style_profile: str
    recommended_charts: tuple[str, ...]
    discouraged_charts: tuple[str, ...]
    required_metadata: tuple[str, ...]
    preferred_formats: tuple[str, ...] = ("pdf", "svg", "png")
    reveal_raw_points: bool = False
    print_safe_hatches: bool = True


@dataclass(frozen=True)
class ResultPlotPolicyResolution:
    """A policy plus an auditable account of how it was selected."""

    policy: ResultPlotPolicy
    selection_basis: str
    signals: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_provenance(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy.policy_id,
            "venue_family": self.policy.venue_family,
            "style_profile": self.policy.style_profile,
            "selection_basis": self.selection_basis,
            "signals": list(self.signals),
            "recommended_charts": list(self.policy.recommended_charts),
            "discouraged_charts": list(self.policy.discouraged_charts),
            "required_metadata": list(self.policy.required_metadata),
            "preferred_formats": list(self.policy.preferred_formats),
            "reveal_raw_points": self.policy.reveal_raw_points,
            "print_safe_hatches": self.policy.print_safe_hatches,
            "warnings": list(self.warnings),
        }


_POLICY_TEMPLATES: dict[str, ResultPlotPolicy] = {
    "stem_computing": ResultPlotPolicy(
        policy_id="stem_computing_v1",
        venue_family="stem_computing",
        style_profile="stem_conference",
        recommended_charts=(
            "grouped_bar",
            "line",
            "heatmap",
            "pareto_scatter",
            "sensitivity_line",
            "box",
            "scatter",
        ),
        discouraged_charts=("radar",),
        required_metadata=(
            "source_data",
            "metric_direction",
            "uncertainty_semantics",
            "reproduction_command",
        ),
    ),
    "nature_multidisciplinary": ResultPlotPolicy(
        policy_id="nature_multidisciplinary_v1",
        venue_family="nature_multidisciplinary",
        style_profile="nature_family",
        recommended_charts=(
            "box",
            "violin",
            "scatter",
            "forest",
            "line",
            "heatmap",
            "image",
        ),
        discouraged_charts=("radar", "grouped_bar"),
        required_metadata=(
            "source_data",
            "sample_size",
            "uncertainty_semantics",
            "replicate_semantics",
        ),
        reveal_raw_points=True,
    ),
    "biomedical_clinical": ResultPlotPolicy(
        policy_id="biomed_clinical_v1",
        venue_family="biomedical_clinical",
        style_profile="biomed_omics",
        recommended_charts=(
            "forest",
            "km_survival",
            "box",
            "violin",
            "line",
            "scatter",
            "hist",
        ),
        discouraged_charts=("radar", "grouped_bar"),
        required_metadata=(
            "source_data",
            "sample_size",
            "confidence_interval",
            "replicate_semantics",
            "statistical_test",
        ),
        reveal_raw_points=True,
    ),
    "biomedical_omics": ResultPlotPolicy(
        policy_id="biomed_omics_v1",
        venue_family="biomedical_omics",
        style_profile="biomed_omics",
        recommended_charts=(
            "volcano",
            "heatmap",
            "box",
            "violin",
            "forest",
            "scatter",
        ),
        discouraged_charts=("radar", "grouped_bar"),
        required_metadata=(
            "source_data",
            "sample_size",
            "multiple_testing_method",
            "replicate_semantics",
        ),
        reveal_raw_points=True,
    ),
    "social_behavioral": ResultPlotPolicy(
        policy_id="social_behavioral_v1",
        venue_family="social_behavioral",
        style_profile="social_humanities",
        recommended_charts=(
            "forest",
            "line",
            "box",
            "violin",
            "hist",
            "scatter",
            "stacked_bar",
        ),
        discouraged_charts=("radar",),
        required_metadata=(
            "source_data",
            "effect_size",
            "confidence_interval",
            "exact_p_value",
            "replication_package",
        ),
        reveal_raw_points=True,
    ),
}

_STYLE_TO_POLICY = {
    "stem_conference": "stem_computing",
    "nature_family": "nature_multidisciplinary",
    "social_humanities": "social_behavioral",
    "biomed_omics": "biomedical_omics",
}


def register_style_profile(name: str, inherits: str = "stem_conference") -> str:
    """Let a caller declare a project-specific style profile.

    The renderer keeps its own registry of profiles, and this module is
    deliberately independent of it, so a profile registered there was silently
    rejected here and the request fell back to the venue default. Callers that
    add a profile to the renderer register the same name here, naming the
    built-in profile whose venue policy it inherits.
    """
    normalized = str(name or "").strip().lower()
    if not normalized:
        return ""
    parent = str(inherits or "").strip().lower()
    if parent not in _STYLE_TO_POLICY:
        raise ValueError(
            f"unknown parent style profile {inherits!r}; "
            f"choose one of {sorted(_STYLE_TO_POLICY)}"
        )
    _STYLE_PROFILES.add(normalized)
    _STYLE_TO_POLICY[normalized] = _STYLE_TO_POLICY[parent]
    return normalized


_OMICS_TERMS = (
    "omics",
    "genomic",
    "genetics",
    "transcriptom",
    "proteom",
    "metabolom",
    "bioinformatics",
    "gene expression",
)
_CLINICAL_TERMS = (
    "biomedical",
    "biomedicine",
    "medicine",
    "medical",
    "clinical",
    "patient",
    "oncology",
    "epidemiology",
    "public health",
    "jama",
    "lancet",
    "nejm",
    "bmj",
)
_SOCIAL_TERMS = (
    "social science",
    "sociology",
    "psychology",
    "economics",
    "econometric",
    "political science",
    "education",
    "humanities",
    "apa",
    "aea",
)
_STEM_TERMS = (
    "computer science",
    "machine learning",
    "artificial intelligence",
    "engineering",
    "robotics",
    "ccf",
    "acm",
    "ieee",
    "neurips",
    "icml",
    "iclr",
    "aaai",
    "ijcai",
    "acl",
    "emnlp",
    "cvpr",
    "iccv",
    "eccv",
    "kdd",
    "sigir",
    "nature machine intelligence",
)
_PREFIX_TERMS = frozenset(
    {"genomic", "transcriptom", "proteom", "metabolom", "econometric"}
)


def resolve_result_plot_policy(
    *,
    explicit_style_profile: str | None = None,
    spec_style_profile: str | None = None,
    target_venue: str = "",
    discipline: str = "",
    article_type: str = "",
    records: Sequence[Mapping[str, Any]] = (),
) -> ResultPlotPolicyResolution:
    """Resolve a stable policy without mutating caller data.

    A valid explicit profile is authoritative. Otherwise deterministic
    venue/discipline/record signals outrank the planner-provided spec profile;
    the existing STEM profile remains the final compatibility fallback.
    """

    warnings: list[str] = []
    explicit = _normalize_profile(explicit_style_profile)
    if explicit_style_profile and explicit is None:
        warnings.append(f"unknown_explicit_style_profile:{explicit_style_profile}")
    if explicit is not None:
        family = _STYLE_TO_POLICY[explicit]
        return _resolution(
            family,
            "explicit_style_profile",
            (f"style_profile:{explicit}",),
            warnings,
            records,
            style_profile=explicit,
        )

    normalized_text = _normalize_text(
        " ".join((target_venue, discipline, article_type))
    )
    fields = _record_fields(records)
    family = _infer_family(normalized_text, fields)
    if family is not None:
        text_signals = tuple(
            signal
            for signal in (
                f"target_venue:{_normalize_text(target_venue)}" if target_venue else "",
                f"discipline:{_normalize_text(discipline)}" if discipline else "",
                f"article_type:{_normalize_text(article_type)}" if article_type else "",
            )
            if signal
        )
        basis = "venue_discipline" if normalized_text else "record_schema"
        signals = (*text_signals, f"record_fields:{','.join(sorted(fields))}")
        return _resolution(family, basis, signals, warnings, records)

    spec_profile = _normalize_profile(spec_style_profile)
    if spec_style_profile and spec_profile is None:
        warnings.append(f"unknown_spec_style_profile:{spec_style_profile}")
    if spec_profile is not None:
        family = _STYLE_TO_POLICY[spec_profile]
        return _resolution(
            family,
            "spec_style_profile",
            (f"style_profile:{spec_profile}",),
            warnings,
            records,
        )

    if normalized_text:
        warnings.append("unrecognized_venue_or_discipline")
    warnings.append("defaulted_to_stem_computing")
    return _resolution("stem_computing", "default", (), warnings, records)


def _resolution(
    family: str,
    basis: str,
    signals: Sequence[str],
    warnings: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    style_profile: str | None = None,
) -> ResultPlotPolicyResolution:
    template = _POLICY_TEMPLATES[family]
    dynamic = _record_recommendations(records, family)
    policy = ResultPlotPolicy(
        policy_id=template.policy_id,
        venue_family=template.venue_family,
        # A registered project profile inherits the family's chart policy but
        # keeps its own name, so the renderer looks up the profile the caller
        # actually asked for rather than the family default.
        style_profile=style_profile or template.style_profile,
        recommended_charts=_unique((*dynamic, *template.recommended_charts)),
        discouraged_charts=template.discouraged_charts,
        required_metadata=template.required_metadata,
        preferred_formats=template.preferred_formats,
        reveal_raw_points=template.reveal_raw_points,
        print_safe_hatches=template.print_safe_hatches,
    )
    return ResultPlotPolicyResolution(
        policy=policy,
        selection_basis=basis,
        signals=tuple(signal for signal in signals if signal),
        warnings=tuple(warnings),
    )


def _infer_family(text: str, fields: frozenset[str]) -> str | None:
    if _contains_any(text, _OMICS_TERMS) or (
        "log2fc" in fields and bool({"neg_log10_p", "p_value", "p"} & fields)
    ):
        return "biomedical_omics"
    if _contains_any(text, _CLINICAL_TERMS) or {"time", "event"}.issubset(fields):
        return "biomedical_clinical"
    if _contains_any(text, _SOCIAL_TERMS):
        return "social_behavioral"
    if _contains_any(text, _STEM_TERMS):
        return "stem_computing"
    if re.search(r"\bnature\b", text):
        return "nature_multidisciplinary"
    return None


def _record_recommendations(
    records: Sequence[Mapping[str, Any]], family: str
) -> tuple[str, ...]:
    fields = _record_fields(records)
    figure_types = _unique(
        tuple(
            _normalize_text(str(record.get("figure_type", ""))).replace(" ", "_")
            for record in records
            if isinstance(record, Mapping) and record.get("figure_type")
        )
    )
    charts: list[str] = []
    type_map = {
        "benchmark": "grouped_bar",
        "ablation": "heatmap",
        "sensitivity": "sensitivity_line",
        "pareto": "pareto_scatter",
        "survival": "km_survival",
        "volcano": "volcano",
        "forest": "forest",
        "box": "box",
        "violin": "violin",
        "line": "line",
    }
    charts.extend(type_map[kind] for kind in figure_types if kind in type_map)
    if {"time", "event"}.issubset(fields) or {
        "time",
        "value",
        "censored",
    }.issubset(fields):
        charts.append("km_survival")
    if "log2fc" in fields and bool({"neg_log10_p", "p_value", "p"} & fields):
        charts.append("volcano")
    if {"lo", "hi"}.issubset(fields) and bool({"estimate", "value"} & fields):
        charts.append("forest")
    if {"variant", "dataset"}.issubset(fields):
        charts.append("heatmap")
    if {"dataset", "method", "metric"}.issubset(fields):
        charts.append("grouped_bar")
    if {"group", "value"}.issubset(fields):
        charts.extend(("box", "violin") if family != "stem_computing" else ("box",))
    if {"category", "segment", "value"}.issubset(fields):
        charts.append("stacked_bar")
    if {"x", "y"}.issubset(fields):
        charts.extend(("line", "scatter"))
    return _unique(charts)


def _record_fields(records: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    return frozenset(
        str(key).strip().lower()
        for record in records
        if isinstance(record, Mapping)
        for key in record
    )


def _normalize_profile(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _STYLE_PROFILES else None


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    for term in terms:
        trailing_boundary = "" if term in _PREFIX_TERMS else r"(?=$|\s)"
        if re.search(rf"(?:^|\s){re.escape(term)}{trailing_boundary}", text):
            return True
    return False


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


_REFUSED_CHARTS = frozenset(
    {
        "pie",
        "pie_chart",
        "3d",
        "3d_bar",
        "3d_scatter",
        "dual_y",
        "dual_axis",
        "twinx",
        "secondary_y",
    }
)


def refuse_chart_kind(kind: str) -> str | None:
    """Return a skip reason for encodings this stack will not draw."""
    key = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _REFUSED_CHARTS:
        return f"refused_chart:{key}"
    return None


def empty_effect_reason(
    kind: str, records: Sequence[Mapping[str, Any]] = ()
) -> str | None:
    """Annotate a recorded null/empty effect. Do not use this to skip a panel.

    Degenerate only: identical bars, a ROC curve with no Youden gap, a volcano
    with no points past ordinary thresholds, a heatmap with no row spread.
    Missing records are a separate skip. Recorded nulls still draw.
    """
    if not records:
        return None
    key = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    values = [_as_float(record.get("value")) for record in records]
    numeric = [value for value in values if value is not None]

    if key in {"bar", "grouped_bar", "stacked_bar"} and len(numeric) >= 2:
        span = max(numeric) - min(numeric)
        if span <= 1e-12 * (1.0 + max(abs(v) for v in numeric)):
            return "empty_effect:bar_range"

    if key in {"heatmap"} and len(numeric) >= 4:
        mean = sum(numeric) / len(numeric)
        var = sum((v - mean) ** 2 for v in numeric) / len(numeric)
        if var <= 1e-12:
            return "empty_effect:heatmap_variance"

    tpr = [_as_float(record.get("tpr")) for record in records]
    fpr = [_as_float(record.get("fpr")) for record in records]
    pairs = [(a, b) for a, b in zip(tpr, fpr) if a is not None and b is not None]
    if pairs and max(a - b for a, b in pairs) < 0.15:
        return "empty_effect:roc_youden"

    if key == "volcano":
        hits = 0
        for record in records:
            log2fc = _as_float(record.get("log2fc"))
            if log2fc is None:
                continue
            p_value = _as_float(record.get("p_value"))
            if p_value is None:
                p_value = _as_float(record.get("p"))
            neg = _as_float(record.get("neg_log10_p"))
            sig_p = (p_value is not None and p_value < 0.05) or (
                neg is not None and neg >= 1.3
            )
            if abs(log2fc) >= 1.0 and sig_p:
                hits += 1
        if hits == 0:
            return "empty_effect:volcano_hits"
    return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
