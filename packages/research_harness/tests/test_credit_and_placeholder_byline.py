"""Owner-mandated byline and CRediT conventions (2026-08-17).

Drafts must carry a three-author / two-department / one-corresponding byline
placeholder, and a CRediT statement in role-list form.
"""

from research_harness._workflow.execution.latex_compiler import (
    DEFAULT_CREDIT_ROLES,
    PLACEHOLDER_AUTHOR_BLOCK,
    _format_authors_latex,
    credit_authorship_block,
)


def test_empty_author_list_yields_three_author_two_department_placeholder():
    block = _format_authors_latex([], "article")
    assert block == PLACEHOLDER_AUTHOR_BLOCK
    for name in ("Author 1", "Author 2", "Author 3"):
        assert name in block
    # two departments, and only the third author is corresponding
    # (owner template 2026-08-23: superscript marks + department lines)
    assert block.count("Department") == 2
    assert block.count("Corresponding author") == 1
    assert "Author 3$^{2,*}$" in block
    assert "Author 1$^{1}$" in block and "Author 2$^{1}$" in block
    assert "\\texttt{corresponding.author@institution.edu}" in block
    assert "Anonymous" not in block


def test_real_author_list_is_untouched():
    assert _format_authors_latex(["Ada", "Grace"], "article") == "Ada \\and Grace"


def test_credit_block_is_role_list_without_prose_gloss():
    block = credit_authorship_block()
    assert "\\section*{CRediT authorship contribution statement}" in block
    for i, roles in enumerate(DEFAULT_CREDIT_ROLES, start=1):
        assert f"\\textbf{{Author {i}:}} {roles}." in block
    # role-list form only: no narrative restatement of who did what
    assert " developed the " not in block
    assert " designed the " not in block
    assert block.rstrip().endswith(
        "All authors have read and agreed to the submitted version of the manuscript."
    )


def test_credit_roles_are_reassignable_per_paper():
    custom = ("Conceptualization", "Data curation", "Supervision")
    block = credit_authorship_block(custom)
    assert "\\textbf{Author 1:} Conceptualization." in block
    assert "\\textbf{Author 3:} Supervision." in block
