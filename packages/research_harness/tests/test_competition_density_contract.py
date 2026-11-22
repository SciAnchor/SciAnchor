from __future__ import annotations

import importlib.util
import inspect
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
RH_SOURCE = REPO_ROOT / "packages" / "research_harness" / "research_harness"
MCP_SOURCE = (
    REPO_ROOT
    / "packages"
    / "research_harness_mcp"
    / "research_harness_mcp"
    / "tools_workflow.py"
)
PROMPT_SHIM_SOURCE = RH_SOURCE / "execution" / "prompts.py"
CERTIFICATION_SOURCE = RH_SOURCE / "panorama" / "certify.py"
STOP_SOURCE = RH_SOURCE / "longtask" / "runner.py"


def _package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _PrimitiveSpec:
    def __init__(self, **values: Any):
        self.__dict__.update(values)


class _PrimitiveCategory:
    ANALYSIS = "analysis"


def _register_primitive(_spec: Any):
    return lambda function: function


@dataclass
class _CandidateDraft:
    title: str
    pitch: str


def _load_rh_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    prefix = "pgl03b_rh"
    _package(prefix)
    _package(f"{prefix}.storage")
    _package(f"{prefix}.primitives")
    _module(f"{prefix}.storage.db", Database=object)
    _module(f"{prefix}.primitives.registry", register_primitive=_register_primitive)
    _module(
        f"{prefix}.primitives.types",
        PrimitiveCategory=_PrimitiveCategory,
        PrimitiveSpec=_PrimitiveSpec,
    )
    _module(
        f"{prefix}.primitives.candidate_seed",
        CandidateDraft=_CandidateDraft,
        seed_candidates=lambda **_: [],
        upsert_candidate=lambda **_: 1,
    )
    red_ocean = _load(
        f"{prefix}.primitives.red_ocean",
        RH_SOURCE / "primitives" / "red_ocean.py",
    )
    recommend = _load(
        f"{prefix}.primitives.recommend",
        RH_SOURCE / "primitives" / "recommend.py",
    )

    workflow_prefix = "pgl03b_workflow"
    _package(workflow_prefix)
    _package(f"{workflow_prefix}.execution")
    _module(
        f"{workflow_prefix}.execution.writing_rigor",
        build_rigor_block=lambda *_, **__: "",
        normalize_section_key=lambda section: section,
    )
    prompts = _load(
        f"{workflow_prefix}.execution.prompts",
        RH_SOURCE / "_workflow" / "execution" / "prompts.py",
    )
    return red_ocean, recommend, prompts


RED_OCEAN, RECOMMEND, PROMPTS = _load_rh_modules()


def _load_tools_workflow() -> ModuleType:
    return _load("pgl03b_tools_workflow", MCP_SOURCE)


TOOLS_WORKFLOW = _load_tools_workflow()


def test_mcp_projection_matches_canonical_for_all_threshold_states() -> None:
    for area in (0.2, 0.8):
        for task in (0.2, 0.8):
            for method in (0.2, 0.8):
                expected = RED_OCEAN.competition_density_projection(
                    area,
                    task,
                    method,
                )
                assert (
                    TOOLS_WORKFLOW._competition_density_projection(
                        area,
                        task,
                        method,
                    )
                    == expected
                )


def test_direction_ranking_prompt_is_density_invariant() -> None:
    baseline = PROMPTS.direction_ranking_prompt("gaps", "claims", "topic")
    with_density = PROMPTS.direction_ranking_prompt(
        "gaps",
        "claims",
        "topic",
        area_red_ocean=0.95,
        task_red_ocean=0.95,
        method_red_ocean=0.95,
        opportunity_angle="red_ocean",
    )

    assert with_density == baseline
    lowered = with_density.lower()
    assert "market saturation" not in lowered
    assert "penalize novelty" not in lowered
    assert "reward novelty" not in lowered
    assert "angle_fit" not in lowered
    assert "composite = novelty*0.4 + feasibility*0.3 + impact*0.3" in lowered
    signature = inspect.signature(PROMPTS.direction_ranking_prompt)
    assert "area_red_ocean" in signature.parameters
    assert "opportunity_angle" in signature.parameters


