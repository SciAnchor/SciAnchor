"""Tests for Sprint 4 writing pipeline — writing_checks, latex_compiler, writing primitives."""

from __future__ import annotations

import pytest

from research_harness.execution.writing_checks import (
    AI_BOILERPLATE_PHRASES,
    REVIEW_DIMENSIONS,
    SECTION_WORD_TARGETS,
    WEASEL_WORDS,
    check_ai_boilerplate,
    check_number_consistency,
    check_paragraph_development,
    check_repetition,
    check_section_structure,
    check_uncited_paragraphs,
    check_weasel_words,
    check_word_count,
    run_all_checks,
)
from research_harness.execution.latex_compiler import (
    TEMPLATES,
    _escape_latex,
    _fix_unicode,
    _section_sort_key,
    _validate_before_compile,
    assemble_latex,
    template_fingerprint,
)
from research_harness.primitives.writing_impls import _bibtex_escape


# -- Writing Checks -----------------------------------------------------------


class TestWordCount:
    def test_within_target(self):
        # Introduction target is now 1200-1800
        content = " ".join(["word"] * 1400)  # 1400 words
        result = check_word_count(content, "introduction")
        assert result.passed

    def test_below_target(self):
        content = " ".join(["word"] * 100)  # 100 words, too short for intro
        result = check_word_count(content, "introduction")
        assert not result.passed

    def test_above_target(self):
        content = " ".join(["word"] * 2000)  # 2000 words, too long for intro
        result = check_word_count(content, "introduction")
        assert not result.passed

    def test_custom_target(self):
        content = " ".join(["word"] * 500)
        result = check_word_count(content, "custom_section", target_words=500)
        assert result.passed

    def test_no_target(self):
        content = "any content"
        result = check_word_count(content, "unknown_section_xyz")
        assert result.passed


class TestAIBoilerplate:
    def test_clean_text(self):
        text = (
            "We evaluate our approach on three benchmarks and report accuracy metrics."
        )
        result = check_ai_boilerplate(text)
        assert result.passed

    def test_boilerplate_detected(self):
        text = (
            "In this paper, we propose a novel approach that achieves state-of-the-art results. "
            "Our proposed method leveraging the power of transformers is groundbreaking. "
            "It is worth noting that our paradigm shift paves the way for future research."
        )
        result = check_ai_boilerplate(text)
        assert not result.passed
        assert len(result.items_found) > 3

    def test_few_phrases_ok(self):
        text = "The proposed method achieves good results. In conclusion, we demonstrated improvements."
        result = check_ai_boilerplate(text)
        assert result.passed  # <= 3 phrases allowed


class TestWeaselWords:
    def test_clean_text(self):
        text = "The model achieves 95.2% accuracy on the test set, surpassing the baseline by 3.1 points."
        result = check_weasel_words(text)
        assert result.passed

    def test_hedging_detected(self):
        hedgy = (
            "The results somewhat suggest that perhaps our approach might relatively "
            "improve performance. It seems that the method arguably provides fairly "
            "moderate gains. The improvement appears to be rather marginal."
        )
        result = check_weasel_words(hedgy)
        assert not result.passed
        assert len(result.items_found) > 3


class TestRepetition:
    def test_no_repetition(self):
        text = "First sentence here. Second different sentence. Third unique statement."
        result = check_repetition(text)
        assert result.passed

    def test_repetition_detected(self):
        text = (
            "Our method achieves state of the art results. "
            "The model achieves state of the art performance. "
            "This approach achieves state of the art accuracy. "
            "We show that it achieves state of the art scores."
        )
        result = check_repetition(text)
        assert not result.passed


class TestSectionStructure:
    def test_empty_content(self):
        result = check_section_structure("", "introduction")
        assert not result.passed

    def test_intro_without_citations(self):
        result = check_section_structure(
            "Some text without any citations.", "introduction"
        )
        assert not result.passed

    def test_intro_with_citations(self):
        result = check_section_structure(
            r"Prior work \cite{vaswani2017} showed that transformers are effective.",
            "introduction",
        )
        assert result.passed

    def test_results_no_citations_ok(self):
        result = check_section_structure("Our model achieves 95% accuracy.", "results")
        assert result.passed  # results section doesn't need citations


class TestUncitedParagraphs:
    def test_flags_long_uncited_paragraph_in_intro(self):
        paragraph = (
            "Time series forecasting matters for many industrial systems and "
            "has seen a wave of new architectures in recent years. " * 3
        )
        result = check_uncited_paragraphs(paragraph, "introduction")
        assert not result.passed
        assert result.items_found

    def test_cited_paragraph_passes(self):
        paragraph = (
            "Time series forecasting matters for industrial systems [1]. "
            "Recent architectures improved accuracy substantially [2, 3]. "
            + "More supported discussion follows here with detail. " * 5
            + "These trends motivate our design [4]."
        )
        assert check_uncited_paragraphs(paragraph, "introduction").passed

    def test_latex_cite_counts_as_citation(self):
        paragraph = (
            "Forecasting underpins planning~\\cite{box1970}. "
            + "Extended discussion of the field and its methods. " * 6
        )
        assert check_uncited_paragraphs(paragraph, "related_work").passed

    def test_not_applied_to_method(self):
        long_uncited = "We define the gating function and its properties. " * 8
        assert check_uncited_paragraphs(long_uncited, "method").passed

    def test_latex_blocks_ignored(self):
        table = "\\begin{table}\n" + "row & row \\\\ " * 30 + "\n\\end{table}"
        assert check_uncited_paragraphs(table, "introduction").passed


