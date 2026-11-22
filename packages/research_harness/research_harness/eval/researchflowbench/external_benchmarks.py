"""External benchmark registry for ResearchFlowBench calibration.

The registry intentionally stores adapter metadata only. It points RH toward
public benchmark harnesses and datasets without vendoring third-party task data
or hidden gold into the Research Harness repository.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .contract import GOLD_STORAGE_LOCAL_ONLY
from .metric_map import metric_map_payload, metric_mappings_for_benchmark
from research_harness.config import state_path


@dataclass(frozen=True)
class ExternalBenchmarkSpec:
    """A public benchmark candidate worth testing against RH."""

    benchmark_id: str
    name: str
    priority: str
    adapter_status: str
    publication_ready: bool
    repo_url: str
    paper_url: str
    dataset_url: str
    license_key: str
    task_unit: str
    public_metrics: tuple[str, ...]
    metric_labels: tuple[str, ...]
    rh_axes: tuple[str, ...]
    recommended_scope: str
    fetch_steps: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Return a JSON-serializable registry record."""

        payload = asdict(self)
        payload["metric_mappings"] = [
            mapping.to_dict()
            for mapping in metric_mappings_for_benchmark(self.benchmark_id)
        ]
        return payload


@dataclass(frozen=True)
class ExternalBenchmarkExportResult:
    """Paths written by ``export_external_benchmark_registry``."""

    output_dir: Path
    json_path: Path
    markdown_path: Path
    benchmark_count: int
    recommended_p0_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": "researchflowbench.external_benchmark_export.v0.1",
            "output_dir": str(self.output_dir),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "benchmark_count": self.benchmark_count,
            "recommended_p0_ids": list(self.recommended_p0_ids),
        }


@dataclass(frozen=True)
class LocalBenchmarkDataSpec:
    """Local-only data contract for an official benchmark source."""

    benchmark_id: str
    adapter_id: str
    official_source_url: str
    expected_local_path: str
    license_key: str
    redistribution_policy: str
    gold_label_policy: str
    supported_metrics: tuple[str, ...]
    required_local_files: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "adapter_id": self.adapter_id,
            "official_source_url": self.official_source_url,
            "expected_local_path": self.expected_local_path,
            "license_key": self.license_key,
            "redistribution_policy": self.redistribution_policy,
            "gold_label_policy": self.gold_label_policy,
            "supported_metrics": list(self.supported_metrics),
            "required_local_files": list(self.required_local_files),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class LocalBenchmarkDataCheck:
    """Preflight result for one local-only external benchmark data contract."""

    benchmark_id: str
    adapter_id: str
    status: str
    root_source: str
    root_path: str
    expected_local_path: str
    required_local_files: tuple[str, ...]
    found_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    official_source_url: str
    license_key: str
    redistribution_policy: str
    gold_label_policy: str
    message: str

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "adapter_id": self.adapter_id,
            "status": self.status,
            "root_source": self.root_source,
            "root_path": self.root_path,
            "expected_local_path": self.expected_local_path,
            "required_local_files": list(self.required_local_files),
            "found_files": list(self.found_files),
            "missing_files": list(self.missing_files),
            "official_source_url": self.official_source_url,
            "license_key": self.license_key,
            "redistribution_policy": self.redistribution_policy,
            "gold_label_policy": self.gold_label_policy,
            "message": self.message,
        }


