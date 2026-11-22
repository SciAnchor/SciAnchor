"""Venue prescription: the resolver binding a paper's direction + target venue
to a concrete set of EAG quality targets (the "first-impression" plan).

This is the strict-binding layer of the EAG optimization. ``target_venue`` +
``discipline`` + ``article_type`` + ``paper_type`` resolve to a
:class:`VenuePrescription` carrying per-dimension quality targets that BOTH the
EAG generator (RH) and the downstream discriminator consume. Each target is
agent-understandable: a metric type (deterministic / llm_judge / vlm_judge), a
target value or band, the audit tool that enforces it, and a remediation hint.

The serialized form (``to_dict``) is the "EAG target document". Defaults are
calibrated to top-venue norms; they are meant to
be refined by scoring target-venue exemplars (see the first-impression plan).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..venue_facts import venue_tier_label

# --- metric type vocabulary ------------------------------------------------

METRIC_DETERMINISTIC = "deterministic"
METRIC_LLM_JUDGE = "llm_judge"
METRIC_VLM_JUDGE = "vlm_judge"

# --- discipline -> style profile --------------------------------------------

_STYLE_BY_DISCIPLINE = {
    "biomed": "biomed_omics",
    "medicine": "biomed_omics",
    "omics": "biomed_omics",
    "clinical": "biomed_omics",
    "social": "social_humanities",
    "humanities": "social_humanities",
    "economics": "social_humanities",
    "nature": "nature_family",
    "interdisciplinary": "nature_family",
}
_DEFAULT_STYLE = "stem_conference"

# --- default page limits (venue family, mirrors writing_impls) --------------


def _default_page_limit(target_venue: str) -> int:
    v = target_venue.lower()
    if "aaai" in v:
        return 7
    if any(m in v for m in ("acl", "emnlp", "naacl")):
        return 8
    if any(m in v for m in ("neurips", "iclr", "icml")):
        return 9
    return 0  # unknown venue: caller must declare explicitly


def _style_profile_for(discipline: str) -> str:
    d = (discipline or "").lower().strip()
    for key, profile in _STYLE_BY_DISCIPLINE.items():
        if key in d:
            return profile
    return _DEFAULT_STYLE


# Fallback section word bands, kept in sync with the authoritative source
# (``_workflow.execution.writing_checks.SECTION_WORD_TARGETS``). Used only when
# that module cannot be imported (defensive, avoids a primitives->execution
# import at module load time).
_FALLBACK_WORD_TARGETS: dict[str, tuple[int, int]] = {
    "abstract": (180, 260),
    "introduction": (1200, 1800),
    "related_work": (1500, 2800),
    "method": (2000, 3500),
    "experiments": (2500, 4500),
    "results": (1000, 2000),
    "discussion": (600, 1200),
    "conclusion": (250, 500),
    "limitations": (200, 500),
    "appendix": (500, 5000),
}


# RH's abstract word caps for known target venues, keyed by venue name and common aliases.
# A band the venue's own cap refuses is one every draft pays a REPAIR for.
_VENUE_ABSTRACT_MAX = {
    150: (
        "npj Digital Medicine",
        "npj Digit. Med.",
        "npjdigitalmed",
    ),
    200: (
        "Scientific Reports",
        "Sci. Rep.",
        "Sci Rep",
        "srep",
        "Nature Portfolio Scientific Reports",
        "Scientific Reports (Nature Portfolio)",
    ),
    300: (
        "Humanities and Social Sciences Communications",
        "HSSC",
        "Humanit Soc Sci Commun",
        "palcomms",
    ),
    250: (
        "Information Processing & Management",
        "IPM",
        "Inf. Process. Manag.",
        "Information Processing and Management",
        "Reliability Engineering & System Safety",
        "RESS",
        "Reliab. Eng. Syst. Saf.",
        "Applied Soft Computing",
        "ASC",
        "Appl. Soft Comput.",
        "Alexandria Engineering Journal",
        "AEJ",
        "Alex. Eng. J.",
        "International Journal of Electrical Power & Energy Systems",
        "IJEPES",
        "Int. J. Electr. Power Energy Syst.",
        "International Journal of Electrical Power and Energy Systems",
        "Discover Computing",
        "Discov. Comput.",
        "Information Retrieval Journal",
        "Discover Internet of Things",
        "Discov. Internet Things",
        "DIoT",
    ),
}


def _venue_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


_ABSTRACT_MAX_BY_KEY = {
    _venue_key(name): cap
    for cap, names in _VENUE_ABSTRACT_MAX.items()
    for name in names
}


def venue_abstract_max(
    venue: str, venue_profile: dict[str, Any] | None = None
) -> int | None:
    """The venue's abstract word cap: the profile's own when given, else the copied table."""
    words = (
        (venue_profile or {}).get("words") if isinstance(venue_profile, dict) else None
    )
    cap = words.get("abstract_max") if isinstance(words, dict) else None
    if isinstance(cap, int) and cap > 0:
        return cap
    return _ABSTRACT_MAX_BY_KEY.get(_venue_key(venue or ""))


def _section_word_targets() -> dict[str, tuple[int, int]]:
    """Lazy-load the authoritative word bands; fall back to the local copy."""
    try:
        from .._workflow.execution.writing_checks import SECTION_WORD_TARGETS

        return SECTION_WORD_TARGETS
    except Exception:
        return dict(_FALLBACK_WORD_TARGETS)


@dataclass(frozen=True)
class QualityTarget:
    """One first-impression dimension as an agent-understandable target."""

    dimension: str
    metric_type: str
    target: dict[
        str, Any
    ]  # {"op": ">=", "value": 4.0, "scale": "0-5"} or {"band": [lo, hi]}
    audit_tool: str  # discriminator-side enforcement entry
    remediation: str  # what the generator/simulator should do when not met
    binding: str = ""  # which venue/discipline signal sets this value


@dataclass(frozen=True)
class VenuePrescription:
    """Resolved first-impression targets for one paper."""

    target_venue: str = ""
    discipline: str = ""
    article_type: str = ""
    paper_type: str = "empirical"
    venue_tier: str = ""
    style_profile: str = ""
    official_page_limit: int = 0
    abstract_word_band: tuple[int, int] = (180, 260)
    section_word_bands: dict[str, tuple[int, int]] = field(default_factory=dict)
    quality_targets: tuple[QualityTarget, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serializable form — the EAG target document for the discriminator."""
        return {
            "target_venue": self.target_venue,
            "discipline": self.discipline,
            "article_type": self.article_type,
            "paper_type": self.paper_type,
            "venue_tier": self.venue_tier,
            "style_profile": self.style_profile,
            "official_page_limit": self.official_page_limit,
            "abstract_word_band": list(self.abstract_word_band),
            "section_word_bands": {
                k: list(v) for k, v in self.section_word_bands.items()
            },
            "quality_targets": [asdict(t) for t in self.quality_targets],
        }


