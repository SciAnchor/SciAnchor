"""A venue that has shipped a finished manuscript keeps its class.

Three drafts went out in 2026-08 with mismatched classes: the npj submission
compiled as a plain 11pt article although RH had already produced an npj paper
in Springer Nature's own sn-jnl, and the HSSC paper used a different geometry
from the HSSC papers before it. Only the Elsevier one was right, and only
because the owner had named the class by hand. These tests bind venue to class
so the next paper for a venue starts where the last one landed.
"""

import pytest

from research_harness._workflow.execution.latex_compiler import (
    TEMPLATES,
    resolve_template_key,
)


@pytest.mark.parametrize(
    "venue,expected",
    [
        # Springer Nature family — the class RH's npj VTE paper shipped in
        ("npj Digital Medicine", "springer_nature"),
        ("npj digital medicine", "springer_nature"),
        ("Nature Communications", "springer_nature"),
        ("Nature Medicine", "springer_nature"),
        ("Scientific Reports", "springer_nature"),
        # Humanities and Social Sciences Communications
        ("Humanities and Social Sciences Communications", "hssc"),
        ("HSSC", "hssc"),
        ("Palgrave Communications", "hssc"),
        # Elsevier journals
        ("Pattern Recognition", "elsevier"),
        ("Neurocomputing", "elsevier"),
        ("Expert Systems with Applications", "elsevier"),
        ("Biomedical Signal Processing and Control", "elsevier"),
        # conferences must keep resolving as before
        ("AAAI 2026", "aaai"),
        ("NeurIPS'25", "neurips"),
        ("EMNLP", "acl"),
    ],
)
def test_venue_binds_to_its_shipped_class(venue, expected):
    assert resolve_template_key(venue) == expected


@pytest.mark.parametrize(
    "venue",
    ["computer vision journal", "pure CS venue", "computer graphics journal"],
)
def test_pure_cs_defaults_to_elsevier(venue):
    """Owner rule: a pure-CS manuscript with no venue class goes Elsevier."""
    assert resolve_template_key(venue) == "elsevier"


def test_journal_templates_declare_their_class():
    assert "sn-jnl" in TEMPLATES["springer_nature"]
    assert "elsarticle" in TEMPLATES["elsevier"]
    assert "article" in TEMPLATES["hssc"]


def test_unknown_venue_still_falls_back():
    assert resolve_template_key("a journal nobody has heard of") == "generic"
