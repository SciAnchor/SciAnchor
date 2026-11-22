"""Private manuscript logic gate helpers for RH paper-writing self-development.

The gate validates writing architecture artifacts before section drafting. It
does not draft prose, call LLMs, touch storage, or add a public surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


CORE_CLAIM_CONTRACT_SCHEMA_VERSION = "rh.manuscript.core_claim_contract.v1"
ARGUMENT_TREE_SCHEMA_VERSION = "rh.manuscript.argument_tree.v1"
TERM_REGISTRY_SCHEMA_VERSION = "rh.manuscript.term_registry.v1"
PROMISE_REALIZATION_MATRIX_SCHEMA_VERSION = (
    "rh.manuscript.promise_realization_matrix.v1"
)
PARAGRAPH_INTENT_TREE_SCHEMA_VERSION = "rh.manuscript.paragraph_intent_tree.v1"
FINE_LOGIC_AUDIT_SCHEMA_VERSION = "rh.manuscript.fine_logic_audit.v1"
FINE_LOGIC_AUDIT_REPORT_SCHEMA_VERSION = "rh.manuscript.fine_logic_audit_report.v1"
MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION = "rh.manuscript.logic_bundle.v1"


@dataclass(frozen=True)
class ManuscriptLogicGateReport:
    schema_version: str
    status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        payload["metrics"] = dict(self.metrics)
        return payload


@dataclass(frozen=True)
class FineLogicAuditReport:
    schema_version: str
    status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        payload["metrics"] = dict(self.metrics)
        return payload


def evaluate_manuscript_logic_bundle(
    bundle: Mapping[str, Any],
) -> ManuscriptLogicGateReport:
    """Validate a manuscript logic bundle before paper-scale drafting."""

    blockers: list[str] = []
    warnings: list[str] = []

    if _text(bundle.get("schema_version")) != MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION:
        blockers.append("schema_version:manuscript_logic_bundle")

    core_claim = _mapping(bundle.get("core_claim_contract"))
    argument_tree = _mapping(bundle.get("argument_tree"))
    term_registry = _list_of_mappings(bundle.get("term_registry"))
    promise_matrix = _list_of_mappings(bundle.get("promise_realization_matrix"))
    paragraph_tree = _list_of_mappings(bundle.get("paragraph_intent_tree"))
    fine_logic_audit = _mapping(bundle.get("fine_logic_audit"))
    fine_report = evaluate_fine_logic_audit(fine_logic_audit)

    blockers.extend(_validate_core_claim_contract(core_claim))
    blockers.extend(_validate_argument_tree(argument_tree))
    blockers.extend(_validate_term_registry(term_registry))
    blockers.extend(_validate_promise_matrix(promise_matrix))
    blockers.extend(_validate_paragraph_tree(paragraph_tree, term_registry))
    blockers.extend(fine_report.blockers)

    metrics = {
        "problem_count": len(_list_of_mappings(argument_tree.get("problems"))),
        "term_count": len(term_registry),
        "promise_count": len(promise_matrix),
        "paragraph_count": len(paragraph_tree),
        "side_claim_count": sum(
            1 for paragraph in paragraph_tree if paragraph.get("serves_claim") is False
        ),
        **fine_report.metrics,
    }

    if metrics["problem_count"] == 0:
        blockers.append("missing:argument_tree.problems")
    if metrics["term_count"] == 0:
        blockers.append("missing:term_registry")
    if metrics["promise_count"] == 0:
        warnings.append("empty:promise_realization_matrix")
    if metrics["paragraph_count"] == 0:
        blockers.append("missing:paragraph_intent_tree")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return ManuscriptLogicGateReport(
        schema_version="rh.manuscript.logic_gate_report.v1",
        status="pass" if not unique_blockers else "block",
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        metrics=metrics,
    )


def evaluate_fine_logic_audit(
    fine_logic_audit: Mapping[str, Any],
) -> FineLogicAuditReport:
    """Validate the fine-grained argument audit portion of a manuscript plan."""

    blockers = _validate_fine_logic_audit(fine_logic_audit)
    metrics = _fine_logic_metrics(fine_logic_audit)
    if metrics["argument_link_count"] == 0:
        blockers.append("missing:fine_logic.argument_link_map")
    if metrics["claim_certainty_count"] == 0:
        blockers.append("missing:fine_logic.claim_certainty_audit")
    if metrics["paragraph_flow_count"] == 0:
        blockers.append("missing:fine_logic.paragraph_flow_audit")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return FineLogicAuditReport(
        schema_version=FINE_LOGIC_AUDIT_REPORT_SCHEMA_VERSION,
        status="pass" if not unique_blockers else "block",
        blockers=unique_blockers,
        warnings=(),
        metrics=metrics,
    )


def _fine_logic_metrics(fine_logic_audit: Mapping[str, Any]) -> dict[str, int]:
    return {
        "argument_link_count": len(
            _list_of_mappings(fine_logic_audit.get("argument_link_map"))
        ),
        "assumption_count": len(
            _list_of_mappings(fine_logic_audit.get("assumption_warrant_table"))
        ),
        "claim_certainty_count": len(
            _list_of_mappings(fine_logic_audit.get("claim_certainty_audit"))
        ),
        "paragraph_flow_count": len(
            _list_of_mappings(fine_logic_audit.get("paragraph_flow_audit"))
        ),
        "figure_table_message_count": len(
            _list_of_mappings(fine_logic_audit.get("figure_table_message_audit"))
        ),
        "writing_defect_count": len(
            _list_of_mappings(fine_logic_audit.get("writing_defect_log"))
        ),
    }


def _validate_core_claim_contract(core_claim: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if _text(core_claim.get("schema_version")) not in {
        "",
        CORE_CLAIM_CONTRACT_SCHEMA_VERSION,
    }:
        blockers.append("schema_version:core_claim_contract")

    required_text_fields = (
        "one_sentence_claim",
        "central_problem",
        "paper_type",
        "target_venue",
    )
    for field in required_text_fields:
        if not _text(core_claim.get(field)):
            blockers.append(f"missing:core_claim_contract.{field}")

    allowed_focus = _text_list(core_claim.get("allowed_focus"))
    if not allowed_focus:
        blockers.append("missing:core_claim_contract.allowed_focus")
    if len(allowed_focus) > 3:
        blockers.append("too_many:core_claim_contract.allowed_focus")

    one_sentence_claim = _text(core_claim.get("one_sentence_claim"))
    if one_sentence_claim and _sentence_count(one_sentence_claim) > 1:
        blockers.append("too_many:core_claim_contract.one_sentence_claim.sentences")
    if len(one_sentence_claim.split()) > 45:
        blockers.append("too_long:core_claim_contract.one_sentence_claim")

    return blockers


def _validate_argument_tree(argument_tree: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if _text(argument_tree.get("schema_version")) not in {
        "",
        ARGUMENT_TREE_SCHEMA_VERSION,
    }:
        blockers.append("schema_version:argument_tree")
    if not _text(argument_tree.get("root_claim")):
        blockers.append("missing:argument_tree.root_claim")

    problems = _list_of_mappings(argument_tree.get("problems"))
    if len(problems) > 3:
        blockers.append("too_many:argument_tree.problems")

    contribution_ids: set[str] = set()
    for index, problem in enumerate(problems, start=1):
        problem_id = _text(problem.get("problem_id")) or f"index_{index}"
        if not _text(problem.get("statement")):
            blockers.append(f"missing:argument_tree.problem.{problem_id}.statement")
        contribution_id = _text(problem.get("contribution_id"))
        if not contribution_id:
            blockers.append(
                f"missing:argument_tree.problem.{problem_id}.contribution_id"
            )
        elif contribution_id in contribution_ids:
            blockers.append(f"duplicate:argument_tree.contribution.{contribution_id}")
        else:
            contribution_ids.add(contribution_id)
        if not _text_list(problem.get("evidence_ids")):
            blockers.append(f"missing:argument_tree.problem.{problem_id}.evidence_ids")
        if not _text_list(problem.get("section_ids")):
            blockers.append(f"missing:argument_tree.problem.{problem_id}.section_ids")

    return blockers


def _validate_term_registry(term_registry: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    seen_terms: set[str] = set()
    for entry in term_registry:
        term = _text(entry.get("term"))
        if not term:
            blockers.append("missing:term_registry.term")
            continue
        normalized = _normalize_term(term)
        if normalized in seen_terms:
            blockers.append(f"duplicate:term_registry.{term}")
        seen_terms.add(normalized)
        if not _text(entry.get("definition")):
            blockers.append(f"missing:term_registry.{term}.definition")
        if not _text(entry.get("first_use")):
            blockers.append(f"missing:term_registry.{term}.first_use")
        for alias in _text_list(entry.get("allowed_aliases")):
            if _normalize_term(alias) == normalized:
                blockers.append(f"self_alias:term_registry.{term}.{alias}")
    return blockers


def _validate_promise_matrix(promise_matrix: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for index, promise in enumerate(promise_matrix, start=1):
        label = _text(promise.get("promise")) or f"index_{index}"
        promise_key = label
        if not _text(promise.get("made_in")):
            blockers.append(f"missing:promise.{promise_key}.made_in")
        if not _text_list(promise.get("realized_by")):
            blockers.append(f"unrealized:promise.{promise_key}")
        if not _text_list(promise.get("evidence_ids")):
            blockers.append(f"missing:promise.{promise_key}.evidence_ids")
    return blockers


def _validate_paragraph_tree(
    paragraph_tree: list[Mapping[str, Any]],
    term_registry: list[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    allowed_terms = _allowed_terms(term_registry)
    forbidden_terms = _forbidden_terms(term_registry)

    for index, paragraph in enumerate(paragraph_tree, start=1):
        paragraph_id = _text(paragraph.get("paragraph_id")) or f"index_{index}"
        if not _text(paragraph.get("section")):
            blockers.append(f"missing:paragraph.{paragraph_id}.section")
        if not _text(paragraph.get("intent")):
            blockers.append(f"missing:paragraph.{paragraph_id}.intent")
        if paragraph.get("serves_claim") is not True:
            blockers.append(f"side_claim:paragraph.{paragraph_id}")
        for term in _text_list(paragraph.get("allowed_terms")):
            normalized = _normalize_term(term)
            if normalized not in allowed_terms or normalized in forbidden_terms:
                blockers.append(
                    f"undefined_or_forbidden:paragraph.{paragraph_id}.term.{term}"
                )
    return blockers


def _validate_fine_logic_audit(fine_logic_audit: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not fine_logic_audit:
        return ["missing:fine_logic_audit"]
    if _text(fine_logic_audit.get("schema_version")) not in {
        "",
        FINE_LOGIC_AUDIT_SCHEMA_VERSION,
    }:
        blockers.append("schema_version:fine_logic_audit")

    blockers.extend(
        _validate_argument_link_map(
            _list_of_mappings(fine_logic_audit.get("argument_link_map"))
        )
    )
    blockers.extend(
        _validate_assumption_warrant_table(
            _list_of_mappings(fine_logic_audit.get("assumption_warrant_table"))
        )
    )
    blockers.extend(
        _validate_claim_certainty_audit(
            _list_of_mappings(fine_logic_audit.get("claim_certainty_audit"))
        )
    )
    blockers.extend(
        _validate_paragraph_flow_audit(
            _list_of_mappings(fine_logic_audit.get("paragraph_flow_audit"))
        )
    )
    blockers.extend(
        _validate_intro_logic_map(_mapping(fine_logic_audit.get("intro_logic_map")))
    )
    blockers.extend(
        _validate_figure_table_message_audit(
            _list_of_mappings(fine_logic_audit.get("figure_table_message_audit"))
        )
    )
    blockers.extend(
        _validate_writing_defect_log(
            _list_of_mappings(fine_logic_audit.get("writing_defect_log"))
        )
    )
    return blockers


def _validate_argument_link_map(arguments: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for index, argument in enumerate(arguments, start=1):
        claim_id = _text(argument.get("claim_id")) or f"index_{index}"
        for field in ("claim", "grounds", "warrant", "qualifier"):
            if not _text(argument.get(field)):
                blockers.append(f"missing:fine_logic.argument.{claim_id}.{field}")
        if not _text_list(argument.get("evidence_ids")):
            blockers.append(f"missing:fine_logic.argument.{claim_id}.evidence_ids")
        if not _text(argument.get("backing")) and not _text_list(
            argument.get("backing_evidence_ids")
        ):
            blockers.append(f"missing:fine_logic.argument.{claim_id}.backing")
        if not _text(argument.get("rebuttal_or_alternative")):
            blockers.append(
                f"missing:fine_logic.argument.{claim_id}.rebuttal_or_alternative"
            )
        if not _text_list(argument.get("paragraph_ids")):
            blockers.append(f"missing:fine_logic.argument.{claim_id}.paragraph_ids")
    return blockers


def _validate_assumption_warrant_table(
    assumptions: list[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    for index, assumption in enumerate(assumptions, start=1):
        assumption_id = _text(assumption.get("assumption_id")) or f"index_{index}"
        for field in ("assumption", "why_needed", "where_to_state", "risk_if_omitted"):
            if not _text(assumption.get(field)):
                blockers.append(
                    f"missing:fine_logic.assumption.{assumption_id}.{field}"
                )
        if not _text_list(assumption.get("backing_evidence_ids")):
            blockers.append(
                f"missing:fine_logic.assumption.{assumption_id}.backing_evidence_ids"
            )
    return blockers


def _validate_claim_certainty_audit(claims: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    certainty_rank = {
        "unsupported": 0,
        "tentative": 1,
        "bounded": 2,
        "strong": 3,
        "universal": 4,
    }
    for index, claim in enumerate(claims, start=1):
        claim_id = _text(claim.get("claim_id")) or f"index_{index}"
        for field in (
            "claim",
            "evidence_strength",
            "allowed_certainty",
            "actual_certainty",
            "status",
        ):
            if not _text(claim.get(field)):
                blockers.append(
                    f"missing:fine_logic.claim_certainty.{claim_id}.{field}"
                )

        status = _normalize_term(claim.get("status"))
        if status == "overclaim":
            blockers.append(f"overclaim:fine_logic.claim_certainty.{claim_id}")

        allowed = _normalize_term(claim.get("allowed_certainty"))
        actual = _normalize_term(claim.get("actual_certainty"))
        if certainty_rank.get(actual, -1) > certainty_rank.get(allowed, -1):
            blockers.append(
                f"mismatch:fine_logic.claim_certainty.{claim_id}.actual_exceeds_allowed"
            )
    return blockers


def _validate_paragraph_flow_audit(flows: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for index, flow in enumerate(flows, start=1):
        paragraph_id = _text(flow.get("paragraph_id")) or f"index_{index}"
        for field in (
            "topic_sentence",
            "old_info_link",
            "new_stress_info",
            "transition_relation",
        ):
            if not _text(flow.get(field)):
                blockers.append(
                    f"missing:fine_logic.paragraph_flow.{paragraph_id}.{field}"
                )
        if flow.get("signal_word_valid") is not True:
            blockers.append(
                f"invalid:fine_logic.paragraph_flow.{paragraph_id}.signal_word"
            )
        if len(_text_list(flow.get("chain"))) < 2:
            blockers.append(f"too_short:fine_logic.paragraph_flow.{paragraph_id}.chain")
        if _normalize_term(flow.get("status")) in {"block", "broken", "fail"}:
            blockers.append(f"broken:fine_logic.paragraph_flow.{paragraph_id}")
    return blockers


def _validate_intro_logic_map(intro_logic_map: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not intro_logic_map:
        return ["missing:fine_logic.intro_logic_map"]
    for field in (
        "problem_relevance",
        "problem_hardness",
        "prior_shortcomings",
        "keen_insight",
        "technical_challenges",
        "validation_plan",
        "assessment",
    ):
        if not _text(intro_logic_map.get(field)):
            blockers.append(f"missing:fine_logic.intro_logic_map.{field}")
    return blockers


def _validate_figure_table_message_audit(
    assets: list[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    for index, asset in enumerate(assets, start=1):
        asset_id = _text(asset.get("asset_id")) or f"index_{index}"
        for field in ("asset_type", "intended_message", "major_finding"):
            if not _text(asset.get(field)):
                blockers.append(f"missing:fine_logic.figure_table.{asset_id}.{field}")
        if not _text_list(asset.get("supports_claim_ids")):
            blockers.append(
                f"missing:fine_logic.figure_table.{asset_id}.supports_claim_ids"
            )
        if not _text_list(asset.get("evidence_ids")):
            blockers.append(f"missing:fine_logic.figure_table.{asset_id}.evidence_ids")
        if _normalize_term(asset.get("status")) in {"block", "broken", "fail"}:
            blockers.append(f"broken:fine_logic.figure_table.{asset_id}")
    return blockers


def _validate_writing_defect_log(defects: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for index, defect in enumerate(defects, start=1):
        defect_id = _text(defect.get("defect_id")) or f"index_{index}"
        severity = _normalize_term(defect.get("severity"))
        status = _normalize_term(defect.get("status"))
        if severity in {"blocker", "critical"} and status not in {
            "fixed",
            "accepted",
            "waived",
        }:
            blockers.append(f"unresolved:fine_logic.defect.{defect_id}")
    return blockers


def _allowed_terms(term_registry: list[Mapping[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for entry in term_registry:
        term = _text(entry.get("term"))
        if term:
            terms.add(_normalize_term(term))
        for alias in _text_list(entry.get("allowed_aliases")):
            terms.add(_normalize_term(alias))
    return terms


def _forbidden_terms(term_registry: list[Mapping[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for entry in term_registry:
        for alias in _text_list(entry.get("forbidden_aliases")):
            terms.add(_normalize_term(alias))
    return terms


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _text_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _sentence_count(value: str) -> int:
    endings = {".", "?", "!", "。", "？", "！"}
    return sum(1 for char in value if char in endings)


def _normalize_term(value: str) -> str:
    return _text(value).casefold()