def _target(dimension, metric_type, op_value, audit_tool, remediation, binding=""):
    """Helper: build a scalar (>=) target; use ``_band`` for ranges."""
    return QualityTarget(
        dimension=dimension,
        metric_type=metric_type,
        target={"op": ">=", "value": op_value},
        audit_tool=audit_tool,
        remediation=remediation,
        binding=binding,
    )


def _band(dimension, metric_type, lo, hi, audit_tool, remediation, binding=""):
    """Helper: build a range target."""
    return QualityTarget(
        dimension=dimension,
        metric_type=metric_type,
        target={"band": [lo, hi]},
        audit_tool=audit_tool,
        remediation=remediation,
        binding=binding,
    )


def resolve_venue_prescription(
    *,
    target_venue: str = "",
    discipline: str = "",
    article_type: str = "",
    paper_type: str = "empirical",
    page_limit: int | None = None,
    venue_profile: dict[str, Any] | None = None,
) -> VenuePrescription:
    """Resolve a paper's direction + target venue into EAG quality targets.

    ``discipline`` is the topic's domain name (the same signal the figure
    renderer uses); ``target_venue`` drives tier + page limit + style.
    """
    venue = (target_venue or "").strip()
    disc = (discipline or "").strip()
    tier = venue_tier_label(venue) if venue else ""
    official = (
        page_limit if page_limit and page_limit > 0 else _default_page_limit(venue)
    )
    style = _style_profile_for(disc)
    word_targets = _section_word_targets()
    abstract_band = word_targets.get("abstract", (180, 260))
    cap = venue_abstract_max(venue, venue_profile)
    if cap:  # the venue's cap is the band's ceiling; the floor keeps four fifths of it
        abstract_band = (
            min(abstract_band[0], round(cap * 0.8)),
            min(abstract_band[1], cap),
        )
    section_bands = {
        k: v for k, v in word_targets.items() if k not in {"title", "abstract"}
    }

    # The 14 first-impression dimensions. Thresholds are top-venue defaults;
    # the first-impression plan refines them by scoring target-venue exemplars.
    targets: list[QualityTarget] = [
        _band(
            "title",
            METRIC_LLM_JUDGE,
            5,
            14,
            "title_convention",
            "recast the title: noun-phrase or conclusion form, 5-14 words, problem+method+result",
            "venue_family",
        ),
        _band(
            "abstract",
            METRIC_DETERMINISTIC,
            *abstract_band,
            "word_count",
            "trim or expand the abstract into the venue word band",
            "abstract_convention",
        ),
        _target(
            "intro_hook",
            METRIC_LLM_JUDGE,
            4.0,
            "intro_arc_review",
            "open with a concrete data-point/gap/question hook, not boilerplate importance",
            "discipline",
        ),
        _target(
            "logical_flow",
            METRIC_LLM_JUDGE,
            4.0,
            "section_review",
            "strengthen topic sentences and move-to-move transitions",
            "threshold",
        ),
        _target(
            "completeness",
            METRIC_LLM_JUDGE,
            4.0,
            "section_review",
            "add missing evidence, baselines, or ablations",
            "threshold",
        ),
        _target(
            "figure_density",
            METRIC_DETERMINISTIC,
            1.0,
            "figure_density_check",
            "add figures/tables so the paper meets the per-1k-word density floor",
            "venue_tier",
        ),
        _target(
            "aesthetics",
            METRIC_VLM_JUDGE,
            8.0,
            "vlm_figure_review",
            "improve visual polish: composition, spacing, label legibility",
            "venue_family",
        ),
        _target(
            "palette",
            METRIC_DETERMINISTIC,
            1.0,
            "style_profile_check",
            "render figures with the discipline style profile, not defaults",
            "discipline",
        ),
        _target(
            "figure_typography",
            METRIC_VLM_JUDGE,
            7.0,
            "result_figure_publication_gate",
            "fix panel alignment, legends, axis labels, unit clarity",
            "venue_family",
        ),
        _target(
            "skeleton",
            METRIC_LLM_JUDGE,
            4.0,
            "skeleton_review",
            "ensure the section architecture matches the venue convention",
            "venue_family",
        ),
        _target(
            "layout",
            METRIC_DETERMINISTIC,
            1.0,
            "pdf_quality_scan",
            "resolve overfull/underfull boxes and undefined references",
            "layout_template",
        ),
        _target(
            "page_fill",
            METRIC_DETERMINISTIC,
            0.9,
            "page_fill_check",
            "fill the main text toward the official page limit",
            "official_page_limit",
        ),
        _target(
            "paragraph_length",
            METRIC_DETERMINISTIC,
            1.0,
            "paragraph_development",
            "vary paragraph rhythm; no 1-2 sentence body paragraphs",
            "discipline",
        ),
        _target(
            "main_appendix",
            METRIC_DETERMINISTIC,
            1.0,
            "appendix_coverage_check",
            "keep contribution/method/results in main; move full ablations/hyperparams/datasets to appendix",
            "appendix_policy",
        ),
    ]

    return VenuePrescription(
        target_venue=venue,
        discipline=disc,
        article_type=(article_type or "").strip(),
        paper_type=(paper_type or "empirical").strip(),
        venue_tier=tier,
        style_profile=style,
        official_page_limit=official,
        abstract_word_band=abstract_band,
        section_word_bands=section_bands,
        quality_targets=tuple(targets),
    )
