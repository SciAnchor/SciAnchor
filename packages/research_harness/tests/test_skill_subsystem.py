"""Smoke tests for the skill manifest, agent config, and install engine.

These run against the actual ``skills/`` directory shipped in this repo, so
they double as a regression check that the manifest stays parseable and that
``paper-writing`` (and its tracks) is always discoverable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from research_harness.cli import main


# Locate the repo root (works whether tests run from worktree or main)
HERE = Path(__file__).resolve()
REPO_ROOT = next(
    p for p in HERE.parents if (p / "skills").is_dir() and (p / "setup.sh").is_file()
)


def test_build_manifest_finds_all_shipped_skills() -> None:
    from research_harness.skill import build_manifest

    manifest = build_manifest(REPO_ROOT)
    names = manifest.names()
    assert len(names) >= 14, f"expected >= 14 skills, got {names}"
    # Ceiling raised 35 -> 40 (2026-08-10): rh-paper-perfection and
    # project-novelty-certification shipped deliberately (commits e6e603c,
    # 7ee9522) taking the surface to 37.
    assert len(names) <= 40, f"public skill surface should stay <= 40, got {names}"
    assert "rh-codex-checkpoint" not in names
    assert "rh-codex-verify" not in names
    assert "rh-session-resume" not in names
    assert "rh-artifact-record" not in names
    assert "long-task-supervisor" not in names
    # paper-writing is the trigger skill that started this whole subsystem
    assert "manuscript-logic-gate" in names
    assert "manuscript-math-formalization" in names
    assert "paper-writing" in names
    assert "domain-writing-stem" in names
    assert "domain-writing-biomedical" in names
    assert "domain-writing-social-science" in names
    assert "domain-writing-humanities" in names
    assert "domain-writing-law-policy" in names
    pw = manifest.get("paper-writing")
    assert pw is not None
    assert "survey-review" in pw.tracks
    assert "original-research" in pw.tracks


def test_skill_bootstrap_and_doctor_commands_are_registered() -> None:
    from click.testing import CliRunner

    runner = CliRunner()
    for command in ("bootstrap", "doctor"):
        result = runner.invoke(main, ["skill", command, "--help"])
        assert result.exit_code == 0, result.output
        assert "--agent" in result.output
        assert "Claude" in result.output or "critical RH" in result.output


def test_rh_agent_policy_skills_declare_bootstrap_feedback_and_figure_gates() -> None:
    required = {
        "skills/rh-paper-production/SKILL.md": (
            "rh skill doctor --agent claude-code --agent codex",
            "rh-paper-figure-generator",
            "npj Figure 1",
            "figure_generate",
        ),
        "skills/rh-paper-figure-generator/SKILL.md": (
            "figure_contract",
            "Do not send an ad-hoc hand-written prompt directly",
        ),
        "skills/figure-quality/SKILL.md": (
            "single generated candidate is not enough",
            "visible typo",
        ),
        "skills/rh-self-evolution/SKILL.md": (
            "rh self-evolution record-human-feedback",
            "rh self-evolution record-note",
            "trajectory-list",
            "human_feedback",
        ),
    }
    for relative_path, markers in required.items():
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{relative_path} is missing {marker!r}"


def test_ccfa_manuscript_quality_gates_are_generic_and_declared() -> None:
    paper_production = (
        REPO_ROOT / "skills" / "rh-paper-production" / "SKILL.md"
    ).read_text(encoding="utf-8")
    required_markers = (
        "TITLE_ABSTRACT_CONTRIBUTION_GATE",
        "NUMERIC_CONSISTENCY_GATE",
        "RELATED_WORK_SYNTHESIS_GATE",
        "RESULT_EVIDENCE_DENSITY_GATE",
        "ANTI_DEFENSIVE_WRITING_GATE",
        "SCIENTIFIC_TERMINOLOGY_GATE",
        "DATASET_PROTOCOL_APPENDIX_GATE",
        "not topic-specific fixes",
        "venue-target or planning meta-language",
        "CCF-A target",
        "w/o affect memory",
        "metric direction",
        "single mixed leaderboard",
        "public source link",
    )
    for marker in required_markers:
        assert marker in paper_production, f"rh-paper-production is missing {marker!r}"
    assert "ESDiff" not in paper_production


def test_figure_quality_declares_result_figure_publication_gate() -> None:
    figure_quality = (REPO_ROOT / "skills" / "figure-quality" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for marker in (
        "RESULT_FIGURE_PUBLICATION_GATE",
        "default script output",
        "domain-specific scientific-figure templates",
        "stray explanatory paragraph",
        "source-data traceability",
    ):
        assert marker in figure_quality, f"figure-quality is missing {marker!r}"


def test_rh_self_evolution_is_backlog_first_during_research_work() -> None:
    self_evolution = (
        REPO_ROOT / "skills" / "rh-self-evolution" / "SKILL.md"
    ).read_text(encoding="utf-8")
    router = (REPO_ROOT / "skills" / "research-harness" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for text in (self_evolution, router):
        assert "self-evolution backlog" in text
        assert "active research" in text or "active paper" in text
        assert "unless the user explicitly" in text
    assert "Do not patch `research-harness`" in self_evolution
    assert "Do not synchronously patch RH mechanisms" in router
    assert "Batch Repair" in self_evolution


def test_domain_writing_skills_are_discoverable_and_contract_locked() -> None:
    from research_harness.skill import build_manifest

    manifest = build_manifest(REPO_ROOT)
    expected_profiles = {
        "domain-writing-stem": (
            "STEM_ENGINEERING_WRITING_PROFILE",
            "baseline",
            "ablation",
            "DOMAIN_WRITING_PROFILE",
        ),
        "domain-writing-biomedical": (
            "BIOMEDICAL_WRITING_PROFILE",
            "PICO",
            "ethics",
            "DOMAIN_WRITING_PROFILE",
        ),
        "domain-writing-social-science": (
            "SOCIAL_SCIENCE_WRITING_PROFILE",
            "identification strategy",
            "construct",
            "DOMAIN_WRITING_PROFILE",
        ),
        "domain-writing-humanities": (
            "HUMANITIES_WRITING_PROFILE",
            "interpretive",
            "archive",
            "DOMAIN_WRITING_PROFILE",
        ),
        "domain-writing-law-policy": (
            "LAW_POLICY_WRITING_PROFILE",
            "normative",
            "precedent",
            "DOMAIN_WRITING_PROFILE",
        ),
    }

    for name, required_markers in expected_profiles.items():
        skill = manifest.get(name)
        assert skill is not None, f"{name} is missing from skill manifest"
        assert skill.extras["public_suite"] == "paper"
        assert skill.extras["task_type"] == "domain-writing-profile"
        assert "DOMAIN_WRITING_PROFILE" in skill.extras["artifact_schemas"]
        text = (REPO_ROOT / skill.skill_md).read_text(encoding="utf-8")
        for marker in required_markers:
            assert marker in text, f"{name} is missing {marker!r}"


def test_paper_writing_routes_through_domain_writing_profiles() -> None:
    paper_writing = (REPO_ROOT / "skills" / "paper-writing" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    section_drafting = (
        REPO_ROOT / "skills" / "section-drafting" / "SKILL.md"
    ).read_text(encoding="utf-8")

    required_skills = {
        "domain-writing-stem",
        "domain-writing-biomedical",
        "domain-writing-social-science",
        "domain-writing-humanities",
        "domain-writing-law-policy",
    }

    for skill_name in required_skills:
        assert skill_name in paper_writing
        assert skill_name in section_drafting
    assert "DOMAIN_WRITING_PROFILE" in paper_writing
    assert "DOMAIN_WRITING_PROFILE" in section_drafting
    for marker in (
        "PAPER_PROFILE",
        "discipline",
        "research_type",
        "study_design",
        "reporting_map",
        "evidence_rule",
        "do not silently default to STEM",
    ):
        assert marker in paper_writing
        assert marker in section_drafting


def test_domain_writing_skills_declare_paper_profile_interop() -> None:
    from research_harness.skill import build_manifest

    manifest = build_manifest(REPO_ROOT)
    for name in (
        "domain-writing-stem",
        "domain-writing-biomedical",
        "domain-writing-social-science",
        "domain-writing-humanities",
        "domain-writing-law-policy",
    ):
        skill = manifest.get(name)
        assert skill is not None
        text = (REPO_ROOT / skill.skill_md).read_text(encoding="utf-8")
        assert "PAPER_PROFILE" in text
        assert "reporting_map" in text
        assert "evidence_rule" in text


def test_discovery_skills_route_domain_method_search_profiles() -> None:
    skill_paths = (
        "skills/literature-search/SKILL.md",
        "skills/literature-mapping/SKILL.md",
        "skills/gap-analysis/SKILL.md",
        "skills/evidence-gating/SKILL.md",
        "skills/research-harness/SKILL.md",
    )
    for skill_path in skill_paths:
        text = (REPO_ROOT / skill_path).read_text(encoding="utf-8")
        for marker in (
            "DOMAIN_METHOD_SEARCH_PROFILE",
            "method_route",
            "search_route",
            "search_strategies",
            "method_requirements",
            "baseline_anchor_fields",
            "do not silently default to STEM",
        ):
            assert marker in text, f"{skill_path} is missing {marker!r}"


def test_evaluation_and_problem_anchor_gates_are_declared() -> None:
    skill_paths = (
        "skills/gap-analysis/SKILL.md",
        "skills/evidence-gating/SKILL.md",
        "skills/research-init/SKILL.md",
        "skills/research-harness/SKILL.md",
    )
    for skill_path in skill_paths:
        text = (REPO_ROOT / skill_path).read_text(encoding="utf-8")
        for marker in (
            "EVALUATION_GATE_PROFILE",
            "PROBLEM_ANCHOR",
            "baseline_mode",
            "paper_access_status",
            "fatal_flaws",
            "pilot",
        ):
            assert marker in text, f"{skill_path} is missing {marker!r}"


def test_experiment_grounding_gates_are_declared() -> None:
    skill_paths = (
        "skills/evidence-gating/SKILL.md",
        "skills/claim-extraction/SKILL.md",
        "skills/research-harness/SKILL.md",
    )
    for skill_path in skill_paths:
        text = (REPO_ROOT / skill_path).read_text(encoding="utf-8")
        for marker in (
            "EXPERIMENT_GROUNDING_PROFILE",
            "EXPERIMENT_GOAL",
            "EXPERIMENT_PLAN",
            "variable_grounding",
            "codebook",
            "pre_deploy_code_review",
            "IMPACT_REPORT",
            "claim-bound",
        ):
            assert marker in text, f"{skill_path} is missing {marker!r}"


def test_skeleton_source_integrity_gates_are_declared() -> None:
    skill_paths = (
        "skills/paper-writing/SKILL.md",
        "skills/section-drafting/SKILL.md",
        "skills/publication-pack/SKILL.md",
        "skills/provenance-review/SKILL.md",
        "skills/research-harness/SKILL.md",
    )
    for skill_path in skill_paths:
        text = (REPO_ROOT / skill_path).read_text(encoding="utf-8")
        for marker in (
            "SKELETON_SOURCE_INTEGRITY_PROFILE",
            "required_section_groups",
            "source_trace",
            "Claims-Evidence Matrix",
            "citation_integrity",
            "bib_doi_verification",
            "dangling citations",
            "source artifacts",
        ):
            assert marker in text, f"{skill_path} is missing {marker!r}"


def test_presubmission_and_rebuttal_gates_are_declared() -> None:
    skill_paths = (
        "skills/paper-writing/SKILL.md",
        "skills/publication-pack/SKILL.md",
        "skills/provenance-review/SKILL.md",
        "skills/research-harness/SKILL.md",
    )
    for skill_path in skill_paths:
        text = (REPO_ROOT / skill_path).read_text(encoding="utf-8")
        for marker in (
            "PRESUBMISSION_SEVERITY_GATE_PROFILE",
            "CRITICAL",
            "MAJOR",
            "MINOR",
            "integrity_gate",
            "REBUTTAL_READINESS_GATE_PROFILE",
            "ISSUE_BOARD",
            "REVISION_PLAN",
            "provenance gate",
            "commitment gate",
            "coverage gate",
        ):
            assert marker in text, f"{skill_path} is missing {marker!r}"


def test_result_to_claim_analysis_gates_are_declared() -> None:
    skill_paths = (
        "skills/claim-extraction/SKILL.md",
        "skills/evidence-gating/SKILL.md",
        "skills/paper-writing/SKILL.md",
        "skills/research-harness/SKILL.md",
    )
    for skill_path in skill_paths:
        text = (REPO_ROOT / skill_path).read_text(encoding="utf-8")
        for marker in (
            "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
            "CLAIMS_FROM_RESULTS",
            "relative_delta_table",
            "statistical_summary",
            "practical significance",
            "claim_strength",
            "A_confirmed",
            "F_unsupported_or_blocked",
            "overclaimed",
            "negative results",
        ):
            assert marker in text, f"{skill_path} is missing {marker!r}"


def test_rh_paper_production_declares_consistency_and_ccfa_figure_gates() -> None:
    paper_text = (REPO_ROOT / "skills/rh-paper-production/SKILL.md").read_text(
        encoding="utf-8"
    )
    figure_text = (REPO_ROOT / "skills/figure-quality/SKILL.md").read_text(
        encoding="utf-8"
    )

    for marker in (
        "PAPER_POOL_CONSISTENCY_GATE",
        "manuscript bibliography",
        "paper_pool",
        "figure_plan",
        "control/handoff summary",
        "artifact_sync_blocked",
        "npj Figure 1",
        "figure_generate",
        "illustration-fake",
    ):
        assert marker in paper_text
    assert "npj-hero-figure-engineering" not in paper_text
    assert "npj Figure 1" in figure_text
    assert "RH illustration route" in figure_text
    assert "first-class programmatic route" in figure_text
    assert "Automated RH writing uses this path" in figure_text
    assert "only when credentials are available" not in figure_text
    assert "This is the default programmatic route." not in figure_text
    for marker in (
        "CCFA_FIGURE_REVIEW_GATE",
        "Provider completion is only an asset-generation event",
        "contribution clarity",
        "information density",
        "provider_output_not_human_reviewed",
        "review_pending",
    ):
        assert marker in figure_text


def test_public_skills_declare_lightweight_product_contract() -> None:
    from research_harness.skill import build_manifest

    required = {
        "public_suite",
        "task_type",
        "data_access_level",
        "inputs",
        "outputs",
        "gates",
        "artifact_schemas",
        "estimated_runtime",
    }
    allowed_suites = {"research", "paper", "review", "zotero", "benchmark"}

    manifest = build_manifest(REPO_ROOT)
    for skill in manifest.skills:
        missing = sorted(field for field in required if not skill.extras.get(field))
        assert not missing, (
            f"{skill.name} is missing product contract fields: {missing}"
        )
        assert skill.extras["public_suite"] in allowed_suites


def test_write_then_load_manifest_roundtrip(tmp_path: Path) -> None:
    from research_harness.skill import build_manifest, load_manifest, write_manifest

    fake = tmp_path / "repo"
    (fake / "skills" / "alpha").mkdir(parents=True)
    (fake / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: just a test\n---\n# alpha\n"
    )

    manifest = build_manifest(fake)
    assert manifest.names() == ["alpha"]
    write_manifest(manifest, fake)
    loaded = load_manifest(fake)
    assert loaded.names() == ["alpha"]
    assert loaded.skills[0].description == "just a test"


def test_install_symlink_strategy_creates_links(tmp_path: Path) -> None:
    from research_harness.skill import (
        build_manifest,
        install,
        make_explicit_config,
        verify,
    )

    target = tmp_path / "claude-skills"
    config = make_explicit_config(target, strategy="symlink")
    manifest = build_manifest(REPO_ROOT)

    report = install(manifest, config, REPO_ROOT)

    assert all(r.action == "created" for r in report.results)
    pw = target / "paper-writing"
    assert pw.is_symlink()
    assert (pw / "SKILL.md").is_file()
    assert (pw / "tracks" / "survey-review.md").is_file()

    # idempotency
    report2 = install(manifest, config, REPO_ROOT)
    assert all(r.action == "skipped" for r in report2.results)

    # verify reports OK on a clean install
    vreport = verify(manifest, config, REPO_ROOT)
    assert all(r.action == "ok" for r in vreport.results)


def test_install_copy_strategy_writes_files(tmp_path: Path) -> None:
    from research_harness.skill import build_manifest, install, make_explicit_config

    target = tmp_path / "skills-copy"
    config = make_explicit_config(target, strategy="copy")
    manifest = build_manifest(REPO_ROOT)

    install(manifest, config, REPO_ROOT, only=["paper-writing"])
    pw = target / "paper-writing"
    assert pw.is_dir()
    assert not pw.is_symlink()
    assert (pw / "SKILL.md").is_file()
    assert (pw / "tracks" / "survey-review.md").is_file()


def test_agent_config_loader(tmp_path: Path) -> None:
    from research_harness.skill import load_agent_config

    cfg_text = """
