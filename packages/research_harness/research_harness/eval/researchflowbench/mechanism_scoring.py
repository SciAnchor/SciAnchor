from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Iterable, Mapping


BLOCKING_GATE_VERDICTS = frozenset({"block", "blocked", "rollback", "needs_review"})
BLOCKING_REVIEW_STATUSES = frozenset(
    {"blocked", "blocking", "needs_review", "open", "unresolved"}
)
TRACE_REF_KEYS = frozenset(
    {
        "artifact_refs",
        "canonical_payload_refs",
        "dependency_artifact_ids",
        "dependency_refs",
        "derived_from_artifact_ids",
        "source_artifact",
        "source_artifact_ids",
        "source_artifacts",
        "source_refs",
        "upstream_artifact_ids",
    }
)
TRACE_DEPENDENCY_TYPES = frozenset(
    {
        "consumes",
        "consumed_by",
        "dependency",
        "depends_on",
        "derived_from",
        "input_to",
        "source",
        "supported_by",
    }
)
TRACE_SOURCE_ARTIFACT_TYPES = frozenset(
    {
        "adversarial_resolution",
        "baseline_matrix",
        "claim_candidate_set",
        "direction_proposal",
        "draft_pack",
        "evidence_pack",
        "experiment_result",
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
STALE_STATES = frozenset({"stale", "obsolete", "outdated", "invalidated"})
FALSE_NOVELTY_TOKENS = frozenset(
    {
        "close prior",
        "close_prior",
        "false novelty",
        "false_novelty",
        "missing close priors",
        "missing_close_priors",
    }
)


@dataclass(frozen=True)
class MechanismDiagnostic:
    code: str
    mechanism: str
    severity: str
    message: str
    path: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MechanismScore:
    mechanism: str
    score: float
    passed: bool
    diagnostics: tuple[MechanismDiagnostic, ...] = ()
    checked_count: int = 0
    failed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = [item.to_dict() for item in self.diagnostics]
        return payload


@dataclass(frozen=True)
class MechanismScoreReport:
    score: float
    passed: bool
    mechanism_scores: tuple[MechanismScore, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "mechanism_scores": [item.to_dict() for item in self.mechanism_scores],
        }


@dataclass(frozen=True)
class _Artifact:
    artifact_id: str
    artifact_type: str
    payload: Mapping[str, Any]
    path: str


def score_artifact_mechanisms(
    bundle: Mapping[str, Any] | Any,
    *,
    required_families: Iterable[str] = (),
    required_facets: Iterable[str] = (),
) -> MechanismScoreReport:
    mechanism_scores = (
        score_artifact_trace(bundle),
        score_rollback(bundle),
        score_baseline_governance(
            bundle,
            required_families=required_families,
            required_facets=required_facets,
        ),
    )
    score = _mean(score_item.score for score_item in mechanism_scores)
    return MechanismScoreReport(
        score=score,
        passed=all(score_item.passed for score_item in mechanism_scores),
        mechanism_scores=mechanism_scores,
    )


def score_artifact_trace(bundle: Mapping[str, Any] | Any) -> MechanismScore:
    payload = _mapping(bundle)
    artifacts = _artifacts(payload)
    publication_packs = [
        artifact for artifact in artifacts if _is_publication_pack(artifact)
    ]
    diagnostics: list[MechanismDiagnostic] = []
    if not publication_packs:
        diagnostics.append(
            _diagnostic(
                code="publication_pack_missing",
                mechanism="artifact_trace",
                severity="error",
                message="artifact bundle does not contain a publication_pack artifact",
                path="artifacts",
            )
        )
        return _score("artifact_trace", diagnostics, checked_count=1, failed_count=1)

    failed_count = 0
    dependency_edges = _dependency_edges(payload)
    gate_decisions = _items(
        payload.get("gate_decisions") or payload.get("gate_decision")
    )
    review_issues = _items(payload.get("review_issues") or payload.get("review_issue"))

    for pack in publication_packs:
        if _has_dependency_trace(
            pack, dependency_edges, artifacts
        ) or _has_payload_trace(pack, artifacts):
            continue
        blockers = _trace_blockers(pack, gate_decisions, review_issues)
        if blockers:
            diagnostics.append(
                _diagnostic(
                    code="publication_pack_trace_blocked",
                    mechanism="artifact_trace",
                    severity="warning",
                    message=(
                        "publication_pack lacks upstream trace, but a blocking "
                        "gate_decision or review_issue records the trace failure"
                    ),
                    path=pack.path,
                    details={
                        "publication_pack_artifact_id": pack.artifact_id,
                        "blocker_ids": blockers,
                    },
                )
            )
            continue
        failed_count += 1
        diagnostics.append(
            _diagnostic(
                code="publication_pack_missing_upstream_trace",
                mechanism="artifact_trace",
                severity="error",
                message=(
                    "publication_pack must have an upstream dependency edge or "
                    "canonical payload artifact reference"
                ),
                path=pack.path,
                details={"publication_pack_artifact_id": pack.artifact_id},
            )
        )

    return _score(
        "artifact_trace",
        diagnostics,
        checked_count=len(publication_packs),
        failed_count=failed_count,
    )


def score_rollback(bundle: Mapping[str, Any] | Any) -> MechanismScore:
    payload = _mapping(bundle)
    rollback_events = _items(
        payload.get("rollback_events") or payload.get("rollback_event")
    )
    stale_source_ids = _stale_source_ids(payload)
    diagnostics: list[MechanismDiagnostic] = []

    if not rollback_events:
        if stale_source_ids:
            diagnostics.append(
                _diagnostic(
                    code="rollback_event_missing_for_stale_source",
                    mechanism="rollback",
                    severity="error",
                    message="stale sources require a rollback_event",
                    path="rollback_events",
                    details={"stale_source_artifact_ids": sorted(stale_source_ids)},
                )
            )
            return _score("rollback", diagnostics, checked_count=1, failed_count=1)
        return _score("rollback", diagnostics, checked_count=1, failed_count=0)

    checked_count = 0
    failed_count = 0
    for index, raw_event in enumerate(rollback_events):
        event = _mapping(raw_event)
        path = f"rollback_events[{index}]"
        event_id = _id_value(event, ("rollback_event_id", "event_id", "id")) or path

        affected_ids = _ids_from_value(
            event.get("affected_artifact_ids")
            or event.get("affected_object_ids")
            or event.get("affected_artifacts")
        )
        rollback_cone = event.get("rollback_cone")
        cone_ids = _rollback_cone_ids(rollback_cone)
        event_stale_ids = stale_source_ids | _event_stale_source_ids(event)
        covered_ids = affected_ids | cone_ids

        checks = (
            (
                bool(affected_ids),
                "rollback_event_missing_affected_artifact_ids",
                "rollback_event must list affected_artifact_ids",
                f"{path}.affected_artifact_ids",
                {"rollback_event_id": event_id},
            ),
            (
                bool(cone_ids),
                "rollback_event_missing_rollback_cone",
                "rollback_event must include a non-empty rollback_cone",
                f"{path}.rollback_cone",
                {"rollback_event_id": event_id},
            ),
            (
                bool(_id_value(event, ("gate_decision_artifact_id", "gate_id"))),
                "rollback_event_missing_gate_decision_artifact_id",
                "rollback_event must reference gate_decision_artifact_id",
                f"{path}.gate_decision_artifact_id",
                {"rollback_event_id": event_id},
            ),
            (
                bool(_ids_from_value(event.get("review_issue_ids"))),
                "rollback_event_missing_review_issue_ids",
                "rollback_event must reference review_issue_ids",
                f"{path}.review_issue_ids",
                {"rollback_event_id": event_id},
            ),
            (
                bool(event_stale_ids) and event_stale_ids.issubset(covered_ids),
                "rollback_event_missing_stale_source_coverage",
                (
                    "rollback_event affected_artifact_ids/rollback_cone must "
                    "cover the stale source"
                ),
                path,
                {
                    "rollback_event_id": event_id,
                    "stale_source_artifact_ids": sorted(event_stale_ids),
                    "covered_artifact_ids": sorted(covered_ids),
                },
            ),
        )
        checked_count += len(checks)
        for ok, code, message, check_path, details in checks:
            if ok:
                continue
            failed_count += 1
            diagnostics.append(
                _diagnostic(
                    code=code,
                    mechanism="rollback",
                    severity="error",
                    message=message,
                    path=check_path,
                    details=details,
                )
            )

    return _score(
        "rollback",
        diagnostics,
        checked_count=checked_count,
        failed_count=failed_count,
    )


def score_baseline_governance(
    bundle: Mapping[str, Any] | Any,
    *,
    required_families: Iterable[str] = (),
    required_facets: Iterable[str] = (),
) -> MechanismScore:
    payload = _mapping(bundle)
    matrix = payload.get("baseline_matrix")
    matrix_mapping = _mapping(matrix)
    coverage = _mapping(matrix_mapping.get("coverage")) if matrix_mapping else {}
    required_family_ids = _ids_from_value(
        required_families
        or payload.get("required_families")
        or coverage.get("required_families")
    )
    required_facet_ids = _ids_from_value(
        required_facets
        or payload.get("required_facets")
        or coverage.get("required_facets")
    )
    diagnostics: list[MechanismDiagnostic] = []

    checked_count = 1
    failed_count = 0
    if not matrix:
        failed_count += 1
        diagnostics.append(
            _diagnostic(
                code="baseline_matrix_missing",
                mechanism="baseline_governance",
                severity="error",
                message="baseline_governance requires a baseline_matrix",
                path="baseline_matrix",
            )
        )
        matrix_rows: list[Mapping[str, Any]] = []
        matrix_families: set[str] = set()
        matrix_facets: set[str] = set()
    else:
        matrix_rows = _baseline_rows(matrix)
        matrix_families = _baseline_families(matrix, matrix_rows)
        matrix_facets = _baseline_facets(matrix, matrix_rows)

    coverage_checks = (
        (
            "baseline_matrix_missing_required_family",
            "required_family",
            "baseline_matrix does not cover a required family",
            required_family_ids - matrix_families,
        ),
        (
            "baseline_matrix_missing_required_facet",
            "required_facet",
            "baseline_matrix does not cover a required facet",
            required_facet_ids - matrix_facets,
        ),
    )
    for code, detail_key, message, missing_values in coverage_checks:
        checked_count += len(missing_values)
        failed_count += len(missing_values)
        diagnostics.extend(
            _diagnostic(
                code=code,
                mechanism="baseline_governance",
                severity="error",
                message=message,
                path="baseline_matrix",
                details={detail_key: value},
            )
            for value in sorted(missing_values)
        )

    stale_baselines = _stale_baselines(matrix_rows)
    if stale_baselines:
        diagnostics.append(
            _diagnostic(
                code="stale_baseline_detected",
                mechanism="baseline_governance",
                severity="warning",
                message="baseline_matrix marks one or more baselines as stale",
                path="baseline_matrix",
                details={"baseline_ids": stale_baselines},
            )
        )

    if _false_novelty_required(payload):
        checked_count += 1
        if not _false_novelty_gate_reason_present(payload):
            failed_count += 1
            diagnostics.append(
                _diagnostic(
                    code="false_novelty_gate_reason_missing",
                    mechanism="baseline_governance",
                    severity="error",
                    message=(
                        "false-novelty cases require a gate_decision/review_issue "
                        "reason that explicitly records the false novelty finding"
                    ),
                    path="gate_decisions",
                )
            )

    return _score(
        "baseline_governance",
        diagnostics,
        checked_count=checked_count,
        failed_count=failed_count,
    )


def _score(
    mechanism: str,
    diagnostics: list[MechanismDiagnostic],
    *,
    checked_count: int,
    failed_count: int,
) -> MechanismScore:
    total = max(checked_count, 1)
    score = round(max(total - failed_count, 0) / total, 6)
    return MechanismScore(
        mechanism=mechanism,
        score=score,
        passed=not any(item.severity == "error" for item in diagnostics),
        diagnostics=tuple(diagnostics),
        checked_count=checked_count,
        failed_count=failed_count,
    )


def _diagnostic(
    *,
    code: str,
    mechanism: str,
    severity: str,
    message: str,
    path: str = "",
    details: Mapping[str, Any] | None = None,
) -> MechanismDiagnostic:
    return MechanismDiagnostic(
        code=code,
        mechanism=mechanism,
        severity=severity,
        message=message,
        path=path,
        details=dict(details or {}),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict"):
        return _mapping(value.to_dict())
    return asdict(value) if is_dataclass(value) else {}


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return [value]
    return [value]


def _artifacts(payload: Mapping[str, Any]) -> list[_Artifact]:
    artifacts: list[_Artifact] = []
    for key in ("artifacts", "objects"):
        for index, raw_artifact in enumerate(_items(payload.get(key))):
            artifact = _artifact(raw_artifact, path=f"{key}[{index}]")
            if artifact.artifact_id or artifact.artifact_type:
                artifacts.append(artifact)
    if "publication_pack" in payload:
        pack = _artifact(payload.get("publication_pack"), path="publication_pack")
        artifact_id = (
            pack.artifact_id
            or _id_value(
                payload,
                ("publication_pack_artifact_id", "publication_pack_id"),
            )
            or "publication_pack"
        )
        artifacts.append(
            _Artifact(
                artifact_id=artifact_id,
                artifact_type=pack.artifact_type or "publication_pack",
                payload=pack.payload,
                path=pack.path,
            )
        )
    return artifacts


def _artifact(value: Any, *, path: str) -> _Artifact:
    payload = _mapping(value)
    return _Artifact(
        artifact_id=_id_value(
            payload,
            ("artifact_id", "object_id", "id", "publication_pack_artifact_id"),
        ),
        artifact_type=_id_value(
            payload,
            ("artifact_type", "object_type", "type", "schema_version"),
        ),
        payload=payload,
        path=path,
    )


def _is_publication_pack(artifact: _Artifact) -> bool:
    artifact_type = artifact.artifact_type.lower()
    if artifact_type == "publication_pack":
        return True
    if "publication_pack" in artifact_type:
        return True
    return artifact.artifact_id.lower().startswith("publication_pack")


def _dependency_edges(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    edges: list[Mapping[str, Any]] = []
    for key in ("dependencies", "dependency_edges", "artifact_dependencies", "edges"):
        for raw_edge in _items(payload.get(key)):
            edge = _mapping(raw_edge)
            if edge:
                edges.append(edge)
    return edges


def _has_dependency_trace(
    publication_pack: _Artifact,
    dependency_edges: list[Mapping[str, Any]],
    artifacts: list[_Artifact],
) -> bool:
    valid_source_ids = _valid_trace_source_ids(artifacts, publication_pack)
    for edge in dependency_edges:
        target_id = _id_value(
            edge,
            (
                "target_artifact_id",
                "target_object_id",
                "target",
                "to",
                "artifact_id",
            ),
        )
        source_id = _id_value(
            edge,
            (
                "source_artifact_id",
                "source_object_id",
                "source",
                "from",
                "dependency_artifact_id",
                "depends_on_artifact_id",
            ),
        )
        relation = _id_value(
            edge,
            ("dependency_type", "edge_type", "relation", "rel", "type"),
        ).lower()
        if (
            target_id == publication_pack.artifact_id
            and source_id
            and source_id in valid_source_ids
            and (not relation or relation in TRACE_DEPENDENCY_TYPES)
        ):
            return True
    return False


def _has_payload_trace(
    publication_pack: _Artifact,
    artifacts: list[_Artifact],
) -> bool:
    valid_source_ids = _valid_trace_source_ids(artifacts, publication_pack)
    ref_ids = _trace_ref_ids(publication_pack.payload) | _trace_ref_ids(
        _mapping(publication_pack.payload.get("payload"))
    )
    return bool(ref_ids) and ref_ids.issubset(valid_source_ids)


def _trace_ref_ids(payload: Mapping[str, Any]) -> set[str]:
    ref_ids: set[str] = set()
    for key, value in payload.items():
        if str(key) in TRACE_REF_KEYS:
            ref_ids.update(_ids_from_value(value))
    return ref_ids


def _valid_trace_source_ids(
    artifacts: list[_Artifact],
    publication_pack: _Artifact,
) -> set[str]:
    valid_ids: set[str] = set()
    for artifact in artifacts:
        if artifact.artifact_id == publication_pack.artifact_id:
            continue
        state = _id_value(artifact.payload, ("state", "status", "reliability_state"))
        risk_flags = {
            flag.lower() for flag in _ids_from_value(artifact.payload.get("risk_flags"))
        }
        if state.lower() in STALE_STATES or "stale" in risk_flags:
            continue
        if artifact.artifact_type not in TRACE_SOURCE_ARTIFACT_TYPES:
            continue
        if artifact.artifact_id:
            valid_ids.add(artifact.artifact_id)
    return valid_ids


def _trace_blockers(
    publication_pack: _Artifact,
    gate_decisions: list[Any],
    review_issues: list[Any],
) -> list[str]:
    blockers: list[str] = []
    for index, raw_gate in enumerate(gate_decisions):
        gate = _mapping(raw_gate)
        verdict = _id_value(gate, ("verdict", "gate_verdict", "status")).lower()
        if verdict not in BLOCKING_GATE_VERDICTS:
            continue
        if _targets_publication_pack(gate, publication_pack) or _mentions_trace(gate):
            blockers.append(
                _id_value(
                    gate,
                    ("gate_decision_artifact_id", "gate_id", "artifact_id", "id"),
                )
                or f"gate_decisions[{index}]"
            )
    for index, raw_issue in enumerate(review_issues):
        issue = _mapping(raw_issue)
        status = _id_value(issue, ("status", "state", "verdict")).lower()
        if status and status not in BLOCKING_REVIEW_STATUSES:
            continue
        if _targets_publication_pack(issue, publication_pack) or _mentions_trace(issue):
            blockers.append(
                _id_value(issue, ("review_issue_id", "issue_id", "artifact_id", "id"))
                or f"review_issues[{index}]"
            )
    return blockers


def _targets_publication_pack(
    item: Mapping[str, Any], publication_pack: _Artifact
) -> bool:
    target_ids = _ids_from_value(
        item.get("target_artifact_ids")
        or item.get("target_object_ids")
        or item.get("target_artifacts")
        or item.get("targets")
        or item.get("invalidated_object_ids")
    )
    return publication_pack.artifact_id in target_ids


def _mentions_trace(item: Mapping[str, Any]) -> bool:
    haystack = _flatten_text(item)
    return "artifact_trace" in haystack or "missing_artifact_trace" in haystack


def _stale_source_ids(payload: Mapping[str, Any]) -> set[str]:
    stale_ids = set(
        _ids_from_value(
            payload.get("stale_source_artifact_ids")
            or payload.get("stale_artifact_ids")
            or payload.get("stale_sources")
        )
    )
    for artifact in _artifacts(payload):
        state = _id_value(artifact.payload, ("state", "status", "reliability_state"))
        risk_flags = _ids_from_value(artifact.payload.get("risk_flags"))
        if state.lower() in STALE_STATES or "stale" in {
            flag.lower() for flag in risk_flags
        }:
            stale_ids.add(artifact.artifact_id)
    return {item for item in stale_ids if item}


def _event_stale_source_ids(event: Mapping[str, Any]) -> set[str]:
    return _ids_from_value(
        event.get("stale_source_artifact_ids")
        or event.get("stale_source_artifact_id")
        or event.get("stale_source_ids")
        or event.get("stale_source")
        or event.get("trigger_artifact_id")
        or event.get("trigger_artifact_ids")
        or event.get("trigger_object_id")
        or event.get("trigger_object_ids")
    )


def _rollback_cone_ids(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        cone = _mapping(value)
        return _ids_from_value(
            cone.get("affected_artifact_ids")
            or cone.get("affected_object_ids")
            or cone.get("affected_artifacts")
            or cone.get("affected_objects")
            or cone.get("rollback_cone")
        )
    return _ids_from_value(value)


def _baseline_rows(matrix: Any) -> list[Mapping[str, Any]]:
    if isinstance(matrix, Mapping):
        for key in ("rows", "baselines", "entries"):
            rows = matrix.get(key)
            if rows:
                return [_mapping(row) for row in _items(rows) if _mapping(row)]
        families = matrix.get("families")
        if isinstance(families, Mapping):
            rows: list[Mapping[str, Any]] = []
            for family, value in families.items():
                if not _has_value(value):
                    continue
                row = dict(_mapping(value))
                row.setdefault("family", str(family))
                rows.append(row)
            return rows
        return [_mapping(matrix)]
    return [_mapping(row) for row in _items(matrix) if _mapping(row)]


def _baseline_families(
    matrix: Any,
    rows: list[Mapping[str, Any]],
) -> set[str]:
    families: set[str] = set()
    if isinstance(matrix, Mapping) and isinstance(matrix.get("families"), Mapping):
        families.update(
            str(family)
            for family, value in matrix["families"].items()
            if _has_value(value)
        )
    for row in rows:
        family = _id_value(row, ("family", "method_family", "baseline_family"))
        if family:
            families.add(family)
    return families


def _baseline_facets(
    matrix: Any,
    rows: list[Mapping[str, Any]],
) -> set[str]:
    facets: set[str] = set()
    if isinstance(matrix, Mapping):
        facets.update(_ids_from_value(matrix.get("facets")))
        coverage = matrix.get("coverage")
        if isinstance(coverage, Mapping):
            facets.update(_ids_from_value(coverage.get("covered_facets")))
    for row in rows:
        facets.update(_ids_from_value(row.get("facet") or row.get("facet_id")))
        row_facets = row.get("facets")
        if isinstance(row_facets, Mapping):
            facets.update(
                str(key) for key, value in row_facets.items() if _has_value(value)
            )
        else:
            facets.update(_ids_from_value(row_facets))
    return facets


def _stale_baselines(rows: list[Mapping[str, Any]]) -> list[str]:
    stale_ids: list[str] = []
    for index, row in enumerate(rows):
        state = _id_value(row, ("state", "status", "reliability_state")).lower()
        risk_flags = {flag.lower() for flag in _ids_from_value(row.get("risk_flags"))}
        is_stale = (
            bool(row.get("stale")) or state in STALE_STATES or "stale" in risk_flags
        )
        if is_stale:
            stale_ids.append(
                _id_value(row, ("baseline_id", "artifact_id", "id", "object_id"))
                or f"baseline_matrix[{index}]"
            )
    return stale_ids


def _false_novelty_required(payload: Mapping[str, Any]) -> bool:
    if bool(
        payload.get("expected_false_novelty")
        or payload.get("false_novelty_expected")
        or payload.get("novelty_claimed")
    ):
        return True
    for key in ("corrupted_case_ids", "expected_findings", "required_gate_reasons"):
        if _contains_false_novelty(payload.get(key)):
            return True
    return False


def _false_novelty_gate_reason_present(payload: Mapping[str, Any]) -> bool:
    gate_decisions = _items(
        payload.get("gate_decisions") or payload.get("gate_decision")
    )
    review_issues = _items(payload.get("review_issues") or payload.get("review_issue"))
    return any(
        _contains_false_novelty(item) for item in [*gate_decisions, *review_issues]
    )


def _contains_false_novelty(value: Any) -> bool:
    haystack = _flatten_text(value)
    return any(token in haystack for token in FALSE_NOVELTY_TOKENS)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, Mapping):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value).lower()


def _ids_from_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, Mapping):
        ids: set[str] = set()
        for key, item in value.items():
            if isinstance(item, (str, int, float)) and item:
                ids.add(str(item))
            elif item:
                ids.add(str(key))
        return ids
    if isinstance(value, (list, tuple, set, frozenset)):
        ids: set[str] = set()
        for item in value:
            if isinstance(item, Mapping):
                item_id = _id_value(
                    item,
                    ("artifact_id", "object_id", "baseline_id", "id", "ref"),
                )
                if item_id:
                    ids.add(item_id)
            elif item is not None and item != "":
                ids.add(str(item))
        return ids
    return {str(value)} if value else set()


def _id_value(payload: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return str(value)
    return ""


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_has_value(item) for item in value)
    return bool(value)


def _mean(values: Iterable[float]) -> float:
    collected = tuple(values)
    return round(sum(collected) / len(collected), 6) if collected else 0.0
