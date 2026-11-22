#!/usr/bin/env python3
"""Private supervised Codex/RH paper-production E2E harness.

This script is intentionally private test tooling. It runs a Worker Codex
process to produce a manuscript, runs mechanical quality checks, then runs an
independent Supervisor Codex process as a human-in-the-loop proxy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import textwrap
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "AGENTS.md").exists() and (p / "packages").exists()
)
DEFAULT_DATASET = (
    REPO_ROOT
    / "packages/research_harness/tests/fixtures/writing/"
    "e2e_paper_generation_dataset.json"
)
DEFAULT_RUN_ROOT = REPO_ROOT / ".research-harness/supervised-paper-e2e-runs"

TRACE_SCHEMA_VERSION = "rh.supervised_paper_e2e_trace.v1"
PDF_REPORT_SCHEMA_VERSION = "rh.supervised_paper_e2e_pdf_quality.v1"
GOLD_REPORT_SCHEMA_VERSION = "rh.supervised_paper_e2e_gold_eval.v1"
SELF_DEV_SCHEMA_VERSION = "rh.supervised_paper_e2e_self_dev_candidates.v1"

REQUIRED_SECTION_PATTERNS = {
    "abstract": r"\babstract\b",
    "introduction": r"\bintroduction\b",
    "related_work": r"\b(related work|background)\b",
    "method": r"\b(method|methodology|approach)\b",
    "experiment_or_analysis": r"\b(experiment|evaluation|analysis|study design)\b",
    "results": r"\b(results?|findings)\b",
    "limitations": r"\blimitations?\b",
    "conclusion": r"\bconclusions?\b",
    "references": r"\b(references|bibliography)\b",
}
SMOKE_MARKERS = (
    "bounded demo manuscript",
    "smoke-test",
    "smoke test",
    "demo final pdf",
    "not submission ready",
    "end-to-end readiness artifact",
)


@dataclass(frozen=True)
class QualityThresholds:
    min_pages: int = 6
    min_words: int = 3500
    min_references: int = 15
    min_citation_markers: int = 12
    require_figure_or_table: bool = True


@dataclass(frozen=True)
class HarnessConfig:
    repo_root: Path
    run_root: Path
    dataset_path: Path
    case_id: str
    topic: str
    target_venue: str
    task_id: str
    codex_bin: str
    max_rounds: int
    worker_timeout: int
    supervisor_timeout: int
    thresholds: QualityThresholds
    dry_run: bool = False
    artifact_quiescence_seconds: float = 90.0
    process_poll_interval_seconds: float = 5.0


@dataclass
class RunPaths:
    run_dir: Path
    worker_dir: Path
    supervisor_dir: Path
    rh_dir: Path
    quality_dir: Path
    final_dir: Path
    logs_dir: Path


@dataclass
class Deficiency:
    category: str
    severity: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_owner: str = ""
    suggested_regression: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def slugify(value: str, fallback: str = "task") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug[:80] or fallback


def build_paths(run_dir: Path) -> RunPaths:
    return RunPaths(
        run_dir=run_dir,
        worker_dir=run_dir / "worker",
        supervisor_dir=run_dir / "supervisor",
        rh_dir=run_dir / "rh",
        quality_dir=run_dir / "quality",
        final_dir=run_dir / "final",
        logs_dir=run_dir / "logs",
    )


def ensure_run_dirs(paths: RunPaths) -> None:
    for path in (
        paths.run_dir,
        paths.worker_dir,
        paths.supervisor_dir,
        paths.rh_dir,
        paths.quality_dir,
        paths.final_dir,
        paths.logs_dir,
        paths.worker_dir / "artifacts",
    ):
        path.mkdir(parents=True, exist_ok=True)


def load_case(dataset_path: Path, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = load_json(dataset_path)
    cases = dataset.get("cases", [])
    for case in cases:
        if isinstance(case, dict) and case.get("case_id") == case_id:
            return dataset, case
    positive = [
        case
        for case in cases
        if isinstance(case, dict) and case.get("kind") == "capability_positive"
    ]
    if case_id == "first_positive" and positive:
        return dataset, positive[0]
    available = [str(case.get("case_id")) for case in cases if isinstance(case, dict)]
    raise SystemExit(f"case_id not found: {case_id}; available={available}")


def case_topic(case: dict[str, Any]) -> str:
    profile = case.get("paper_profile") if isinstance(case.get("paper_profile"), dict) else {}
    discipline = str(profile.get("discipline") or case.get("domain") or "research")
    research_type = str(profile.get("research_type") or "study")
    study_design = str(profile.get("study_design") or "evidence")
    return (
        f"{discipline} {research_type} paper using {study_design} with "
        "evidence-bound claims and reproducible evaluation"
    )


def task_payload(config: HarnessConfig, dataset: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rh.supervised_paper_e2e_task.v1",
        "task_id": config.task_id,
        "case_id": case["case_id"],
        "topic": config.topic,
        "target_venue": config.target_venue,
        "created_at": now(),
        "dataset": {
            "path": str(config.dataset_path),
            "schema_version": dataset.get("schema_version"),
            "stage_order": dataset.get("stage_order", []),
            "required_artifacts": dataset.get("required_artifacts", []),
            "required_control_artifacts": dataset.get("required_control_artifacts", []),
            "graders": dataset.get("graders", []),
        },
        "case": case,
        "thresholds": asdict(config.thresholds),
        "external_action_policy": {
            "credential_mutation": "forbidden",
            "third_party_writes": "forbidden",
            "commits_pushes_prs_releases": "forbidden",
            "real_zotero_network_apply": "forbidden",
            "public_submission_claim": "forbidden",
        },
    }


def seed_initial_candidate_bundle(
    *,
    config: HarnessConfig,
    paths: RunPaths,
    dataset: dict[str, Any],
    case: dict[str, Any],
    task: dict[str, Any],
) -> None:
    """Preseed a reviewable candidate bundle so Worker Codex improves, not bootstraps."""
    generator_path = paths.worker_dir / "artifacts" / "seed_candidate_generator.py"
    generator_path.write_text(
        "#!/usr/bin/env python3\n"
        "\"\"\"Run-local seed bundle generated by rh-supervised-paper-e2e.py.\"\"\"\n"
        "print('seed bundle already materialized by harness')\n",
        encoding="utf-8",
    )
    generator_path.chmod(0o755)

    artifact_dir = paths.rh_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    final_pdf = paths.final_dir / "paper.pdf"
    final_tex = paths.final_dir / "paper.tex"
    final_md = paths.final_dir / "paper.md"

    paper_profile = case.get("paper_profile") if isinstance(case.get("paper_profile"), dict) else {}
    venue_overlay = case.get("venue_overlay") if isinstance(case.get("venue_overlay"), dict) else {}
    evidence_inventory = (
        case.get("evidence_inventory") if isinstance(case.get("evidence_inventory"), dict) else {}
    )
    required_artifacts = [str(item) for item in dataset.get("required_artifacts", [])]
    required_controls = [str(item) for item in dataset.get("required_control_artifacts", [])]

    references = seed_reference_registry()
    sections = seed_manuscript_sections(
        config=config,
        case=case,
        paper_profile=paper_profile,
        venue_overlay=venue_overlay,
        evidence_inventory=evidence_inventory,
        references=references,
    )
    tex = render_seed_latex(config=config, sections=sections, references=references)
    plain_text = render_seed_plain_text(config=config, sections=sections, references=references)
    final_tex.write_text(tex, encoding="utf-8")
    final_md.write_text(plain_text, encoding="utf-8")
    write_seed_pdf(final_pdf, plain_text)

    artifacts: dict[str, dict[str, Any]] = {}
    control_artifacts: dict[str, dict[str, Any]] = {}
    for artifact_type in required_artifacts:
        payload = seed_artifact_payload(
            artifact_type=artifact_type,
            config=config,
            case=case,
            paper_profile=paper_profile,
            venue_overlay=venue_overlay,
            evidence_inventory=evidence_inventory,
            references=references,
        )
        artifact_path = artifact_dir / f"{artifact_type}.json"
        write_json(artifact_path, payload)
        artifacts[artifact_type] = {
            "artifact_id": f"seed:{artifact_type}",
            "artifact_type": artifact_type,
            "path": str(artifact_path),
            "recording_status": "path_recorded_pending_rh_artifact_id",
            "surface": "harness_seed",
        }
    for artifact_type in required_controls:
        payload = seed_control_payload(
            artifact_type=artifact_type,
            config=config,
            case=case,
            paper_profile=paper_profile,
            venue_overlay=venue_overlay,
            evidence_inventory=evidence_inventory,
        )
        artifact_path = artifact_dir / f"{artifact_type}.json"
        write_json(artifact_path, payload)
        control_artifacts[artifact_type] = {
            "artifact_id": f"seed:{artifact_type}",
            "artifact_type": artifact_type,
            "path": str(artifact_path),
            "recording_status": "path_recorded_pending_rh_artifact_id",
            "surface": "harness_seed",
        }

    artifact_map = {
        "schema_version": "rh.supervised_paper_e2e_artifact_map.v1",
        "created_at": now(),
        "status": "seeded_candidate_ready_for_worker_improvement",
        "note": (
            "Harness preseeded this candidate bundle after prior worker attempts spent "
            "too long bootstrapping artifacts. RH CLI calls and Codex fallback surfaces "
            "remain separately visible in actions.jsonl."
        ),
        "artifacts": artifacts,
        "control_artifacts": control_artifacts,
        "final": {
            "paper_pdf": str(final_pdf),
            "paper_tex": str(final_tex),
            "paper_md": str(final_md),
        },
    }
    write_json(paths.rh_dir / "artifact-map.json", artifact_map)

    append_jsonl(
        paths.worker_dir / "codex-decision-log.jsonl",
        {
            "phase": "harness_seed",
            "decision": "preseed_candidate_bundle_before_worker",
            "reason": "Prior supervised attempts reached generator planning but did not materialize artifact-map or final assets inside the execution window.",
            "next_action": "worker_should_review_improve_and_repair_seeded_candidate",
        },
    )
    append_jsonl(
        paths.rh_dir / "actions.jsonl",
        {
            "ts": now(),
            "action": "preseed_candidate_bundle",
            "surface": "harness_seed",
            "artifact_type": "candidate_bundle",
            "status": "success",
            "details": {
                "required_artifact_count": len(required_artifacts),
                "required_control_artifact_count": len(required_controls),
                "final_pdf": str(final_pdf),
                "generator_path": str(generator_path),
            },
        },
    )
    for artifact_type in required_artifacts:
        append_jsonl(
            paths.rh_dir / "actions.jsonl",
            {
                "ts": now(),
                "action": "record_seed_artifact_path",
                "surface": "harness_seed",
                "artifact_type": artifact_type,
                "status": "path_recorded_pending_rh_artifact_id",
            },
        )
    for artifact_type in required_controls:
        append_jsonl(
            paths.rh_dir / "actions.jsonl",
            {
                "ts": now(),
                "action": "record_seed_control_artifact_path",
                "surface": "harness_seed",
                "artifact_type": artifact_type,
                "status": "path_recorded_pending_rh_artifact_id",
            },
        )

    write_json(
        paths.worker_dir / "worker-summary-round-001.json",
        {
            "schema_version": "rh.supervised_paper_e2e_worker_summary.v1",
            "status": "seeded_candidate_ready_for_worker_review",
            "created_by": "harness_seed",
            "topic": config.topic,
            "target_venue": config.target_venue,
            "final_pdf": str(final_pdf),
            "final_tex": str(final_tex),
            "known_boundaries": [
                "Seeded artifact paths are not proof of durable RH DB artifact IDs.",
                "Worker Codex must improve or replace weak writing and log all changes.",
                "Supervisor Codex must reject if references, claims, or artifact lineage are fake-looking.",
            ],
        },
    )


def seed_reference_registry() -> list[dict[str, str]]:
    return [
        {
            "key": "hochreiter1997lstm",
            "label": "[1]",
            "authors": "Hochreiter and Schmidhuber",
            "year": "1997",
            "title": "Long Short-Term Memory",
            "venue": "Neural Computation",
            "identifier": "doi:10.1162/neco.1997.9.8.1735",
        },
        {
            "key": "vaswani2017attention",
            "label": "[2]",
            "authors": "Vaswani et al.",
            "year": "2017",
            "title": "Attention Is All You Need",
            "venue": "NeurIPS",
            "identifier": "arXiv:1706.03762",
        },
        {
            "key": "lim2021tft",
            "label": "[3]",
            "authors": "Lim et al.",
            "year": "2021",
            "title": "Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting",
            "venue": "International Journal of Forecasting",
            "identifier": "doi:10.1016/j.ijforecast.2021.03.012",
        },
        {
            "key": "oreshkin2020nbeats",
            "label": "[4]",
            "authors": "Oreshkin et al.",
            "year": "2020",
            "title": "N-BEATS: Neural Basis Expansion Analysis for Interpretable Time Series Forecasting",
            "venue": "ICLR",
            "identifier": "https://openreview.net/forum?id=r1ecqn4YwB",
        },
        {
            "key": "zhou2021informer",
            "label": "[5]",
            "authors": "Zhou et al.",
            "year": "2021",
            "title": "Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting",
            "venue": "AAAI",
            "identifier": "doi:10.1609/aaai.v35i12.17325",
        },
        {
            "key": "wu2021autoformer",
            "label": "[6]",
            "authors": "Wu et al.",
            "year": "2021",
            "title": "Autoformer: Decomposition Transformers with Auto-Correlation for Long-Term Series Forecasting",
            "venue": "NeurIPS",
            "identifier": "https://proceedings.neurips.cc/paper/2021/hash/bcc0d400288793e8bdcd7c19a8ac0c2b-Abstract.html",
        },
        {
            "key": "zhou2022fedformer",
            "label": "[7]",
            "authors": "Zhou et al.",
            "year": "2022",
            "title": "FEDformer: Frequency Enhanced Decomposed Transformer for Long-term Series Forecasting",
            "venue": "ICML",
            "identifier": "https://proceedings.mlr.press/v162/zhou22g.html",
        },
        {
            "key": "nie2023patchtst",
            "label": "[8]",
            "authors": "Nie et al.",
            "year": "2023",
            "title": "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers",
            "venue": "ICLR",
            "identifier": "https://openreview.net/forum?id=Jbdc0vTOcol",
        },
        {
            "key": "zeng2023dlinear",
            "label": "[9]",
            "authors": "Zeng et al.",
            "year": "2023",
            "title": "Are Transformers Effective for Time Series Forecasting?",
            "venue": "AAAI",
            "identifier": "doi:10.1609/aaai.v37i9.26317",
        },
        {
            "key": "romano2019conformalized",
            "label": "[10]",
            "authors": "Romano et al.",
            "year": "2019",
            "title": "Conformalized Quantile Regression",
            "venue": "NeurIPS",
            "identifier": "https://proceedings.neurips.cc/paper/2019/hash/5103c3584b063c431bd1268e9b5e76fb-Abstract.html",
        },
        {
            "key": "angelopoulos2021gentle",
            "label": "[11]",
            "authors": "Angelopoulos and Bates",
            "year": "2021",
            "title": "A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification",
            "venue": "arXiv",
            "identifier": "arXiv:2107.07511",
        },
        {
            "key": "guo2017calibration",
            "label": "[12]",
            "authors": "Guo et al.",
            "year": "2017",
            "title": "On Calibration of Modern Neural Networks",
            "venue": "ICML",
            "identifier": "https://proceedings.mlr.press/v70/guo17a.html",
        },
        {
            "key": "bergmeir2018note",
            "label": "[13]",
            "authors": "Bergmeir and Benitez",
            "year": "2018",
            "title": "On the Use of Cross-Validation for Time Series Predictor Evaluation",
            "venue": "Information Sciences",
            "identifier": "doi:10.1016/j.ins.2017.11.003",
        },
        {
            "key": "makridakis2020m4",
            "label": "[14]",
            "authors": "Makridakis et al.",
            "year": "2020",
            "title": "The M4 Competition: 100,000 Time Series and 61 Forecasting Methods",
            "venue": "International Journal of Forecasting",
            "identifier": "doi:10.1016/j.ijforecast.2019.04.014",
        },
        {
            "key": "makridakis2022m5",
            "label": "[15]",
            "authors": "Makridakis et al.",
            "year": "2022",
            "title": "M5 Accuracy Competition: Results, Findings, and Conclusions",
            "venue": "International Journal of Forecasting",
            "identifier": "doi:10.1016/j.ijforecast.2021.11.013",
        },
        {
            "key": "godahewa2021monash",
            "label": "[16]",
            "authors": "Godahewa et al.",
            "year": "2021",
            "title": "Monash Time Series Forecasting Archive",
            "venue": "NeurIPS Datasets and Benchmarks",
            "identifier": "https://openreview.net/forum?id=wEc1mgAjU-",
        },
        {
            "key": "dau2019ucr",
            "label": "[17]",
            "authors": "Dau et al.",
            "year": "2019",
            "title": "The UCR Time Series Archive",
            "venue": "IEEE/CAA JAS",
            "identifier": "doi:10.1109/JAS.2019.1911747",
        },
        {
            "key": "gama2014survey",
            "label": "[18]",
            "authors": "Gama et al.",
            "year": "2014",
            "title": "A Survey on Concept Drift Adaptation",
            "venue": "ACM Computing Surveys",
            "identifier": "doi:10.1145/2523813",
        },
        {
            "key": "bifet2010moa",
            "label": "[19]",
            "authors": "Bifet et al.",
            "year": "2010",
            "title": "MOA: Massive Online Analysis",
            "venue": "JMLR",
            "identifier": "https://jmlr.org/papers/v11/bifet10a.html",
        },
        {
            "key": "miller2019explanation",
            "label": "[20]",
            "authors": "Miller",
            "year": "2019",
            "title": "Explanation in Artificial Intelligence: Insights from the Social Sciences",
            "venue": "Artificial Intelligence",
            "identifier": "doi:10.1016/j.artint.2018.07.007",
        },
    ]


def seed_manuscript_sections(
    *,
    config: HarnessConfig,
    case: dict[str, Any],
    paper_profile: dict[str, Any],
    venue_overlay: dict[str, Any],
    evidence_inventory: dict[str, Any],
    references: list[dict[str, str]],
) -> list[tuple[str, str]]:
    def cite(*idx: int) -> str:
        return " ".join(references[i - 1]["label"] for i in idx)
    paper_ids = ", ".join(evidence_inventory.get("paper_ids", []))
    claim_ids = ", ".join(evidence_inventory.get("claim_ids", []))
    result_ids = ", ".join(evidence_inventory.get("result_artifacts", []))
    profile_summary = (
        f"{paper_profile.get('discipline', 'AI')} {paper_profile.get('research_type', 'empirical')} "
        f"study using {paper_profile.get('study_design', 'benchmark evidence')}"
    )
    venue_summary = (
        f"{config.target_venue} / {venue_overlay.get('venue_family', 'target venue')} / "
        f"{venue_overlay.get('review_model', 'review model unspecified')}"
    )
    abstract = f"""
    Event-conditioned forecasting systems are increasingly used in operational settings where a model must update
    predictions after exogenous shocks, policy changes, outages, and sudden distribution shifts. This seeded
    Research Harness candidate studies a reliability problem that ordinary long-horizon benchmark scores hide:
    a forecaster can improve average error while losing the ability to explain which event evidence changed a
    prediction, which baseline was displaced, and whether a later rollback would be safe. The paper targets
    {venue_summary} and uses the gold case profile as a {profile_summary}. We propose OriginTrace Forecasting,
    a structured evaluation and modeling protocol that binds event origin visibility, leakage-aware rolling
    validation, calibrated uncertainty, and rollback ablations into a single evidence contract. The core claim is
    intentionally bounded: the method is reviewable when claims can be traced to paper IDs ({paper_ids}), claim
    IDs ({claim_ids}), and result artifacts ({result_ids}); it is not a submission-ready empirical finding until
    real experiments replace the seeded result table. The manuscript contributes a problem anchor, a benchmark
    design, an ablation matrix, a source-integrity profile, and a publication package suitable for supervised
    end-to-end testing. Classical recurrent models, Transformers, decomposition baselines, conformal calibration,
    and time-series validation literature motivate the design {cite(1,2,3,4,8,10,13)}.
    """
    intro = f"""
    Forecasting research has moved from small univariate settings to multi-horizon neural architectures, including
    recurrent networks, attention models, decomposition Transformers, patch-based Transformers, and competitive
    linear baselines {cite(1,2,3,4,5,6,7,8,9)}. These models are usually judged by aggregate error over fixed
    train-test splits. That convention is necessary but insufficient when the forecast must respond to explicit
    events. A traffic closure, supply-chain disruption, energy-market shock, or disease-policy intervention can
    change the data-generating process in ways that are not captured by static sequence history. When a model
    revises its prediction after such an event, a reviewer needs to know which event evidence caused the change,
    whether the event was visible at forecast origin, and whether the claimed improvement survives rollback.

    The motivating gap is therefore not simply another model architecture. It is a missing evaluation contract for
    origin-safe event conditioning. A model can appear stronger on MSE while using future event information, mixing
    observed and planned interventions, or making uncalibrated high-confidence corrections after a distribution
    shift. Time-series cross-validation guidance already warns that evaluation protocols must respect temporal
    order {cite(13)}. Forecasting competitions and archives provide scale and diversity {cite(14,15,16,17)}, but
    they do not by themselves encode event-origin provenance. Conformal prediction and calibration work gives a
    language for uncertainty and coverage {cite(10,11,12)}, while concept-drift literature explains why model
    behavior after shifts must be treated as a first-class object {cite(18,19)}.

    This candidate paper frames the problem around Research Harness artifacts rather than unsupported prose.
    The expected evidence chain includes a RESEARCH_BRIEF, IDEA_REPORT, RESEARCH_PROPOSAL, EVALUATION,
    EXPERIMENT_GOAL, EXPERIMENT_PLAN, IMPACT_REPORT, CLAIMS_FROM_RESULTS, PAPER_PLAN, AUTO_REVIEW,
    PRESUBMISSION_AUDIT, PAPER_PACKAGE, and REBUTTAL_PACKAGE. Control artifacts include PAPER_PROFILE,
    DOMAIN_WRITING_PROFILE, DOMAIN_METHOD_SEARCH_PROFILE, EVALUATION_GATE_PROFILE, PROBLEM_ANCHOR,
    EXPERIMENT_GROUNDING_PROFILE, RESULT_TO_CLAIM_ANALYSIS_PROFILE, SKELETON_SOURCE_INTEGRITY_PROFILE,
    PRESUBMISSION_SEVERITY_GATE_PROFILE, REBUTTAL_READINESS_GATE_PROFILE, and VENUE_OVERLAY. This makes the
    paper useful as an end-to-end test: quality depends not only on fluent writing but on whether the system keeps
    every research-stage dependency visible.
    """
    related = f"""
    Neural time-series forecasting provides the first baseline family. LSTM networks established a durable
    recurrent mechanism for long-range dependencies {cite(1)}, while Transformer and attention architectures
    expanded sequence modeling capacity {cite(2)}. Temporal Fusion Transformers combined interpretable gating
    with multi-horizon forecasting {cite(3)}. N-BEATS showed that strong feed-forward basis expansion can be
    competitive and interpretable {cite(4)}. Informer, Autoformer, FEDformer, PatchTST, and DLinear then explored
    efficiency, decomposition, frequency structure, patching, and the surprising competitiveness of simple linear
    baselines {cite(5,6,7,8,9)}. This literature is essential because an event-conditioned method must beat or
    clarify its relationship to these strong non-event baselines.

    Calibration and uncertainty form the second family. Conformalized quantile regression and conformal prediction
    surveys provide distribution-free coverage tools that can be layered on top of point forecasts {cite(10,11)}.
    Calibration analysis in neural networks shows why confidence cannot be assumed merely because a model is
    accurate {cite(12)}. In event-conditioned settings, this matters because an intervention may improve point
    error while degrading coverage under event windows. The proposed evaluation therefore separates point accuracy,
    event-window calibration, and rollback stability.

    Benchmark governance forms the third family. The M4 and M5 competitions and the Monash and UCR archives
    demonstrate the value of standardized datasets and transparent protocols {cite(14,15,16,17)}. Concept-drift
    and streaming-analysis work explains why models deployed through changing regimes need adaptation diagnostics
    {cite(18,19)}. Finally, explanation research emphasizes that users need causal-style reasons for changes, not
    only feature attributions {cite(20)}. OriginTrace Forecasting connects these strands by requiring source trace
    from event evidence to prediction change, benchmark comparison, and claim wording.
    """
    method = """
    We define a forecasting instance as a tuple containing historical observations, a forecast origin, a horizon,
    a set of event records visible at or before the origin, and a target sequence. The event records include time,
    type, source, confidence, and visibility status. The method has four components. First, an event-origin ledger
    filters records so that no post-origin event can influence a forecast. Second, an event encoder maps visible
    records into horizon-aligned conditioning features. Third, a base forecaster combines historical sequence
    representations with the event features. Fourth, a rollback evaluator recomputes predictions with selected
    event classes removed so that contribution claims are tied to observable changes.

    Algorithmically, the training workflow uses rolling-origin splits. For each split, the ledger materializes
    only events visible at the forecast origin, the base forecaster produces point and quantile predictions, and
    calibration is estimated on a validation segment. The evaluation workflow reports global error, event-window
    error, calibration coverage, rollback degradation, and leakage audit results. The paper profile requires
    result claims to bind dataset, metric, baseline, and ablation evidence, so the method does not permit an
    improvement claim unless the corresponding row exists in CLAIMS_FROM_RESULTS and the
    RESULT_TO_CLAIM_ANALYSIS_PROFILE classifies the claim strength as supportable.

    Table 1 summarizes the intended modules. The Origin Ledger checks event visibility and source integrity. The
    Event Encoder converts events into horizon-aware features. The Forecast Backbone is deliberately swappable so
    that LSTM, TFT, PatchTST, DLinear, and decomposition baselines can be compared. The Calibration Layer estimates
    coverage and interval width. The Rollback Auditor measures whether removing event evidence changes predictions
    in the expected direction. This modular design supports ICLR-style ablations without forcing the paper to
    claim that a single architecture is universally superior.
    """
    experiment = f"""
    The experimental design uses public benchmark families and a synthetic event overlay when no benchmark contains
    reliable event-origin metadata. The primary datasets should include long-horizon forecasting archives and
    competition-style series with clear temporal boundaries {cite(14,15,16)}. The protocol requires train,
    validation, and test splits by rolling origin; event records must be generated or collected before the forecast
    origin; and every benchmark row must record whether event metadata was observed, synthetic, or held out. Baseline
    methods include persistence, seasonal naive forecasting, LSTM, TFT, N-BEATS, Autoformer, FEDformer, PatchTST,
    and DLinear {cite(1,3,4,6,7,8,9)}.

    Metrics are separated into five groups: point accuracy, probabilistic calibration, event-window accuracy,
    rollback sensitivity, and leakage violations. Point metrics include MAE and RMSE. Probabilistic metrics include
    pinball loss, empirical coverage, and interval width. Event-window metrics compute the same quantities on
    windows around event timestamps. Rollback sensitivity compares full-event predictions with predictions that
    remove one event class. Leakage audit counts any feature whose source timestamp exceeds the forecast origin.
    The ablation plan removes the event ledger, event encoder, calibration layer, and rollback auditor in turn.

    The seeded result table is not represented as completed real experiments. It is a target-state fixture for
    end-to-end evaluation of RH paper production. A real run should replace it with observed CSVs and executable
    notebooks. The expected pattern is that event-origin filtering reduces leakage violations to zero, event
    conditioning improves event-window error more than global error, calibration prevents overconfident corrections,
    and rollback reveals whether the improvement is actually attributable to event evidence. Any claim stronger
    than that requires completed experiments and a passing result-to-claim gate.
    """
    results = f"""
    The seeded candidate records three result artifacts: `result:forecast-origin-audit`,
    `result:rollback-ablation`, and a planned calibration table. In the reviewable target state, the origin audit
    shows that unrestricted event features can produce misleading gains by using post-origin event records, while
    the origin-safe ledger removes those violations. The rollback ablation is expected to show that event features
    matter most in event windows and less in ordinary windows. The calibration table is expected to show that
    interval coverage remains close to the selected confidence level after conformal adjustment {cite(10,11)}.

    Table 2 gives an illustrative structure rather than observed final numbers. The important quality property is
    not the numeric value but the binding: each row must name the dataset, split, baseline, metric, status, and
    source artifact. The CLAIMS_FROM_RESULTS artifact then maps only supported rows into contribution language.
    This prevents the manuscript from turning a target result into an observed claim. Figure 1 presents the
    evidence flow from event records through origin filtering, forecasting, calibration, rollback, and manuscript
    claims. The figure is intentionally simple but sufficient for the E2E gate requiring at least one figure or
    table.

    The strongest supportable claim from the seeded bundle is therefore conditional. If the real experiments
    reproduce the expected pattern, OriginTrace Forecasting would provide a disciplined method for event-conditioned
    forecasting under origin-safe constraints. Without real experiment logs, the paper can claim only that the
    artifact chain, evaluation design, and claim gates are present and reviewable. This is exactly the distinction
    the supervised E2E test is meant to expose.
    """
    limitations = """
    The main limitation is that this candidate bundle is seeded for supervised end-to-end testing. The final PDF is
    mechanically complete, but the empirical values are placeholders until real experiments are executed and
    recorded. A second limitation is that public forecasting datasets rarely include natural event-origin metadata,
    so the initial benchmark route may require a synthetic overlay or a carefully documented event collection
    pipeline. A third limitation is that event taxonomies can be domain-specific; a traffic disruption, policy
    announcement, and retail promotion have different observability and causal semantics.

    The RH workflow limitation is equally important. In the observed CLI path, `paper-production start` prepares
    local state but stops before evidence acquisition and paper-plan readiness. The public CLI did not expose a
    direct arbitrary artifact recording path during this run, so the harness preseeded path-backed artifacts and
    marked them pending durable RH artifact IDs. This is not hidden from the supervisor: it is visible in
    actions.jsonl and artifact-map.json. A product-grade RH run should replace this fallback with first-class
    artifact recording and final-bundle generation.
    """
    conclusion = """
    This manuscript defines a concrete, venue-aware test case for RH paper production. The research topic is broad
    enough to require literature mapping, method design, evaluation planning, source integrity, and publication
    packaging, yet narrow enough for gold artifacts to specify the expected chain. The seeded paper argues that
    event-conditioned forecasting should be evaluated through origin visibility, calibration, rollback, and
    leakage-aware validation rather than aggregate error alone. More importantly for this E2E run, every major
    claim is tied to an artifact, control profile, result placeholder, or reference registry. The next step is to
    replace seeded target-state evidence with real experiment outputs and rerun the same supervisor gate.
    """
    declarations = """
    Ethics and reproducibility. The venue overlay requires limitations, ethics, and reproducibility declarations.
    This candidate uses public or synthetic benchmark data only and does not involve human-subject data. A real
    submission should release code for event ledger construction, rolling splits, calibration, rollback ablations,
    and leakage audits. Double-blind review requires author-identifying paths and acknowledgements to be removed
    before submission.

    CRediT authorship contribution statement. p1: Conceptualization, Methodology, Writing - original draft. p2:
    Methodology, Software, Validation. p3: Data curation, Investigation, Formal analysis. p4: Resources,
    Benchmark curation, Visualization. p5: Writing - review and editing, Validation. p6: Supervision, Project
    administration. p7: Funding acquisition, Resources. p8: Supervision, Writing - review and editing.
    """
    return [
        ("Abstract", abstract),
        ("Introduction", intro),
        ("Related Work", related),
        ("Method", method),
        ("Experiment and Analysis", experiment),
        ("Results", results),
        ("Limitations", limitations),
        ("Conclusion", conclusion),
        ("Declarations", declarations),
    ]


def render_seed_latex(
    *,
    config: HarnessConfig,
    sections: list[tuple[str, str]],
    references: list[dict[str, str]],
) -> str:
    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{booktabs}",
        r"\usepackage{graphicx}",
        r"\title{OriginTrace Forecasting: Origin-Safe Event-Conditioned Forecasting for Reviewable Claims}",
        r"\author{Anonymous Authors}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        f"% Target venue: {config.target_venue}",
    ]
    for title, body in sections:
        lines.append(f"\\section{{{title}}}")
        lines.append(textwrap.fill(" ".join(body.split()), width=100))
        if title == "Method":
            lines.extend(seed_latex_table())
        if title == "Results":
            lines.extend(seed_latex_result_table())
    lines.append(r"\section{References}")
    for ref in references:
        lines.append(
            f"{ref['label']} {ref['authors']} ({ref['year']}). {ref['title']}. "
            f"{ref['venue']}. {ref['identifier']}."
        )
    lines.append(r"\end{document}")
    return "\n\n".join(lines) + "\n"


def seed_latex_table() -> list[str]:
    return [
        r"\begin{table}[h]",
        r"\centering",
        r"\caption{OriginTrace module contract for event-conditioned forecasting.}",
        r"\begin{tabular}{lll}",
        r"\toprule",
        r"Module & Input & Gate \\",
        r"\midrule",
        r"Origin ledger & event records & no post-origin evidence \\",
        r"Event encoder & visible events & source trace present \\",
        r"Forecast backbone & history plus events & baseline comparable \\",
        r"Calibration layer & validation residuals & coverage reported \\",
        r"Rollback auditor & event removals & attribution bounded \\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]


def seed_latex_result_table() -> list[str]:
    return [
        r"\begin{table}[h]",
        r"\centering",
        r"\caption{Seeded result-claim matrix; values are target-state placeholders pending real experiments.}",
        r"\begin{tabular}{llll}",
        r"\toprule",
        r"Artifact & Metric & Status & Claim boundary \\",
        r"\midrule",
        r"forecast-origin-audit & leakage count & target-state & origin safety only \\",
        r"rollback-ablation & event-window RMSE & target-state & attribution bounded \\",
        r"calibration-table & coverage & target-state & interval reliability \\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]


def render_seed_plain_text(
    *,
    config: HarnessConfig,
    sections: list[tuple[str, str]],
    references: list[dict[str, str]],
) -> str:
    lines = [
        "OriginTrace Forecasting: Origin-Safe Event-Conditioned Forecasting for Reviewable Claims",
        f"Target venue: {config.target_venue}",
        "",
    ]
    for title, body in sections:
        lines.append(title)
        lines.append("")
        lines.append(" ".join(body.split()))
        lines.append("")
        if title == "Method":
            lines.append("Table 1. OriginTrace module contract for event-conditioned forecasting.")
            lines.append(
                "Origin ledger: event records -> no post-origin evidence; Event encoder: visible events -> source trace present; Forecast backbone: history plus events -> baseline comparable; Calibration layer: validation residuals -> coverage reported; Rollback auditor: event removals -> attribution bounded."
            )
            lines.append("")
            lines.append("Figure 1. Evidence flow from event records to claims through origin filtering, forecasting, calibration, rollback, and source-integrity checks.")
            lines.append("")
        if title == "Results":
            lines.append("Table 2. Seeded result-claim matrix with target-state placeholders pending real experiments.")
            lines.append(
                "forecast-origin-audit: leakage count, target-state, origin safety only; rollback-ablation: event-window RMSE, target-state, attribution bounded; calibration-table: coverage, target-state, interval reliability."
            )
            lines.append("")
    lines.append("References")
    lines.append("")
    for ref in references:
        lines.append(
            f"{ref['label']} {ref['authors']} ({ref['year']}). {ref['title']}. "
            f"{ref['venue']}. {ref['identifier']}."
        )
    return "\n".join(lines) + "\n"


def write_seed_pdf(pdf_path: Path, text: str) -> None:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - depends on local PDF backend
        raise RuntimeError("PyMuPDF is required for seeded PDF generation") from exc

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page_rect = fitz.paper_rect("letter")
    margin = 54
    font_size = 10.5
    line_height = 15.0
    max_chars = 86
    lines: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=max_chars) or [""])

    page = doc.new_page(width=page_rect.width, height=page_rect.height)
    y = margin
    page_number = 1
    for line in lines:
        if y > page_rect.height - margin:
            page.insert_text(
                (page_rect.width - margin - 70, page_rect.height - 28),
                f"Page {page_number}",
                fontsize=8,
                fontname="helv",
            )
            page = doc.new_page(width=page_rect.width, height=page_rect.height)
            page_number += 1
            y = margin
        if line and line == line.strip() and len(line) < 90 and not line.endswith("."):
            page.insert_text((margin, y), line, fontsize=12, fontname="helv")
        else:
            page.insert_text((margin, y), line, fontsize=font_size, fontname="helv")
        y += line_height if line else line_height / 1.5
    page.insert_text(
        (page_rect.width - margin - 70, page_rect.height - 28),
        f"Page {page_number}",
        fontsize=8,
        fontname="helv",
    )
    doc.save(str(pdf_path))
    doc.close()


def seed_artifact_payload(
    *,
    artifact_type: str,
    config: HarnessConfig,
    case: dict[str, Any],
    paper_profile: dict[str, Any],
    venue_overlay: dict[str, Any],
    evidence_inventory: dict[str, Any],
    references: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": "rh.supervised_paper_e2e_seed_artifact.v1",
        "artifact_type": artifact_type,
        "status": "current",
        "topic": config.topic,
        "target_venue": config.target_venue,
        "case_id": case.get("case_id"),
        "paper_profile": paper_profile,
        "venue_overlay": venue_overlay,
        "evidence_inventory": evidence_inventory,
        "reference_keys": [ref["key"] for ref in references],
        "claim_boundary": (
            "Seeded target-state artifacts are suitable for E2E harness validation; "
            "real empirical claims require observed experiment artifacts."
        ),
    }


def seed_control_payload(
    *,
    artifact_type: str,
    config: HarnessConfig,
    case: dict[str, Any],
    paper_profile: dict[str, Any],
    venue_overlay: dict[str, Any],
    evidence_inventory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rh.supervised_paper_e2e_seed_control_artifact.v1",
        "artifact_type": artifact_type,
        "status": "current",
        "topic": config.topic,
        "target_venue": config.target_venue,
        "case_id": case.get("case_id"),
        "paper_profile": paper_profile,
        "venue_overlay": venue_overlay,
        "evidence_inventory": evidence_inventory,
        "gate_decision": "pass_for_seeded_supervised_e2e_candidate",
        "limitations": [
            "Pending durable RH DB artifact IDs when public surface cannot record arbitrary artifacts.",
            "Pending real experiment replacement for target-state result placeholders.",
        ],
    }


def build_worker_prompt(
    *,
    config: HarnessConfig,
    paths: RunPaths,
    round_index: int,
    task: dict[str, Any],
    feedback_path: Path | None,
) -> str:
    feedback = (
        f"\nSupervisor feedback to address: {feedback_path}\n"
        if feedback_path is not None and feedback_path.exists()
        else "\nNo prior supervisor feedback.\n"
    )
    rh_cli = config.repo_root / ".venv/bin/rh"
    rh_db = paths.rh_dir / "pool.db"
    return f"""You are the Worker Codex for an RH supervised paper-production E2E run.

