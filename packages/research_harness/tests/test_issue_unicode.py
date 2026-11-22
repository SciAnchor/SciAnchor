"""U+2010 regressions: synthetic controls and the captured A0124 source pool."""

import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_harness.execution import latex_compiler as compiler
from research_harness.primitives.writing_impls import _bibtex_escape


@pytest.fixture(autouse=True)
def no_external_transport(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("external transport is forbidden in Unicode regressions")

    from llm_router.client import LLMClient

    for name in ("chat", "chat_accounted"):
        monkeypatch.setattr(LLMClient, name, refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def test_unicode_hyphen_preserves_names_and_existing_math():
    names = "Yıldırım, Chloé, Müller, Dollár, 李"
    normalized = r"Y\i{}ld\i{}r\i{}m, Chlo\'e, M\"uller, Dollár, 李"
    math = r"$\alpha_i \leq \beta$; \(x_1 + x_2\); \[\sum_i x_i\]"
    source = names + " risk‐aware " + math
    expected = normalized + " risk-aware " + math
    assert compiler._fix_unicode(source) == expected
    assert compiler._fix_unicode(expected) == expected
    assert _bibtex_escape(names + " risk‐aware") == normalized + " risk-aware"
    assert _bibtex_escape("Generation & Distribution") == r"Generation \& Distribution"


@pytest.mark.parametrize("engine", ["tectonic", "pdflatex"])
def test_frozen_unicode_is_rejected_without_rewriting(tmp_path, monkeypatch, engine):
    """Synthetic missing-glyph engine response, not an original TeX run."""
    tex = r"\documentclass{article}\begin{document}Risk‐aware.\end{document}"
    bib = "@misc{ref1,title={Risk‐aware control}}"
    monkeypatch.setattr(
        compiler.shutil, "which", lambda name: name if name == engine else None
    )
    monkeypatch.setattr(compiler, "_populate_page_count", lambda *args: None)

    def run(args, **kwargs):
        work = Path(kwargs["cwd"])
        assert (work / "main.tex").read_text() == tex
        assert (work / "references.bib").read_text() == bib
        (work / "main.pdf").write_bytes(b"%PDF-synthetic-control")
        (work / "main.log").write_text(
            'Missing character: There is no ‐ ("2010) in font ec-lmr10!\n'
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(compiler.subprocess, "run", run)
    result = compiler.compile_latex(
        tex, bib, str(tmp_path), filename="main", preserve_source=True
    )
    assert not result.success and not result.pdf_path and not result.auto_fixes
    assert any("missing character" in error for error in result.errors)
    assert (tmp_path / "main.tex").read_text() == tex
    assert (tmp_path / "references.bib").read_text() == bib
    assert not (tmp_path / "main.pdf").exists()