def test_public_prompt_shim_keeps_the_density_neutral_canonical_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_names = (
        "research_harness",
        "research_harness._workflow",
        "research_harness._workflow.execution",
        "research_harness.execution",
    )
    packages = {name: ModuleType(name) for name in package_names}
    for package in packages.values():
        package.__path__ = []  # type: ignore[attr-defined]
    packages["research_harness._workflow.execution"].prompts = PROMPTS
    for name, package in packages.items():
        monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(
        sys.modules,
        "research_harness._workflow.execution.prompts",
        PROMPTS,
    )

    shim_name = "research_harness.execution.prompts"
    spec = importlib.util.spec_from_file_location(shim_name, PROMPT_SHIM_SOURCE)
    assert spec is not None and spec.loader is not None
    shim = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, shim_name, shim)
    spec.loader.exec_module(shim)

    assert shim.direction_ranking_prompt is PROMPTS.direction_ranking_prompt


def test_private_triage_prompt_is_density_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    class _Client:
        def __init__(self, _config: Any):
            pass

        def chat(self, prompt: str) -> str:
            captured.append(prompt)
            return '{"score": 8, "breakdown": {"novelty": 8}}'

    # Stub llm_router via monkeypatch only: a bare sys.modules assignment
    # would permanently shadow the real package and break later tests that
    # monkeypatch llm_router.config / llm_router.client (CI-only ordering).
    package_module = ModuleType("llm_router")
    package_module.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llm_router", package_module)
    client_module = ModuleType("llm_router.client")
    client_module.LLMClient = _Client
    client_module.resolve_llm_config = lambda: object()
    monkeypatch.setitem(sys.modules, "llm_router.client", client_module)
    draft = _CandidateDraft(title="candidate", pitch="same evidence")

    RECOMMEND._llm_score_draft(draft, 0.0, 0.0, 0.0, "frontier")
    RECOMMEND._llm_score_draft(draft, 1.0, 1.0, 1.0, "red_ocean")

    assert len(captured) == 2
    assert captured[0] == captured[1]
    lowered = captured[0].lower()
    assert "red ocean" not in lowered
    assert "opportunity angle" not in lowered
    assert "competition density" not in lowered


def test_competition_density_projection_is_three_dimensional_and_ordered() -> None:
    projection = RED_OCEAN.competition_density_projection(0.8, 0.2, 0.7)

    assert projection == {
        "area": 0.8,
        "task": 0.2,
        "method": 0.7,
        "threshold": 0.7,
        "dense_dimensions": ["area", "method"],
    }
    assert (
        RED_OCEAN.competition_density_projection(0.2, 0.2, 0.2)["dense_dimensions"]
        == []
    )
    assert RED_OCEAN.opportunity_angle(0.0, 0.8, 0.2) == RED_OCEAN.opportunity_angle(
        1.0, 0.8, 0.2
    )


def test_legacy_primitive_names_remain_registered() -> None:
    assert RED_OCEAN.COMPUTE_AREA_RED_OCEAN_SPEC.name == "compute_area_red_ocean"
    assert RED_OCEAN.COMPUTE_TASK_RED_OCEAN_SPEC.name == "compute_task_red_ocean"
    assert RED_OCEAN.COMPUTE_METHOD_RED_OCEAN_SPEC.name == "compute_method_red_ocean"


def test_legacy_outputs_gain_exact_competition_density_aliases() -> None:
    score = RED_OCEAN.RedOceanScore(
        scope_type="task",
        scope_id="forecasting",
        score=0.75,
    ).to_dict()
    assert score["score"] == 0.75
    assert score["competition_density"] == score["score"]

    candidate = RECOMMEND.GeneratedCandidate(
        candidate_id=1,
        lineage_key="lineage",
        title="candidate",
        llm_score=9.0,
        area_red_ocean=0.8,
        task_red_ocean=0.2,
        method_red_ocean=0.7,
        opportunity_angle="new_task_mature_method",
    ).to_dict()
    assert candidate["area_red_ocean"] == 0.8
    assert candidate["opportunity_angle"] == "new_task_mature_method"
    assert candidate["competition_density"] == {
        "area": 0.8,
        "task": 0.2,
        "method": 0.7,
        "threshold": 0.7,
        "dense_dimensions": ["area", "method"],
    }