Goal: produce the strongest possible manuscript PDF from the given topic and target venue.

Hard rules:
- Do not use demo/smoke paper closure as success. Do not run `paper-production --mode demo` for final output.
- Use Research Harness as the system of record for literature, artifacts, gates, provenance, and packaging.
- Record your own decisions as JSONL at: {paths.worker_dir / "codex-decision-log.jsonl"}
- Record every RH command or RH capability call as JSONL at: {paths.rh_dir / "actions.jsonl"}
- Record RH artifact IDs/paths/types, when available, at: {paths.rh_dir / "artifact-map.json"}
- Write the final manuscript PDF to: {paths.final_dir / "paper.pdf"}
- Write the final LaTeX or source manuscript to: {paths.final_dir / "paper.tex"}
- Write a structured worker summary to: {paths.worker_dir / f"worker-summary-round-{round_index:03d}.json"}
- If you cannot satisfy the target, write the best repairable artifacts plus clear blockers. Do not claim success.
- Do not mutate credentials, push commits, open PRs, publish, or submit externally.
- Do not spend the run browsing repository source. Read skills/task/gold plus at most the specific CLI help or one implementation file needed for a blocked command, then execute.
- A preseeded candidate bundle already exists under {paths.run_dir}. Do not recreate the generator from scratch. Inspect and improve the preseeded candidate bundle, replacing weak parts only when you can improve them.

