"""Style fingerprint, content-invariant gate, and deterministic destyle."""

from research_harness._workflow.execution.style_fingerprint import (
    DESTYLE_RHS_WORDS,
    content_invariant,
    destyle_deterministic,
    split_sentences,
    style_fingerprint,
    style_fingerprint_findings,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Every tell planted deliberately; see test names for which is which.
AI_TEXT = """
The proposed framework represents a significant advancement in temporal modeling for long sequences. Moreover, the architecture captures complex dependencies across multiple scales of temporal resolution today. Furthermore, the design enables the efficient processing of very long input sequences here. Moreover, the evaluation shows consistent improvements across all of the benchmark datasets used. In summary, the framework advances the state of temporal modeling considerably.

The proposed method is not just a minor improvement, but a fundamental rethinking of the problem. It offers accuracy, efficiency, and robustness. The pipeline — which builds on standard components — is simple, and the training — despite its scale — remains stable.

The proposed system relies on a design that scales because it uses attention which is sparse, although the cost, which grows with length, remains a concern that we address, because sparsity, which we exploit, reduces it while accuracy is kept although memory grows. In summary, the design is efficient.

The proposed pipeline processes each batch in a streaming fashion for efficiency and lower latency. Results are reported on three datasets with standard splits and shared preprocessing settings applied. Errors are computed against the held-out labels under the same protocol as prior work here. In summary, the pipeline is effective and matches the established evaluation practice of the field.
"""

HUMAN_TEXT = """
We study sparse attention. The cost of dense attention grows quadratically, which limits sequence length in practice; several approximations trade accuracy for speed. Our variant differs in one respect. It allocates budget per query rather than per layer, so heads that need context get it.

Experiments cover three datasets. On LRA the gap to dense attention is 0.4 points. Training is stable across seeds.
"""


def _axis(fp, name):
    return next(a for a in fp.axes if a.axis == name)


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestSplitSentences:
    def test_abbreviations_not_split(self):
        sents = split_sentences(
            "We follow prior work (e.g. Smith et al. 2020). It works."
        )
        assert len(sents) == 2
        assert "e.g." in sents[0]

    def test_empty(self):
        assert split_sentences("") == []


class TestFingerprint:
    def test_all_planted_tells_flagged(self):
        fp = style_fingerprint(AI_TEXT)
        flagged_axes = {f.axis for f in fp.flags}
        assert "connective_cadence" in flagged_axes  # Moreover -> Furthermore
        assert "negative_parallelism" in flagged_axes
        assert "clause_stacking" in flagged_axes
        assert "closer_habit" in flagged_axes
        assert "em_dash_per_1k" in flagged_axes  # two-dash sentence
        assert "opener_repetition" in flagged_axes  # "The proposed" x4

    def test_failed_axes_on_ai_text(self):
        fp = style_fingerprint(AI_TEXT)
        failed = {a.axis for a in fp.failed_axes}
        assert "consecutive_connective_openers" in failed
        assert "closer_habit" in failed
        assert "opener_repetition" in failed

    def test_human_text_mostly_clean(self):
        fp = style_fingerprint(HUMAN_TEXT)
        failed = {a.axis for a in fp.failed_axes}
        assert "consecutive_connective_openers" not in failed
        assert "negative_parallelism" not in failed
        assert "opener_repetition" not in failed
        assert "closer_habit" not in failed

    def test_rule_of_three_auto_passes_on_short_text(self):
        fp = style_fingerprint(AI_TEXT)  # "accuracy, efficiency, and robustness"
        axis = _axis(fp, "rule_of_three")
        assert axis.value > 0
        assert axis.passed  # under the 500-word floor, rate axes auto-pass
        assert not [f for f in fp.flags if f.axis == "rule_of_three"]

    def test_rule_of_three_gated_on_long_text(self):
        # r3: triad drumbeat is a real tell (contrastive d=+1.02) — over the
        # exemplar band on a full-length text it fails and flags each triad.
        filler = "The encoder maps every input frame onto a shared latent space for training. "
        triad = "The design is simple, fast, and robust in practice. "
        text = (filler * 8 + triad) * 8  # ~600 words, ~13 triads/1k
        fp = style_fingerprint(text)
        axis = _axis(fp, "rule_of_three")
        assert not axis.passed
        assert [f for f in fp.flags if f.axis == "rule_of_three"]

    def test_new_generation_side_axes_present(self):
        fp = style_fingerprint(AI_TEXT)
        for name in (
            "nominalization_per_1k",
            "hedge_per_1k",
            "subord_per_sent",
            "lexical_rotation",
        ):
            assert _axis(fp, name) is not None

    def test_empty_text(self):
        fp = style_fingerprint("")
        assert fp.axes == [] and fp.flags == []

    def test_findings_are_low_severity(self):
        findings = style_fingerprint_findings(AI_TEXT)
        assert findings
        assert all(f.severity == "low" for f in findings)
        assert all(f.angle == "style_fingerprint" for f in findings)
        assert not style_fingerprint_findings(HUMAN_TEXT) or all(
            f.severity == "low" for f in style_fingerprint_findings(HUMAN_TEXT)
        )


class TestLexicalRotation:
    def _rotating_text(self):
        # high-MATTR filler (mostly unique invented words) + a method/approach
        # rotation: dominant 'method' x6, runner-up 'approach' x4
        import itertools

        syll = ["".join(p) for p in itertools.product("bcdfglmnprst", "aeiou")]
        vocab = iter(a + b for a, b in itertools.product(syll, syll))
        sents = [
            "The " + " ".join(next(vocab) for _ in range(12)) + "." for _ in range(40)
        ]
        sents += ["The method performs well under condition %s." % c for c in "abcdef"]
        sents += ["The approach performs well under condition %s." % c for c in "ghij"]
        return " ".join(sents)

    def test_rotation_fails_axis_and_flags_minority_sentences(self):
        fp = style_fingerprint(self._rotating_text())
        axis = next(a for a in fp.axes if a.axis == "lexical_rotation")
        assert not axis.passed  # MATTR over the exemplar band
        flags = [f for f in fp.flags if f.axis == "lexical_rotation"]
        assert flags
        assert all(f.extra_allowed == ("method",) for f in flags)
        assert all("approach" in f.extra_deletable for f in flags)

    def test_repeating_dominant_term_is_not_rotation(self):
        # 'method' 30x with 'approach' 1x = term discipline, not rotation
        text = self._rotating_text().replace("approach", "method")
        fp = style_fingerprint(text)
        assert not [f for f in fp.flags if f.axis == "lexical_rotation"]


# ---------------------------------------------------------------------------
# Content-invariant gate
# ---------------------------------------------------------------------------

BEFORE = (
    "The model improves accuracy by 3.2% on CIFAR-10 \\cite{he2016resnet}, "
    "and it may generalize to other benchmarks."
)


class TestContentInvariant:
    def test_rejects_added_number(self):
        g = content_invariant(BEFORE, BEFORE.replace("3.2%", "3.2% (4.1% top-5)"))
        assert not g["passed"] and any("numbers" in i for i in g["issues"])

    def test_rejects_new_content_word(self):
        g = content_invariant(
            BEFORE, BEFORE.replace("The model", "The transformer model")
        )
        assert not g["passed"] and any(
            "outside the edit window" in i for i in g["issues"]
        )

    def test_rejects_citation_change(self):
        g = content_invariant(BEFORE, BEFORE.replace("he2016resnet", "he2015resnet"))
        assert not g["passed"] and any("citation" in i for i in g["issues"])

    def test_rejects_deleted_negation(self):
        before = "The method does not improve accuracy on small datasets."
        after = "The method does improve accuracy on small datasets."
        g = content_invariant(before, after)
        assert not g["passed"] and any("protected" in i for i in g["issues"])

    def test_rejects_deleted_hedge(self):
        g = content_invariant(BEFORE, BEFORE.replace("may generalize", "generalizes"))
        assert not g["passed"] and any("protected" in i for i in g["issues"])

    def test_rejects_growth(self):
        long_before = BEFORE * 3
        g = content_invariant(
            long_before,
            long_before
            + " "
            + BEFORE.replace("\\cite{he2016resnet}", "")
            .replace("3.2%", "")
            .replace("CIFAR-10", "benchmarks"),
        )
        assert not g["passed"] and any(
            "grew" in i or "sentence" in i for i in g["issues"]
        )

    def test_accepts_filler_deletion(self):
        before = "It is worth noting that the model improves accuracy by 3.2%."
        after = "The model improves accuracy by 3.2%."
        assert content_invariant(before, after)["passed"]

    def test_accepts_sentence_split(self):
        before = (
            "The model improves accuracy on CIFAR-10, and it also reduces "
            "training cost, and it may generalize to other benchmarks."
        )
        after = (
            "The model improves accuracy on CIFAR-10 and also reduces training "
            "cost. It may generalize to other benchmarks."
        )
        assert content_invariant(before, after)["passed"]

    def test_accepts_inflection_change(self):
        before = "The result, highlighting the role of scale, supports the claim."
        after = "The result highlights the role of scale and supports the claim."
        assert content_invariant(before, after)["passed"]

    def test_extra_allowed_admits_table_rhs(self):
        before = "We delve into the feature space."
        after = "We examine the feature space."
        assert not content_invariant(before, after)["passed"]
        assert content_invariant(before, after, extra_allowed=DESTYLE_RHS_WORDS)[
            "passed"
        ]

    def test_extras_admit_canonical_term_swap(self):
        # lexical_rotation surgery: the flag licenses framework -> method
        before = "We adopt the framework for sparse attention."
        after = "We adopt the method for sparse attention."
        assert not content_invariant(before, after)["passed"]
        assert content_invariant(
            before, after, extra_allowed=("method",), extra_deletable=("framework",)
        )["passed"]


# ---------------------------------------------------------------------------
# Deterministic destyle
# ---------------------------------------------------------------------------


class TestDestyleDeterministic:
    def test_substitution_and_deletion(self):
        r = destyle_deterministic(
            "It is worth noting that the model delves into the feature space."
        )
        assert r.text == "The model examines the feature space."
        assert r.gate["passed"] and len(r.changes) == 2

    def test_mixed_case_word_not_recapitalized(self):
        r = destyle_deterministic("It is worth noting that mRNA levels rose.")
        assert r.text == "mRNA levels rose."

    def test_mid_sentence_deletion(self):
        r = destyle_deterministic(
            "The gap is small, and it should be noted that variance is high."
        )
        assert r.text == "The gap is small, and variance is high."

    def test_capital_substitution(self):
        r = destyle_deterministic("In order to evaluate this, we run ablations.")
        assert r.text == "To evaluate this, we run ablations."

    def test_preserves_citations_and_numbers(self):
        src = (
            "We utilize the encoder of \\cite{vaswani2017} and improve BLEU by "
            "2.1 points in order to close the gap."
        )
        r = destyle_deterministic(src)
        assert "\\cite{vaswani2017}" in r.text and "2.1" in r.text
        assert "utilize" not in r.text and "in order to" not in r.text
        assert r.gate["passed"]

    def test_idempotent(self):
        once = destyle_deterministic(AI_TEXT)
        twice = destyle_deterministic(once.text)
        assert twice.text == once.text and twice.changes == []

    def test_clean_text_untouched(self):
        r = destyle_deterministic(HUMAN_TEXT)
        assert r.text == HUMAN_TEXT and r.changes == []


# ---------------------------------------------------------------------------
# Gated LLM surgery (manuscript_destyle with a fake LLM)
# ---------------------------------------------------------------------------

# three back-to-back connective openers: over the r3 band (max 1 consecutive)
DESTYLE_SRC = (
    "Results are strong on the main benchmark today. Moreover, the ablation "
    "confirms the effect across settings. Furthermore, the gain persists "
    "under the stricter protocol. Moreover, the trend holds across sizes."
)


class TestManuscriptDestyle:
    def _run(self, monkeypatch, responder):
        import research_harness.primitives.polish_impls as PI

        monkeypatch.setattr(
            PI, "_llm", lambda *a, **k: type("L", (), {"model": "fake"})()
        )
        monkeypatch.setattr(PI, "_chat", lambda llm, prompt: responder(prompt))
        return PI.manuscript_destyle(manuscript=DESTYLE_SRC)

    def test_valid_edit_applied(self, monkeypatch):
        def responder(prompt):
            assert "connective_cadence" in prompt
            return (
                '{"edits":[{"id":0,"after":"The gain persists under the '
                'stricter protocol."}]}'
            )

        out = self._run(monkeypatch, responder)
        assert "Furthermore" not in out["text"]
        assert any(a["axis"] == "connective_cadence" for a in out["applied"])
        assert out["vetoed"] == []

    def test_violating_edit_vetoed(self, monkeypatch):
        def responder(prompt):
            return (
                '{"edits":[{"id":0,"after":"The transformer gain persists '
                'under the stricter protocol."}]}'
            )

        out = self._run(monkeypatch, responder)
        assert out["text"] == DESTYLE_SRC  # unchanged
        assert (
            out["vetoed"] and "outside the edit window" in out["vetoed"][0]["issues"][0]
        )

    def test_llm_failure_returns_original(self, monkeypatch):
        out = self._run(monkeypatch, lambda p: "not json at all {{{")
        assert out["text"] == DESTYLE_SRC


class TestR1GateTightening:
    def test_rejects_unmarked_split(self):
        # detaching a relative clause rebinds it — the r0 failure mode
        before = "The cost remains a concern, which we address through sparsity."
        after = "The cost remains a concern. We address it through sparsity."
        g = content_invariant(before, after)
        assert not g["passed"] and any("unmarked clause" in i for i in g["issues"])

    def test_accepts_semicolon_split(self):
        before = "The cost grows with length; sparsity reduces it in practice."
        after = "The cost grows with length. Sparsity reduces it in practice."
        assert content_invariant(before, after)["passed"]

    def test_rejects_nonredundant_deletion(self):
        before = (
            "Requiring both outcomes to favor the intervention gives the result weight."
        )
        after = "Requiring both outcomes gives the result weight."
        g = content_invariant(before, after)
        assert not g["passed"] and any("content deleted" in i for i in g["issues"])

    def test_accepts_redundant_closer_deletion(self):
        before = (
            "The probe tests transport under domain shift. Transport under "
            "domain shift is what the probe tests."
        )
        after = "The probe tests transport under domain shift."
        assert content_invariant(before, after)["passed"]


class TestR2Anchoring:
    def test_rejects_adverb_scope_shift(self):
        before = "The model often fails on rare idioms in low-resource settings."
        after = "Often, the model fails on rare idioms in low-resource settings."
        g = content_invariant(before, after)
        assert not g["passed"] and any("scope shift" in i for i in g["issues"])

    def test_accepts_split_keeping_anchors(self):
        before = "The gate may reject edits; the loop only applies survivors."
        after = "The gate may reject edits. The loop only applies survivors."
        assert content_invariant(before, after)["passed"]