[agent]
name = "test-agent"
version = ">=1.0"

[skills]
install_path = "%s"
strategy = "copy"

[skills.include]
only = ["paper-writing", "literature-search"]
""" % str(tmp_path / "out").replace("\\", "/")

    cfg_path = tmp_path / ".rh-agent.toml"
    cfg_path.write_text(cfg_text)
    config = load_agent_config(cfg_path)
    assert config.agent_name == "test-agent"
    assert config.strategy == "copy"
    assert config.include.only == ["paper-writing", "literature-search"]


def test_mcp_runtime_strategy_writes_nothing(tmp_path: Path) -> None:
    from research_harness.skill import build_manifest, install, make_explicit_config

    target = tmp_path / "should-not-be-created"
    config = make_explicit_config(target, strategy="mcp-runtime")
    manifest = build_manifest(REPO_ROOT)
    report = install(manifest, config, REPO_ROOT)

    assert not target.exists()
    assert all(r.action == "runtime-only" for r in report.results)


def test_mcp_skill_tools() -> None:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "research_harness_mcp"))
    from research_harness_mcp.tools_skill import skill_get, skill_list

    out = skill_list({})
    assert out["schema_version"] == "1.0"
    assert any(s["name"] == "paper-writing" for s in out["skills"])

    pw = skill_get({"name": "paper-writing", "track": "survey-review"})
    assert pw["name"] == "paper-writing"
    assert pw.get("track", {}).get("name") == "survey-review"
    assert "Track B" in pw["track"]["content"]


def test_mcp_skill_get_rejects_track_path_traversal() -> None:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "research_harness_mcp"))
    from research_harness_mcp.tools_skill import skill_get

    out = skill_get({"name": "paper-writing", "track": "../../../docs/STATUS"})

    assert "track" not in out
    assert out["track_error"].startswith(
        "track '../../../docs/STATUS' not found for skill 'paper-writing'"
    )
    assert "# Research Harness Status" not in str(out)


def test_skill_get_unknown_returns_helpful_error() -> None:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "research_harness_mcp"))
    from research_harness_mcp.tools_skill import skill_get

    out = skill_get({"name": "does-not-exist"})
    assert "error" in out
    assert "available" in out
    assert isinstance(out["available"], list)


def test_shipped_agent_profiles_load() -> None:
    from research_harness.skill import load_agent_config

    expected = {
        "claude-code.toml": ("claude-code", "~/.claude/skills", "symlink"),
        "codex.toml": ("codex", "~/.codex/skills", "symlink"),
        "gemini.toml": ("gemini", "~/.gemini/skills", "symlink"),
        "opencode.toml": ("opencode", "~/.config/opencode/skills", "symlink"),
        "openclaw.toml": ("openclaw", "${OPENCLAW_HOME}/skills", "copy"),
    }

    for filename, (agent_name, install_path, strategy) in expected.items():
        config = load_agent_config(REPO_ROOT / "skills" / "agent-profiles" / filename)
        assert config.agent_name == agent_name
        assert config.install_path == Path(install_path).expanduser()
        assert config.strategy == strategy


def test_skill_verify_cli_allows_extra_by_default(tmp_path: Path, runner) -> None:
    from research_harness.skill import build_manifest, install, make_explicit_config

    target = tmp_path / "codex-skills"
    config = make_explicit_config(target, strategy="symlink")
    manifest = build_manifest(REPO_ROOT)

    install(manifest, config, REPO_ROOT)
    (target / "unrelated-skill").mkdir()

    result = runner.invoke(
        main,
        [
            "skill",
            "verify",
            "--skills-root",
            str(REPO_ROOT),
            "--target",
            str(target),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[extra   ] unrelated-skill" in result.output
    assert "extra=1" in result.output


def test_skill_verify_cli_strict_extra_fails(tmp_path: Path, runner) -> None:
    from research_harness.skill import build_manifest, install, make_explicit_config

    target = tmp_path / "codex-skills"
    config = make_explicit_config(target, strategy="symlink")
    manifest = build_manifest(REPO_ROOT)

    install(manifest, config, REPO_ROOT)
    (target / "unrelated-skill").mkdir()

    result = runner.invoke(
        main,
        [
            "skill",
            "verify",
            "--skills-root",
            str(REPO_ROOT),
            "--target",
            str(target),
            "--strict-extra",
        ],
    )

    assert result.exit_code == 1, result.output
    assert "extra=1" in result.output


def _read_yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} must contain a YAML mapping"
    return payload


def test_final_bundle_quality_has_v2_skill_package_contracts() -> None:
    from research_harness.skill.manifest import _parse_frontmatter

    skill_dir = REPO_ROOT / "skills" / "final-bundle-quality"
    skill_md = skill_dir / "SKILL.md"
    skill_yaml = skill_dir / "skill.yaml"
    contracts_dir = skill_dir / "contracts"

    assert skill_md.is_file()
    assert skill_yaml.is_file()
    assert (contracts_dir / "input.yaml").is_file()
    assert (contracts_dir / "output.yaml").is_file()
    assert (contracts_dir / "guardrails.yaml").is_file()

    frontmatter = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    manifest = _read_yaml(skill_yaml)

    required_keys = {
        "name",
        "version",
        "license",
        "capability_type",
        "description",
        "input_schema",
        "output_schema",
        "allowed_tools",
        "required_artifacts",
        "guardrails",
        "replay_tests",
        "promotion_policy",
    }
    assert required_keys <= manifest.keys()
    assert manifest["name"] == frontmatter["name"]
    assert str(manifest["version"]) == str(frontmatter["version"])
    assert manifest["capability_type"] == "evaluator"
    assert manifest["license"]
    assert manifest["allowed_tools"]
    assert "final_bundle" in manifest["required_artifacts"]
    assert manifest["guardrails"]["input"]
    assert manifest["guardrails"]["output"]

    contracts = {
        name: _read_yaml(contracts_dir / f"{name}.yaml")
        for name in ("input", "output", "guardrails")
    }
    for name, contract in contracts.items():
        assert contract["schema_version"].startswith("rh.schema.")
        assert contract["type"], f"{name} contract must declare a type"

    assert contracts["input"]["schema_version"] == manifest["input_schema"]
    assert contracts["output"]["schema_version"] == manifest["output_schema"]


def test_publication_pack_has_v2_skill_package_contracts() -> None:
    from research_harness.skill.manifest import _parse_frontmatter

    skill_dir = REPO_ROOT / "skills" / "publication-pack"
    skill_md = skill_dir / "SKILL.md"
    skill_yaml = skill_dir / "skill.yaml"
    contracts_dir = skill_dir / "contracts"

    assert skill_md.is_file()
    assert skill_yaml.is_file()
    assert (contracts_dir / "input.yaml").is_file()
    assert (contracts_dir / "output.yaml").is_file()
    assert (contracts_dir / "guardrails.yaml").is_file()

    frontmatter = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    manifest = _read_yaml(skill_yaml)

    assert manifest["name"] == frontmatter["name"]
    assert str(manifest["version"]) == str(frontmatter["version"])
    assert manifest["capability_type"] == "evaluator"
    assert "draft_pack" in manifest["required_artifacts"]
    assert "evidence_pack" in manifest["required_artifacts"]
    assert "publication_pack" in manifest["produced_artifacts"]
    assert "publication_pack_generate" in manifest["allowed_tools"]
    assert "external.publish" in manifest["forbidden_tools"]
    assert manifest["guardrails"]["input"]
    assert manifest["guardrails"]["output"]

    contracts = {
        name: _read_yaml(contracts_dir / f"{name}.yaml")
        for name in ("input", "output", "guardrails")
    }
    for name, contract in contracts.items():
        assert contract["schema_version"].startswith("rh.schema.")
        assert contract["type"], f"{name} contract must declare a type"

    assert contracts["input"]["schema_version"] == manifest["input_schema"]
    assert contracts["output"]["schema_version"] == manifest["output_schema"]


def test_final_bundle_quality_promotion_policy_requires_real_held_out_replay() -> None:
    manifest = _read_yaml(REPO_ROOT / "skills" / "final-bundle-quality" / "skill.yaml")
    policy = manifest["promotion_policy"]
    replay_tests = manifest["replay_tests"]

    assert policy["held_out_replay_required"] is True
    assert policy["controlled_replay_counts_for_promotion"] is False
    assert policy["required_strength"] == "exact_profile_held_out"
    assert "project_artifacts:752" in policy["excluded_promotion_evidence"]
    assert "project_artifacts:771" in policy["current_promotion_evidence"]
    assert any(test["artifact_ref"] == "project_artifacts:771" for test in replay_tests)
    assert any(test["artifact_ref"] == "project_artifacts:752" for test in replay_tests)
    assert any(
        test["promotion_eligible"] is False and "controlled" in test["profile_match"]
        for test in replay_tests
    )


def test_final_bundle_quality_v2_package_loads_as_runtime_capability() -> None:
    from research_harness.skill import load_skill_package_manifest

    package = load_skill_package_manifest(REPO_ROOT / "skills" / "final-bundle-quality")
    capability = package.to_capability_manifest()
    payload = capability.to_dict()

    assert package.name == "final-bundle-quality"
    assert package.contract_paths["input"] == Path("contracts/input.yaml")
    assert payload["name"] == "final-bundle-quality"
    assert payload["capability_type"] == "evaluator"
    assert payload["owner"] == "core"
    assert payload["input_schema"] == "rh.schema.input.final_bundle_quality.v0"
    assert payload["output_schema"] == (
        "rh.schema.artifact.final_bundle_quality_report.v0"
    )
    assert "artifact.read" in payload["allowed_tools"]
    assert "external.publish" in payload["forbidden_tools"]
    assert "final_bundle" in payload["required_artifacts"]
    assert "final_bundle_quality_report" in payload["produced_artifacts"]
    assert "promotion_evidence_classified" in payload["guardrails"]
    assert "topic5_exact_profile_replay" in payload["tests"]
    assert payload["metadata"]["promotion_policy"]["held_out_replay_required"] is True


def test_final_bundle_quality_runtime_capability_validates_run_spec() -> None:
    from research_harness.runtime import RunSpec, RunVisibleInputs
    from research_harness.skill import load_skill_package_manifest

    capability = load_skill_package_manifest(
        REPO_ROOT / "skills" / "final-bundle-quality"
    ).to_capability_manifest()
    spec = RunSpec(
        run_id="run.final_bundle_quality.from_package",
        task_type="evaluation",
        topic_id=8,
        objective="Evaluate final_bundle quality through the v2 package.",
        visible_inputs=RunVisibleInputs(
            artifact_refs=("artifact:final_bundle:716",),
        ),
        required_outputs=("final_bundle_quality_report",),
        capability_policy={
            "allowed_capabilities": ("final-bundle-quality",),
            "allowed_tools": capability.allowed_tools,
            "denied_tools": capability.forbidden_tools,
        },
        guardrails={"runtime": capability.guardrails},
    )

    results = capability.validate_run_spec(spec)

    assert all(result.passed for result in results)


def test_final_bundle_quality_builds_runtime_contract_template() -> None:
    from research_harness.runtime import CapabilityManifest, RunSpec
    from research_harness.skill import load_skill_package_manifest

    package = load_skill_package_manifest(REPO_ROOT / "skills" / "final-bundle-quality")

    contract = package.to_runtime_contract(
        topic_id=8,
        artifact_refs=("artifact:final_bundle:716",),
        objective="Evaluate the active final_bundle.",
        literal_inputs={"mode": "quality_scan"},
        run_id="run.final_bundle_quality.topic8",
    )
    capability = CapabilityManifest(**contract["capability_manifest"])
    spec = RunSpec(**contract["run_spec"])
    results = capability.validate_run_spec(
        spec,
        requested_tools=capability.allowed_tools,
    )

    assert contract["skill_name"] == "final-bundle-quality"
    assert spec.run_id == "run.final_bundle_quality.topic8"
    assert spec.required_outputs == ("final_bundle_quality_report",)
    assert spec.capability_policy["allowed_capabilities"] == ["final-bundle-quality"]
    assert all(result.passed for result in results)


def test_iter_skill_package_capabilities_finds_promoted_skill_packages() -> None:
    from research_harness.skill import iter_skill_package_capabilities

    capabilities = list(iter_skill_package_capabilities(REPO_ROOT))
    names = {capability.name for capability in capabilities}

    assert "final-bundle-quality" in names
    assert "publication-pack" in names


def test_skill_capabilities_cli_lists_v2_runtime_capabilities(runner) -> None:
    result = runner.invoke(
        main,
        [
            "--json",
            "skill",
            "capabilities",
            "--skills-root",
            str(REPO_ROOT),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    capabilities = payload["capabilities"]
    final_bundle = next(
        item for item in capabilities if item["name"] == "final-bundle-quality"
    )
    publication_pack = next(
        item for item in capabilities if item["name"] == "publication-pack"
    )
    assert final_bundle["capability_type"] == "evaluator"
    assert final_bundle["input_schema"] == "rh.schema.input.final_bundle_quality.v0"
    assert publication_pack["capability_type"] == "evaluator"
    assert publication_pack["output_schema"] == "rh.schema.artifact.publication_pack.v0"


def test_skill_list_cli_filters_by_public_suite(runner) -> None:
    result = runner.invoke(
        main,
        [
            "--json",
            "skill",
            "list",
            "--skills-root",
            str(REPO_ROOT),
            "--suite",
            "paper",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    names = {skill["name"] for skill in payload["skills"]}
    assert "paper-writing" in names
    assert "publication-pack" in names
    assert "literature-search" not in names
    assert {skill["extras"]["public_suite"] for skill in payload["skills"]} == {"paper"}


def test_skill_list_cli_groups_by_public_suite(runner) -> None:
    result = runner.invoke(
        main,
        [
            "skill",
            "list",
            "--skills-root",
            str(REPO_ROOT),
            "--group-by-suite",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "research:" in result.output
    assert "paper:" in result.output
    assert "zotero:" in result.output
    assert "  literature-search" in result.output
    assert "  paper-writing" in result.output
