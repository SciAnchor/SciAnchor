"""Frozen venue assembly controls; legacy callers retain their existing template."""

from copy import deepcopy

import pytest

from research_harness.execution.latex_compiler import (
    assemble_latex,
    credit_authorship_block,
)


PROFILE = {
    "structure": [
        "Abstract",
        "Introduction",
        "Results",
        "Discussion",
        "Methods",
        "References",
        "Acknowledgements",
        "Author contributions",
        "Competing interests",
    ],
    "byline": {
        "placeholders_required": True,
        "corresponding_marker": "bottom_left",
        "placeholder_tokens": [
            "Author 1",
            "Author 2",
            "Author 3",
            "Institution One",
            "Institution Two",
            "corresponding.author@institution.edu",
        ],
    },
}
CREDIT = credit_authorship_block(
    ("Conceptualization", "Validation", "Supervision")
).split("\n\n", 1)[1]


def test_profile_controls_order_bibliography_byline_and_credit_without_mutation():
    sections = {
        name.lower().replace(" ", "_"): "Evidence."
        for name in reversed(PROFILE["structure"][1:])
    }
    sections["author_contributions"] = CREDIT
    sections["references"] = "This generated prose must not replace the bibliography."
    original = deepcopy((sections, PROFILE))
    tex, bib = assemble_latex(
        "Title",
        [],
        "Abstract.",
        sections,
        ["@article{key,title={Paper}}"],
        venue_profile=PROFILE,
        preserve_section_order=True,
    )
    positions = [
        tex.index(r"\bibliography{references}")
        if name == "References"
        else tex.index(r"\section{" + name + "}")
        for name in PROFILE["structure"][1:]
    ]
    assert positions == sorted(positions)
    assert tex.count(r"\bibliography{references}") == 1
    assert r"\section{References}" not in tex
    assert "generated prose" not in tex
    assert "@article{key" in bib
    assert CREDIT in tex and tex.count(r"\textbf{Author 1:}") == 1
    assert "CRediT authorship contribution statement" not in tex
    for token in PROFILE["byline"]["placeholder_tokens"]:
        assert token in tex
    assert (
        "Author 3$^{2,*}$" in tex
        and "Author 1$^{1}$" in tex
        and "Author 2$^{1}$" in tex
    )
    assert (sections, PROFILE) == original


def test_missing_references_draft_still_places_real_bibliography_before_backmatter():
    tex, _ = assemble_latex(
        "T",
        [],
        "A",
        {"acknowledgements": "Thanks.", "methods": "M."},
        venue_profile=PROFILE,
    )
    assert tex.index(r"\section{Methods}") < tex.index(r"\bibliography{references}")
    assert tex.index(r"\bibliography{references}") < tex.index(
        r"\section{Acknowledgements}"
    )


def test_elsevier_credit_heading_preserves_spelling_and_roles():
    profile = {
        **PROFILE,
        "structure": [
            "Abstract",
            "Method",
            "CRediT authorship contribution statement",
            "Declaration of competing interest",
            "References",
            "Appendix",
        ],
    }
    tex, _ = assemble_latex(
        "T",
        [],
        "A",
        {
            "credit_authorship_contribution_statement": CREDIT,
            "declaration_of_competing_interest": "None.",
            "appendix": "Details.",
        },
        venue_profile=profile,
    )
    assert r"\section{CRediT authorship contribution statement}" in tex
    assert CREDIT in tex and tex.count(r"\textbf{Author 1:}") == 1
    assert tex.index(r"\bibliography{references}") < tex.index(r"\section{Appendix}")


def test_profile_keeps_existing_default_credit_at_its_declared_seat_when_not_drafted():
    profile = {
        **PROFILE,
        "structure": [
            "Abstract",
            "Method",
            "CRediT authorship contribution statement",
            "Declaration of competing interest",
            "References",
        ],
    }
    tex, _ = assemble_latex(
        "T",
        [],
        "A",
        {"method": "M.", "declaration_of_competing_interest": "None."},
        venue_profile=profile,
    )
    assert tex.index(r"\section{CRediT authorship contribution statement}") < tex.index(
        r"\bibliography{references}"
    )
    assert tex.count(r"\textbf{Author 1:}") == 1


def test_profile_keeps_nested_custom_credit_without_an_extra_default_block():
    profile = {
        **PROFILE,
        "structure": ["Abstract", "Methods", "Declarations", "References"],
        "declarations_block": ["Author contributions", "Competing interests"],
    }
    content = r"\subsection{Author contributions}" + "\n" + CREDIT
    tex, _ = assemble_latex(
        "T", [], "A", {"declarations": content}, venue_profile=profile
    )
    assert CREDIT in tex and tex.count(r"\textbf{Author 1:}") == 1


def test_required_contributions_outside_structure_use_standard_title():
    profile = {
        **PROFILE,
        "structure": ["Abstract", "Introduction", "References"],
        "byline": {**PROFILE["byline"], "contributions_required": True},
    }
    tex, _ = assemble_latex("T", [], "A", {"introduction": "I."}, venue_profile=profile)
    assert r"\section{Author contributions}" in tex
    assert tex.count(r"\textbf{Author 1:}") == 1


def test_omitted_profile_is_identical_to_explicit_none_and_keeps_real_authors():
    args = ("T", ["Ada", "Grace"], "A", {"methods": "M.", "results": "R."})
    legacy = assemble_latex(*args)
    assert legacy == assemble_latex(*args, venue_profile=None)
    assert r"Ada \and Grace" in legacy[0]
    assert "Institution One" not in legacy[0]
    assert "CRediT authorship contribution statement" in legacy[0]


