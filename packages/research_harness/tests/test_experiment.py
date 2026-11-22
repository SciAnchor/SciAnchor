"""Tests for experiment subpackage — validator, metric parser, sandbox, verified registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from research_harness.experiment.metric_parser import (
    detect_nan_divergence,
    parse_metrics,
)
from research_harness.experiment.sandbox import is_improvement, run_experiment
from research_harness.experiment.validator import (
    auto_fix_unbound_locals,
    validate_code,
    validate_imports,
    validate_security,
    validate_syntax,
)
from research_harness.experiment.verified_registry import (
    ALWAYS_ALLOWED,
    VerifiedRegistry,
    build_registry_from_metrics,
)


# -- Metric Parser -----------------------------------------------------------


class TestMetricParser:
    def test_plain_format(self):
        metrics = parse_metrics("accuracy: 0.95\nloss: 0.23\n")
        assert metrics["accuracy"] == pytest.approx(0.95)
        assert metrics["loss"] == pytest.approx(0.23)

    def test_condition_prefixed(self):
        metrics = parse_metrics(
            "condition=baseline accuracy: 0.85\ncondition=ours accuracy: 0.92\n"
        )
        assert metrics["baseline/accuracy"] == pytest.approx(0.85)
        assert metrics["ours/accuracy"] == pytest.approx(0.92)

    def test_ratio_format(self):
        metrics = parse_metrics("condition=model success_rate: 85/100\n")
        assert metrics["model/success_rate"] == pytest.approx(0.85)

    def test_summary_format(self):
        metrics = parse_metrics("SUMMARY condition=ours metric=f1 mean=0.91 std=0.03\n")
        assert metrics["ours/f1"] == pytest.approx(0.91)
        assert metrics["ours/f1_std"] == pytest.approx(0.03)

    def test_skips_nan(self):
        metrics = parse_metrics("accuracy: nan\nloss: 0.5\n")
        assert "accuracy" not in metrics
        assert metrics["loss"] == pytest.approx(0.5)

    def test_nan_divergence_detection(self):
        assert detect_nan_divergence("loss: nan", "") != ""
        assert detect_nan_divergence("", "math domain error") != ""
        assert detect_nan_divergence("loss: 200.5", "") != ""
        assert detect_nan_divergence("accuracy: 0.95", "") == ""

    def test_inf_detection(self):
        assert detect_nan_divergence("loss: inf", "") != ""
        assert (
            detect_nan_divergence("information about training", "") == ""
        )  # "info" not "inf"


# -- Validator ----------------------------------------------------------------


class TestValidator:
    def test_valid_code(self):
        code = "import numpy as np\nx = np.array([1, 2, 3])\nprint(x.mean())\n"
        result = validate_code(code)
        assert result.ok

    def test_syntax_error(self):
        issues = validate_syntax("def foo(\n")
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].category == "syntax"

    def test_dangerous_call(self):
        issues = validate_security("import os\nos.system('rm -rf /')\n")
        assert any(i.severity == "error" and "os.system" in i.message for i in issues)

    def test_dangerous_builtin(self):
        issues = validate_security("eval('print(1)')\n")
        assert any(i.severity == "error" and "eval" in i.message for i in issues)

    def test_banned_module(self):
        issues = validate_security("import subprocess\n")
        assert any(i.severity == "error" and "subprocess" in i.message for i in issues)

    def test_unknown_import_is_warning(self):
        issues = validate_imports("import some_obscure_package\n")
        assert any(
            i.severity == "warning" and "some_obscure_package" in i.message
            for i in issues
        )

    def test_safe_imports_pass(self):
        code = "import numpy\nimport torch\nimport json\nimport math\n"
        issues = validate_imports(code)
        assert not any(i.severity == "error" for i in issues)

    def test_combined_validation(self):
        bad_code = "import subprocess\nsubprocess.run(['ls'])\n"
        result = validate_code(bad_code)
        assert not result.ok
        assert result.error_count >= 1

    def test_auto_fix_unbound(self):
        code = "if True:\n    x = 1\nprint(x)\n"
        fixed, n = auto_fix_unbound_locals(code)
        assert n >= 1
        assert "x = None" in fixed


class TestValidatorModes:
    """Strict validator mode."""

    def test_strict_blocks_httpx(self):
        code = "import httpx\nr = httpx.get('https://api.openai.com')\n"
        issues = validate_security(code, mode="strict")
        # httpx is 'unknown' under strict (warning, not error)
        assert not any(i.severity == "error" for i in issues)

    def test_strict_blocks_urllib(self):
        issues = validate_security("import urllib.request\n", mode="strict")
        assert any(i.severity == "error" and "urllib" in i.message for i in issues)

    def test_strict_blocks_subprocess(self):
        issues = validate_security("import subprocess\n", mode="strict")
        assert any(i.severity == "error" and "subprocess" in i.message for i in issues)

    def test_strict_blocks_ctypes(self):
        issues = validate_security("import ctypes\n", mode="strict")
        assert any(i.severity == "error" and "ctypes" in i.message for i in issues)

    def test_strict_blocks_eval(self):
        issues = validate_security("eval('1+1')\n", mode="strict")
        assert any(i.severity == "error" and "eval" in i.message for i in issues)


# -- Sandbox ------------------------------------------------------------------


class TestSandbox:
    def test_simple_experiment(self):
        code = 'print("accuracy: 0.95")\nprint("loss: 0.23")\n'
        result = run_experiment(code, timeout_sec=10.0)
        assert result.returncode == 0
        assert result.metrics["accuracy"] == pytest.approx(0.95)
        assert result.metrics["loss"] == pytest.approx(0.23)
        assert not result.timed_out

    def test_timeout(self):
        code = "import time\ntime.sleep(100)\n"
        result = run_experiment(code, timeout_sec=1.0)
        assert result.timed_out
        assert result.returncode == -1

    def test_error_code(self):
        code = "raise ValueError('boom')\n"
        result = run_experiment(code, timeout_sec=5.0)
        assert result.returncode != 0
        assert "boom" in result.stderr

    def test_is_improvement(self):
        assert is_improvement(0.95, 0.90, direction="maximize")
        assert not is_improvement(0.85, 0.90, direction="maximize")
        assert is_improvement(0.10, 0.15, direction="minimize")
        assert not is_improvement(0.20, 0.15, direction="minimize")

    def test_multi_file_with_import(self):
        files = {
            "helper.py": "def score(x):\n    return x * 2\n",
            "main.py": "from helper import score\nprint(f'accuracy: {score(0.45)}')\n",
        }
        result = run_experiment(files=files, entry_point="main.py", timeout_sec=10.0)
        assert result.returncode == 0, result.stderr
        assert result.metrics["accuracy"] == pytest.approx(0.9)

    def test_env_default_denies_parent_secrets(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-123")
        monkeypatch.setenv("UNRELATED_SECRET", "do-not-pass")
        code = (
            "import os\n"
            "print(f\"key: {os.environ.get('OPENAI_API_KEY', 'MISSING')}\")\n"
            "print(f\"anthropic: {os.environ.get('ANTHROPIC_API_KEY', 'MISSING')}\")\n"
            "print(f\"unrelated: {os.environ.get('UNRELATED_SECRET', 'MISSING')}\")\n"
        )
        result = run_experiment(code, timeout_sec=10.0)
        assert "key: MISSING" in result.stdout
        assert "anthropic: MISSING" in result.stdout
        assert "unrelated: MISSING" in result.stdout

    def test_env_explicit_minimal_allowlist(self, monkeypatch):
        monkeypatch.setenv("RH_EXPERIMENT_SEED", "7")
        monkeypatch.setenv("RH_EXPERIMENT_OTHER", "8")
        code = (
            "import os\n"
            "print(f\"seed: {os.environ.get('RH_EXPERIMENT_SEED', 'MISSING')}\")\n"
            "print(f\"other: {os.environ.get('RH_EXPERIMENT_OTHER', 'MISSING')}\")\n"
        )
        result = run_experiment(
            code,
            timeout_sec=10.0,
            env_allowlist={"RH_EXPERIMENT_SEED"},
        )
        assert "seed: 7" in result.stdout
        assert "other: MISSING" in result.stdout

    def test_extra_env_overlay(self):
        code = (
            "import os\n"
            "print(f\"spec_only: {os.environ.get('MY_SPEC_VAR', 'MISSING')}\")\n"
        )
        result = run_experiment(
            code, timeout_sec=10.0, extra_env={"MY_SPEC_VAR": "hello-spec"}
        )
        assert "spec_only: hello-spec" in result.stdout

    def test_entry_point_missing_raises(self):
        with pytest.raises(ValueError, match="not present in files"):
            run_experiment(files={"other.py": "print('ok')\n"}, entry_point="main.py")

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="requires either 'code' or 'files'"):
            run_experiment()

    @pytest.mark.parametrize("path_kind", ["absolute", "parent", "nested_parent"])
    def test_rejects_unsafe_file_path_before_spawn(self, tmp_path, path_kind):
        work_dir = tmp_path / "work"
        unsafe_path = {
            "absolute": str(tmp_path / "absolute_escape.py"),
            "parent": "../parent_escape.py",
            "nested_parent": "nested/../../nested_escape.py",
        }[path_kind]

        with patch("research_harness.experiment.sandbox.run_confined") as run:
            with pytest.raises(ValueError, match="safe relative path"):
                run_experiment(
                    files={unsafe_path: "print('escaped')\n", "main.py": "print(1)\n"},
                    work_dir=work_dir,
                )

        run.assert_not_called()

    @pytest.mark.parametrize("entry_point", ["/tmp/absolute.py", "../parent.py"])
    def test_rejects_unsafe_entry_point_before_spawn(self, tmp_path, entry_point):
        with patch("research_harness.experiment.sandbox.run_confined") as run:
            with pytest.raises(ValueError, match="safe relative path"):
                run_experiment(
                    files={entry_point: "print(1)\n"},
                    entry_point=entry_point,
                    work_dir=tmp_path / "work",
                )

        run.assert_not_called()

    def test_rejects_symlink_file_before_spawn(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("original\n", encoding="utf-8")
        (work_dir / "main.py").symlink_to(outside)

        with patch("research_harness.experiment.sandbox.run_confined") as run:
            with pytest.raises(ValueError, match="symlink"):
                run_experiment(code="print('escaped')\n", work_dir=work_dir)

        run.assert_not_called()
        assert outside.read_text(encoding="utf-8") == "original\n"

    def test_rejects_symlink_ancestor_before_spawn(self, tmp_path):
        work_dir = tmp_path / "work"
        outside = tmp_path / "outside"
        work_dir.mkdir()
        outside.mkdir()
        (work_dir / "nested").symlink_to(outside, target_is_directory=True)

        with patch("research_harness.experiment.sandbox.run_confined") as run:
            with pytest.raises(ValueError, match="symlink"):
                run_experiment(
                    files={
                        "nested/helper.py": "print('escaped')\n",
                        "main.py": "print(1)\n",
                    },
                    work_dir=work_dir,
                )

        run.assert_not_called()
        assert not (outside / "helper.py").exists()

    def test_rejects_hardlinked_file_before_spawn(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("original\n", encoding="utf-8")
        (work_dir / "main.py").hardlink_to(outside)

        with patch("research_harness.experiment.sandbox.run_confined") as run:
            with pytest.raises(ValueError, match="single-link regular file"):
                run_experiment(code="print('escaped')\n", work_dir=work_dir)

        run.assert_not_called()
        assert outside.read_text(encoding="utf-8") == "original\n"

    def test_rejects_leaf_symlink_swapped_after_validation(self, tmp_path):
        from research_harness.experiment import sandbox

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        target = work_dir / "main.py"
        target.write_text("original\n", encoding="utf-8")
        outside = tmp_path / "outside.py"
        outside.write_text("outside\n", encoding="utf-8")
        validate = sandbox._reject_symlink_components

        def validate_then_swap(root, relative_path):
            validate(root, relative_path)
            target.unlink()
            target.symlink_to(outside)

        with (
            patch.object(
                sandbox, "_reject_symlink_components", side_effect=validate_then_swap
            ),
            patch.object(sandbox, "run_confined") as run,
        ):
            with pytest.raises(ValueError, match="symlink"):
                run_experiment(code="print('escaped')\n", work_dir=work_dir)

        run.assert_not_called()
        assert outside.read_text(encoding="utf-8") == "outside\n"

    def test_rejects_ancestor_symlink_swapped_after_validation(self, tmp_path):
        from research_harness.experiment import sandbox

        work_dir = tmp_path / "work"
        nested = work_dir / "nested"
        outside = tmp_path / "outside"
        nested.mkdir(parents=True)
        outside.mkdir()
        validate = sandbox._reject_symlink_components

        def validate_then_swap(root, relative_path):
            validate(root, relative_path)
            nested.rmdir()
            nested.symlink_to(outside, target_is_directory=True)

        with (
            patch.object(
                sandbox, "_reject_symlink_components", side_effect=validate_then_swap
            ),
            patch.object(sandbox, "run_confined") as run,
        ):
            with pytest.raises(ValueError, match="symlink"):
                run_experiment(
                    files={"nested/main.py": "print('escaped')\n"},
                    entry_point="nested/main.py",
                    work_dir=work_dir,
                )

        run.assert_not_called()
        assert not (outside / "main.py").exists()


# -- Verified Registry --------------------------------------------------------


class TestVerifiedRegistry:
    def test_basic_verification(self):
        registry = VerifiedRegistry()
        registry.add_value(0.95, "accuracy")
        assert registry.is_verified(0.95)
        assert registry.is_verified(0.9500001)  # within 1% tolerance
        assert not registry.is_verified(0.80)

    def test_rounding_variants(self):
        registry = VerifiedRegistry()
        registry.add_value(0.9534, "accuracy")
        assert registry.is_verified(0.95)  # rounded to 2dp
        assert registry.is_verified(0.953)  # rounded to 3dp

    def test_percentage_variant(self):
        registry = VerifiedRegistry()
        registry.add_value(0.87, "accuracy")
        assert registry.is_verified(87.0)  # percentage conversion

    def test_inverse_variant(self):
        registry = VerifiedRegistry()
        registry.add_value(73.42, "metric")
        assert registry.is_verified(0.7342)  # inverse conversion

    def test_build_from_metrics(self):
        metrics = {
            "baseline/accuracy": 0.85,
            "ours/accuracy": 0.92,
            "baseline/f1": 0.80,
            "ours/f1": 0.88,
        }
        registry = build_registry_from_metrics(metrics, "accuracy")
        assert registry.primary_metric is not None  # picks first match
        assert "baseline" in registry.condition_names
        assert "ours" in registry.condition_names
        # Both accuracy values are registered
        assert registry.is_verified(0.85)
        assert registry.is_verified(0.92)
        # Pairwise diff
        assert registry.is_verified(0.07)

    def test_always_allowed(self):
        assert 0.0 in ALWAYS_ALLOWED
        assert 100.0 in ALWAYS_ALLOWED
        assert 2024.0 in ALWAYS_ALLOWED
        assert 256.0 in ALWAYS_ALLOWED

    def test_lookup_returns_source(self):
        registry = VerifiedRegistry()
        registry.add_value(42.0, "the_answer")
        assert registry.lookup(42.0) is not None
        assert "the_answer" in registry.lookup(42.0)
        assert registry.lookup(999.0) is None


# -- Experiment Primitives (integration) --------------------------------------


class TestExperimentPrimitives:
    def test_code_validate_primitive(self):
        from research_harness.primitives.experiment_impls import code_validate

        result = code_validate(code="import numpy\nprint(1)\n")
        assert result.ok

    def test_code_validate_rejects_dangerous(self):
        from research_harness.primitives.experiment_impls import code_validate

        result = code_validate(code="import subprocess\nsubprocess.run(['ls'])\n")
        assert not result.ok

    def test_experiment_run_primitive(self):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code='print("val_loss: 0.42")\n',
            timeout_sec=5.0,
            primary_metric="val_loss",
        )
        assert result.primary_metric_value == pytest.approx(0.42)
        assert result.returncode == 0

    def test_experiment_run_preserves_ablation_contract(self):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code="print('METRIC accuracy=0.9')",
            canonical_components=["retriever"],
            ablation_components=["retriever"],
            repeats=3,
            variance_estimates=[0.02],
            acceptance_criteria=["accuracy improves by 0.5%"],
            evidence_kind="final",
        )

        assert result.canonical_components == ["retriever"]
        assert result.ablation_components == ["retriever"]
        assert result.repeats == 3
        assert result.variance_estimates == [0.02]
        assert result.acceptance_criteria == ["accuracy improves by 0.5%"]
        assert result.evidence_kind == "final"

    @pytest.mark.parametrize(
        ("direction", "without", "expected"),
        [
            ("maximize", 0.95, "helped"),
            ("maximize", 0.85, "hurt"),
            ("maximize", 0.91, "inconclusive"),
            ("maximize", 0.89, "inconclusive"),
            ("maximize", 0.905, "inconclusive"),
            ("minimize", 0.85, "helped"),
            ("minimize", 0.95, "hurt"),
        ],
    )
    def test_experiment_run_derives_observed_ablation_outcome(
        self, direction, without, expected
    ):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code=(
                'print("condition=full accuracy: 0.9")\n'
                f'print("condition=without_1 accuracy: {without}")\n'
            ),
            primary_metric="accuracy",
            canonical_components=["retriever"],
            ablation_components=["retriever"],
            repeats=3,
            variance_estimates=[0.0001],
            acceptance_criteria=[],
            evidence_kind="final",
            component_provenance=[
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ],
            metric_direction=direction,
        )

        assert result.ablation_outcomes == [
            {
                "component_family": "retriever",
                "removal_effect": expected,
                "provenance_tag": "borrowed",
                "source_paper_id": 9,
                "evidence": (
                    f"observed accuracy: full=0.9, without_1={without}, "
                    f"direction={direction}, noise_bound=0.01"
                ),
            }
        ]

    def test_experiment_run_does_not_echo_unmeasured_or_malformed_provenance(self):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code='print("condition=full accuracy: 0.9")',
            primary_metric="accuracy",
            canonical_components=["retriever"],
            ablation_components=["retriever"],
            repeats=3,
            variance_estimates=[0.0001],
            acceptance_criteria=[],
            evidence_kind="final",
            component_provenance=[
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": None,
                }
            ],
        )

        assert result.ablation_outcomes == []

    @pytest.mark.parametrize("variance", [-0.01, float("nan")])
    def test_experiment_run_rejects_invalid_outcome_variance(self, variance):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code=(
                'print("condition=full accuracy: 0.9")\n'
                'print("condition=without_1 accuracy: 0.85")\n'
            ),
            primary_metric="accuracy",
            canonical_components=["retriever"],
            ablation_components=["retriever"],
            repeats=3,
            variance_estimates=[variance],
            acceptance_criteria=[],
            evidence_kind="final",
            component_provenance=[
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ],
        )

        assert result.ablation_outcomes == []

    def test_failed_experiment_run_cannot_produce_observed_outcome(self):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code=(
                'print("condition=full accuracy: 0.9")\n'
                'print("condition=without_1 accuracy: 0.85")\n'
                "raise SystemExit(1)\n"
            ),
            primary_metric="accuracy",
            canonical_components=["retriever"],
            ablation_components=["retriever"],
            repeats=3,
            variance_estimates=[0.0001],
            acceptance_criteria=[],
            evidence_kind="final",
            component_provenance=[
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ],
        )

        assert result.returncode == 1
        assert result.ablation_outcomes == []

    @pytest.mark.parametrize(
        ("returncode", "timed_out", "divergence"),
        [(1, False, ""), (0, True, ""), (0, False, "NaN detected")],
    )
    def test_unsuccessful_sandbox_result_cannot_produce_outcome(
        self, returncode, timed_out, divergence
    ):
        from research_harness.experiment.sandbox import SandboxResult
        from research_harness.primitives.experiment_impls import experiment_run

        sandbox_result = SandboxResult(
            returncode=returncode,
            stdout="",
            stderr="",
            elapsed_sec=0.1,
            metrics={"full/accuracy": 0.9, "without_1/accuracy": 0.85},
            timed_out=timed_out,
            divergence=divergence,
        )
        with patch(
            "research_harness.primitives.experiment_impls.run_experiment",
            return_value=sandbox_result,
        ):
            result = experiment_run(
                code="pass",
                primary_metric="accuracy",
                canonical_components=["retriever"],
                ablation_components=["retriever"],
                repeats=3,
                variance_estimates=[0.0001],
                acceptance_criteria=[],
                evidence_kind="final",
                component_provenance=[
                    {
                        "component_family": "retriever",
                        "provenance_tag": "borrowed",
                        "source_paper_id": 9,
                    }
                ],
            )

        assert result.ablation_outcomes == []

    def test_verified_registry_build_and_check(self, tmp_path):
        from research_harness.primitives.experiment_impls import (
            verified_registry_build,
            verified_registry_check,
        )
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 't')")
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, 'stub', 'stub')"
        )
        conn.commit()
        conn.close()

        build_result = verified_registry_build(
            db=db,
            topic_id=1,
            metrics={"baseline/acc": 0.85, "ours/acc": 0.92},
            primary_metric_name="acc",
        )
        assert build_result.whitelist_size > 0
        assert build_result.primary_metric is not None  # picks first match

        check_result = verified_registry_check(
            db=db,
            topic_id=1,
            numbers=[0.92, 0.85, 999.99],
        )
        assert 0.92 in check_result.verified
        assert 999.99 in check_result.unverified
        assert check_result.pass_rate < 1.0

    def test_verified_registry_build_allows_topic_without_project(self, tmp_path):
        from research_harness.primitives.experiment_impls import verified_registry_build
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (7, 'topic-only')")
        conn.commit()
        conn.close()

        result = verified_registry_build(
            db=db,
            topic_id=7,
            metrics={"audit/pass_rate": 1.0},
            primary_metric_name="pass_rate",
        )

        assert result.whitelist_size >= 1
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT project_id, topic_id, number_original FROM verified_numbers WHERE topic_id = 7"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["project_id"] is None
        assert row["topic_id"] == 7
        assert row["number_original"] == 1.0
