"""Regression tests for the compiled-manuscript typography gate.

These pin the defects that shipped in four manuscripts before the gate existed:
tables pinned to hand-tuned centimetre widths that overflowed the text block,
vertical rules, body-length captions, and letter paper at an A4 venue.
"""

from __future__ import annotations

from research_harness._workflow.execution.typography_checks import (
    OVERFULL_MAJOR_PT,
    check_overfull_boxes,
    check_paper_size,
    check_table_constructs,
    check_typography,
    format_report,
)

NPJ_TABLE = r"""
\begin{table}[!tbp]
\caption{Discrimination by cohort.}
\begin{tabular}{p{3.0cm}p{4.0cm}p{1.4cm}p{2.1cm}}
\toprule
Cohort & Method & C-index & Status \\
\bottomrule
\end{tabular}
\end{table}
"""

ADAPTIVE_TABLE = r"""
\begin{table}[!tbp]
\caption{Discrimination by cohort.}
\begin{tabularx}{\textwidth}{lXrr}
\toprule
Cohort & Method & C-index & Status \\
\bottomrule
\end{tabularx}
\end{table}
"""


class TestOverfull:
    def test_major_overfull_reported(self):
        log = "main.tex:403: Overfull \\hbox (93.3333pt too wide) in paragraph at lines 402--403"
        findings = check_overfull_boxes(log)
        assert len(findings) == 1
        assert findings[0].severity == "major"
        assert findings[0].line == 403

    def test_sub_threshold_overfull_ignored(self):
        # TeX flags fractions of a point that no reader can see; those are noise.
        assert not check_overfull_boxes("Overfull \\hbox (1.9pt too wide) in paragraph")

    def test_minor_band_between_thresholds(self):
        log = f"Overfull \\hbox ({OVERFULL_MAJOR_PT - 5:.1f}pt too wide) in paragraph"
        findings = check_overfull_boxes(log)
        assert [f.severity for f in findings] == ["minor"]

    def test_duplicate_log_lines_reported_once(self):
        line = "main.tex:403: Overfull \\hbox (93.3pt too wide) in paragraph at lines 402--403"
        assert len(check_overfull_boxes(f"{line}\n{line}\n")) == 1


class TestTableConstructs:
    def test_pinned_column_widths_are_major(self):
        findings = check_table_constructs(NPJ_TABLE)
        pinned = [f for f in findings if f.check == "fixed_width_columns"]
        assert len(pinned) == 1
        assert pinned[0].severity == "major"

    def test_vertical_rules_flagged(self):
        tex = r"\begin{tabular}{p{2.8cm}|p{3.5cm}|l}" "\n" r"\end{tabular}"
        checks = {f.check for f in check_table_constructs(tex)}
        assert "vertical_rules" in checks

    def test_adaptive_table_is_clean(self):
        assert check_table_constructs(ADAPTIVE_TABLE) == []

    def test_single_pinned_column_tolerated(self):
        # One fixed column (e.g. a notes column) is a normal typesetting choice.
        tex = r"\begin{tabular}{lp{4cm}r}" "\n" r"\end{tabular}"
        assert not [
            f for f in check_table_constructs(tex) if f.check == "fixed_width_columns"
        ]


class TestPaperSize:
    def test_letter_at_nature_venue_is_major(self):
        tex = (
            r"\documentclass[11pt]{article}" "\n" r"\usepackage[letterpaper]{geometry}"
        )
        findings = check_paper_size(tex, "hssc")
        assert len(findings) == 1
        assert findings[0].severity == "major"

    def test_a4_at_nature_venue_clean(self):
        tex = r"\documentclass[11pt]{article}" "\n" r"\usepackage[a4paper]{geometry}"
        assert check_paper_size(tex, "hssc") == []

    def test_letter_at_letter_venue_clean(self):
        tex = r"\documentclass[letterpaper]{article}"
        assert check_paper_size(tex, "aaai") == []

    def test_unknown_venue_not_checked(self):
        tex = r"\documentclass[letterpaper]{article}"
        assert check_paper_size(tex, "some-workshop") == []


class TestCaptions:
    def test_body_length_caption_flagged(self):
        tex = r"\caption{" + "word " * 200 + "}"
        checks = {f.check for f in check_typography(tex).findings}
        assert "caption_length" in checks

    def test_normal_caption_clean(self):
        tex = r"\caption{Cohort characteristics and modality availability.}"
        assert not [
            f for f in check_typography(tex).findings if f.check == "caption_length"
        ]


class TestReport:
    def test_report_ok_only_without_majors(self):
        report = check_typography(ADAPTIVE_TABLE, "", venue_key="springer_nature")
        assert report.ok
        assert format_report(report) == "typography: clean"

    def test_report_summarises_majors(self):
        log = "Overfull \\hbox (93.3pt too wide) in paragraph at lines 1--2"
        report = check_typography(NPJ_TABLE, log, venue_key="springer_nature")
        assert not report.ok
        assert report.to_dict()["major_count"] >= 2
        assert "fixed_width_columns" in format_report(report)


class TestBareArticleDefault:
    """A bare \\documentclass{article} silently means US letter."""

    def test_bare_article_at_a4_venue_is_major(self):
        tex = r"\documentclass[11pt]{article}" "\n" r"\usepackage[margin=1in]{geometry}"
        findings = check_paper_size(tex, "hssc")
        assert len(findings) == 1
        assert findings[0].severity == "major"
        assert "defaults to US letter" in findings[0].message

    def test_bare_article_with_a4_option_clean(self):
        tex = r"\documentclass[11pt,a4paper]{article}"
        assert check_paper_size(tex, "hssc") == []

    def test_bare_article_at_letter_venue_clean(self):
        tex = r"\documentclass[11pt]{article}"
        assert check_paper_size(tex, "aaai") == []

    def test_class_file_venues_not_second_guessed(self):
        # sn-jnl / elsarticle pin their own geometry; no bare-article default applies.
        tex = r"\documentclass[pdflatex,sn-nature]{sn-jnl}"
        assert check_paper_size(tex, "springer_nature") == []