class TestNumberConsistency:
    def test_flags_number_repeated_three_times(self):
        content = (
            "Our method achieves 3.1% improvement. The 3.1% gain holds across "
            "datasets. To summarize, we improve accuracy by 3.1%."
        )
        result = check_number_consistency(content)
        assert not result.passed
        assert any("3.1%" in item for item in result.items_found)

    def test_two_mentions_allowed(self):
        content = "We reach 0.371 MSE. The final 0.371 MSE beats the baseline."
        assert check_number_consistency(content).passed

    def test_bare_integers_ignored(self):
        content = "In 2026 we ran 3 seeds on 3 datasets over 3 weeks with 3 GPUs."
        assert check_number_consistency(content).passed


class TestParagraphDevelopment:
    def test_flags_thin_paragraph(self):
        content = (
            "Our gating mechanism substantially improves forecasting accuracy "
            "across all evaluated benchmarks, baselines, and deployment regimes "
            "without any additional tuning cost.\n\n"
            "A second, properly developed paragraph follows. It states a claim. "
            "It supports the claim with evidence. It analyzes what the evidence "
            "means. It transitions onward."
        )
        result = check_paragraph_development(content, "method")
        assert not result.passed
        assert any("gating mechanism" in item for item in result.items_found)

    def test_developed_paragraphs_pass(self):
        para = (
            "The claim comes first. Evidence supports it with a number. The "
            "analysis explains why it matters. A transition leads onward."
        )
        content = "\n\n".join(
            [para, para + " One more sentence here.", para + " Extra detail. And more."]
        )
        assert check_paragraph_development(content, "method").passed

    def test_uniform_rhythm_flagged(self):
        para = "One sentence here. Two sentences here. Three sentences here."
        content = "\n\n".join([para] * 5)
        result = check_paragraph_development(content, "discussion")
        assert not result.passed
        assert any("near-uniform" in item for item in result.items_found)

    def test_abstract_exempt(self):
        assert check_paragraph_development("Short claim only.", "abstract").passed


class TestRunAllChecks:
    def test_returns_all_checks(self):
        content = " ".join(["word"] * 900)
        results = run_all_checks(content, "introduction")
        check_names = {r.check_name for r in results}
        assert "word_count" in check_names
        assert "ai_boilerplate" in check_names
        assert "weasel_words" in check_names
        assert "repetition" in check_names
        assert "section_structure" in check_names
        assert "uncited_paragraphs" in check_names
        assert "number_consistency" in check_names
        assert "paragraph_development" in check_names
        assert "structural_verbosity" in check_names
        assert "table_text_agreement" in check_names
        assert len(results) == 14


# -- LaTeX Compiler -----------------------------------------------------------


class TestLatexEscape:
    def test_special_chars(self):
        assert _escape_latex("50% accuracy") == r"50\% accuracy"
        assert _escape_latex("A & B") == r"A \& B"
        assert _escape_latex("$100") == r"\$100"


class TestUnicodeFix:
    def test_dashes(self):
        assert _fix_unicode("\u2013") == "--"
        assert _fix_unicode("\u2014") == "---"

    def test_quotes(self):
        assert _fix_unicode("\u201c") == "``"
        assert _fix_unicode("\u201d") == "''"

    def test_greek(self):
        assert _fix_unicode("\u03b1") == r"$\alpha$"

    def test_math(self):
        assert _fix_unicode("\u2264") == r"$\leq$"
        assert _fix_unicode("\u00d7") == r"$\times$"

    def test_latin_extended_that_t1_latin_modern_drops(self):
        assert _fix_unicode("Y\u0131ld\u0131r\u0131m") == r"Y\i{}ld\i{}r\i{}m"
        assert (
            _fix_unicode("\u015f\u011f\u015e\u0142\u0141\u0161")
            == r"\c{s}\u{g}\c{S}\l{}\L{}\v{s}"
        )

    def test_bibliography_escape_covers_the_same_glyphs(self):
        escaped = _bibtex_escape("Y\u0131ld\u0131r\u0131m \u2013 \u201cPancake\u201d")
        assert (
            r"\i{}" in escaped
            and "--" in escaped
            and "``" in escaped
            and "''" in escaped
        )
        assert "\u0131" not in escaped and "\u2013" not in escaped


class TestSectionSortKey:
    def test_known_sections(self):
        assert _section_sort_key("introduction") < _section_sort_key("method")
        assert _section_sort_key("method") < _section_sort_key("experiments")
        assert _section_sort_key("experiments") < _section_sort_key("conclusion")

    def test_unknown_sections(self):
        assert _section_sort_key("custom_thing") == 999