_EXTERNAL_BENCHMARKS: tuple[ExternalBenchmarkSpec, ...] = (
    ExternalBenchmarkSpec(
        benchmark_id="autoresearchbench",
        name="AutoResearchBench",
        priority="P0",
        adapter_status="adapter_available",
        publication_ready=True,
        repo_url="https://github.com/CherYou/AutoResearchBench",
        paper_url="https://arxiv.org/abs/2604.25256",
        dataset_url="https://huggingface.co/datasets/Lk123/AutoResearchBench",
        license_key="apache-2.0",
        task_unit="1000 scientific literature discovery queries: 600 Deep, 400 Wide",
        public_metrics=("deep_accuracy", "wide_iou"),
        metric_labels=("Deep Accuracy", "Wide IoU"),
        rh_axes=(
            "literature_discovery",
            "deep_research",
            "set_completion",
            "public_leaderboard_signal",
        ),
        recommended_scope=(
            "Use as the first public-impact adapter for RH literature discovery; "
            "do not use it as a replacement for RH governance/provenance tasks."
        ),
        fetch_steps=(
            "git clone https://github.com/CherYou/AutoResearchBench.git",
            "curl -L -o input_data/AutoResearchBench.jsonl.obf.json "
            "https://huggingface.co/datasets/Lk123/AutoResearchBench/resolve/main/AutoResearchBench.jsonl.obf.json",
            "python3 decrypt_benchmark.py --input-file input_data/AutoResearchBench.jsonl.obf.json "
            "--output-file input_data/AutoResearchBench.jsonl",
        ),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="litsearch",
        name="LitSearch",
        priority="P0",
        adapter_status="adapter_next",
        publication_ready=True,
        repo_url="https://github.com/princeton-nlp/LitSearch",
        paper_url="https://arxiv.org/abs/2407.18940",
        dataset_url="https://huggingface.co/datasets/princeton-nlp/LitSearch",
        license_key="mit",
        task_unit="597 realistic literature-search queries over recent ML/NLP papers",
        public_metrics=("retrieval_recall", "rerank_quality"),
        metric_labels=("Retrieval Recall", "Rerank Quality"),
        rh_axes=(
            "paper_search",
            "retrieval_quality",
            "retrieval_provenance",
            "citation_candidate_generation",
        ),
        recommended_scope=(
            "Use as a low-cost retrieval adapter for paper_search and citation "
            "candidate quality before running heavier agent benchmarks."
        ),
        fetch_steps=(
            "git clone https://github.com/princeton-nlp/LitSearch.git",
            "python - <<'PY'\nfrom datasets import load_dataset\nload_dataset('princeton-nlp/LitSearch', 'query', split='full')\nload_dataset('princeton-nlp/LitSearch', 'corpus_clean', split='full')\nPY",
        ),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="researcherbench",
        name="ResearcherBench",
        priority="P1",
        adapter_status="license_review",
        publication_ready=False,
        repo_url="https://github.com/GAIR-NLP/ResearcherBench",
        paper_url="https://arxiv.org/abs/2507.16280",
        dataset_url="https://github.com/GAIR-NLP/ResearcherBench/tree/main/data",
        license_key="noassertion",
        task_unit="65 frontier AI research questions with expert rubrics",
        public_metrics=("coverage", "faithfulness", "groundedness"),
        metric_labels=("Coverage", "Faithfulness", "Groundedness"),
        rh_axes=(
            "deep_research",
            "report_quality",
            "citation_faithfulness",
            "claim_grounding",
        ),
        recommended_scope=(
            "Use for deep-research report calibration after license terms are "
            "confirmed; strong fit for RH report and citation-quality claims."
        ),
        fetch_steps=(
            "git clone https://github.com/GAIR-NLP/ResearcherBench.git",
            "prepare RH responses as data/user_data/<model_name>.json",
            "./eval.sh",
        ),
        limitations=("license_review_required",),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="sage_literature_retrieval",
        name="SAGE",
        priority="P1",
        adapter_status="adapter_planned",
        publication_ready=True,
        repo_url="https://huggingface.co/papers/2602.05975",
        paper_url="https://arxiv.org/abs/2602.05975",
        dataset_url="https://huggingface.co/papers/2602.05975",
        license_key="noassertion",
        task_unit=(
            "1,200 scientific literature retrieval queries across four domains "
            "over a 200,000-paper corpus"
        ),
        public_metrics=("retrieval_recall", "rerank_quality", "retrieval_scaling"),
        metric_labels=("Retrieval Recall", "Rerank Quality", "Retrieval Scaling"),
        rh_axes=(
            "paper_search",
            "deep_research",
            "retrieval_quality",
            "citation_candidate_generation",
        ),
        recommended_scope=(
            "Use after LitSearch to stress larger-corpus scientific retrieval "
            "and deep-research candidate generation."
        ),
        fetch_steps=(
            "review SAGE paper and dataset release notes",
            "download official query and corpus files into RESEARCH_HARNESS_BENCHMARK_DATA/sage_literature_retrieval",
            "implement adapter only after license and schema are confirmed",
        ),
        limitations=("adapter_not_implemented", "license_review_required"),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="paperarena",
        name="PaperArena",
        priority="P1",
        adapter_status="adapter_planned",
        publication_ready=True,
        repo_url="https://github.com/Melmaphother/PaperArena",
        paper_url="https://arxiv.org/abs/2510.10909",
        dataset_url="https://paperarena-ai.github.io/",
        license_key="noassertion",
        task_unit=(
            "tool-augmented scientific literature reasoning tasks requiring "
            "cross-paper evidence integration"
        ),
        public_metrics=("average_score", "efficiency", "tool_steps"),
        metric_labels=("Average Score", "Efficiency", "Tool Steps"),
        rh_axes=(
            "scientific_literature_reasoning",
            "tool_orchestration",
            "citation_grounding",
            "evidence_synthesis",
        ),
        recommended_scope=(
            "Use after retrieval adapters to evaluate RH evidence synthesis, "
            "tool-use traces, and grounded cross-paper answers."
        ),
        fetch_steps=(
            "git clone https://github.com/Melmaphother/PaperArena.git",
            "review dataset license, tool runtime, and judge requirements",
            "map PaperArena MC/CA/OA outputs to RH evidence reasoning axes",
        ),
        limitations=("adapter_not_implemented", "license_review_required"),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="scienceagentbench",
        name="ScienceAgentBench",
        priority="P2",
        adapter_status="heavy_harness",
        publication_ready=True,
        repo_url="https://github.com/OSU-NLP-Group/ScienceAgentBench",
        paper_url="https://arxiv.org/abs/2410.05080",
        dataset_url="https://huggingface.co/datasets/osunlp/ScienceAgentBench",
        license_key="mit-code/cc-by-4.0-tasks",
        task_unit="102 data-driven scientific discovery programming tasks",
        public_metrics=("task_success", "execution_score", "cost"),
        metric_labels=("Task Success", "Execution Score", "Cost"),
        rh_axes=(
            "scientific_execution",
            "code_generation",
            "cost_latency",
            "reproducibility",
        ),
        recommended_scope=(
            "Use as a P1 execution benchmark once RH has a stable code-agent "
            "runner and isolated evaluation environment."
        ),
        fetch_steps=(
            "git clone https://github.com/OSU-NLP-Group/ScienceAgentBench.git",
            "load annotation inputs from https://huggingface.co/datasets/osunlp/ScienceAgentBench",
            "download benchmark_verified.zip from the official project link; do not redistribute unzipped files",
        ),
        limitations=("full_gold_files_not_redistributable", "docker_or_conda_required"),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="deepresearch_bench",
        name="DeepResearch Bench",
        priority="P2",
        adapter_status="leaderboard_harness_planned",
        publication_ready=True,
        repo_url="https://github.com/Ayanami0730/deep_research_bench",
        paper_url="https://arxiv.org/abs/2506.11763",
        dataset_url="https://deepresearch-bench.github.io/",
        license_key="noassertion",
        task_unit="100 PhD-level deep-research tasks across 22 fields",
        public_metrics=(
            "report_quality",
            "effective_citation_count",
            "citation_accuracy",
        ),
        metric_labels=(
            "Report Quality",
            "Effective Citation Count",
            "Citation Accuracy",
        ),
        rh_axes=(
            "deep_research",
            "report_quality",
            "citation_faithfulness",
            "information_retrieval",
        ),
        recommended_scope=(
            "Use as the first public deep-research leaderboard target after RH "
            "can emit citation-rich reports with reproducible source traces."
        ),
        fetch_steps=(
            "git clone https://github.com/Ayanami0730/deep_research_bench.git",
            "review official evaluator and leaderboard submission format",
            "map RH final report bundles to the benchmark's report and citation evaluators",
        ),
        limitations=("adapter_not_implemented", "judge_or_submission_review_required"),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="deepresearch_bench_ii",
        name="DeepResearch Bench II",
        priority="P2",
        adapter_status="leaderboard_harness_planned",
        publication_ready=True,
        repo_url="https://deepresearch-bench.github.io/",
        paper_url="https://arxiv.org/abs/2601.08536",
        dataset_url="https://deepresearch-bench.github.io/",
        license_key="noassertion",
        task_unit=(
            "132 grounded research tasks with fine-grained binary rubrics "
            "derived from expert reports"
        ),
        public_metrics=(
            "information_recall",
            "analysis_quality",
            "presentation_quality",
        ),
        metric_labels=("Information Recall", "Analysis", "Presentation"),
        rh_axes=(
            "deep_research",
            "evidence_synthesis",
            "report_quality",
            "rubric_satisfaction",
        ),
        recommended_scope=(
            "Use after DeepResearch Bench v1 for rubric-level diagnosis of "
            "RH report recall, analysis, and presentation quality."
        ),
        fetch_steps=(
            "review DeepResearch Bench II release and rubric access terms",
            "map RH publication bundles to report-style submissions",
            "implement local evaluator only after rubric license and judge costs are clear",
        ),
        limitations=(
            "adapter_not_implemented",
            "license_review_required",
            "judge_cost_review_required",
        ),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="paperbench",
        name="PaperBench",
        priority="P2",
        adapter_status="heavy_harness",
        publication_ready=True,
        repo_url="https://github.com/openai/frontier-evals",
        paper_url="https://arxiv.org/abs/2504.01848",
        dataset_url="https://github.com/openai/frontier-evals/tree/main/project/paperbench",
        license_key="mit",
        task_unit="20 ICML 2024 Spotlight/Oral paper replication tasks",
        public_metrics=("replication_score_percent",),
        metric_labels=("Replication Score (%)",),
        rh_axes=(
            "paper_replication",
            "artifact_linked_reporting",
            "reproducibility",
            "execution_validation",
        ),
        recommended_scope=(
            "Use as a long-horizon P1/P2 calibration target for RH replication "
            "and artifact-linked reporting, not as an early smoke test."
        ),
        fetch_steps=(
            "git clone https://github.com/openai/frontier-evals.git --filter=blob:none",
            "git lfs fetch --include 'project/paperbench/data/**' --exclude ''",
            "git lfs checkout project/paperbench/data",
        ),
        limitations=("gpu_recommended", "long_runtime", "api_keys_required_for_judge"),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="core_bench",
        name="CORE-Bench",
        priority="P2",
        adapter_status="hal_harness_preferred",
        publication_ready=True,
        repo_url="https://github.com/siegelz/core-bench",
        paper_url="https://arxiv.org/abs/2409.11363",
        dataset_url="https://huggingface.co/datasets/siegelz/core-bench",
        license_key="mit",
        task_unit="270 computational reproducibility tasks from 90 papers",
        public_metrics=("reproduction_accuracy", "task_question_score"),
        metric_labels=("Reproduction Accuracy", "Task Question Score"),
        rh_axes=(
            "computational_reproducibility",
            "paper_artifact_navigation",
            "execution_validation",
        ),
        recommended_scope=(
            "Use through the Holistic Agent Leaderboard harness for public "
            "reproducibility positioning after RH execution traces are stable."
        ),
        fetch_steps=(
            "git clone https://github.com/siegelz/core-bench.git",
            "load dataset from https://huggingface.co/datasets/siegelz/core-bench",
            "prefer https://github.com/princeton-pli/hal-harness for current runs",
        ),
        limitations=("docker_required", "current_repo_harness_not_maintained"),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="mlr_bench",
        name="MLR-Bench",
        priority="P3",
        adapter_status="long_horizon_harness_planned",
        publication_ready=True,
        repo_url="https://arxiv.org/abs/2505.19955",
        paper_url="https://arxiv.org/abs/2505.19955",
        dataset_url="https://arxiv.org/abs/2505.19955",
        license_key="noassertion",
        task_unit=(
            "201 open-ended ML research tasks covering idea generation, "
            "proposal, experimentation, and paper writing"
        ),
        public_metrics=("research_quality", "experiment_validity", "paper_quality"),
        metric_labels=("Research Quality", "Experiment Validity", "Paper Quality"),
        rh_axes=(
            "idea_generation",
            "proposal_quality",
            "experiment_execution",
            "paper_writing",
            "scientific_reliability",
        ),
        recommended_scope=(
            "Use as a P3 full research-lifecycle benchmark after RH has stable "
            "experiment execution and paper-writing replay gates."
        ),
        fetch_steps=(
            "review MLR-Bench code/data release and judge requirements",
            "map RH proposal, experiment, and paper artifacts to MLR-Bench stages",
            "run only in isolated long-horizon worktrees with human approval gates",
        ),
        limitations=(
            "adapter_not_implemented",
            "long_runtime",
            "judge_cost_review_required",
        ),
    ),
    ExternalBenchmarkSpec(
        benchmark_id="airs_bench",
        name="AIRS-Bench",
        priority="P3",
        adapter_status="license_review",
        publication_ready=False,
        repo_url="https://github.com/facebookresearch/airs-bench",
        paper_url="https://arxiv.org/abs/2602.06855",
        dataset_url="https://huggingface.co/datasets/facebook/airs-bench",
        license_key="cc-by-nc-4.0",
        task_unit="20 frontier ML research-agent tasks from 17 papers",
        public_metrics=("average_normalized_score", "valid_submission_rate", "elo"),
        metric_labels=("Average Normalized Score", "Valid Submission Rate", "Elo"),
        rh_axes=(
            "frontier_ml_research",
            "agent_scaffold_quality",
            "execution_validation",
        ),
        recommended_scope=(
            "Keep as a P2 research-only calibration target because the license "
            "is non-commercial and the harness is heavier than P0 adapters."
        ),
        fetch_steps=(
            "git clone https://github.com/facebookresearch/airs-bench.git",
            "./datasets/download_hf_datasets_text.sh datasets/datasets_download_location/",
        ),
        limitations=("license_review_required", "non_commercial_license"),
    ),
)