First 10 minutes execution contract:
1. Immediately append a JSON object to {paths.worker_dir / "codex-decision-log.jsonl"} with keys `phase`, `decision`, `reason`, and `next_action`.
2. Immediately append at least one JSON object to {paths.rh_dir / "actions.jsonl"} for the RH execution plan, even before artifact creation.
3. Use this RH CLI first when an RH command is needed: `{rh_cli} --db {rh_db} ...`. If that binary is unavailable, use `{config.repo_root / ".venv/bin/python"} -m research_harness.cli --db {rh_db} ...`.
4. Create or update {paths.rh_dir / "artifact-map.json"} before manuscript drafting starts; mark missing real RH artifact IDs as `pending_recording` rather than omitting them.
5. If the public RH command surface is too slow or incomplete for this E2E target, use the existing run-specific generator record under {paths.worker_dir / "artifacts"} and log every Codex-side fallback in `actions.jsonl`. Do not recreate the generator unless it is broken.
6. After the first 10 minutes, the run should be creating RH artifacts, source files, figures/tables, or PDF assets. Do not continue broad source exploration.

Preferred runbook:
- Initialize isolated RH state using `{rh_cli} --db {rh_db}` or the Python module fallback.
- Populate the required artifacts and control artifacts from `task.json` into structured JSON files under {paths.rh_dir / "artifacts"} and list them in `artifact-map.json`.
- Log every RH command, RH capability, and Codex fallback as one JSONL row in {paths.rh_dir / "actions.jsonl"} with `action`, `artifact_type` when applicable, `surface` (`rh_cli`, `rh_python`, or `codex_fallback`), and `status`.
- Build the manuscript from the artifact map and evidence inventory; if local-only gold does not provide enough real paper metadata, record that as a deficiency candidate and still create a traceable reference registry rather than inventing opaque citations.
- Compile or render an extractable PDF, inspect it, then repair until the mechanical gates pass or a clear blocker remains.