class TestAssembleLatex:
    def test_basic_assembly(self):
        tex, bib = assemble_latex(
            title="Test Paper",
            authors=["Alice", "Bob"],
            abstract="This is a test abstract.",
            sections={
                "introduction": "This is the intro.",
                "method": "This is the method.",
                "conclusion": "This concludes.",
            },
        )
        assert r"\title{Test Paper}" in tex
        assert r"Alice \and Bob" in tex
        assert r"\begin{abstract}" in tex
        assert r"\section{Introduction}" in tex
        assert r"\section{Method}" in tex
        assert r"\section{Conclusion}" in tex
        # Check ordering: intro before method before conclusion
        intro_pos = tex.index("Introduction")
        method_pos = tex.index("Method")
        conclusion_pos = tex.index("Conclusion")
        assert intro_pos < method_pos < conclusion_pos

    def test_empty_sections(self):
        tex, bib = assemble_latex(
            title="Empty",
            authors=[],
            abstract="",
            sections={},
        )
        assert r"\title{Empty}" in tex
        # An empty author list yields the mandated placeholder byline (three
        # authors, two departments, third corresponding), not "Anonymous".
        assert "Anonymous" not in tex
        assert "Author 1" in tex and "Author 3" in tex
        assert tex.count("Department") == 2
        assert "Corresponding author" in tex

    def test_bibliography(self):
        bib_entries = [
            "@article{test2024, title={Test}, author={Smith}, year={2024}}",
        ]
        tex, bib = assemble_latex(
            title="T",
            authors=[],
            abstract="",
            sections={},
            bibliography_entries=bib_entries,
        )
        assert "@article{test2024" in bib

    def test_template_selection(self):
        for tmpl_name in TEMPLATES:
            tex, _ = assemble_latex(
                title="T",
                authors=["A"],
                abstract="A",
                sections={},
                template=tmpl_name,
            )
            assert r"\title{T}" in tex or r"\icmltitle{T}" in tex

    def test_template_fingerprint_changes_with_template_policy(self):
        original = TEMPLATES["aaai"]
        try:
            baseline = template_fingerprint("aaai")
            TEMPLATES["aaai"] = original.replace(r"\emergencystretch=2em", "")
            assert template_fingerprint("aaai") != baseline
        finally:
            TEMPLATES["aaai"] = original

    def test_default_and_arxiv_templates_are_single_column(self):
        # Default English manuscript layout is single-column; two-column is
        # reserved for explicit venue templates (aaai/icml). See
        # skills/rh-paper-production/SKILL.md "Figures And Manuscript".
        for tmpl_name in ("generic", "arxiv"):
            assert "twocolumn" not in TEMPLATES[tmpl_name]
        default_tex, _ = assemble_latex(
            title="T", authors=["A"], abstract="A", sections={}
        )
        assert "twocolumn" not in default_tex

    def test_aaai_template_is_self_contained_two_column_draft(self):
        tex, _ = assemble_latex(
            title="AAAI Draft",
            authors=[],
            abstract="Abstract.",
            sections={"method": r"\begin{remark}Contract holds.\end{remark}"},
            template="aaai",
        )
        assert r"\twocolumn[" in tex
        assert r"\newtheorem{remark}{Remark}" in tex
        assert r"\bibliographystyle{plainnat}" in tex
        assert r"\emergencystretch=2em" in tex
        assert r"\usepackage{algorithm}" not in tex

    def test_algorithm_packages_are_loaded_only_when_used(self):
        plain_tex, _ = assemble_latex(
            title="Plain Draft",
            authors=[],
            abstract="",
            sections={"method": "No algorithm environment here."},
            template="aaai",
        )
        algorithm_tex, _ = assemble_latex(
            title="Algorithm Draft",
            authors=[],
            abstract="",
            sections={
                "method": (
                    r"\begin{algorithm}"
                    "\n"
                    r"\begin{algorithmic}[1]"
                    "\n"
                    r"\State Check gates."
                    "\n"
                    r"\end{algorithmic}"
                    "\n"
                    r"\end{algorithm}"
                )
            },
            template="aaai",
        )

        assert r"\usepackage{algorithm}" not in plain_tex
        assert r"\usepackage{algpseudocode}" not in plain_tex
        assert r"\usepackage{algorithm}" in algorithm_tex
        assert r"\usepackage{algpseudocode}" in algorithm_tex

    def test_tabularx_packages_are_loaded_only_when_used(self):
        plain_tex, _ = assemble_latex(
            title="Plain Draft",
            authors=[],
            abstract="",
            sections={"results": "No table environment here."},
            template="aaai",
        )
        table_tex, _ = assemble_latex(
            title="Table Draft",
            authors=[],
            abstract="",
            sections={
                "results": (
                    r"\begin{tabularx}{\textwidth}{@{}lY@{}}"
                    "\n"
                    r"\toprule"
                    "\n"
                    r"Task & Diagnostic focus \\"
                    "\n"
                    r"\bottomrule"
                    "\n"
                    r"\end{tabularx}"
                )
            },
            template="aaai",
        )

        assert r"\usepackage{tabularx}" not in plain_tex
        assert r"\newcolumntype{Y}" not in plain_tex
        assert r"\usepackage{array}" in table_tex
        assert r"\usepackage{tabularx}" in table_tex
        assert r"\newcolumntype{Y}{>{\raggedright\arraybackslash}X}" in table_tex

    def test_aaai_textwidth_tabularx_tables_are_promoted_to_wide_floats(self):
        tex, _ = assemble_latex(
            title="Wide Table Draft",
            authors=[],
            abstract="",
            sections={
                "results": (
                    r"\begin{table}[t]"
                    "\n"
                    r"\centering"
                    "\n"
                    r"\begin{tabularx}{\textwidth}{@{}lY@{}}"
                    "\n"
                    r"\toprule"
                    "\n"
                    r"Task & Diagnostic focus \\"
                    "\n"
                    r"\bottomrule"
                    "\n"
                    r"\end{tabularx}"
                    "\n"
                    r"\end{table}"
                )
            },
            template="aaai",
        )

        assert r"\begin{table*}[t]" in tex
        assert r"\end{table*}" in tex
        assert r"\begin{table}[t]" not in tex

    def test_markdown_inline_code_is_latex_safe(self):
        tex, _ = assemble_latex(
            title="T",
            authors=[],
            abstract="",
            sections={
                "discussion": "The `gap_detect` and `paper_acquire` calls timed out."
            },
        )
        assert r"\texttt{gap\_detect}" in tex
        assert r"\texttt{paper\_acquire}" in tex
        assert "`gap_detect`" not in tex

    def test_markdown_headings_are_normalized_inside_sections(self):
        tex, _ = assemble_latex(
            title="T",
            authors=[],
            abstract="",
            sections={"results": "## 4 Results\n\n### 4.1 Setup\n\nText."},
        )
        assert "## 4 Results" not in tex
        assert r"\section{Results}" in tex
        assert r"\subsubsection{4.1 Setup}" in tex

    def test_python_escaped_text_commands_are_restored(self):
        tex, _ = assemble_latex(
            title="T",
            authors=[],
            abstract="",
            sections={
                "results": (
                    "\textbf{Lost bold backslash.} "
                    "\texttt{algorithmic[1]} should stay monospace."
                )
            },
        )

        assert r"\textbf{Lost bold backslash.}" in tex
        assert r"\texttt{algorithmic[1]}" in tex
        assert "\textbf" not in tex

    def test_precompile_validation_flags_python_escaped_text_commands(self):
        tex = (
            r"\begin{document}"
            "\n"
            "\textbf{Lost bold backslash.}"
            "\n"
            r"\end{document}"
        )

        findings = _validate_before_compile(tex, "")

        assert any(
            finding.level == "error" and finding.category == "malformed_latex_command"
            for finding in findings
        )

    def test_unicode_in_content(self):
        tex, _ = assemble_latex(
            title="Test",
            authors=[],
            abstract="Performance \u2264 baseline",
            sections={"results": "Accuracy \u00d7 100"},
        )
        assert r"$\leq$" in tex
        assert r"$\times$" in tex