_LOCAL_BENCHMARK_DATA: tuple[LocalBenchmarkDataSpec, ...] = (
    LocalBenchmarkDataSpec(
        benchmark_id="autoresearchbench",
        adapter_id="researchflowbench.adapters.autoresearchbench.v0.1",
        official_source_url="https://huggingface.co/datasets/Lk123/AutoResearchBench",
        expected_local_path=(
            "${RESEARCH_HARNESS_BENCHMARK_DATA}/autoresearchbench/input_data/"
            "AutoResearchBench.jsonl"
        ),
        license_key="apache-2.0",
        redistribution_policy=(
            "do not commit official obfuscated or decrypted data; keep local "
            "plaintext exports outside the repository"
        ),
        gold_label_policy=GOLD_STORAGE_LOCAL_ONLY,
        supported_metrics=("deep_accuracy", "wide_iou"),
        required_local_files=("input_data/AutoResearchBench.jsonl",),
        notes=(
            "Adapter consumes only the official plaintext JSONL produced by the upstream decrypt step.",
            "Generated gold files are local judge artifacts and must not be committed.",
        ),
    ),
    LocalBenchmarkDataSpec(
        benchmark_id="litsearch",
        adapter_id="researchflowbench.adapters.litsearch.v0.1",
        official_source_url="https://huggingface.co/datasets/princeton-nlp/LitSearch",
        expected_local_path="${RESEARCH_HARNESS_BENCHMARK_DATA}/litsearch",
        license_key="mit",
        redistribution_policy=(
            "do not commit official dataset rows or generated task packs; "
            "rebuild from a local official export"
        ),
        gold_label_policy=GOLD_STORAGE_LOCAL_ONLY,
        supported_metrics=("retrieval_recall", "rerank_quality"),
        required_local_files=("query/queries.jsonl", "corpus_clean/corpus.jsonl"),
        notes=(
            "Adapter can run with query records only for smoke tests, but full scoring expects gold paper IDs.",
            "Corpus exports are local-only because they are third-party benchmark data.",
        ),
    ),
)