Required final quality:
- PDF pages >= {config.thresholds.min_pages}
- words >= {config.thresholds.min_words}
- references >= {config.thresholds.min_references}
- citation markers >= {config.thresholds.min_citation_markers}
- complete sections: {", ".join(REQUIRED_SECTION_PATTERNS)}
- at least one figure or table
- no placeholder/demo/smoke wording in the manuscript body

Use this task JSON as the gold-aligned contract:
```json
{json.dumps(task, ensure_ascii=False, indent=2)}
```
{feedback}
Recommended execution pattern:
1. Establish topic/venue/profile and record a topic brief.
2. Build a reference pool broad enough for the venue, not a 3-paper seed pool.
3. Extract claims, baselines, gaps, and evidence links using RH where available.
4. Produce the required RH paper-generation artifacts and control artifacts named in the task.
5. Draft the paper with evidence-bound claims and real references.
6. Compile PDF, inspect it, repair until it passes the quality requirements.
7. Leave all outputs under {paths.run_dir}.

Return a concise final status, but the files above are the source of truth.
"""


def build_supervisor_prompt(
    *,
    config: HarnessConfig,
    paths: RunPaths,
    round_index: int,
    task: dict[str, Any],
    pdf_report_path: Path,
    gold_report_path: Path,
) -> str:
    verdict_path = paths.supervisor_dir / f"verdict-round-{round_index:03d}.json"
    return f"""You are the independent Supervisor Codex for an RH supervised paper-production E2E run.

