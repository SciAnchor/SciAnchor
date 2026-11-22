"""Data models for project-level Research Harness self-evolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Priority = Literal["P0", "P1", "P2", "P3"]
CandidateStatus = Literal[
    "needs_verification",
    "verified",
    "rejected",
    "needs_human_approval",
    "implemented",
]
GateAction = Literal["accept", "reject", "needs_human_approval"]
ArchiveGateAction = Literal[
    "accept",
    "reject",
    "needs_human_approval",
    "promote",
    "evaluate",
    "refine",
]


@dataclass(frozen=True)
class PDFQualityIssue:
    """A deterministic issue found in a final PDF/TeX bundle."""

    category: str
    severity: str
    message: str
    source_path: str = ""
    line_number: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PDFQualitySignal:
    """Quality signal for a compiled publication bundle."""

    topic_id: int = 0
    target_profile: str = ""
    tex_path: str = ""
    pdf_path: str = ""
    log_path: str = ""
    artifact_id: int = 0
    issues: tuple[PDFQualityIssue, ...] = ()
    transcript_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PDFQualityTrajectoryPoint:
    """Durable historical PDF-quality snapshot for one final_bundle artifact."""

    artifact_id: int
    topic_id: int = 0
    target_profile: str = ""
    evidence_source: str = ""
    issue_count: int = 0
    blocking_issue_count: int = 0
    recompile_repairable_issue_count: int = 0
    layout_issue_count: int = 0
    encoding_issue_count: int = 0
    overfull_hbox_count: int = 0
    underfull_hbox_count: int = 0
    invalid_utf8_count: int = 0
    malformed_latex_command_count: int = 0
    path_scan_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PDFQualityReplayTrajectory:
    """Path-safe replay trajectory assembled from durable PDF-quality evidence."""

    topic_id: int
    target_profile: str = ""
    points: tuple[PDFQualityTrajectoryPoint, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PDFQualityTrajectoryGateResult:
    """Threshold decision for a PDF quality replay trajectory."""

    action: str
    passed: bool
    reasons: tuple[str, ...] = ()
    checked_artifact_ids: tuple[int, ...] = ()
    thresholds: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalBundleReplayCandidate:
    """Candidate active final_bundle considered for held-out replay."""

    artifact_id: int
    topic_id: int
    target_profile: str = ""
    accepted: bool = False
    exclusion_reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalBundleReplayDiscoveryReport:
    """Diagnostic report explaining held-out final_bundle replay availability."""

    source_topic_id: int = 0
    source_artifact_ids: tuple[int, ...] = ()
    target_profiles: tuple[str, ...] = ()
    candidates: tuple[FinalBundleReplayCandidate, ...] = ()
    accepted_artifact_ids: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceReference:
    """Pointer to local or external evidence supporting a finding."""

    ref: str
    source_type: str = "local"
    note: str = ""


@dataclass(frozen=True)
class RecommendedAction:
    """A concrete action proposed before or during implementation."""

    action_type: str
    description: str
    target_surface: str = ""
    required_before_patch: bool = False


@dataclass(frozen=True)
class EvolutionFinding:
    """Structured project-level problem or opportunity."""

    finding_id: str
    source_kind: str
    category: str
    priority: Priority
    summary: str
    affected_surfaces: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceReference, ...] = ()
    recommended_actions: tuple[RecommendedAction, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImprovementCandidate:
    """A manually reviewed candidate archived with replay evidence."""

    candidate_id: str
    finding_id: str
    title: str
    target_kind: str
    affected_surfaces: tuple[str, ...] = ()
    priority_score: int = 0
    verification_plan: tuple[str, ...] = ()
    status: CandidateStatus = "needs_verification"
    patch_allowed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplaySplit:
    """Replay references assigned to source/dev/promotion roles for a candidate."""

    candidate_id: str
    source_refs: tuple[str, ...] = ()
    mutate_dev_refs: tuple[str, ...] = ()
    promotion_test_refs: tuple[str, ...] = ()
    held_out_refs: tuple[str, ...] = ()
    incubating: bool = False
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateArchiveRecord:
    """Durable archive view of one self-evolution candidate."""

    candidate_id: str
    finding_id: str
    target_kind: str
    status: CandidateStatus
    priority_score: int = 0
    affected_surfaces: tuple[str, ...] = ()
    rh_axis_ids: tuple[str, ...] = ()
    replay_split: ReplaySplit | None = None
    gate_action: ArchiveGateAction | str = ""
    gate_reasons: tuple[str, ...] = ()
    parent_candidate_id: str = ""
    champion_candidate_id: str = ""
    artifact_refs: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    cost_quality_telemetry: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChampionRegistryEntry:
    """Current champion pointer for one evolvable RH surface."""

    target_kind: str
    champion_candidate_id: str
    finding_id: str
    rh_axis_ids: tuple[str, ...] = ()
    replay_refs: tuple[str, ...] = ()
    promotion_strength: str = ""
    artifact_refs: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationGateResult:
    """Decision from candidate verification policy."""

    candidate_id: str
    action: GateAction
    reasons: tuple[str, ...] = ()
