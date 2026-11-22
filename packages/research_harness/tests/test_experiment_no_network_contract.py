"""Confined experiments have no network, so nothing may ask for one or hand them credentials."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_harness.experiment import confine, sandbox
from research_harness.experiment.validator import (
    validate_code,
    validate_imports,
    validate_security,
)
from research_harness.primitives.experiment_impls import code_validate, experiment_run
from research_harness.primitives.experiment_loop_impl import experiment_loop
from research_harness.primitives.registry import (
    CODE_VALIDATE_SPEC,
    EXPERIMENT_LOOP_SPEC,
)
from research_harness.primitives.types import ExperimentBudget
from research_harness.storage.db import Database


@pytest.mark.parametrize("check", [validate_code, validate_security, validate_imports])
def test_agent_mode_is_refused(check):
    with pytest.raises(ValueError, match="no network"):
        check("print(1)\n", mode="agent")


def test_code_validate_primitive_refuses_agent_mode():
    with pytest.raises(ValueError, match="no network"):
        code_validate(code="print(1)\n", mode="agent")


def test_specs_default_to_strict_and_say_why():
    for spec in (CODE_VALIDATE_SPEC, EXPERIMENT_LOOP_SPEC):
        mode = spec.input_schema["properties"]["mode"]
        assert mode["default"] == "strict"
        assert "no network" in mode["description"]
    assert "LLM API experiments" not in EXPERIMENT_LOOP_SPEC.description


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(db_path=tmp_path / "loop.db")
    d.migrate()
    conn = d.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        conn.commit()
    finally:
        conn.close()
    return d


def test_experiment_loop_refuses_agent_mode_before_any_work(db):
    def gen(**_):
        pytest.fail("code generation ran for a refused mode")

    with pytest.raises(ValueError, match="no network"):
        experiment_loop(
            db=db,
            topic_id=1,
            code_generate_fn=gen,
            task_description="t",
            primary_metric="m",
            mode="agent",
            budget=ExperimentBudget(max_iterations=1),
        )
    conn = db.connect()
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM experiment_loop_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "HF_TOKEN",
        "DB_PASSWORD",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_AUTH",
        "SESSION_COOKIE",
    ],
)
def test_credentials_never_reach_the_confined_child(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "secret-value")
    monkeypatch.setattr(
        sandbox, "run_confined", lambda *a, **k: pytest.fail("child started")
    )
    with pytest.raises(ValueError, match="credential"):
        sandbox.run_experiment(
            "print(1)\n", work_dir=tmp_path / "a", extra_env={name: "x"}
        )
    with pytest.raises(ValueError, match="credential"):
        sandbox.run_experiment(
            "print(1)\n", work_dir=tmp_path / "b", env_allowlist={name}
        )
    with pytest.raises(ValueError, match="credential"):
        experiment_run(code="print(1)\n", env_vars={name: "x"})


def test_non_secret_env_vars_still_pass(tmp_path, monkeypatch):
    seen = {}

    def fake(argv, *, env, **_):
        seen.update(env)
        import subprocess

        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(sandbox, "run_confined", fake)
    sandbox.run_experiment(
        "print(1)\n", work_dir=tmp_path / "w", extra_env={"SEED": "7"}
    )
    assert seen["SEED"] == "7"


def test_proxy_pass_surfaces_missing_confinement(tmp_path, monkeypatch):
    from research_harness.execution import llm_primitives
    from research_harness.primitives.experiment_matrix_impl import run_proxy_pass

    path = tmp_path / "m.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE method_atoms (id INTEGER PRIMARY KEY, name TEXT, description TEXT);"
        "INSERT INTO method_atoms VALUES (1, 'a', 'atom');"
        "CREATE TABLE experiment_matrix_cell (id INTEGER PRIMARY KEY, topic_id INT, goal_id INT,"
        " atom_combo TEXT, status TEXT, proxy_metric_name TEXT, proxy_metric_value REAL,"
        " baseline_metric REAL, delta_to_sota REAL, updated_at TEXT);"
        "INSERT INTO experiment_matrix_cell VALUES (1, 1, 1, '[1]', 'pending', 'acc', NULL, 0.5, NULL, NULL);"
    )
    conn.commit()
    conn.close()

    class Db:
        def connect(self):
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c

    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: object())
    monkeypatch.setattr(llm_primitives, "_client_chat", lambda *a, **k: "print(1)")

    def refuse(**_):
        raise confine.ConfinementUnavailable(
            "no verified OS confinement backend on test"
        )

    monkeypatch.setattr(sandbox, "run_experiment", refuse)
    with pytest.raises(confine.ConfinementUnavailable):
        run_proxy_pass(1, Db())