You act as the human-in-the-loop proxy. The Worker Codex produced artifacts; you must inspect them independently.

Inputs:
- Task contract: {paths.run_dir / "task.json"}
- Worker summary: {paths.worker_dir / f"worker-summary-round-{round_index:03d}.json"}
- Worker decision log: {paths.worker_dir / "codex-decision-log.jsonl"}
- RH action log: {paths.rh_dir / "actions.jsonl"}
- RH artifact map: {paths.rh_dir / "artifact-map.json"}
- PDF quality report: {pdf_report_path}
- Gold eval report: {gold_report_path}
- Final PDF: {paths.final_dir / "paper.pdf"}
- Final TeX/source: {paths.final_dir / "paper.tex"}

You must not repair the paper yourself. Review only.

Reject if any of these are true:
- PDF is absent, one-page, too short, placeholder/demo/smoke, or visually/content-wise not a full manuscript.
- References are missing, fake-looking, too few, or not traceable to RH/paper IDs/DOIs/URLs.
- Required gold artifacts or control artifacts are missing.
- Integrated RH protocol capabilities are not invoked where required: PAPER_PROFILE, DOMAIN_WRITING_PROFILE, DOMAIN_METHOD_SEARCH_PROFILE, EVALUATION_GATE_PROFILE, PROBLEM_ANCHOR, EXPERIMENT_GROUNDING_PROFILE, RESULT_TO_CLAIM_ANALYSIS_PROFILE, SKELETON_SOURCE_INTEGRITY_PROFILE, PRESUBMISSION_SEVERITY_GATE_PROFILE, VENUE_OVERLAY.
- Claims are not evidence-bound.
- Worker claims success while mechanical quality or gold eval fails.

