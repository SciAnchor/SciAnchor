"""Deterministic paper-pool screening and coverage diagnostics."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from research_harness.storage.db import Database


AUDIT_SCHEMA_VERSION = "rh.paper_pool_audit.v1"
BUILD_GATE_DETAILS_SCHEMA_VERSION = "rh.build_coverage_gate_details.v1"
COVERAGE_BLOCKER_SCHEMA = "rh.schema.report.coverage_blockers.v1"

#: Conditions that `_is_coverage_eligible` tests, in the order it tests them.
#: A paper can fail several at once, so the breakdown reports all of them —
#: reporting only the first would make a three-repair paper look like a
#: one-repair win and understate the real cost of closing the gate.
COVERAGE_BLOCKERS: tuple[str, ...] = (
    "metadata_unusable",
    "flagged_noise",
    "duplicate_secondary",
    "dismissed_or_excluded",
    "not_screened_in",
    "not_manuscript_eligible",
    "not_annotated",
    "no_pdf_path",
)

#: Blockers a repair pass can plausibly clear without new acquisition.
#: Noise and duplicates are decisions, not defects — no amount of metadata
#: repair converts them, so counting them as "repairable" would promise a gain
#: that cannot be delivered.
REPAIRABLE_BLOCKERS: frozenset[str] = frozenset(
    {
        "metadata_unusable",
        "not_screened_in",
        "not_manuscript_eligible",
        "not_annotated",
        "no_pdf_path",
    }
)

NOISE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("cellular_rejuvenation", "cellular rejuvenation"),
    ("chlorophyll", "chlorophyll"),
    ("infectious_disease", "infectious disease"),
    ("fraud_detection", "fraud detection"),
    ("air_mobility_fleet", "air mobility fleet"),
    ("health_conference", "health science conference"),
    ("sound_event_detection", "sound event detection"),
)

ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "dataset_source": (
        "dataset",
        "data source",
        "trip record",
        "taxi",
        "openstreetmap",
        "poi",
        "point of interest",
        "permit",
        "transaction",
        "mobility record",
    ),
    "gis_spatial_statistics": (
        "gis",
        "arcgis",
        "hotspot",
        "hot spot",
        "spatial statistics",
        "moran",
        "getis",
        "kernel density",
    ),
    "causal_identification": (
        "causal",
        "counterfactual",
        "difference-in-differences",
        "difference in differences",
        "synthetic control",
        "treatment effect",
        "placebo",
    ),
    "spatiotemporal_graph_learning": (
        "spatiotemporal graph",
        "spatio-temporal graph",
        "graph neural",
        "graph learning",
        "event graph",
        "st-gnn",
        "stgnn",
    ),
    "sports_event_consumption": (
        "sports event",
        "sport event",
        "event consumption",
        "consumption",
        "economic impact",
        "event impact",
    ),
    "baseline_evaluation": (
        "baseline",
        "benchmark",
        "evaluation",
        "metric",
        "ablation",
        "protocol",
        "conformal",
    ),
}


def audit_topic_paper_pool(
    db: Database,
    topic_id: int,
    *,
    required_roles: tuple[str, ...] | None = None,
    min_coverage_eligible: int = 0,
) -> dict[str, Any]:
    """Return a JSON-safe audit of topic-linked papers.

    The audit is intentionally deterministic and conservative. It separates raw
    search/linkage provenance from papers that are eligible to satisfy strict
    build coverage.
    """

    rows = _load_topic_papers(db, topic_id)
    duplicate_groups = _duplicate_title_groups(rows)
    duplicate_secondary_ids = {
        paper_id for group in duplicate_groups for paper_id in group["paper_ids"][1:]
    }

    status_counts: Counter[str] = Counter()
    metadata_bad: list[dict[str, Any]] = []
    noise: list[dict[str, Any]] = []
    coverage_eligible_ids: list[int] = []
    blocker_rows: list[tuple[dict[str, Any], str, str, bool]] = []
    active_role_patterns = _active_role_patterns(required_roles)
    role_hits: dict[str, list[int]] = {role: [] for role in active_role_patterns}

    for row in rows:
        paper_id = int(row["id"])
        status = _clean(row["status"]) or "unknown"
        status_counts[status] += 1
        screened_out = _is_screened_out_or_dismissed(row)

        metadata_reason = _metadata_bad_reason(row)
        if metadata_reason and not screened_out:
            metadata_bad.append(
                _paper_example(row, reason=metadata_reason, include_url=True)
            )

        noise_reason = _noise_reason(row)
        if noise_reason and not screened_out:
            noise.append(_paper_example(row, reason=noise_reason, include_url=True))

        is_coverage_eligible = _is_coverage_eligible(
            row,
            metadata_reason,
            noise_reason,
            paper_id,
            duplicate_secondary_ids,
        )
        if is_coverage_eligible:
            coverage_eligible_ids.append(paper_id)

        # P-2: keep the inputs the blocker breakdown needs, so the shortfall can
        # be attributed to specific repairable conditions instead of reported as
        # a bare "N/M eligible".
        blocker_rows.append(
            (row, metadata_reason, noise_reason, paper_id in duplicate_secondary_ids)
        )

        if not is_coverage_eligible:
            continue

        text = _searchable_text(row)
        assigned_role = _clean(row.get("evidence_role"))
        for role, patterns in active_role_patterns.items():
            # An explicit topic-level evidence_role assignment counts even
            # when title/abstract lack the gate keywords; text patterns
            # remain the fallback for unassigned papers.
            if role == assigned_role or any(pattern in text for pattern in patterns):
                role_hits[role].append(paper_id)

    role_coverage = {
        role: {"covered": bool(ids), "paper_ids": ids[:10]}
        for role, ids in role_hits.items()
    }
    missing_roles = [
        role for role, coverage in role_coverage.items() if not coverage["covered"]
    ]

    counts = {
        "total_linked": len(rows),
        "non_dismissed": sum(
            1
            for row in rows
            if not _clean(row["relevance"]).startswith(("dismissed", "excluded"))
        ),
        "meta_only": int(status_counts.get("meta_only", 0)),
        "coverage_eligible": len(coverage_eligible_ids),
        "excluded_metadata_bad": len(metadata_bad),
        "excluded_noise": len(noise),
        "duplicate_title_groups": len(duplicate_groups),
        "duplicate_title_records": sum(
            max(0, len(group["paper_ids"]) - 1) for group in duplicate_groups
        ),
        "distinct_years": len({row["year"] for row in rows if row["year"] is not None}),
    }

    # P-1: fill the yield ledger from the audit itself, so the acquisition
    # trend exists without anyone remembering to record it.
    record_audit_coverage_snapshot(topic_id=topic_id, counts=counts)

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "topic_id": topic_id,
        "counts": counts,
        "status_counts": dict(status_counts),
        "coverage_eligible_paper_ids": coverage_eligible_ids,
        # P-2: which conditions are holding the shortfall, and which single
        # repair converts the most papers. Without this the operator can only
        # see "N/M eligible" and optimises whatever number is visible instead.
        "coverage_blockers": coverage_blocker_breakdown(
            blocker_rows, min_coverage_eligible=min_coverage_eligible
        ),
        "examples": {
            "excluded_metadata_bad": metadata_bad[:10],
            "excluded_noise": noise[:10],
            "duplicate_title_groups": duplicate_groups[:10],
        },
        "role_coverage": role_coverage,
        "missing_roles": missing_roles,
        "required_roles": list(active_role_patterns),
    }


def _active_role_patterns(
    required_roles: tuple[str, ...] | None,
) -> dict[str, tuple[str, ...]]:
    if required_roles is None:
        return dict(ROLE_PATTERNS)
    return {
        role: ROLE_PATTERNS[role] for role in required_roles if role in ROLE_PATTERNS
    }


def build_coverage_gate_details(
    *,
    audit: dict[str, Any],
    min_coverage_eligible: int,
    min_year_span: int,
    missing_required_artifacts: list[str] | None = None,
    missing_citation_expansion: bool = False,
) -> dict[str, Any]:
    counts = dict(audit.get("counts") or {})
    reasons: list[dict[str, Any]] = []

    missing_artifacts = list(missing_required_artifacts or [])
    if missing_artifacts:
        reasons.append(
            {
                "code": "missing_required_artifacts",
                "message": "Build stage is missing required artifacts.",
                "missing": missing_artifacts,
            }
        )

    coverage_eligible = int(counts.get("coverage_eligible") or 0)
    total_linked = int(counts.get("total_linked") or 0)
    meta_only = int(counts.get("meta_only") or 0)
    if coverage_eligible < min_coverage_eligible:
        reasons.append(
            {
                "code": "insufficient_coverage_eligible_papers",
                "message": (
                    f"{coverage_eligible}/{min_coverage_eligible} papers are eligible "
                    "for strict build coverage after screening."
                ),
                "observed": coverage_eligible,
                "minimum": min_coverage_eligible,
            }
        )
    if meta_only and coverage_eligible < min_coverage_eligible:
        reasons.append(
            {
                "code": "too_many_meta_only",
                "message": (
                    f"{meta_only}/{total_linked} topic papers are meta_only; "
                    "metadata-only records cannot satisfy strict build coverage."
                ),
                "meta_only": meta_only,
                "total_linked": total_linked,
            }
        )
    if int(counts.get("excluded_metadata_bad") or 0) > 0:
        reasons.append(
            {
                "code": "empty_title_candidates",
                "message": "Empty-title or metadata-bad papers must be excluded before build.",
                "examples": audit["examples"]["excluded_metadata_bad"][:5],
            }
        )
    if int(counts.get("excluded_noise") or 0) > 0:
        reasons.append(
            {
                "code": "off_topic_core_candidates",
                "message": "Off-topic cross-domain papers are present in the topic pool.",
                "examples": audit["examples"]["excluded_noise"][:5],
            }
        )
    if int(counts.get("duplicate_title_records") or 0) > 0:
        reasons.append(
            {
                "code": "duplicate_title_candidates",
                "message": "Duplicate-title records must be merged or down-weighted.",
                "examples": audit["examples"]["duplicate_title_groups"][:5],
            }
        )
    if int(counts.get("distinct_years") or 0) < min_year_span:
        reasons.append(
            {
                "code": "insufficient_year_span",
                "message": "Build coverage requires papers across multiple years.",
                "observed": int(counts.get("distinct_years") or 0),
                "minimum": min_year_span,
            }
        )
    missing_roles = list(audit.get("missing_roles") or [])
    if missing_roles:
        reasons.append(
            {
                "code": "missing_evidence_roles",
                "message": "Screened pool does not cover all required evidence roles.",
                "missing": missing_roles,
            }
        )
    if missing_citation_expansion:
        reasons.append(
            {
                "code": "missing_citation_expansion_report",
                "message": "Build coverage requires citation expansion from seed papers.",
            }
        )

    # P-1: a gate that only reports `needs_coverage` reads as "stop everything",
    # which is what happened on 2026-08-08. State what the shortfall does NOT
    # block, so the sequencing error is visible at the point of decision.
    decoupled = decoupled_deliverable_status(
        available_artifacts=set(audit.get("available_artifacts") or ()),
        exemplar_candidate_count=int(counts.get("coverage_eligible") or 0),
        coverage_eligible=int(counts.get("coverage_eligible") or 0),
        min_coverage_eligible=min_coverage_eligible,
    )

    # P-1: the gate is where an operator decides whether to keep acquiring, so
    # "is fetching still buying eligible papers?" belongs here rather than in a
    # separate report nobody opens.
    yield_trend_report = _acquisition_yield_trend(audit)
    recovery = _recovery_actions(reasons)
    if yield_trend_report.get("should_stop"):
        recovery.insert(
            0,
            (
                "acquisition yield has stalled — "
                f"{yield_trend_report.get('stop_detail') or 'no recent eligible gain'}. "
                "Repair existing records before acquiring more; see "
                "paper_pool_audit.coverage_blockers for which repair converts most."
            ),
        )

    return {
        "schema_version": BUILD_GATE_DETAILS_SCHEMA_VERSION,
        "gate_decision": "needs_coverage" if reasons else "pass",
        "can_advance": not reasons,
        "reasons": reasons,
        "recovery_actions": recovery,
        "gate_decoupled_deliverables": decoupled,
        "acquisition_yield": yield_trend_report,
        "paper_pool_audit": audit,
    }


def _acquisition_yield_trend(audit: dict[str, Any]) -> dict[str, Any]:
    """Read the acquisition yield trend for this topic; never raise."""
    try:
        from research_harness.acquisition import yield_monitor

        return yield_monitor.yield_trend(
            int(audit.get("topic_id") or 0),
            ledger_path=yield_monitor.DEFAULT_LEDGER,
        )
    except Exception:  # noqa: BLE001 - a missing trend must not break the gate
        return {"snapshots": 0, "should_stop": False, "stop_reason": ""}


def _load_topic_papers(db: Database, topic_id: int) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.doi, p.arxiv_id, p.s2_id,
                   p.url, p.pdf_path, p.status, p.abstract, p.compiled_summary,
                   pt.relevance, pt.screening_status, pt.evidence_role,
                   pt.manuscript_eligible
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _duplicate_title_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        title = _clean(row["title"])
        if not title:
            continue
        grouped[_normalize_title(title)].append(row)

    groups: list[dict[str, Any]] = []
    for group in grouped.values():
        if len(group) <= 1:
            continue
        groups.append(
            {
                "title": _clean(group[0]["title"]),
                "paper_ids": [int(row["id"]) for row in group],
            }
        )
    return sorted(groups, key=lambda item: (-len(item["paper_ids"]), item["title"]))


def _metadata_bad_reason(row: dict[str, Any]) -> str:
    if not _clean(row["title"]):
        return "empty_title"
    if not any(
        _clean(row.get(field))
        for field in ("doi", "arxiv_id", "s2_id", "url", "venue", "pdf_path")
    ):
        return "missing_source_identifier"
    return ""


def _noise_reason(row: dict[str, Any]) -> str:
    text = _searchable_text(row)
    for code, pattern in NOISE_PATTERNS:
        if pattern in text:
            return code
    return ""


def _is_coverage_eligible(
    row: dict[str, Any],
    metadata_reason: str,
    noise_reason: str,
    paper_id: int,
    duplicate_secondary_ids: set[int],
) -> bool:
    if metadata_reason or noise_reason or paper_id in duplicate_secondary_ids:
        return False
    if _clean(row["relevance"]).startswith(("dismissed", "excluded")):
        return False
    if _clean(row.get("screening_status")) != "screened_in":
        return False
    if int(row.get("manuscript_eligible") or 0) != 1:
        return False
    return _clean(row["status"]) == "annotated" and bool(_clean(row["pdf_path"]))


#: Deliverables that a strict-coverage shortfall does NOT block.
#:
#: From the topic 73 postmortem: "The strict gate is real and must pass before
#: final external release. It is not a valid reason to withhold the
#: already-feasible EAG skeleton, move maps, study contract, and figure/table
#: contract." Each entry therefore declares its OWN precondition — a claim of
#: gate-independence is worthless without stating what the deliverable actually
#: needs.
GATE_DECOUPLED_DELIVERABLES: tuple[dict[str, Any], ...] = (
    {
        "deliverable": "eag_exemplar_skeleton",
        "requires": ("topic_venue_contract", "exemplar_candidates>=1"),
        "blocked_by_coverage": False,
        "note": "structure transfer needs a venue contract and one exemplar, not a full pool",
    },
    {
        "deliverable": "paragraph_move_map",
        "requires": ("topic_venue_contract", "exemplar_candidates>=1"),
        "blocked_by_coverage": False,
        "note": "derived from the exemplar's rhetorical structure",
    },
    {
        "deliverable": "study_contract",
        "requires": ("topic_brief", "PAPER_PROFILE"),
        "blocked_by_coverage": False,
        "note": "population, assignment, outcomes, estimands and claim boundaries are design decisions",
    },
    {
        "deliverable": "figure_table_contract",
        "requires": ("topic_brief", "DOMAIN_WRITING_PROFILE"),
        "blocked_by_coverage": False,
        "note": "which displays the paper owes is a design decision, not an evidence count",
    },
)


def decoupled_deliverable_status(
    *,
    available_artifacts: set[str] | frozenset[str],
    exemplar_candidate_count: int = 0,
    coverage_eligible: int = 0,
    min_coverage_eligible: int = 0,
) -> dict[str, Any]:
    """Report which gate-decoupled deliverables are feasible right now.

    Deliberately does not weaken the coverage gate and does not move tools
    between stages. It answers a narrower question the gate never answered:
    while coverage is short, what useful work is still available?

    A gate that only reports ``needs_coverage`` invites the reader to stop
    everything — which is exactly what happened on 2026-08-08.
    """
    feasible: list[dict[str, Any]] = []
    not_yet: list[dict[str, Any]] = []

    for entry in GATE_DECOUPLED_DELIVERABLES:
        missing: list[str] = []
        for requirement in entry["requires"]:
            if requirement.startswith("exemplar_candidates>="):
                needed = int(requirement.split(">=", 1)[1])
                if exemplar_candidate_count < needed:
                    missing.append(f"{requirement} (have {exemplar_candidate_count})")
            elif requirement not in available_artifacts:
                missing.append(requirement)
        record = {
            "deliverable": entry["deliverable"],
            "requires": list(entry["requires"]),
            "note": entry["note"],
        }
        if missing:
            not_yet.append({**record, "missing": missing})
        else:
            feasible.append(record)

    shortfall = max(0, min_coverage_eligible - coverage_eligible)
    if feasible:
        guidance = (
            f"{len(feasible)} deliverable(s) are feasible now and are NOT blocked "
            f"by the coverage shortfall ({coverage_eligible}/{min_coverage_eligible}). "
            "Produce them before or alongside further acquisition."
        )
    else:
        guidance = (
            "No decoupled deliverable is feasible yet, and the reason is their own "
            "missing inputs — not the coverage shortfall. Supply those inputs first."
        )

    return {
        "coverage_eligible": coverage_eligible,
        "min_coverage_eligible": min_coverage_eligible,
        "coverage_shortfall": shortfall,
        "feasible_now": feasible,
        "not_yet_feasible": not_yet,
        # Invariant: coverage never appears here. Kept explicit so a future
        # change that starts gating these on coverage fails a test.
        "blocked_by_coverage": [],
        "guidance": guidance,
    }


def record_audit_coverage_snapshot(
    *,
    topic_id: int,
    counts: dict[str, Any],
) -> None:
    """Append this audit's coverage counts to the yield ledger.

    The audit is the natural write point: it already computes the eligible
    count and it runs on every build gate check, so the series fills itself.
    A ledger nobody writes to produces no trend — and the trend is the whole
    point, since acquisition batching in RH emerges across runner iterations
    rather than inside one loop.
    """
    try:
        from research_harness.acquisition import yield_monitor

        yield_monitor.record_coverage_snapshot(
            topic_id=int(topic_id),
            eligible=int(counts.get("coverage_eligible") or 0),
            linked=int(counts.get("total_linked") or 0),
            ledger_path=yield_monitor.DEFAULT_LEDGER,
        )
    except Exception:  # noqa: BLE001 - recording must never break an audit
        return


def explain_coverage_ineligibility(
    row: dict[str, Any],
    *,
    metadata_reason: str = "",
    noise_reason: str = "",
    is_duplicate_secondary: bool = False,
) -> list[str]:
    """Return every condition that keeps ``row`` out of strict coverage.

    Mirrors ``_is_coverage_eligible`` condition for condition, but returns the
    attribution instead of a bare bool. An empty list means eligible.
    """
    blockers: list[str] = []
    if metadata_reason:
        blockers.append("metadata_unusable")
    if noise_reason:
        blockers.append("flagged_noise")
    if is_duplicate_secondary:
        blockers.append("duplicate_secondary")
    if _clean(row.get("relevance")).startswith(("dismissed", "excluded")):
        blockers.append("dismissed_or_excluded")
    if _clean(row.get("screening_status")) != "screened_in":
        blockers.append("not_screened_in")
    if int(row.get("manuscript_eligible") or 0) != 1:
        blockers.append("not_manuscript_eligible")
    if _clean(row.get("status")) != "annotated":
        blockers.append("not_annotated")
    if not _clean(row.get("pdf_path")):
        blockers.append("no_pdf_path")
    return blockers


def coverage_blocker_breakdown(
    rows: list[tuple[dict[str, Any], str, str, bool]],
    *,
    min_coverage_eligible: int,
) -> dict[str, Any]:
    """Attribute the coverage shortfall to specific, repairable conditions.

    ``rows`` carries ``(row, metadata_reason, noise_reason, is_duplicate)`` per
    paper — the same four inputs the eligibility predicate consumes.

    The headline output is ``single_blocker_ranking``: papers blocked by
    exactly ONE condition, grouped by that condition. Those are the papers a
    single repair pass actually converts, so the ranking answers the question
    the 2026-08-08 run could not: which repair buys the most eligible papers?
    """
    eligible = 0
    blocker_counts: Counter[str] = Counter()
    single_counts: Counter[str] = Counter()
    repairable_papers = 0

    for row, metadata_reason, noise_reason, is_duplicate in rows:
        blockers = explain_coverage_ineligibility(
            row,
            metadata_reason=metadata_reason,
            noise_reason=noise_reason,
            is_duplicate_secondary=is_duplicate,
        )
        if not blockers:
            eligible += 1
            continue
        blocker_counts.update(blockers)
        if len(blockers) == 1:
            single_counts.update(blockers)
        if all(b in REPAIRABLE_BLOCKERS for b in blockers):
            repairable_papers += 1

    shortfall = max(0, min_coverage_eligible - eligible)
    return {
        "schema": COVERAGE_BLOCKER_SCHEMA,
        "papers_examined": len(rows),
        "eligible": eligible,
        "required": min_coverage_eligible,
        "shortfall": shortfall,
        "repairable_papers": repairable_papers,
        # If repair alone cannot close the gap, more acquisition is the only
        # path — saying so prevents another long repair loop that cannot win.
        "shortfall_closable_by_repair": shortfall == 0
        or repairable_papers >= shortfall,
        "blockers": [
            {"blocker": name, "papers": count}
            for name, count in sorted(
                blocker_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "single_blocker_ranking": [
            {
                "blocker": name,
                "papers": count,
                "repairable": name in REPAIRABLE_BLOCKERS,
            }
            for name, count in sorted(
                single_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
    }


def _is_screened_out_or_dismissed(row: dict[str, Any]) -> bool:
    relevance = _clean(row.get("relevance"))
    screening_status = _clean(row.get("screening_status"))
    return screening_status == "screened_out" or relevance.startswith(
        ("dismissed", "excluded")
    )


def _paper_example(
    row: dict[str, Any],
    *,
    reason: str,
    include_url: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "paper_id": int(row["id"]),
        "title": _clean(row["title"]),
        "reason": reason,
    }
    if include_url and _clean(row["url"]):
        item["url"] = _clean(row["url"])
    return item


def _searchable_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("title"),
        row.get("venue"),
        row.get("abstract"),
        row.get("compiled_summary"),
    ]
    return " ".join(_clean(part).lower() for part in parts if _clean(part))


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _recovery_actions(reasons: list[dict[str, Any]]) -> list[str]:
    if not reasons:
        return []
    codes = {str(reason.get("code", "")) for reason in reasons}
    actions = ["run paper_pool_audit --exclude-noise --dedupe --metadata-check"]
    if {
        "insufficient_coverage_eligible_papers",
        "missing_evidence_roles",
        "too_many_meta_only",
    } & codes:
        actions.append(
            "run targeted_search for missing evidence roles and ingest only screened candidates"
        )
    if "too_many_meta_only" in codes:
        actions.append("annotate or acquire full text for screened_in core papers")
    if {
        "empty_title_candidates",
        "off_topic_core_candidates",
        "duplicate_title_candidates",
    } & codes:
        actions.append(
            "mark empty, duplicate, and off-topic records as excluded before deep-read"
        )
    return actions