class TestPublicationCitationNormalization:
    def test_numbered_citations_do_not_rewrite_latex_optional_args(self):
        from research_harness.primitives.writing_impls import (
            _normalize_numbered_citations_to_natbib,
        )

        text = (
            r"\begin{algorithmic}[1]"
            "\n"
            r"\State Evaluate gate."
            "\n"
            "Prior systems [1, 2--3] establish the baseline."
        )

        normalized = _normalize_numbered_citations_to_natbib(text)

        assert r"\begin{algorithmic}[1]" in normalized
        assert r"\citep{ref1,ref2,ref3}" in normalized

    def test_numbered_citations_do_not_rewrite_markdown_list_labels(self):
        from research_harness.primitives.writing_impls import (
            _normalize_numbered_citations_to_natbib,
        )

        text = "[1] Keep this as a list label.\nPrior systems [4] establish scope."

        normalized = _normalize_numbered_citations_to_natbib(text)

        assert "[1] Keep this as a list label." in normalized
        assert r"\citep{ref4}" in normalized

    def test_a_bracket_holding_a_zero_is_prose_not_a_citation(self):
        """A0114's section_2 was refused for citing ref0: the normalizer read the
        interval [0, 1] as a citation list, invented a key and dropped the interval."""
        from research_harness.primitives.writing_impls import (
            _normalize_numbered_citations_to_natbib,
        )

        text = "Scores lie in [0, 1] and prior systems [4] establish scope."

        normalized = _normalize_numbered_citations_to_natbib(text)

        assert "[0, 1]" in normalized and "ref0" not in normalized
        assert r"\citep{ref4}" in normalized


class TestPublicationBibliographyEvidence:
    def test_bibliography_evidence_fails_on_unresolved_citations(self, tmp_path):
        from research_harness.primitives.writing_impls import (
            _bibliography_style_evidence,
        )

        tex_path = tmp_path / "paper.tex"
        tex_path.write_text(
            r"\citep{ref1}"
            "\n"
            r"\bibliographystyle{plainnat}"
            "\n"
            r"\bibliography{references}",
            encoding="utf-8",
        )

        evidence = _bibliography_style_evidence(
            template="aaai",
            bibliography_entries=["@misc{ref1, title={T}}"],
            tex_path=str(tex_path),
            warnings=["Package natbib Warning: Citation `ref1' undefined."],
            errors=[],
            target_profile="AAAI-style",
        )

        assert evidence["passed"] is False
        assert evidence["undefined_citation_warnings"] == 1

    def test_bibliography_evidence_fails_on_compile_errors(self, tmp_path):
        from research_harness.primitives.writing_impls import (
            _bibliography_style_evidence,
        )

        tex_path = tmp_path / "paper.tex"
        tex_path.write_text(
            r"\citep{ref1}"
            "\n"
            r"\bibliographystyle{plainnat}"
            "\n"
            r"\bibliography{references}",
            encoding="utf-8",
        )

        evidence = _bibliography_style_evidence(
            template="aaai",
            bibliography_entries=["@misc{ref1, title={T}}"],
            tex_path=str(tex_path),
            warnings=[],
            errors=["! LaTeX Error: missing item"],
            target_profile="AAAI-style",
        )

        assert evidence["passed"] is False
        assert evidence["compile_errors"] == 1