def test_partial_legacy_profile_preserves_existing_byline_credit_and_order():
    args = ("T", [], "A", {"methods": "M.", "results": "R."})
    partial = {"venue": "IPM", "lane": "computational", "words": {"abstract_max": 200}}
    assert assemble_latex(*args, venue_profile=partial) == assemble_latex(*args)


@pytest.mark.parametrize(
    "tokens",
    [
        None,
        [],
        ["Author 1"],
        ["Ada", "Author 2", "Author 3", "One", "Two", "a@b"],
        ["Author 1", "Author 2", "Author 3", 42, "Two", "a@b"],
        ["Author 1", "Author 2", "Author 3", "", "Two", "a@b"],
        ["Author 1", "Author 2", "Author 3", r"\input{file}", "Two", "a@b"],
    ],
)
def test_malformed_placeholder_contract_refuses(tokens):
    profile = {**PROFILE, "byline": {**PROFILE["byline"], "placeholder_tokens": tokens}}
    with pytest.raises(ValueError, match="placeholder"):
        assemble_latex("T", [], "A", {}, venue_profile=profile)


def test_profile_without_placeholder_requirement_retains_real_authors_and_unknown_sections():
    profile = {"structure": ["Abstract", "Methods", "References"]}
    tex, _ = assemble_latex(
        "T",
        ["Ada"],
        "A",
        {"methods": "M.", "Extra detail": "Keep me."},
        venue_profile=profile,
    )
    assert r"\author{Ada}" in tex and "Keep me." in tex
    assert r"\section{Extra detail}" in tex
    assert "Author 1" not in tex


def test_non_bottom_marker_uses_profile_tokens_under_author_line():
    byline = {
        **PROFILE["byline"],
        "corresponding_marker": "title",
        "placeholder_tokens": [
            "Author 1",
            "Author 2",
            "Author 3",
            "One & Partners",
            "Two",
            "a_b@example.org",
        ],
    }
    tex, _ = assemble_latex(
        "T", [], "A", {}, venue_profile={**PROFILE, "byline": byline}
    )
    assert r"One \& Partners" in tex and r"a\_b@example.org" in tex
    assert tex.index("Corresponding author") < tex.index(r"\begin{document}")
    assert r"\footnotetext" not in tex


def test_bottom_left_note_is_stamped_at_shipout_not_set_as_a_float_or_footnote():
    """A footnote needs a footnote-size font a cached TeX toolchain may never have loaded (a T1 +
    lmodern 11pt preamble stops on the note's own line); a caption-less float counts toward the figure
    floors; a "]" breaks a template that sets \\maketitle inside \\twocolumn[...]. The note is stamped on
    page 1's bottom-left margin at shipout."""
    for template in ("generic", "aaai"):
        tex, _ = assemble_latex(
            "T", [], "A", {}, venue_profile=PROFILE, template=template
        )
        start = tex.index(r"\begingroup", tex.index(r"\begin{document}"))
        assert start < tex.index(r"\maketitle"), (
            "registered after a title page would have shipped"
        )
        note = tex[start : tex.index(r"\endgroup", start)]
        hooked = note[: note.index(r"\else")]
        assert (
            r"\AddToHookNext{shipout/foreground}" in hooked
            and "Corresponding author: Author 3" in hooked
        )
        assert "corresponding.author@institution.edu" in hooked
        # Placed from the text block, not the paper edge, a column wide.
        for length in (
            r"\oddsidemargin",
            r"\topmargin",
            r"\textheight",
            r"\columnwidth",
        ):
            assert length in hooked
        # Page 1's first column gives up the note's height at top level, after the title block: after
        # \maketitle, or after the \twocolumn[...] argument that holds it (aaai).
        reserve = tex.index(r"\enlargethispage")
        assert reserve > tex.index(r"\maketitle")
        if template == "aaai":
            assert tex.rindex("]", 0, reserve) > tex.index(r"\end{abstract}")
        assert not {"[", "]"} & set(note.replace("[0pt][l]", "")), template
        for absent in (
            r"\footnotetext",
            r"\begin{figure}",
            r"\texttt",
            r"\paperheight",
        ):
            assert absent not in hooked
        # A kernel without the shipout hook gets the footnote instead of an undefined command.
        assert (
            note.index(r"\ifdefined\AddToHookNext")
            < note.index(r"\else")
            < note.index(r"\footnotetext")
        )


def test_title_block_end_skips_brackets_inside_the_twocolumn_argument():
    from research_harness._workflow.execution.latex_compiler import _after_title_block

    tex = "\\twocolumn[\\title{A [b] \\] c}\\maketitle{x}]\nBody"
    out = _after_title_block(tex, tex.index("\\maketitle"), "RESERVE\n")
    assert out.endswith("{x}]\nRESERVE\n\nBody")
    plain = "\\maketitle\nBody"
    assert _after_title_block(plain, 0, "RESERVE\n") == "\\maketitle\nRESERVE\n\nBody"


def test_section_review_is_told_the_venue():
    from research_harness.auto_runner.tool_dispatch import _build_primitive_params

    params = _build_primitive_params(
        "section_review",
        topic_id=1,
        context={
            "_drafted_sections": ["abstract"],
            "_output_section_draft_abstract": {"text": "words"},
            "target_venue": "npj Digital Medicine",
        },
    )
    assert params["target_venue"] == "npj Digital Medicine"