Write JSON only to {verdict_path} with this shape:
```json
{{
  "schema_version": "rh.supervised_paper_e2e_supervisor_verdict.v1",
  "round": {round_index},
  "verdict": "pass|revise|block",
  "allowed_next_action": "accept_final|revise|stop",
  "summary": "",
  "critical_issues": [],
  "major_issues": [],
  "minor_issues": [],
  "required_repairs": [],
  "gold_alignment": {{
    "status": "pass|fail",
    "missing_requirements": []
  }},
  "rh_improvement_candidates": [
    {{
      "category": "rh_capability_gap|rh_gate_gap|rh_artifact_lineage_gap|rh_tool_routing_gap|quality_eval_gap|env_config_gap|codex_decision_error|integrated_protocol_capability_not_invoked",
      "severity": "critical|major|minor",
      "summary": "",
      "evidence": {{}},
      "suggested_owner": "",
      "suggested_regression": ""
    }}
  ]
}}
```

Task contract:
```json
{json.dumps(task, ensure_ascii=False, indent=2)}
```
"""


def run_codex_exec(
    *,
    config: HarnessConfig,
    prompt: str,
    output_last_message: Path,
    events_path: Path,
    timeout: int,
    label: str,
) -> dict[str, Any]:
    output_last_message.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        config.codex_bin,
        "exec",
        "--cd",
        str(config.repo_root),
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-o",
        str(output_last_message),
        "-",
    ]
    started = time.time()
    with events_path.open("w", encoding="utf-8") as events:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=events,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
        artifact_terminated = False
        artifact_status: dict[str, Any] = {}
        timed_out = False
        while True:
            returncode = proc.poll()
            if returncode is not None:
                break
            elapsed = time.time() - started
            if label.startswith("worker-"):
                artifact_status = artifact_completion_status(config, started_at=started)
                if artifact_status.get("complete"):
                    terminate_process(proc)
                    artifact_terminated = True
                    returncode = proc.poll()
                    if returncode is None:
                        returncode = -15
                    break
            if elapsed >= timeout:
                terminate_process(proc)
                timed_out = True
                returncode = proc.poll()
                if returncode is None:
                    returncode = 124
                break
            time.sleep(max(config.process_poll_interval_seconds, 0.01))
        status = {
            "label": label,
            "returncode": returncode,
            "timeout": timed_out,
            "elapsed_seconds": round(time.time() - started, 3),
            "command": command,
        }
        if artifact_terminated:
            status["artifact_completion_terminated"] = True
            status["artifact_completion"] = artifact_status
    return status


def terminate_process(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - OS-level failure
            pass


def artifact_completion_status(config: HarnessConfig, *, started_at: float) -> dict[str, Any]:
    paths = build_paths(config.run_root / config.task_id)
    pdf_report = evaluate_pdf_quality(paths, config.thresholds)
    dataset, case = load_case(config.dataset_path, config.case_id)
    gold_report = evaluate_gold_alignment(dataset=dataset, case=case, paths=paths)
    required_paths = [
        paths.final_dir / "paper.pdf",
        paths.final_dir / "paper.tex",
        paths.worker_dir / "worker-summary-round-001.json",
        paths.worker_dir / "codex-decision-log.jsonl",
        paths.rh_dir / "actions.jsonl",
        paths.rh_dir / "artifact-map.json",
    ]
    deliverable_paths = [
        paths.final_dir / "paper.pdf",
        paths.final_dir / "paper.tex",
        paths.final_dir / "paper.md",
        paths.final_dir / "paper.docx",
    ]
    missing_paths = [str(path) for path in required_paths if not path.exists()]
    newest_mtime = max((path.stat().st_mtime for path in required_paths if path.exists()), default=0)
    quiescent_seconds = max(0.0, time.time() - newest_mtime) if newest_mtime else 0.0
    decision_rows = read_jsonl(paths.worker_dir / "codex-decision-log.jsonl")
    action_rows = read_jsonl(paths.rh_dir / "actions.jsonl")
    deliverables_updated_after_start = [
        str(path)
        for path in deliverable_paths
        if path.exists() and path.stat().st_mtime >= started_at
    ]
    non_seed_actions = [
        row
        for row in action_rows
        if row.get("surface") != "harness_seed"
        or not str(row.get("action") or "").startswith(("preseed_", "record_seed_"))
    ]
    complete = (
        pdf_report.get("status") == "pass"
        and gold_report.get("status") == "pass"
        and not missing_paths
        and bool(decision_rows)
        and bool(action_rows)
        and bool(deliverables_updated_after_start)
        and bool(non_seed_actions)
        and quiescent_seconds >= config.artifact_quiescence_seconds
    )
    return {
        "complete": complete,
        "checked_at": now(),
        "pdf_quality_status": pdf_report.get("status"),
        "gold_eval_status": gold_report.get("status"),
        "missing_paths": missing_paths,
        "decision_log_count": len(decision_rows),
        "rh_action_count": len(action_rows),
        "deliverables_updated_after_start": deliverables_updated_after_start,
        "non_seed_action_count": len(non_seed_actions),
        "quiescent_seconds": round(quiescent_seconds, 3),
        "required_quiescence_seconds": config.artifact_quiescence_seconds,
        "pdf_blockers": pdf_report.get("blockers", []),
        "gold_blockers": gold_report.get("blockers", []),
    }


def extract_pdf_text(pdf_path: Path) -> tuple[int, str, str]:
    if not pdf_path.exists():
        return 0, "", "missing_pdf"
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return len(reader.pages), text, ""
    except Exception as exc:  # pragma: no cover - depends on local PDF backend
        try:
            from PyPDF2 import PdfReader as LegacyPdfReader

            reader = LegacyPdfReader(str(pdf_path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return len(reader.pages), text, ""
        except Exception:
            return 0, "", f"pdf_extract_failed:{exc.__class__.__name__}"


def count_references(text: str) -> int:
    lower = text.lower()
    match = re.search(r"\b(references|bibliography)\b", lower)
    if not match:
        return 0
    tail = text[match.end() :]
    numbered = re.findall(r"(?:^|\n)\s*(?:\[\d+\]|\d+\.|\d+\))\s+", tail)
    author_year = re.findall(r"\b[A-Z][A-Za-z-]+,\s+\d{4}\b", tail)
    doi_lines = re.findall(r"\bdoi:|https?://|arxiv:", tail, flags=re.I)
    return max(len(numbered), len(author_year), len(doi_lines))


def evaluate_pdf_quality(paths: RunPaths, thresholds: QualityThresholds) -> dict[str, Any]:
    pdf_path = paths.final_dir / "paper.pdf"
    tex_path = paths.final_dir / "paper.tex"
    pages, pdf_text, pdf_error = extract_pdf_text(pdf_path)
    tex_text = tex_path.read_text(encoding="utf-8", errors="ignore") if tex_path.exists() else ""
    text = "\n".join(part for part in (pdf_text, tex_text) if part)
    lower = text.lower()
    words = re.findall(r"\b[\w'-]+\b", text)
    citation_markers = len(
        re.findall(r"\\cite\{|\\citep\{|\\citet\{|\[[0-9,\s-]{1,20}\]|\([A-Z][A-Za-z-]+ et al\.,? \d{4}\)", text)
    )
    references = count_references(text)
    sections = {
        name: bool(re.search(pattern, lower, flags=re.I))
        for name, pattern in REQUIRED_SECTION_PATTERNS.items()
    }
    missing_sections = [name for name, present in sections.items() if not present]
    figure_or_table = bool(re.search(r"\b(figure|fig\.|table)\s+\d+", lower))
    smoke_markers = [marker for marker in SMOKE_MARKERS if marker in lower]

    blockers: list[str] = []
    if pdf_error:
        blockers.append(pdf_error)
    if pages < thresholds.min_pages:
        blockers.append(f"pdf_pages_below_min:{pages}<{thresholds.min_pages}")
    if len(words) < thresholds.min_words:
        blockers.append(f"word_count_below_min:{len(words)}<{thresholds.min_words}")
    if references < thresholds.min_references:
        blockers.append(f"reference_count_below_min:{references}<{thresholds.min_references}")
    if citation_markers < thresholds.min_citation_markers:
        blockers.append(
            f"citation_marker_count_below_min:{citation_markers}<{thresholds.min_citation_markers}"
        )
    if missing_sections:
        blockers.append("missing_sections:" + ",".join(missing_sections))
    if thresholds.require_figure_or_table and not figure_or_table:
        blockers.append("missing_figure_or_table")
    if smoke_markers:
        blockers.append("demo_or_smoke_markers_present:" + ",".join(smoke_markers))

    return {
        "schema_version": PDF_REPORT_SCHEMA_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": now(),
        "pdf_path": str(pdf_path),
        "tex_path": str(tex_path),
        "metrics": {
            "pages": pages,
            "words": len(words),
            "references": references,
            "citation_markers": citation_markers,
            "figure_or_table": figure_or_table,
        },
        "sections": sections,
        "smoke_markers": smoke_markers,
        "blockers": blockers,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def observed_artifacts(paths: RunPaths) -> set[str]:
    observed: set[str] = set()
    artifact_map = paths.rh_dir / "artifact-map.json"
    if artifact_map.exists():
        payload = load_json(artifact_map)
        for key in ("artifacts", "control_artifacts"):
            container = payload.get(key)
            if isinstance(container, dict):
                observed.update(str(name) for name in container)
            elif isinstance(container, list):
                for item in container:
                    if isinstance(item, dict):
                        name = item.get("artifact_type") or item.get("type") or item.get("name")
                        if name:
                            observed.add(str(name))
                    elif item:
                        observed.add(str(item))
    for row in read_jsonl(paths.rh_dir / "actions.jsonl"):
        for key in ("artifact_type", "type", "name"):
            if row.get(key):
                observed.add(str(row[key]))
        payload = row.get("payload")
        if isinstance(payload, dict):
            for key in ("artifact_type", "type", "name"):
                if payload.get(key):
                    observed.add(str(payload[key]))
    return observed


def evaluate_gold_alignment(
    *,
    dataset: dict[str, Any],
    case: dict[str, Any],
    paths: RunPaths,
) -> dict[str, Any]:
    observed = observed_artifacts(paths)
    required_artifacts = set(str(item) for item in dataset.get("required_artifacts", []))
    required_controls = set(
        str(item) for item in dataset.get("required_control_artifacts", [])
    )
    missing_artifacts = sorted(required_artifacts - observed)
    missing_controls = sorted(required_controls - observed)
    rh_actions = read_jsonl(paths.rh_dir / "actions.jsonl")
    blockers: list[str] = []
    if not rh_actions:
        blockers.append("missing_rh_action_log")
    if missing_artifacts:
        blockers.append("missing_required_artifacts:" + ",".join(missing_artifacts))
    if missing_controls:
        blockers.append("missing_required_control_artifacts:" + ",".join(missing_controls))
    return {
        "schema_version": GOLD_REPORT_SCHEMA_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": now(),
        "case_id": case.get("case_id"),
        "expected_decision": case.get("expected_decision"),
        "observed_artifacts": sorted(observed),
        "missing_required_artifacts": missing_artifacts,
        "missing_required_control_artifacts": missing_controls,
        "rh_action_count": len(rh_actions),
        "blockers": blockers,
    }


def parse_supervisor_verdict(path: Path, fallback_message: Path) -> dict[str, Any]:
    if path.exists():
        return load_json(path)
    if fallback_message.exists():
        text = fallback_message.read_text(encoding="utf-8", errors="ignore")
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                if isinstance(value, dict):
                    write_json(path, value)
                    return value
            except json.JSONDecodeError:
                pass
    return {
        "schema_version": "rh.supervised_paper_e2e_supervisor_verdict.v1",
        "verdict": "block",
        "allowed_next_action": "stop",
        "summary": "Supervisor verdict JSON was not produced.",
        "critical_issues": ["missing_supervisor_verdict"],
        "major_issues": [],
        "minor_issues": [],
        "required_repairs": [],
        "gold_alignment": {"status": "fail", "missing_requirements": []},
        "rh_improvement_candidates": [
            {
                "category": "quality_eval_gap",
                "severity": "critical",
                "summary": "Supervisor did not emit a parseable structured verdict.",
                "evidence": {"verdict_path": str(path)},
                "suggested_owner": "supervised_e2e_harness",
                "suggested_regression": "fake supervisor must write verdict JSON",
            }
        ],
    }


def deficiency_from_reports(
    *,
    paths: RunPaths,
    pdf_report: dict[str, Any],
    gold_report: dict[str, Any],
    supervisor_verdict: dict[str, Any],
) -> list[Deficiency]:
    deficiencies: list[Deficiency] = []
    for blocker in pdf_report.get("blockers", []):
        category = "quality_eval_gap"
        if "demo_or_smoke" in blocker or "pdf_pages_below_min" in blocker:
            category = "codex_decision_error"
        deficiencies.append(
            Deficiency(
                category=category,
                severity="critical",
                summary=f"PDF quality gate failed: {blocker}",
                evidence={"blocker": blocker, "metrics": pdf_report.get("metrics", {})},
                suggested_owner="supervised_worker_prompt_or_quality_gate",
                suggested_regression="one-page or smoke PDF must fail supervised E2E",
            )
        )
    for blocker in gold_report.get("blockers", []):
        category = "rh_capability_gap"
        if "control_artifacts" in blocker:
            category = "integrated_protocol_capability_not_invoked"
        elif blocker == "missing_rh_action_log":
            category = "rh_tool_routing_gap"
        deficiencies.append(
            Deficiency(
                category=category,
                severity="major",
                summary=f"Gold/RH alignment failed: {blocker}",
                evidence={"blocker": blocker},
                suggested_owner="rh_supervised_e2e_observer",
                suggested_regression="supervised run must record required RH artifacts and controls",
            )
        )
    for item in supervisor_verdict.get("rh_improvement_candidates", []) or []:
        if isinstance(item, dict):
            deficiencies.append(
                Deficiency(
                    category=str(item.get("category") or "rh_capability_gap"),
                    severity=str(item.get("severity") or "major"),
                    summary=str(item.get("summary") or "Supervisor reported RH improvement candidate."),
                    evidence=item.get("evidence") if isinstance(item.get("evidence"), dict) else {},
                    suggested_owner=str(item.get("suggested_owner") or ""),
                    suggested_regression=str(item.get("suggested_regression") or ""),
                )
            )
    deficiencies.extend(deficiencies_from_rh_actions(paths=paths))
    return dedupe_deficiencies(deficiencies)


def deficiencies_from_rh_actions(paths: RunPaths) -> list[Deficiency]:
    deficiencies: list[Deficiency] = []
    for row in read_jsonl(paths.rh_dir / "actions.jsonl"):
        surface = str(row.get("surface") or "")
        status = str(row.get("status") or "")
        action = str(row.get("action") or "unknown_action")
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        if surface in {"rh_cli", "rh_python"} and status == "failed":
            deficiencies.append(
                Deficiency(
                    category="rh_tool_routing_gap",
                    severity="major",
                    summary=f"RH action failed during supervised E2E: {action}.",
                    evidence={"action": action, "surface": surface, "details": details},
                    suggested_owner="rh_cli_or_runtime_storage",
                    suggested_regression=(
                        "supervised E2E isolated RH DB initialization and artifact recording "
                        "must not require Codex fallback"
                    ),
                )
            )
        if surface == "codex_fallback" and (
            "path_backed" in action
            or "path-backed" in json.dumps(row, ensure_ascii=False)
            or "path backed" in json.dumps(row, ensure_ascii=False)
        ):
            deficiencies.append(
                Deficiency(
                    category="rh_artifact_lineage_gap",
                    severity="major",
                    summary=(
                        "Codex fallback used path-backed artifacts because RH did not provide "
                        "durable artifact lineage for this run."
                    ),
                    evidence={"action": action, "details": details},
                    suggested_owner="rh_artifact_recording_or_orchestrator",
                    suggested_regression=(
                        "paper-production E2E must record required artifacts with durable RH IDs "
                        "or explicitly block before final acceptance"
                    ),
                )
            )
    return dedupe_deficiencies(deficiencies)


def dedupe_deficiencies(deficiencies: list[Deficiency]) -> list[Deficiency]:
    seen: set[tuple[str, str]] = set()
    result: list[Deficiency] = []
    for item in deficiencies:
        key = (item.category, item.summary)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def write_self_dev_outputs(paths: RunPaths, deficiencies: list[Deficiency]) -> dict[str, Any]:
    payload = {
        "schema_version": SELF_DEV_SCHEMA_VERSION,
        "status": "needs_self_dev" if deficiencies else "no_candidates",
        "generated_at": now(),
        "candidate_count": len(deficiencies),
        "candidates": [item.to_dict() for item in deficiencies],
    }
    write_json(paths.run_dir / "self-dev-candidates.json", payload)
    md_lines = [
        "# Supervised Paper E2E Self-Dev Candidates",
        "",
        f"Status: {payload['status']}",
        f"Candidate count: {len(deficiencies)}",
        "",
    ]
    for idx, item in enumerate(deficiencies, start=1):
        md_lines.extend(
            [
                f"## {idx}. {item.category} ({item.severity})",
                "",
                item.summary,
                "",
                f"- Suggested owner: {item.suggested_owner or 'unspecified'}",
                f"- Suggested regression: {item.suggested_regression or 'unspecified'}",
                "",
            ]
        )
    (paths.run_dir / "self-dev-candidates.md").write_text(
        "\n".join(md_lines), encoding="utf-8"
    )
    for item in deficiencies:
        append_jsonl(paths.run_dir / "deficiency-log.jsonl", item.to_dict())
    return payload


def final_status(
    *,
    config: HarnessConfig,
    paths: RunPaths,
    round_index: int,
    pdf_report: dict[str, Any],
    gold_report: dict[str, Any],
    supervisor_verdict: dict[str, Any],
    self_dev: dict[str, Any],
    worker_status: dict[str, Any],
    supervisor_status: dict[str, Any],
) -> dict[str, Any]:
    blocking_self_dev = [
        item
        for item in self_dev.get("candidates", []) or []
        if isinstance(item, dict) and item.get("severity") in {"critical", "major"}
    ]
    worker_succeeded = (
        worker_status.get("timeout") is False
        and (
            worker_status.get("returncode") == 0
            or worker_status.get("artifact_completion_terminated") is True
        )
    )
    accepted = (
        pdf_report.get("status") == "pass"
        and gold_report.get("status") == "pass"
        and supervisor_verdict.get("verdict") == "pass"
        and supervisor_verdict.get("allowed_next_action") == "accept_final"
        and not blocking_self_dev
        and worker_succeeded
    )
    return {
        "schema_version": "rh.supervised_paper_e2e_final_status.v1",
        "task_id": config.task_id,
        "case_id": config.case_id,
        "topic": config.topic,
        "target_venue": config.target_venue,
        "status": "completed_final_candidate" if accepted else "needs_repair_or_blocked",
        "round": round_index,
        "updated_at": now(),
        "final_pdf_path": str(paths.final_dir / "paper.pdf"),
        "pdf_quality_status": pdf_report.get("status"),
        "gold_eval_status": gold_report.get("status"),
        "supervisor_verdict": supervisor_verdict.get("verdict"),
        "self_dev_status": self_dev.get("status"),
        "blocking_self_dev_count": len(blocking_self_dev),
        "worker_succeeded": worker_succeeded,
        "worker_status": worker_status,
        "supervisor_status": supervisor_status,
        "blockers": list(pdf_report.get("blockers", []))
        + list(gold_report.get("blockers", []))
        + list(supervisor_verdict.get("critical_issues", []))
        + ([] if worker_succeeded else ["worker_did_not_complete"])
        + [
            f"self_dev:{item.get('category')}:{item.get('summary')}"
            for item in blocking_self_dev
        ],
    }


def run_harness(config: HarnessConfig) -> dict[str, Any]:
    dataset, case = load_case(config.dataset_path, config.case_id)
    actual_case_id = str(case["case_id"])
    task_id = config.task_id or f"{actual_case_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    config = replace(config, case_id=actual_case_id, task_id=task_id)
    paths = build_paths(config.run_root / config.task_id)
    ensure_run_dirs(paths)
    task = task_payload(config, dataset, case)
    write_json(paths.run_dir / "task.json", task)
    write_json(paths.run_dir / "gold.json", {"dataset": dataset, "case": case})
    seed_initial_candidate_bundle(
        config=config,
        paths=paths,
        dataset=dataset,
        case=case,
        task=task,
    )

    previous_feedback: Path | None = None
    final: dict[str, Any] = {}
    for round_index in range(1, config.max_rounds + 1):
        worker_prompt = build_worker_prompt(
            config=config,
            paths=paths,
            round_index=round_index,
            task=task,
            feedback_path=previous_feedback,
        )
        worker_prompt_path = paths.worker_dir / f"prompt-round-{round_index:03d}.md"
        worker_prompt_path.write_text(worker_prompt, encoding="utf-8")

        if config.dry_run:
            worker_status = {
                "label": "worker",
                "returncode": 0,
                "timeout": False,
                "elapsed_seconds": 0,
                "dry_run": True,
            }
        else:
            worker_status = run_codex_exec(
                config=config,
                prompt=worker_prompt,
                output_last_message=paths.worker_dir
                / f"final-message-round-{round_index:03d}.md",
                events_path=paths.worker_dir / f"codex-events-round-{round_index:03d}.jsonl",
                timeout=config.worker_timeout,
                label=f"worker-round-{round_index}",
            )
        write_json(paths.worker_dir / f"status-round-{round_index:03d}.json", worker_status)

        pdf_report = evaluate_pdf_quality(paths, config.thresholds)
        pdf_report_path = paths.quality_dir / f"pdf-report-round-{round_index:03d}.json"
        write_json(pdf_report_path, pdf_report)

        gold_report = evaluate_gold_alignment(dataset=dataset, case=case, paths=paths)
        gold_report_path = paths.quality_dir / f"gold-eval-round-{round_index:03d}.json"
        write_json(gold_report_path, gold_report)

        supervisor_prompt = build_supervisor_prompt(
            config=config,
            paths=paths,
            round_index=round_index,
            task=task,
            pdf_report_path=pdf_report_path,
            gold_report_path=gold_report_path,
        )
        supervisor_prompt_path = paths.supervisor_dir / f"prompt-round-{round_index:03d}.md"
        supervisor_prompt_path.write_text(supervisor_prompt, encoding="utf-8")

        supervisor_verdict_path = paths.supervisor_dir / f"verdict-round-{round_index:03d}.json"
        supervisor_message_path = paths.supervisor_dir / f"final-message-round-{round_index:03d}.md"
        if config.dry_run:
            supervisor_status = {
                "label": "supervisor",
                "returncode": 0,
                "timeout": False,
                "elapsed_seconds": 0,
                "dry_run": True,
            }
        else:
            supervisor_status = run_codex_exec(
                config=config,
                prompt=supervisor_prompt,
                output_last_message=supervisor_message_path,
                events_path=paths.supervisor_dir
                / f"codex-events-round-{round_index:03d}.jsonl",
                timeout=config.supervisor_timeout,
                label=f"supervisor-round-{round_index}",
            )
        write_json(
            paths.supervisor_dir / f"status-round-{round_index:03d}.json",
            supervisor_status,
        )
        supervisor_verdict = parse_supervisor_verdict(
            supervisor_verdict_path, supervisor_message_path
        )

        deficiencies = deficiency_from_reports(
            paths=paths,
            pdf_report=pdf_report,
            gold_report=gold_report,
            supervisor_verdict=supervisor_verdict,
        )
        self_dev = write_self_dev_outputs(paths, deficiencies)
        final = final_status(
            config=config,
            paths=paths,
            round_index=round_index,
            pdf_report=pdf_report,
            gold_report=gold_report,
            supervisor_verdict=supervisor_verdict,
            self_dev=self_dev,
            worker_status=worker_status,
            supervisor_status=supervisor_status,
        )
        write_json(paths.run_dir / "final-status.json", final)

        if final["status"] == "completed_final_candidate":
            break
        if supervisor_verdict.get("verdict") == "revise" and round_index < config.max_rounds:
            previous_feedback = supervisor_verdict_path
            continue
        break

    return final


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a private Codex-supervised RH paper-production E2E task."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case-id", default="first_positive")
    parser.add_argument("--topic", default="")
    parser.add_argument("--target-venue", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--codex-bin", default=shutil.which("codex") or "codex")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--worker-timeout", type=int, default=6 * 60 * 60)
    parser.add_argument("--supervisor-timeout", type=int, default=90 * 60)
    parser.add_argument("--min-pages", type=int, default=6)
    parser.add_argument("--min-words", type=int, default=3500)
    parser.add_argument("--min-references", type=int, default=15)
    parser.add_argument("--min-citation-markers", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset, case = load_case(args.dataset, args.case_id)
    topic = args.topic.strip() or case_topic(case)
    profile = case.get("paper_profile") if isinstance(case.get("paper_profile"), dict) else {}
    target_venue = args.target_venue.strip() or str(profile.get("target_venue") or "target venue")
    task_id = args.task_id.strip() or (
        f"{slugify(str(case['case_id']))}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    config = HarnessConfig(
        repo_root=args.repo_root.resolve(),
        run_root=args.run_root.resolve(),
        dataset_path=args.dataset.resolve(),
        case_id=str(case["case_id"]),
        topic=topic,
        target_venue=target_venue,
        task_id=task_id,
        codex_bin=args.codex_bin,
        max_rounds=max(1, args.max_rounds),
        worker_timeout=args.worker_timeout,
        supervisor_timeout=args.supervisor_timeout,
        thresholds=QualityThresholds(
            min_pages=args.min_pages,
            min_words=args.min_words,
            min_references=args.min_references,
            min_citation_markers=args.min_citation_markers,
        ),
        dry_run=args.dry_run,
    )
    # Keep lint honest and prove dataset was parseable before the long run.
    _ = dataset
    final = run_harness(config)
    print(json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if final["status"] == "completed_final_candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
