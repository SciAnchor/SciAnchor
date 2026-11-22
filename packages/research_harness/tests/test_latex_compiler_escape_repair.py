"""Guard for `_restore_python_escaped_text_commands`.

When an LLM response is JSON-decoded, a bare (undoubled) backslash before a
single-letter JSON escape ("\\t", "\\f", ...) is consumed as a control
character, silently truncating the following LaTeX command. This repairs the
known cases: \\textbf/\\textit/\\texttt (leading "\\t" -> tab) and \\frac
(leading "\\f" -> form-feed).
"""

from __future__ import annotations

from research_harness._workflow.execution.latex_compiler import (
    _restore_python_escaped_text_commands,
)


def test_restores_frac_after_form_feed() -> None:
    damaged = "The gate normalizes as \x0crac{1}{2} of the mass."
    assert _restore_python_escaped_text_commands(damaged) == (
        "The gate normalizes as \\frac{1}{2} of the mass."
    )


def test_restores_textbf_after_tab() -> None:
    damaged = "This is \textbf{important}."
    assert _restore_python_escaped_text_commands(damaged) == (
        "This is \\textbf{important}."
    )


def test_leaves_real_frac_command_untouched() -> None:
    intact = "\\frac{1}{2} is already correct."
    assert _restore_python_escaped_text_commands(intact) == intact


def test_leaves_unrelated_form_feed_untouched() -> None:
    # A form-feed not immediately followed by "rac{" must not be touched.
    text = "page one\x0cpage two"
    assert _restore_python_escaped_text_commands(text) == text