class TestPublicationCitationIntegrityEvidence:
    def test_citation_integrity_evidence_matches_tex_keys_to_bibtex(self, tmp_path):
        from research_harness.primitives.writing_impls import (
            _citation_integrity_evidence,
        )

        tex_path = tmp_path / "paper.tex"
        tex_path.write_text(
            r"\citep{ref1,ref2}" "\n" r"\citet{ref3}",
            encoding="utf-8",
        )

        evidence = _citation_integrity_evidence(
            bibliography_entries=[
                "@misc{ref1, title={A}}",
                "@misc{ref2, title={B}}",
                "@misc{ref3, title={C}}",
            ],
            tex_path=str(tex_path),
            warnings=[],
            errors=[],
        )

        assert evidence["passed"] is True
        assert evidence["citation_key_count"] == 3
        assert evidence["bib_entry_count"] == 3
        assert evidence["missing_bib_keys"] == []

    def test_citation_integrity_evidence_fails_on_missing_bib_key(self, tmp_path):
        from research_harness.primitives.writing_impls import (
            _citation_integrity_evidence,
        )

        tex_path = tmp_path / "paper.tex"
        tex_path.write_text(r"\citep{ref1,ref2}", encoding="utf-8")

        evidence = _citation_integrity_evidence(
            bibliography_entries=["@misc{ref1, title={A}}"],
            tex_path=str(tex_path),
            warnings=[],
            errors=[],
        )

        assert evidence["passed"] is False
        assert evidence["missing_bib_keys"] == ["ref2"]


# -- Writing Primitives (integration) -----------------------------------------


class TestWritingPrimitives:
    def test_outline_generate(self):
        from research_harness.primitives.writing_impls import outline_generate

        result = outline_generate(topic_id=1, project_id=1)
        assert len(result.sections) == 7
        assert result.total_target_words > 0
        assert result.sections[0].section == "introduction"

    def test_section_review_clean(self):
        from research_harness.primitives.writing_impls import section_review

        content = " ".join(["word"] * 900)
        result = section_review(section="introduction", content=content)
        assert len(result.deterministic_checks) == 14
        assert len(result.dimensions) == 13

    def test_section_review_fails_on_boilerplate(self):
        from research_harness.primitives.writing_impls import section_review

        boilerplate = (
            "In this paper, we propose a novel approach. The proposed method "
            "achieves state-of-the-art results. It is worth noting that our "
            "groundbreaking paradigm shift leveraging the power of transformers "
            "paves the way for future work. " * 100
        )
        result = section_review(section="introduction", content=boilerplate)
        assert result.needs_revision
        boilerplate_check = [
            c for c in result.deterministic_checks if c.check_name == "ai_boilerplate"
        ][0]
        assert not boilerplate_check.passed

    def test_section_revise_stub(self):
        from research_harness.primitives.writing_impls import section_revise

        result = section_revise(
            section="introduction",
            content="Original content.",
            review_feedback="Improve clarity.",
        )
        assert result.section == "introduction"
        assert result.word_count > 0

    def test_latex_compile_basic(self, tmp_path):
        from research_harness.primitives.writing_impls import latex_compile

        _result = latex_compile(
            topic_id=1,
            output_dir=str(tmp_path / "output"),
            template="generic",
            sections={
                "introduction": "This is the introduction.",
                "method": "This is the method.",
                "conclusion": "This is the conclusion.",
            },
            title="Test Paper",
            authors=["Alice"],
            abstract="Test abstract.",
        )
        # Even if pdflatex is not installed, the tex file should be written
        tex_file = tmp_path / "output" / "paper.tex"
        assert tex_file.exists()
        tex_content = tex_file.read_text()
        assert r"\title{Test Paper}" in tex_content
        assert r"\section{Introduction}" in tex_content

    def test_latex_compile_with_bib(self, tmp_path):
        from research_harness.primitives.writing_impls import latex_compile

        _result = latex_compile(
            topic_id=1,
            output_dir=str(tmp_path / "output"),
            sections={"introduction": "See \\cite{test2024}."},
            title="T",
            bibliography_entries=[
                "@article{test2024, title={Test}, author={Smith}, year={2024}}"
            ],
        )
        bib_file = tmp_path / "output" / "references.bib"
        assert bib_file.exists()
        assert "@article{test2024" in bib_file.read_text()


# -- Constants sanity checks ---------------------------------------------------


