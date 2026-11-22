"""Prompt-shape tests for direction_ranking.

These tests exercise the prompt builder directly (no LLM call). Legacy
red-ocean/opportunity-angle kwargs remain accepted, but competition density
must never alter merit scoring text.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_SOURCE = (
    REPO_ROOT
    / "packages"
    / "research_harness"
    / "research_harness"
    / "_workflow"
    / "execution"
    / "prompts.py"
)


def _package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


def _load_direction_ranking_prompt():
    prefix = "pgl03b_prompt_tests"
    _package(prefix)
    _package(f"{prefix}.execution")
    writing_rigor = ModuleType(f"{prefix}.execution.writing_rigor")
    writing_rigor.build_rigor_block = lambda *_, **__: ""
    writing_rigor.normalize_section_key = lambda section: section
    sys.modules[writing_rigor.__name__] = writing_rigor
    spec = importlib.util.spec_from_file_location(
        f"{prefix}.execution.prompts",
        PROMPTS_SOURCE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.direction_ranking_prompt


direction_ranking_prompt = _load_direction_ranking_prompt()


def test_baseline_prompt_omits_saturation_block():
    p = direction_ranking_prompt("- gap A", "- claim A", "topic about X")
    assert "Market saturation" not in p
    assert "opportunity_angle" not in p
    assert "angle_fit" not in p
    assert "novelty" in p
    assert "feasibility" in p
    assert "impact" in p


def test_full_legacy_kwargs_are_density_invariant():
    baseline = direction_ranking_prompt("- gap A", "- claim A", "topic about X")
    p = direction_ranking_prompt(
        "- gap A",
        "- claim A",
        "topic about X",
        area_red_ocean=0.85,
        task_red_ocean=0.90,
        method_red_ocean=0.60,
        opportunity_angle="red_ocean",
    )
    assert p == baseline
    assert "Market saturation" not in p
    assert "opportunity_angle" not in p
    assert "angle_fit" not in p


def test_partial_kwargs_do_not_emit_block():
    """All-or-none: if any required kwarg is missing, baseline prompt emitted."""
    p = direction_ranking_prompt(
        "- gap A",
        "- claim A",
        "topic",
        area_red_ocean=0.5,
        task_red_ocean=0.5,
        method_red_ocean=0.5,
    )
    assert "Market saturation" not in p


def test_frontier_legacy_kwarg_does_not_reward_novelty():
    baseline = direction_ranking_prompt("- gap", "- claim", "topic")
    p = direction_ranking_prompt(
        "- gap",
        "- claim",
        "topic",
        area_red_ocean=0.1,
        task_red_ocean=0.1,
        method_red_ocean=0.1,
        opportunity_angle="frontier",
    )
    assert p == baseline
    assert "frontier" not in p
    assert "reward novelty" not in p
