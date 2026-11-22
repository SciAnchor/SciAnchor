"""Compiler preserve mode is deterministic local hardening, not isolation."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from research_harness.execution import latex_compiler as compiler

TEX = "\\documentclass{custom}\n\\begin{document}Content.\\end{document}\n"
BIB = "@article{alpha,title={Evidence}}\n"


@pytest.fixture
def engine(monkeypatch):
    calls = []
    state = {
        "name": "pdflatex",
        "fail": False,
        "mutate": "",
        "timeout": False,
        "delete": False,
        "returncode": 0,
    }
    monkeypatch.setattr(
        compiler.shutil, "which", lambda name: name if name == state["name"] else None
    )
    monkeypatch.setattr(compiler, "_validate_before_compile", lambda *args: [])
    monkeypatch.setattr(compiler, "_populate_page_count", lambda *args: None)
    monkeypatch.setattr(compiler, "_attach_typography_findings", lambda *args: None)

    def run(args, **kwargs):
        calls.append((args, kwargs))
        work = Path(kwargs["cwd"])
        if state["timeout"]:
            raise subprocess.TimeoutExpired(args, 1)
        if state["fail"]:
            message = "! LaTeX Error: File `custom.sty' not found"
            (work / "main.log").write_text(message)
            return SimpleNamespace(returncode=1, stdout=message, stderr=message)
        (work / "main.pdf").write_bytes(b"%PDF-fake-test")
        if state["mutate"]:
            path = work / state["mutate"]
            path.write_text("changed")
            if state["delete"]:
                path.unlink()
        return SimpleNamespace(returncode=state["returncode"], stdout="", stderr="")

    monkeypatch.setattr(compiler.subprocess, "run", run)
    return state, calls


@pytest.mark.parametrize(
    "filename",
    [
        "../main",
        "/tmp/main",
        "a/b",
        "a\\b",
        "-shell-escape",
        "",
        ".",
        "..",
        "a.tex",
        "a\nmain",
        "references",
        None,
    ],
)
def test_rejects_unsafe_stem_before_filesystem_changes(tmp_path, filename):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="filename"):
        compiler.compile_latex(
            TEX, BIB, str(output), filename=filename, preserve_source=True
        )
    assert not output.exists()


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
def test_preserves_source_and_hardens_engine_arguments(tmp_path, engine, name):
    state, calls = engine
    state["name"] = name
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert result.success and not result.auto_fixes
    assert (tmp_path / "main.tex").read_text() == TEX
    assert (tmp_path / "references.bib").read_text() == BIB
    compile_calls = [(args, kw) for args, kw in calls if args[0] != "bibtex"]
    assert all(
        ("-no-shell-escape" if name == "pdflatex" else "--untrusted") in args
        for args, _ in compile_calls
    )
    assert all(
        kw["env"]["openin_any"] == "p" and kw["env"]["openout_any"] == "p"
        for _, kw in calls
    )


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
def test_missing_style_never_triggers_template_fallback(tmp_path, engine, name):
    state, _ = engine
    state.update(name=name, fail=True)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and not result.auto_fixes
    assert (tmp_path / "main.tex").read_text() == TEX


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
@pytest.mark.parametrize("path", ["main.tex", "references.bib"])
def test_rejects_and_restores_engine_source_rewrite(tmp_path, engine, name, path):
    state, _ = engine
    state.update(name=name, mutate=path)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and result.pdf_path == ""
    assert any("source" in error for error in result.errors)
    assert (tmp_path / "main.tex").read_text() == TEX
    assert (tmp_path / "references.bib").read_text() == BIB
    assert not (tmp_path / "main.pdf").exists()


def test_missing_engine_cannot_reuse_stale_pdf(tmp_path, engine):
    state, _ = engine
    state["name"] = "missing"
    (tmp_path / "main.pdf").write_bytes(b"stale")
    result = compiler.compile_latex(
        TEX, "", str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and not result.pdf_path
    assert not (tmp_path / "main.pdf").exists()


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
def test_timeout_fails_closed(tmp_path, engine, name):
    state, _ = engine
    state.update(name=name, timeout=True)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success
    assert any("timed out" in item for item in result.errors)


def test_legacy_mode_keeps_template_fallback(tmp_path, engine):
    state, _ = engine
    state["fail"] = True
    result = compiler.compile_latex(TEX, "", str(tmp_path), filename="main")
    assert result.auto_fixes
    assert (tmp_path / "main.tex").read_text() != TEX


def test_restores_deleted_source_and_removes_unexpected_bibliography(tmp_path, engine):
    state, _ = engine
    state.update(mutate="main.tex", delete=True)
    result = compiler.compile_latex(
        TEX, "", str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and (tmp_path / "main.tex").read_text() == TEX
    state.update(mutate="references.bib", delete=False)
    result = compiler.compile_latex(
        TEX, "", str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and not (tmp_path / "references.bib").exists()


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
def test_nonzero_engine_exit_is_failure_even_when_pdf_exists(tmp_path, engine, name):
    state, _ = engine
    state.update(name=name, returncode=1)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success
    assert result.errors


def test_assembly_can_preserve_the_approved_section_order():
    sections = {
        "results": "Outcome text.",
        "custom method": "Method text.",
        "introduction": "Context text.",
    }
    preserved, _ = compiler.assemble_latex(
        "Paper", [], "", sections, preserve_section_order=True
    )
    assert (
        preserved.index("Outcome text.")
        < preserved.index("Method text.")
        < preserved.index("Context text.")
    )
    legacy, _ = compiler.assemble_latex("Paper", [], "", sections)
    assert legacy.index("Context text.") < legacy.index("Outcome text.")


def test_missing_bibtex_blocks_preserved_manuscript(tmp_path, engine, monkeypatch):
    run = compiler.subprocess.run

    def missing_bibtex(args, **kwargs):
        if args[0] == "bibtex":
            raise FileNotFoundError("bibtex unavailable")
        return run(args, **kwargs)

    monkeypatch.setattr(compiler.subprocess, "run", missing_bibtex)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success
    assert any("bibtex" in error for error in result.errors)


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
def test_missing_glyph_cannot_pass_source_preserving_compile(
    tmp_path, engine, monkeypatch, name
):
    state, _ = engine
    state["name"] = name
    run = compiler.subprocess.run

    def missing_glyph(args, **kwargs):
        result = run(args, **kwargs)
        (Path(kwargs["cwd"]) / "main.log").write_text(
            'Missing character: There is no character ("65B9) in font ec-lmr17!\n'
        )
        return result

    monkeypatch.setattr(compiler.subprocess, "run", missing_glyph)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and not result.pdf_path
    assert any("missing character" in error.lower() for error in result.errors)
    assert (tmp_path / "main.tex").read_text() == TEX
    assert not (tmp_path / "main.pdf").exists()


@pytest.mark.parametrize("name", ["pdflatex", "tectonic"])
@pytest.mark.parametrize("preserve_source", [True, False])
def test_compile_children_cannot_read_publication_credentials(
    tmp_path, monkeypatch, name, preserve_source
):
    for key in (
        "RH_DEPOSIT_SECRET",
        "RH_DEPOSIT_USERNAME",
        "RH_DEPOSIT_PLATFORM",
        "ZENODO_TOKEN",
        "ZENODO_PASSWORD",
        "ZENODO_EMAIL",
        "RH_DOI_PUBLICATION",
        "ARINA_DOI_ACCOUNTS_JSON",
    ):
        monkeypatch.setenv(key, "synthetic-private-value")
    monkeypatch.setenv("ORDINARY_CONFIG", "kept")
    monkeypatch.setattr(
        compiler.shutil,
        "which",
        lambda executable: executable if executable == name else None,
    )
    monkeypatch.setattr(compiler, "_validate_before_compile", lambda *args: [])
    monkeypatch.setattr(compiler, "_attach_typography_findings", lambda *args: None)
    real_run = subprocess.run
    calls = []
    probe = (
        "import json, os; "
        "snapshot = {'publication_present': any(k.startswith(('RH_DEPOSIT_', 'ZENODO_')) "
        "or k in {'RH_DOI_PUBLICATION', 'ARINA_DOI_ACCOUNTS_JSON'} for k in os.environ), "
        "'ordinary_preserved': os.environ.get('ORDINARY_CONFIG') == 'kept'}; "
        "print(json.dumps(snapshot))"
    )

    def run(args, **kwargs):
        outcome = real_run([sys.executable, "-c", probe], **kwargs)
        calls.append((args[0], json.loads(outcome.stdout)))
        if args[0] == "pdfinfo":
            return SimpleNamespace(returncode=0, stdout="Pages: 1\n", stderr="")
        (Path(kwargs["cwd"]) / "main.pdf").write_bytes(b"%PDF-fake-test")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(compiler.subprocess, "run", run)
    result = compiler.compile_latex(
        TEX, BIB, str(tmp_path), filename="main", preserve_source=preserve_source
    )
    assert result.success and result.pages == 1
    assert {command for command, _ in calls} == (
        {name, "pdfinfo", "bibtex"} if name == "pdflatex" else {name, "pdfinfo"}
    )
    assert all(
        snapshot == {"publication_present": False, "ordinary_preserved": True}
        for _, snapshot in calls
    )
    assert os.environ["RH_DEPOSIT_SECRET"] == "synthetic-private-value"