class TestConstants:
    def test_review_dimensions_count(self):
        assert len(REVIEW_DIMENSIONS) == 13

    def test_ai_boilerplate_count(self):
        # Two-layer governance (2026-07 writing upgrade): the union of true
        # cliches and capped register phrases replaces the old flat 75-list.
        assert len(AI_BOILERPLATE_PHRASES) >= 70

    def test_weasel_words_count(self):
        # Deliberately smaller since the upgrade: legitimate scientific hedges
        # (approximately, likely, may, tends to, ...) are no longer flagged.
        assert len(WEASEL_WORDS) >= 15

    def test_section_targets_present(self):
        for section in ["abstract", "introduction", "conclusion"]:
            assert section in SECTION_WORD_TARGETS

    def test_templates_present(self):
        for tmpl in ["neurips", "icml", "iclr", "acl", "generic"]:
            assert tmpl in TEMPLATES


# -- Pre-compilation Validation Gate -------------------------------------------


class TestValidateBeforeCompile:
    """Tests for _validate_before_compile in latex_compiler."""

    def setup_method(self):
        from research_harness.execution.latex_compiler import _validate_before_compile

        self._validate = _validate_before_compile

    def test_clean_document_passes(self):
        tex = r"""\documentclass{article}
\begin{document}
This is clean text with \cite{ref1}.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [f for f in findings if f.level == "error"]
        assert len(errors) == 0

    def test_missing_cite_key_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
See \cite{ref1} and \cite{ref_missing}.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [
            f for f in findings if f.level == "error" and f.category == "cite_missing"
        ]
        assert len(errors) == 1
        assert "ref_missing" in errors[0].message

    def test_multiple_cite_keys_in_one_cite(self):
        tex = r"""\documentclass{article}