def list_external_benchmarks() -> tuple[ExternalBenchmarkSpec, ...]:
    """Return all external benchmark candidates sorted by priority and id."""

    return tuple(
        sorted(
            _EXTERNAL_BENCHMARKS, key=lambda spec: (spec.priority, spec.benchmark_id)
        )
    )


def recommended_external_benchmarks(
    max_priority: str = "P1",
) -> tuple[ExternalBenchmarkSpec, ...]:
    """Return benchmarks at or above a priority cutoff."""

    priority_limit = _priority_rank(max_priority)
    return tuple(
        spec
        for spec in list_external_benchmarks()
        if _priority_rank(spec.priority) <= priority_limit
    )


def list_local_benchmark_data() -> tuple[LocalBenchmarkDataSpec, ...]:
    """Return local data contracts for currently implemented adapters."""

    return tuple(sorted(_LOCAL_BENCHMARK_DATA, key=lambda spec: spec.benchmark_id))


def export_external_benchmark_registry(
    output_dir: str | Path,
) -> ExternalBenchmarkExportResult:
    """Write JSON and Markdown benchmark registry files to ``output_dir``."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    specs = list_external_benchmarks()
    p0_ids = tuple(spec.benchmark_id for spec in recommended_external_benchmarks("P0"))

    payload = {
        "schema_version": "researchflowbench.external_benchmarks.v0.1",
        "policy": {
            "data_handling": (
                "do not vendor released benchmark data into RH; use official "
                "repos/datasets and record local paths in run metadata"
            ),
            "gold_visibility": "external gold remains judge-only",
            "publication_rule": (
                "only publication_ready benchmarks can be used in public claims "
                "without additional license review"
            ),
        },
        "benchmark_count": len(specs),
        "recommended_p0_ids": list(p0_ids),
        "metric_map": metric_map_payload(),
        "local_data_registry": local_benchmark_data_registry_payload(),
        "benchmarks": [spec.to_dict() for spec in specs],
    }
    json_path = out / "external_benchmarks.json"
    markdown_path = out / "external_benchmarks.md"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(_markdown_registry(specs, p0_ids), encoding="utf-8")
    return ExternalBenchmarkExportResult(
        output_dir=out,
        json_path=json_path,
        markdown_path=markdown_path,
        benchmark_count=len(specs),
        recommended_p0_ids=p0_ids,
    )


def external_benchmark_registry_payload() -> dict:
    """Return the benchmark registry as an API/CLI payload."""

    specs = list_external_benchmarks()
    return {
        "schema_version": "researchflowbench.external_benchmarks.v0.1",
        "benchmark_count": len(specs),
        "recommended_p0_ids": [
            spec.benchmark_id for spec in recommended_external_benchmarks("P0")
        ],
        "metric_map": metric_map_payload(),
        "local_data_registry": local_benchmark_data_registry_payload(),
        "benchmarks": [spec.to_dict() for spec in specs],
    }


def local_benchmark_data_registry_payload() -> dict:
    """Return local official-data requirements for implemented adapters."""

    specs = list_local_benchmark_data()
    return {
        "schema_version": "researchflowbench.local_benchmark_data.v0.1",
        "policy": {
            "root_env": "RESEARCH_HARNESS_BENCHMARK_DATA",
            "default_root": ".research-harness/benchmarks",
            "third_party_data_vendored": False,
            "gold_label_policies": {
                "public_safe_synthetic": "gold may be committed only for RH-owned synthetic fixtures",
                "reference_only": "gold labels are referenced by official ID/path but not copied",
                "local_only": "gold labels may exist in a local checkout/export but must not be committed",
                "judge_only": "gold labels are hidden judge artifacts and never visible to agents",
            },
        },
        "benchmark_count": len(specs),
        "benchmarks": [spec.to_dict() for spec in specs],
    }


def check_local_benchmark_data(
    benchmark_id: str | None = None,
    *,
    root: str | Path | None = None,
) -> tuple[LocalBenchmarkDataCheck, ...]:
    """Check whether local official benchmark files required by adapters exist."""

    specs = list_local_benchmark_data()
    if benchmark_id is not None:
        specs = tuple(spec for spec in specs if spec.benchmark_id == benchmark_id)
        if not specs:
            raise ValueError(f"unknown local benchmark data contract: {benchmark_id}")

    root_path, root_source = _resolve_benchmark_root(root)
    return tuple(
        _check_local_benchmark_spec(spec, root_path=root_path, root_source=root_source)
        for spec in specs
    )


def local_benchmark_data_check_payload(
    benchmark_id: str | None = None,
    *,
    root: str | Path | None = None,
) -> dict:
    """Return a machine-readable local benchmark data preflight payload."""

    checks = check_local_benchmark_data(benchmark_id, root=root)
    return {
        "schema_version": "researchflowbench.local_benchmark_data_check.v0.1",
        "policy": {
            "root_env": "RESEARCH_HARNESS_BENCHMARK_DATA",
            "default_root": ".research-harness/benchmarks",
            "third_party_data_vendored": False,
            "gold_label_policy": GOLD_STORAGE_LOCAL_ONLY,
        },
        "status": "pass" if all(check.passed for check in checks) else "blocked",
        "check_count": len(checks),
        "checks": [check.to_dict() for check in checks],
    }


def _resolve_benchmark_root(root: str | Path | None) -> tuple[Path, str]:
    if root is not None:
        return Path(root).expanduser(), "argument"
    env_value = os.environ.get("RESEARCH_HARNESS_BENCHMARK_DATA")
    if env_value:
        return Path(env_value).expanduser(), "environment"
    return state_path("benchmarks"), "default"


def _check_local_benchmark_spec(
    spec: LocalBenchmarkDataSpec,
    *,
    root_path: Path,
    root_source: str,
) -> LocalBenchmarkDataCheck:
    expected = _resolve_expected_local_path(spec.expected_local_path, root_path)
    required_paths = tuple(
        _resolve_required_file(expected, item) for item in spec.required_local_files
    )
    found = tuple(str(path) for path in required_paths if path.is_file())
    missing = tuple(str(path) for path in required_paths if not path.is_file())
    status = "pass" if not missing else "blocked"
    if status == "pass":
        message = "all required local official benchmark files are present"
    else:
        message = (
            "missing required local official benchmark files; do not adapt, score, "
            "or record real-data evidence until this check passes"
        )
    return LocalBenchmarkDataCheck(
        benchmark_id=spec.benchmark_id,
        adapter_id=spec.adapter_id,
        status=status,
        root_source=root_source,
        root_path=str(root_path),
        expected_local_path=str(expected),
        required_local_files=spec.required_local_files,
        found_files=found,
        missing_files=missing,
        official_source_url=spec.official_source_url,
        license_key=spec.license_key,
        redistribution_policy=spec.redistribution_policy,
        gold_label_policy=spec.gold_label_policy,
        message=message,
    )


def _resolve_expected_local_path(template: str, root_path: Path) -> Path:
    return Path(
        template.replace("${RESEARCH_HARNESS_BENCHMARK_DATA}", str(root_path))
    ).expanduser()


def _resolve_required_file(expected_path: Path, required_file: str) -> Path:
    required = Path(required_file)
    if expected_path.suffix and expected_path.name == required.name:
        return expected_path
    return expected_path / required


def _priority_rank(priority: str) -> int:
    if not priority.startswith("P"):
        raise ValueError(f"invalid priority: {priority}")
    return int(priority[1:])


def _markdown_registry(
    specs: tuple[ExternalBenchmarkSpec, ...],
    p0_ids: tuple[str, ...],
) -> str:
    lines = [
        "# ResearchFlowBench External Benchmark Registry",
        "",
        "Policy: do not vendor released benchmark data into RH; use official repos/datasets and record local paths in run metadata.",
        "",
        f"P0 adapters: {', '.join(p0_ids)}",
        "",
        "| Priority | Benchmark | Public metrics | RH metric axes | Publication-ready | Source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for spec in specs:
        mapped_axes = tuple(
            axis_id
            for mapping in metric_mappings_for_benchmark(spec.benchmark_id)
            for axis_id in mapping.rh_axis_ids
        )
        axis_text = ", ".join(dict.fromkeys(mapped_axes)) or ", ".join(spec.rh_axes)
        lines.append(
            "| "
            + " | ".join(
                (
                    spec.priority,
                    spec.name,
                    ", ".join(spec.metric_labels),
                    axis_text,
                    "yes" if spec.publication_ready else "needs review",
                    spec.repo_url,
                )
            )
            + " |"
        )
    lines.extend(["", "## Fetch Plan", ""])
    for spec in specs:
        lines.extend(
            [
                f"### {spec.name}",
                "",
                f"- Scope: {spec.recommended_scope}",
                f"- License: `{spec.license_key}`",
                f"- Dataset: {spec.dataset_url}",
                "- Steps:",
            ]
        )
        lines.extend(f"  - `{step}`" for step in spec.fetch_steps)
        if spec.limitations:
            lines.append(f"- Limitations: {', '.join(spec.limitations)}")
        lines.append("")
    lines.extend(["## Metric Map", ""])
    for axis in metric_map_payload()["rh_axes"]:
        lines.append(
            f"- `{axis['axis_id']}` ({axis['stage']}/{axis['component']}): "
            f"{axis['capability']}"
        )
    lines.extend(
        [
            "",
            "## Local Data Registry",
            "",
            "| Benchmark | Adapter | Expected local path | Metrics | Gold labels |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for local_spec in list_local_benchmark_data():
        lines.append(
            "| "
            + " | ".join(
                (
                    local_spec.benchmark_id,
                    f"`{local_spec.adapter_id}`",
                    f"`{local_spec.expected_local_path}`",
                    ", ".join(local_spec.supported_metrics),
                    local_spec.gold_label_policy,
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
