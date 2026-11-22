"""XCI05: deterministic source-fidelity + bidirectional citation audit."""

from __future__ import annotations

from pathlib import Path

import pytest

import research_harness.primitives.exemplar_impls as EAG
import research_harness.execution.llm_primitives as LP
from research_harness.primitives.polish_impls import (
    manuscript_polish,
    source_fidelity_audit,
)


@pytest.fixture(autouse=True)
def _reset_router():
    EAG._ROUTER_OK = None
    yield
    EAG._ROUTER_OK = None


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def train_model(lr=0.001, epochs=10, verbose=True):\n"
        "    return lr, epochs, verbose\n"
        "\n"
        "async def fetch_batch(size=32):\n"
        "    return size\n",
        encoding="utf-8",
    )
    (root / "pkg" / "readme.md").write_text("# hi\n", encoding="utf-8")
    return root


def _issues(findings):
    return [f.issue for f in findings]


def test_missing_function(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="We call `does_not_exist()` in the pipeline.",
        workspace_root=root,
    )
    assert any("does_not_exist" in i and "not found" in i for i in _issues(out))


def test_wrong_default(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="Training uses `train_model(lr=0.5)`.",
        workspace_root=root,
    )
    assert any("lr" in i and "0.5" in i for i in _issues(out))


def test_correct_default_and_existing_function_clean(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="Training uses `train_model(lr=0.001)` via `pkg/mod.py`.",
        workspace_root=root,
    )
    assert out == []


def test_dangling_path(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="See `pkg/missing.py` for details.",
        workspace_root=root,
    )
    assert any("does not resolve" in i for i in _issues(out))


def test_escaping_path(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="Leak via `../../etc/passwd`.",
        workspace_root=root,
    )
    assert any("escape" in i for i in _issues(out))


def test_unauthorized_citation():
    out = source_fidelity_audit(
        manuscript=r"Prior work \cite{smith2024,evil2020} shows X.",
        composition_contract={"allowed_citation_keys": ["smith2024"]},
    )
    assert any("evil2020" in i and "allow-list" in i for i in _issues(out))
    assert not any("smith2024" in i and "allow-list" in i for i in _issues(out))


def test_required_citation_missing():
    out = source_fidelity_audit(
        manuscript=r"We build on \cite{smith2024}.",
        composition_contract={
            "allowed_citation_keys": ["smith2024", "lee2023"],
            "required_citation_keys": ["smith2024", "lee2023"],
        },
    )
    assert any("lee2023" in i and "missing" in i for i in _issues(out))
    assert not any("smith2024" in i and "missing" in i for i in _issues(out))


def test_polish_refuses_incomplete_review_while_standalone_audit_remains_available(
    tmp_path, monkeypatch
):
    root = _workspace(tmp_path)

    class _FC:
        model = "mock-llm"

    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(LP, "_get_client", lambda *a, **k: _FC())
    monkeypatch.setattr(LP, "_client_chat", boom)
    # also break exemplar _chat path used by polish
    monkeypatch.setattr(EAG, "_chat", boom)

    with pytest.raises(RuntimeError, match="did not complete"):
        manuscript_polish(
            manuscript="We invent `totally_fake_fn()` and hide it.",
            workspace_root=str(root),
            run_consistency=False,
            run_deterministic=False,
        )
    assert source_fidelity_audit(
        manuscript="We invent `totally_fake_fn()` and hide it.",
        workspace_root=str(root),
    )


def test_complete_polish_surfaces_source_fidelity_findings(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    monkeypatch.setattr(
        "research_harness.primitives.polish_impls._chat",
        lambda *args, **kwargs: '{"findings":[]}',
    )
    out = manuscript_polish(
        manuscript="We invent `totally_fake_fn()` and hide it.",
        workspace_root=str(root),
        run_consistency=False,
        run_deterministic=False,
    )
    assert "source_fidelity_audit" in out.checks_run
    assert out.n_high >= 1
    assert out.submission_readiness == "blocked"
    assert any(f.angle == "source_fidelity" for f in out.findings)


def test_kwonly_default_mismatch(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "m.py").write_text(
        "def configure(*, mode='fast', retries=3):\n    return mode, retries\n",
        encoding="utf-8",
    )
    out = source_fidelity_audit(
        manuscript="We use `configure(mode='slow')`.",
        workspace_root=root,
    )
    assert any("mode" in i for i in _issues(out))


def test_absolute_path_outside_workspace(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="See `/etc/passwd` notes.",
        workspace_root=root,
    )
    # absolute path outside root is escape or unresolved — either is a finding
    assert any("escape" in i or "does not resolve" in i for i in _issues(out))


def test_bad_workspace_root_is_finding(tmp_path):
    out = source_fidelity_audit(
        manuscript="mentions `train_model()`.",
        workspace_root=str(tmp_path / "no_such_dir"),
    )
    assert any("not a directory" in i for i in _issues(out))


def test_param_without_default_is_finding(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "m.py").write_text(
        "def score(x, y=1):\n    return x + y\n",
        encoding="utf-8",
    )
    out = source_fidelity_audit(
        manuscript="Call `score(x=2)`.",
        workspace_root=root,
    )
    assert any("no parameter default for `x`" in i for i in _issues(out))


def test_unparseable_default_token(tmp_path):
    root = _workspace(tmp_path)
    out = source_fidelity_audit(
        manuscript="Uses `train_model(lr=??)`.",
        workspace_root=root,
    )
    # either parse failure (medium) or default mismatch (high)
    assert out and any(f.angle == "source_fidelity" for f in out)


def test_numeric_bracket_citation_required():
    out = source_fidelity_audit(
        manuscript="See prior work [1,2] for baselines.",
        composition_contract={
            "allowed_citation_keys": ["1", "2", "3"],
            "required_citation_keys": ["3"],
        },
    )
    assert any("3" in i and "missing" in i for i in _issues(out))