\begin{document}
See \cite{ref1, ref2, ref3}.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}\n@article{ref2, title={T2}, author={B}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [
            f for f in findings if f.level == "error" and f.category == "cite_missing"
        ]
        assert len(errors) == 1
        assert "ref3" in errors[0].message

    def test_placeholder_todo_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
Results show TODO improvement.
\end{document}"""
        findings = self._validate(tex, "")
        warnings = [f for f in findings if f.category == "placeholder"]
        assert len(warnings) >= 1

    def test_placeholder_x_percent_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
We achieve X\% improvement over baselines.
\end{document}"""
        findings = self._validate(tex, "")
        warnings = [f for f in findings if f.category == "placeholder"]
        assert len(warnings) >= 1

    def test_real_percentage_not_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
We achieve 4.5\% improvement over baselines.
\end{document}"""
        findings = self._validate(tex, "")
        placeholders = [f for f in findings if f.category == "placeholder"]
        assert len(placeholders) == 0

    def test_unmatched_begin_end(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{table}
content
\end{figure}
\end{document}"""
        findings = self._validate(tex, "")
        errors = [f for f in findings if f.category == "env_mismatch"]
        assert len(errors) >= 1

    def test_unclosed_environment(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{itemize}
\item one
\end{document}"""
        findings = self._validate(tex, "")
        errors = [f for f in findings if f.category == "env_mismatch"]
        assert len(errors) >= 1
        assert "itemize" in errors[0].message

    def test_comments_ignored(self):
        tex = r"""\documentclass{article}
\begin{document}
% TODO this is a comment
Real content here.
\end{document}"""
        findings = self._validate(tex, "")
        placeholders = [f for f in findings if f.category == "placeholder"]
        assert len(placeholders) == 0

    def test_outside_document_not_scanned_for_placeholders(self):
        tex = r"""\documentclass{article}
% TODO preamble comment
\begin{document}
Clean content.
\end{document}"""
        findings = self._validate(tex, "")
        placeholders = [f for f in findings if f.category == "placeholder"]
        assert len(placeholders) == 0

    def test_citep_and_citet_checked(self):
        tex = r"""\documentclass{article}
\begin{document}
\citet{ref1} show that \citep{ref_bad} agrees.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [
            f for f in findings if f.level == "error" and f.category == "cite_missing"
        ]
        assert len(errors) == 1
        assert "ref_bad" in errors[0].message


# -- Post-draft citation audit -------------------------------------------------


class TestAuditDraftCitations:
    """Tests for _audit_draft_citations in llm_primitives."""

    def setup_method(self):
        from research_harness.execution.llm_primitives import _audit_draft_citations

        self._audit = _audit_draft_citations

    def test_valid_citations_no_warnings(self):
        content = "We follow [1] and extend [3] using techniques from [2]."
        warnings = self._audit(content, evidence_count=5)
        assert len(warnings) == 0

    def test_out_of_range_flagged(self):
        content = "Prior work [1] shows that [32] outperforms [5]."
        warnings = self._audit(content, evidence_count=10)
        assert len(warnings) == 1
        assert "[32]" in warnings[0]

    def test_zero_index_flagged(self):
        content = "See [0] for details."
        warnings = self._audit(content, evidence_count=5)
        assert len(warnings) == 1

    def test_empty_content_no_crash(self):
        assert self._audit("", evidence_count=10) == []

    def test_zero_evidence_count_no_audit(self):
        assert self._audit("[99] is cited.", evidence_count=0) == []


# -- Writing lesson helpers ----------------------------------------------------


class TestWritingLessonHelpers:
    """Tests for _load_writing_lessons and _record_writing_lessons_from_draft."""

    def test_load_writing_lessons_returns_empty_without_db(self):
        from research_harness.execution.llm_primitives import _load_writing_lessons

        result = _load_writing_lessons(None, topic_id=1)
        assert result == ""

    def test_record_writing_lessons_no_crash_without_db(self):
        from research_harness.execution.llm_primitives import (
            _record_writing_lessons_from_draft,
        )

        _record_writing_lessons_from_draft(
            None,
            topic_id=1,
            section="intro",
            content="test",
            audit_warnings=[],
            target_words=0,
        )

    def test_record_with_audit_warnings_no_crash_without_db(self):
        from research_harness.execution.llm_primitives import (
            _record_writing_lessons_from_draft,
        )

        _record_writing_lessons_from_draft(
            None,
            topic_id=1,
            section="intro",
            content="test content",
            audit_warnings=["[99] out of range"],
            target_words=0,
        )


# -- Venue Writing Profiles (Sprint 4) -----------------------------------------


class TestVenueWritingProfiles:
    """Tests for venue writing profile persistence and cache."""

    @pytest.fixture
    def db(self, tmp_path):
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        return db

    def test_persist_and_load(self, db):
        from research_harness.execution.llm_primitives import (
            _persist_venue_profiles,
            _load_cached_venue_profiles,
            WritingPattern,
        )

        patterns = [
            WritingPattern(
                dimension="abstract_hook",
                pattern="empirical gap",
                example="",
                source_paper="",
            ),
            WritingPattern(
                dimension="exp_analysis",
                pattern="paired comparison",
                example="",
                source_paper="",
            ),
        ]
        _persist_venue_profiles(db, "NeurIPS", patterns, 5)

        cached = _load_cached_venue_profiles(db, "NeurIPS")
        assert cached is not None
        assert cached.venue == "NeurIPS"
        assert cached.exemplar_count == 5
        assert len(cached.patterns) == 2
        assert cached.model_used == "cache"

    def test_no_cache_for_unknown_venue(self, db):
        from research_harness.execution.llm_primitives import (
            _load_cached_venue_profiles,
        )

        assert _load_cached_venue_profiles(db, "UNKNOWN_VENUE") is None

    def test_upsert_overwrites(self, db):
        from research_harness.execution.llm_primitives import (
            _persist_venue_profiles,
            _load_cached_venue_profiles,
            WritingPattern,
        )

        p1 = [
            WritingPattern(dimension="hook", pattern="old", example="", source_paper="")
        ]
        _persist_venue_profiles(db, "KDD", p1, 3)

        p2 = [
            WritingPattern(dimension="hook", pattern="new", example="", source_paper="")
        ]
        _persist_venue_profiles(db, "KDD", p2, 8)

        cached = _load_cached_venue_profiles(db, "KDD")
        assert cached is not None
        assert cached.patterns[0].pattern == "new"
        assert cached.exemplar_count == 8

    def test_venue_guidance(self, db):
        from research_harness.execution.llm_primitives import (
            _persist_venue_profiles,
            WritingPattern,
        )
        from research_harness.evolution.topic.writing_skill import (
            WritingSkillAggregator,
        )

        patterns = [
            WritingPattern(
                dimension="abstract_hook",
                pattern="state gap then solve",
                example="",
                source_paper="",
            ),
        ]
        _persist_venue_profiles(db, "ICML", patterns, 4)

        agg = WritingSkillAggregator(db)
        guidance = agg.get_venue_guidance("ICML")
        assert "ICML" in guidance
        assert "abstract_hook" in guidance
        assert "state gap then solve" in guidance

    def test_venue_guidance_empty(self, db):
        from research_harness.evolution.topic.writing_skill import (
            WritingSkillAggregator,
        )

        agg = WritingSkillAggregator(db)
        assert agg.get_venue_guidance("NONEXISTENT") == ""


class TestOutlineGenerateContribGuard:
    """outline_generate must refuse to run with empty contributions to avoid hallucination."""

    @pytest.fixture
    def db(self, tmp_path):
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        return db

    def test_refuses_without_contributions(self, db):
        from research_harness.execution.llm_primitives import outline_generate

        with pytest.raises(ValueError, match="requires paper contributions"):
            outline_generate(db=db, topic_id=1, project_id=1, contributions="")

    def test_refuses_with_whitespace_only_contributions(self, db):
        from research_harness.execution.llm_primitives import outline_generate

        with pytest.raises(ValueError, match="requires paper contributions"):
            outline_generate(db=db, topic_id=1, project_id=1, contributions="   \n  ")


class TestStructuralVerbosity:
    """The failure this guards: a section reads fine sentence by sentence and
    is still a third longer than it needs to be, because the cost is in how the
    material is arranged rather than in padding phrases."""

    SEMICOLON_CHAIN = (
        "We contribute a diagnostic result showing that planted-defect corpora "
        "as currently built cannot certify an error level, demonstrated on our "
        "own corpus at a twenty-order-of-magnitude swing; an exact conditional "
        "test for a frozen round, free of nuisance parameters and carrying an "
        "anti-gaming property that rate-based audits lack; a hierarchical "
        "certificate whose three combination rules are forced by three distinct "
        "dependence regimes rather than by a nested data layout; and a "
        "validated substrate with a genuine negative control on which the "
        "certificate holds its level over seven thousand separate trials."
    )

    def test_flags_semicolon_chained_sentence(self):
        from research_harness._workflow.execution.writing_checks import (
            check_structural_verbosity,
        )

        r = check_structural_verbosity(self.SEMICOLON_CHAIN, "introduction")
        assert not r.passed
        assert "over 60 words" in r.details

    def test_directive_names_the_fix_not_a_cut(self):
        from research_harness._workflow.execution.writing_checks import (
            structural_revision_directives,
        )

        ds = structural_revision_directives(self.SEMICOLON_CHAIN, "introduction")
        assert ds, "a 100+ word semicolon chain must produce a directive"
        joined = " ".join(ds)
        assert "itemize" in joined or "separate sentences" in joined
        assert "not a cut" in joined

    def test_clean_prose_produces_no_directives(self):
        from research_harness._workflow.execution.writing_checks import (
            structural_revision_directives,
        )

        clean = (
            "The corpus is adversarially hardened. Each round is sealed under a "
            "manifest before any audit exists. An isolated auditor then reads it."
        )
        assert structural_revision_directives(clean, "method") == []


class TestRevisionDamage:
    """A revision that loses protected material must not be able to score
    better than leaving the section alone."""

    ORIGINAL = (
        "\\begin{theorem}[Exactness]\\label{thm:exact}\n"
        "Under randomized planting, recall reaches exactly 0.857.\n"
        "\\end{theorem}\n"
        "Prior work \\citep{popper2025,evaluator2026} controls error at 0.05.\n"
    )

    def test_substitution_is_caught_even_when_value_recurs(self):
        """A set comparison passes this; only counting catches it."""
        from research_harness._workflow.execution.writing_checks import revision_damage

        original = "Level 0.05 here, 0.05 there, and recall 0.857."
        substituted = original.replace("0.05", "0.10", 1)
        damage = revision_damage(original, substituted)
        assert damage, "one of two occurrences changed and went undetected"
        assert "0.05" in damage[0]

    def test_faithful_reshaping_is_accepted(self):
        from research_harness._workflow.execution.writing_checks import revision_damage

        reshaped = self.ORIGINAL.replace(
            "Under randomized planting, recall", "Under randomized planting. Recall"
        )
        assert revision_damage(self.ORIGINAL, reshaped) == []

    @pytest.mark.parametrize(
        "mutate,expected",
        [
            (lambda t: t.replace("\\label{thm:exact}", ""), "label"),
            (lambda t: t.replace("popper2025,evaluator2026", "popper2025"), "citation"),
            (lambda t: t.replace("0.857", "0.957"), "number"),
            (lambda t: t.replace("randomized ", ""), "qualifier"),
            (lambda t: t.split("\\end{theorem}")[-1], "theorem"),
        ],
        ids=[
            "dropped-label",
            "dropped-citation",
            "changed-number",
            "dropped-qualifier",
            "deleted-theorem",
        ],
    )
    def test_damage_is_caught(self, mutate, expected):
        from research_harness._workflow.execution.writing_checks import revision_damage

        damage = revision_damage(self.ORIGINAL, mutate(self.ORIGINAL))
        assert damage, f"{expected} damage went undetected"
        assert any(expected in d for d in damage)


class TestTableTextAgreement:
    """The v7.3 defect: a table reporting raw totals under a column called
    "tokens", and prose one paragraph later claiming the protocols were
    budget-matched to within 1.3%. Both true of different denominators; a
    reviewer who spots it discounts every other number in the paper."""

    TABLE = (
        "\\begin{tabular}{lrrrrr}\n"
        "Protocol & accusations/paper & recall & precision & cert. rate & tokens \\\\\n"
        "Rubric reviewer & 6.23 & 0.857 & 0.275 & 0.000 & 1.13M \\\\\n"
        "Evidence-bound (ours) & 1.89 & 0.814 & 0.864 & 0.486 & 2.40M \\\\\n"
        "\\end{tabular}\n"
        "It is budget-matched by construction---22,840 tokens per manuscript for our "
        "audit against 23,143 for the rubric reviewer, a 1.3\\% difference.\n"
    )

    def test_flags_total_column_under_per_unit_claim(self):
        from research_harness._workflow.execution.writing_checks import (
            check_table_text_agreement,
        )

        r = check_table_text_agreement(self.TABLE, "results")
        assert not r.passed
        assert "raw total" in r.details

    def test_relabelled_column_passes(self):
        from research_harness._workflow.execution.writing_checks import (
            check_table_text_agreement,
        )

        fixed = self.TABLE.replace("& tokens \\\\", "& tokens/paper \\\\")
        fixed = fixed.replace("1.13M", "23,143").replace("2.40M", "22,840")
        assert check_table_text_agreement(fixed, "results").passed

    def test_table_without_a_relation_claim_passes(self):
        from research_harness._workflow.execution.writing_checks import (
            check_table_text_agreement,
        )

        plain = (
            "\\begin{tabular}{lr} Protocol & recall \\\\ Ours & 0.814 \\\\ "
            "\\end{tabular}\nRecall is higher for the rubric reviewer.\n"
        )
        assert check_table_text_agreement(plain, "results").passed
