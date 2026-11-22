#!/usr/bin/env python3
"""Audit DOCX prose for math-like expressions outside Word math objects."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


@dataclass
class Finding:
    paragraph_index: int
    severity: str
    rule: str
    match: str
    context: str


RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "high",
        "complexity_notation",
        re.compile(r"(?<![A-Za-z0-9_])(?:O|Θ|Ω)[(（][^)）]{1,80}[)）]"),
    ),
    (
        "high",
        "root_fraction_or_scaled_dot_product",
        re.compile(r"(?<![A-Za-z])(?:[A-Za-zΑ-Ωα-ω]{1,4}[A-Za-zΑ-Ωα-ω0-9]*)\s*/\s*√\s*[A-Za-zΑ-Ωα-ω0-9]+|√\s*[A-Za-zΑ-Ωα-ω0-9]+"),
    ),
    (
        "high",
        "transpose_like_product",
        re.compile(r"(?<![A-Za-z])(?:QK|KQ|X[TX]|Z[TZ]|H[TH])[TＴ](?![a-z])"),
    ),
    (
        "high",
        "dimension_or_real_space",
        re.compile(r"(?<![A-Za-z])(?:[A-Za-zΑ-Ωα-ω]{1,4})t?∈R[A-Za-z0-9×^{}]+"),
    ),
    (
        "high",
        "indexed_train_val_test_set",
        re.compile(r"I(?:train|val|test|_train|_val|_test)\([^)]*[)）]"),
    ),
    (
        "high",
        "function_call_math",
        re.compile(r"(?<![A-Za-z])(?:softmax|CrossAttn|RuleMoE|Embed|Norm|Concat|max|min|log|MSE)\s*\([^，。；\n]{1,120}\)"),
    ),
    (
        "high",
        "formal_operator_expression",
        re.compile(r"(?<![A-Za-z])(?:[A-Za-zΑ-Ωα-ω][A-Za-zΑ-Ωα-ω0-9_{}:+\-−]*\s*){1,5}[=<>≤≥∈∪∩→⊑]\s*[^，。；\n]{1,100}"),
    ),
    (
        "medium",
        "subscript_or_superscript_literal",
        re.compile(r"(?<![A-Za-z])(?:[A-Za-zΑ-Ωα-ω]{1,8})_(?:\{[^}]+}|[A-Za-z0-9]+)|(?<![A-Za-z])(?:[A-Za-zΑ-Ωα-ω]{1,8})\^(?:\{[^}]+}|[A-Za-z0-9]+)"),
    ),
    (
        "medium",
        "compact_index_window",
        re.compile(r"(?<![A-Za-z])(?:[xyzXYZ])(?:1:T|t[-−]L\+1:t|t\+h|i\+h)"),
    ),
    (
        "medium",
        "quantile_triplet",
        re.compile(r"P10/P50/P90"),
    ),
    (
        "low",
        "snake_case_identifier",
        re.compile(r"\b[a-z]+(?:_[a-z0-9]+){1,}\b"),
    ),
]

EXEMPT_RE = re.compile(
    r"HK-MO2018-HK|Macau2018-(?:global|mainland)|ERX-TDF|FSP-TDF|PatchTST|iTransformer|TimeMixer|ModernTCN|MSGNet|LayerNorm|dropout|pinball loss"
)
SNAKE_CASE_RE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+){1,}\b")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_outside_math(element: ET.Element, in_math: bool = False) -> str:
    now_math = in_math or element.tag.startswith(f"{{{M_NS}}}")
    chunks: list[str] = []
    if element.text and not now_math and element.tag == f"{{{W_NS}}}t":
        chunks.append(element.text)
    for child in list(element):
        chunks.append(text_outside_math(child, now_math))
        if child.tail and not now_math:
            chunks.append(child.tail)
    return "".join(chunks)


def paragraphs(document_xml: bytes) -> list[str]:
    root = ET.fromstring(document_xml)
    return [text_outside_math(p) for p in root.iter(f"{{{W_NS}}}p")]


def context_for(text: str, start: int, end: int, width: int = 80) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    return text[left:right]


def audit_docx(path: Path) -> list[Finding]:
    with zipfile.ZipFile(path) as zf:
        document_xml = zf.read("word/document.xml")
    findings: list[Finding] = []
    for idx, text in enumerate(paragraphs(document_xml)):
        if not text.strip():
            continue
        for severity, rule, regex in RULES:
            for match in regex.finditer(text):
                value = match.group(0)
                if EXEMPT_RE.search(value):
                    continue
                finding_severity = severity
                finding_rule = rule
                if rule == "formal_operator_expression" and SNAKE_CASE_RE.search(value):
                    finding_severity = "low"
                    finding_rule = "code_field_condition"
                findings.append(
                    Finding(
                        paragraph_index=idx,
                        severity=finding_severity,
                        rule=finding_rule,
                        match=value,
                        context=context_for(text, match.start(), match.end()),
                    )
                )
    return findings


def audit_text(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for severity, rule, regex in RULES:
        for match in regex.finditer(text):
            value = match.group(0)
            if EXEMPT_RE.search(value):
                continue
            finding_severity = severity
            finding_rule = rule
            if rule == "formal_operator_expression" and SNAKE_CASE_RE.search(value):
                finding_severity = "low"
                finding_rule = "code_field_condition"
            findings.append(
                Finding(
                    paragraph_index=0,
                    severity=finding_severity,
                    rule=finding_rule,
                    match=value,
                    context=context_for(text, match.start(), match.end()),
                )
            )
    return findings


def run_self_test() -> int:
    cases = [
        ("scaled dot product QKT/√d should be high", "注意力分数为QKT/√d。", True),
        ("dimension expression should be high", "设需求窗口Yt∈RL×1。", True),
        ("rolling split index should be high", "仅由Itrain(τ)估计。", True),
        ("rule example should be high", "month=Aug → search hotel high → demand rise", True),
        ("Big-O complexity should be high", "复杂度为O(d·Ntoken）。", True),
        ("dataset id should not be high", "HK-MO2018-HK is a dataset.", False),
        ("English words with ge/rt should not be high", "management and marketing are prose words.", False),
        ("audit key condition is low not high", "leakage_ok=True", False),
    ]
    failures: list[str] = []
    for label, text, expect_high in cases:
        findings = audit_text(text)
        has_high = any(item.severity == "high" for item in findings)
        if has_high != expect_high:
            failures.append(f"{label}: expected high={expect_high}, got {findings}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("docx_math_audit self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path, nargs="?")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--fail-on-high", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if args.docx is None:
        parser.error("docx is required unless --self-test is used")

    findings = audit_docx(args.docx)
    if args.format == "json":
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        if not findings:
            print("No likely unformalized math expressions found.")
        for finding in findings:
            print(
                f"[{finding.severity}] p{finding.paragraph_index} "
                f"{finding.rule}: {finding.match}\n  {finding.context}"
            )

    if args.fail_on_high and any(f.severity == "high" for f in findings):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
