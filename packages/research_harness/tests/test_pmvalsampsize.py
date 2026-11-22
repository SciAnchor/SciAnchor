"""Riley BMJ 2024 O/E wrap — fail closed, no 30-floor."""

import pytest

from research_harness.auto_runner.pmvalsampsize import (
    PmvalSampleSizeError,
    n_star,
    oe_n_star,
)


def test_oe_closed_form():
    assert oe_n_star(prevalence=0.1, se_ln_oe=0.1) == pytest.approx(900.0)


def test_wider_se_cannot_shrink_n_star():
    assert oe_n_star(prevalence=0.1, se_ln_oe=1.0) == pytest.approx(900.0)


def test_missing_prevalence_fails_closed():
    with pytest.raises(PmvalSampleSizeError, match="prevalence"):
        oe_n_star(prevalence="", se_ln_oe=0.1)


def test_slope_without_lp_fails_closed():
    with pytest.raises(PmvalSampleSizeError, match="unsupported"):
        n_star("slope", prevalence=0.1)


def test_no_thirty_event_default():
    with pytest.raises(PmvalSampleSizeError):
        n_star("oe")
