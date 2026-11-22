"""Project-level self-evolution for Research Harness itself.

v1 intentionally exposes only the MVP loop:

- manual archive runs from durable evaluation artifacts;
- champion registry selection from promotion replay evidence;
- deterministic PDF/final-bundle replay gates.

Higher-order feedback triage, reference-library planning, multi-route review
guidance, and skill-bank lifecycle management are future work documented under
``docs/research/`` rather than executable source.
"""

from .archive import (
    build_candidate_archive_record,
    build_candidate_archive_pack_payload,
    build_candidate_archive_record_from_researchflowbench_score,
    build_candidate_archive_records_from_researchflowbench_scores,
    build_champion_registry_entries,
    build_champion_registry_entry,
    build_champion_registry_pack_payload,
    build_replay_split,
    candidate_archive_record_from_payload,
    candidate_archive_record_to_payload,
    record_candidate_archive_pack,
    record_champion_registry_pack,
)
from .collectors import (
    collect_candidate_archive_records_from_artifacts,
    collect_final_bundle_replay_discovery_report,
    collect_final_bundle_replay_signals,
    collect_pdf_quality_signals_from_final_bundles,
    collect_pdf_quality_replay_trajectory,
    record_self_evolution_archive_from_artifacts,
    record_final_bundle_replay_discovery_report,
)
from .models import (
    CandidateArchiveRecord,
    ChampionRegistryEntry,
    EvidenceReference,
    EvolutionFinding,
    FinalBundleReplayCandidate,
    FinalBundleReplayDiscoveryReport,
    ImprovementCandidate,
    PDFQualityIssue,
    PDFQualityReplayTrajectory,
    PDFQualitySignal,
    PDFQualityTrajectoryGateResult,
    PDFQualityTrajectoryPoint,
    RecommendedAction,
    ReplaySplit,
)
from .pdf_quality import scan_pdf_quality_bundle, triage_pdf_quality_signal
from .trajectory_gate import (
    DEFAULT_PDF_QUALITY_TRAJECTORY_THRESHOLDS,
    evaluate_pdf_quality_replay_trajectory,
    record_pdf_quality_trajectory_gate_report,
)

__all__ = [
    "DEFAULT_PDF_QUALITY_TRAJECTORY_THRESHOLDS",
    "CandidateArchiveRecord",
    "ChampionRegistryEntry",
    "EvidenceReference",
    "EvolutionFinding",
    "FinalBundleReplayCandidate",
    "FinalBundleReplayDiscoveryReport",
    "ImprovementCandidate",
    "PDFQualityIssue",
    "PDFQualityReplayTrajectory",
    "PDFQualitySignal",
    "PDFQualityTrajectoryGateResult",
    "PDFQualityTrajectoryPoint",
    "RecommendedAction",
    "ReplaySplit",
    "build_candidate_archive_record",
    "build_candidate_archive_pack_payload",
    "build_candidate_archive_record_from_researchflowbench_score",
    "build_candidate_archive_records_from_researchflowbench_scores",
    "build_champion_registry_entries",
    "build_champion_registry_entry",
    "build_champion_registry_pack_payload",
    "build_replay_split",
    "candidate_archive_record_from_payload",
    "candidate_archive_record_to_payload",
    "collect_candidate_archive_records_from_artifacts",
    "collect_final_bundle_replay_discovery_report",
    "collect_final_bundle_replay_signals",
    "collect_pdf_quality_signals_from_final_bundles",
    "collect_pdf_quality_replay_trajectory",
    "evaluate_pdf_quality_replay_trajectory",
    "record_final_bundle_replay_discovery_report",
    "record_self_evolution_archive_from_artifacts",
    "record_candidate_archive_pack",
    "record_champion_registry_pack",
    "record_pdf_quality_trajectory_gate_report",
    "scan_pdf_quality_bundle",
    "triage_pdf_quality_signal",
]
