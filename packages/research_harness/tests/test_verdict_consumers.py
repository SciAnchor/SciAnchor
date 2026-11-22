"""Verdict-consumer fixes: every computed verdict must reach a gate that acts.

Covers audit findings:

- E1: ungrounded numbers in strict sections block commit_manuscript_version
- E2: v2 run policies re-enable the autonomous completion gate
- E3: a missing LaTeX engine fails closed instead of discarding validation
- E5: experiment_runs.code_hash records the sandbox sha256, not a filename
"""

from __future__ import annotations

import pytest

from research_harness.storage.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    d.migrate()
    return d


@pytest.fixture
def svc(db):
    from research_harness.orchestrator.service import OrchestratorService

    return OrchestratorService(db)


@pytest.fixture
def topic_and_project(db):
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name, description) VALUES ('t', '')")
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description)"
            " VALUES (?, ?, 'stub', 'stub')",
            (topic_id, topic_id),
        )
        conn.commit()
    finally:
        conn.close()
    return topic_id, topic_id


TEX_FABRICATED = (
    "\\documentclass{article}\\begin{document}\n"
    "\\section{Introduction}\nMotivating prose without claims.\n"
    "\\section{Results}\nOur method reaches 0.947 accuracy versus 0.813.\n"
    "\\end{document}\n"
)

TEX_GROUNDED = (
    "\\documentclass{article}\\begin{document}\n"
    "\\section{Introduction}\nMotivating prose without claims.\n"
    "\\section{Results}\nOur method reaches 0.912 accuracy.\n"
    "\\end{document}\n"
)


def _write_bundle(tmp_path, tex_source):
    tex = tmp_path / "main.tex"
    tex.write_text(tex_source)
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-1.5 fake")
    return tex, pdf


def _seed_registry(svc, topic_id, metrics):
    svc.record_experiment_run(
        topic_id,
        code_hash="a" * 64,
        primary_metric_name="accuracy",
        primary_metric_value=next(iter(metrics.values())),
        metrics=metrics,
    )
    # Persist verified numbers the way the pipeline does.
    from research_harness.primitives.experiment_impls import verified_registry_build

    verified_registry_build(
        db=svc._db, topic_id=topic_id, metrics=metrics, run_provenance="test-run"
    )


class TestUngroundedNumberGate:
    """E1: the number-grounding verdict finally has a blocking consumer."""

    def test_fabricated_results_number_blocks_commit(
        self, svc, topic_and_project, tmp_path
    ):
        topic_id, _ = topic_and_project
        _seed_registry(svc, topic_id, {"accuracy": 0.912})
        tex, pdf = _write_bundle(tmp_path, TEX_FABRICATED)

        result = svc.commit_manuscript_version(
            topic_id=topic_id, tex_path=str(tex), pdf_path=str(pdf)
        )

        assert result["success"] is False
        checks = {f["check"] for f in result.get("gate_findings", [])}
        assert "ungrounded_numbers_in_strict_sections" in checks

    def test_grounded_results_number_commits(self, svc, topic_and_project, tmp_path):
        topic_id, _ = topic_and_project
        _seed_registry(svc, topic_id, {"accuracy": 0.912})
        tex, pdf = _write_bundle(tmp_path, TEX_GROUNDED)

        result = svc.commit_manuscript_version(
            topic_id=topic_id, tex_path=str(tex), pdf_path=str(pdf)
        )

        assert result["success"] is True

    def test_empty_registry_never_blocks(self, svc, topic_and_project, tmp_path):
        """A survey/position topic with no experiment runs must not misfire."""
        topic_id, _ = topic_and_project
        tex, pdf = _write_bundle(tmp_path, TEX_FABRICATED)

        result = svc.commit_manuscript_version(
            topic_id=topic_id, tex_path=str(tex), pdf_path=str(pdf)
        )

        assert result["success"] is True

    def test_intro_numbers_do_not_block(self, svc, topic_and_project, tmp_path):
        """Non-strict sections stay out of scope for this gate."""
        topic_id, _ = topic_and_project
        _seed_registry(svc, topic_id, {"accuracy": 0.912})
        tex_src = (
            "\\documentclass{article}\\begin{document}\n"
            "\\section{Introduction}\nPrior work reports 0.777 accuracy.\n"
            "\\section{Results}\nOur method reaches 0.912 accuracy.\n"
            "\\end{document}\n"
        )
        tex, pdf = _write_bundle(tmp_path, tex_src)

        result = svc.commit_manuscript_version(
            topic_id=topic_id, tex_path=str(tex), pdf_path=str(pdf)
        )

        assert result["success"] is True

    def test_force_reason_overrides_with_audit(self, svc, topic_and_project, tmp_path):
        topic_id, _ = topic_and_project
        _seed_registry(svc, topic_id, {"accuracy": 0.912})
        tex, pdf = _write_bundle(tmp_path, TEX_FABRICATED)

        result = svc.commit_manuscript_version(
            topic_id=topic_id,
            tex_path=str(tex),
            pdf_path=str(pdf),
            force_reason="human-audited: number cross-checked against lab notebook",
        )

        assert result["success"] is True