class _ArtifactService:
    def __init__(self):
        self.payload: dict[str, Any] | None = None

    def record_artifact(self, **values: Any) -> Any:
        self.payload = values["payload"]
        return SimpleNamespace(
            id=10,
            version=1,
            stage=values["stage"],
            artifact_type=values["artifact_type"],
        )


def test_experiment_brief_adds_canonical_alias_and_keeps_legacy_values() -> None:
    service = _ArtifactService()
    candidate = {
        "scope": "topic:7",
        "lineage_key": "lineage",
        "title": "candidate",
        "pitch": "pitch",
        "opportunity_angle": "red_ocean",
        "area_red_ocean": 0.8,
        "task_red_ocean": 0.9,
        "method_red_ocean": 0.7,
        "llm_score": 9.0,
    }

    result = TOOLS_WORKFLOW._execute_experiment_handoff_prepare(
        service,
        object(),
        {"topic_id": 7, "candidate_id": 3},
        candidate_loader=lambda *_: candidate,
        evidence_loader=lambda *_: {"gaps": [], "contradictions": []},
    )

    assert result["success"] is True
    assert service.payload is not None
    legacy = service.payload["red_ocean"]
    canonical = service.payload["competition_density"]
    assert {key: canonical[key] for key in ("area", "task", "method")} == legacy
    assert canonical["dense_dimensions"] == ["area", "task", "method"]
    assert canonical["threshold"] == 0.7


class _SQLiteDatabase:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


class _WorkflowService:
    def __init__(self):
        self._artifact_manager = SimpleNamespace(
            get=lambda _artifact_id: SimpleNamespace(
                artifact_type="experiment_brief",
                payload={"candidate_id": 1},
            )
        )

    def get_status(self, _topic_id: int) -> dict[str, Any]:
        return {
            "run": {"current_stage": "propose"},
            "gate": {"decision": "GO", "can_advance": False},
        }

    def record_artifact(self, **values: Any) -> Any:
        return SimpleNamespace(
            id=11,
            version=1,
            stage=values["stage"],
            artifact_type=values["artifact_type"],
        )


def _workflow_database(path: Path) -> _SQLiteDatabase:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE gaps(
                topic_id INTEGER,
                cross_verified INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE research_candidates(
                id INTEGER PRIMARY KEY,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                area_red_ocean REAL NOT NULL,
                task_red_ocean REAL NOT NULL,
                method_red_ocean REAL NOT NULL
            );
            INSERT INTO gaps(topic_id, cross_verified) VALUES (7, 1);
            INSERT INTO research_candidates VALUES
                (1, 'topic:7', 'candidate', 1.0, 1.0, 1.0),
                (2, 'topic:7', 'active', 0.0, 0.0, 0.0);
            """
        )
        connection.commit()
    finally:
        connection.close()
    return _SQLiteDatabase(path)


def test_dense_candidates_remain_live_and_promotable(tmp_path: Path) -> None:
    database = _workflow_database(tmp_path / "workflow.db")
    service = _WorkflowService()

    status = TOOLS_WORKFLOW._execute_workflow_entry(service, database, {"topic_id": 7})
    assert status["candidates"] == {"live": 2, "promoted": 0}
    assert any("2 live candidates" in action for action in status["next_actions"])

    promoted = TOOLS_WORKFLOW._execute_experiment_handoff_submit(
        service,
        database,
        {
            "topic_id": 7,
            "brief_artifact_id": 10,
            "handoff_target": "local",
        },
    )
    assert promoted["success"] is True
    connection = database.connect()
    try:
        assert (
            connection.execute(
                "SELECT status FROM research_candidates WHERE id = 1"
            ).fetchone()[0]
            == "promoted"
        )
    finally:
        connection.close()


def test_novelty_promotion_and_stop_surfaces_do_not_consume_density() -> None:
    forbidden = (
        "area_red_ocean",
        "task_red_ocean",
        "method_red_ocean",
        "opportunity_angle",
        "competition_density",
    )
    guarded_sources = (
        CERTIFICATION_SOURCE.read_text(),
        STOP_SOURCE.read_text(),
        inspect.getsource(TOOLS_WORKFLOW._execute_experiment_handoff_submit),
        inspect.getsource(TOOLS_WORKFLOW._execute_workflow_entry),
    )

    for source in guarded_sources:
        lowered = source.lower()
        assert all(token not in lowered for token in forbidden)