class TestPolicySchemaDrift:
    """E2: v2 policies must enable the same predicates as v1."""

    def _ckpt(self, version):
        return {
            "paper_production_run_policy": {
                "schema_version": f"rh.paper_production_run_policy.{version}",
                "autonomous_completion": True,
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            }
        }

    def test_completion_gate_enabled_for_v2(self):
        from research_harness.auto_runner.stage_executor import (
            _paper_production_autonomous_completion_enabled,
        )

        assert _paper_production_autonomous_completion_enabled(self._ckpt("v2"))
        assert _paper_production_autonomous_completion_enabled(self._ckpt("v1"))

    def test_unknown_schema_still_disabled(self):
        from research_harness.auto_runner.stage_executor import (
            _paper_production_autonomous_completion_enabled,
        )

        assert not _paper_production_autonomous_completion_enabled(self._ckpt("v99"))

    def test_demo_seed_pool_enabled_for_v2(self):
        from research_harness.auto_runner.stage_executor import (
            _paper_production_demo_seed_pool_enabled,
        )

        assert _paper_production_demo_seed_pool_enabled(self._ckpt("v2"))

    def test_llm_planner_policy_accepts_v2(self):
        from research_harness.auto_runner.llm_planner import (
            _paper_production_policy,
        )

        assert _paper_production_policy(self._ckpt("v2")).get("mode") == "demo"

    def test_tool_dispatch_policy_accepts_v2(self):
        from research_harness.auto_runner.tool_dispatch import (
            _paper_production_policy_from_context,
        )

        ctx = self._ckpt("v2")
        assert _paper_production_policy_from_context(ctx).get("mode") == "demo"

    def test_single_source_of_truth(self):
        """No module may keep its own copy of the schema-version literals."""
        import pathlib

        import research_harness.auto_runner as ar

        root = pathlib.Path(ar.__file__).parent
        offenders = []
        for py in root.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            if py.name in ("checkpoint.py", "paper_production_entry.py"):
                continue  # definition site / writer site
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if (
                    '"rh.paper_production_run_policy.v' in stripped
                    and "PAPER_PRODUCTION_POLICY_SCHEMAS" not in stripped
                ):
                    offenders.append(f"{py.name}: {stripped[:80]}")
        assert not offenders, (
            "schema-version literals outside checkpoint.py — the v1/v2 drift "
            f"that killed the completion gate will recur: {offenders}"
        )


class TestNoEngineFailsClosed:
    """E3: missing LaTeX engine must not discard validation errors."""

    def test_no_engine_reports_failure(self, tmp_path, monkeypatch):
        import shutil as _shutil

        from research_harness.execution.latex_compiler import compile_latex

        monkeypatch.setattr(_shutil, "which", lambda name: None)
        result = compile_latex(
            "\\documentclass{article}\\begin{document}ok\\end{document}",
            "",
            str(tmp_path),
        )
        assert result.success is False
        assert any("no LaTeX engine" in e for e in result.errors)


class TestCodeHashRecordsRunIdentity:
    """E5: the hash column stores the sandbox sha256 when available."""

    def test_er_out_hash_preferred(self):
        # The dispatch expression, extracted: er_out wins, filename is fallback.
        er_out = {"code_hash": "b" * 64}
        cg_out = {"entry_point": "main.py"}
        chosen = er_out.get("code_hash", "") or cg_out.get("entry_point", "main.py")
        assert chosen == "b" * 64

    def test_dispatch_source_no_longer_defaults_to_filename(self):
        import pathlib

        import research_harness.auto_runner.tool_dispatch as td

        text = pathlib.Path(td.__file__).read_text(encoding="utf-8")
        assert 'code_hash=cg_out.get("entry_point", "main.py")' not in text
        assert 'code_hash=er_out.get("code_hash", "")' in text
