"""Deterministic typography checks for compiled manuscripts.

Why this exists: ``latex_compiler`` treated "tectonic exited 0" as success, so a
manuscript could ship with tables overflowing the text block, hand-pinned
``p{3.0cm}`` columns, vertical rules, and letter paper at an A4 venue. Those are
the defects an editor sees first, and none of them were machine-checked.

The checks are intentionally source+log based (no PDF rasterisation): they read
the TeX source for construct-level smells and the compiler log for the boxes TeX
already measured for us.

Thresholds are deliberately loose. TeX reports an overfull box for a 0.5pt
overhang that nobody can see; ``OVERFULL_MAJOR_PT`` is the point where a reader
notices a table or line poking into the margin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# A box wider than the text block by this many points is visible on the page.
OVERFULL_MINOR_PT = 5.0
OVERFULL_MAJOR_PT = 20.0

# Captions longer than this read as a paragraph that escaped the body.
CAPTION_MAX_CHARS = 600

# Paper size expected per venue family. Venues absent from the map are not
# checked (their class file usually pins geometry itself).
VENUE_PAPER_SIZE: dict[str, str] = {
    "hssc": "a4",
    "springer_nature": "a4",
    "nature": "a4",
    "elsevier": "a4",
    "arxiv": "a4",
    "generic": "a4",
    "aaai": "letter",
    "neurips": "letter",
    "icml": "letter",
    "iclr": "letter",
    "acl": "letter",
}

# Tectonic prefixes the offending source line ("main.tex:403: Overfull ..."),
# which points at the box itself; the trailing "at lines 402--403" range starts
# at the top of the enclosing paragraph and is the weaker locator of the two.
_OVERFULL_RE = re.compile(
    r"(?:[\w./-]+\.tex:(?P<src>\d+):\s*)?"
    r"Overfull \\[hv]box \((?P<pts>[0-9.]+)pt too wide\)"
    r"(?:[^\n]*?at lines? (?P<start>\d+)(?:--(?P<end>\d+))?)?",
    re.I,
)
_TABULAR_RE = re.compile(r"\\begin\{tabular\}\s*(?:\[[^\]]*\])?\s*\{")
_FIXED_COL_RE = re.compile(r"[pmb]\{[0-9.]+\s*(?:cm|mm|in|pt)\}")
_CAPTION_RE = re.compile(r"\\caption\{", re.S)
_PAPER_A4_RE = re.compile(r"a4paper|\ba4\b", re.I)
_PAPER_LETTER_RE = re.compile(r"letterpaper", re.I)
# \documentclass{article} / \documentclass[11pt]{article} with no paper option.
_BARE_ARTICLE_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{article\}")


@dataclass
class TypographyFinding:
    """One machine-checkable layout defect."""

    check: str
    severity: str  # "major" | "minor"
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
        }


@dataclass
class TypographyReport:
    findings: list[TypographyFinding] = field(default_factory=list)

    @property
    def majors(self) -> list[TypographyFinding]:
        return [f for f in self.findings if f.severity == "major"]

    @property
    def ok(self) -> bool:
        return not self.majors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "major_count": len(self.majors),
            "findings": [f.to_dict() for f in self.findings],
        }


def _balanced_group(text: str, start: int) -> str:
    """Return the brace group starting at ``start`` (index of the opening brace)."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and text[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return text[start:]


def check_overfull_boxes(log_text: str) -> list[TypographyFinding]:
    """Findings for boxes TeX measured as sticking out of the text block."""
    seen: set[tuple[float, int | None]] = set()
    out: list[TypographyFinding] = []
    for m in _OVERFULL_RE.finditer(log_text or ""):
        pts = float(m.group("pts"))
        loc = m.group("src") or m.group("end") or m.group("start")
        line = int(loc) if loc else None
        if pts < OVERFULL_MINOR_PT or (pts, line) in seen:
            continue
        seen.add((pts, line))
        out.append(
            TypographyFinding(
                check="overfull_box",
                severity="major" if pts >= OVERFULL_MAJOR_PT else "minor",
                message=(
                    f"content overflows the text block by {pts:.1f}pt"
                    + (f" (line {line})" if line else "")
                    + "; use tabularx/X columns or shorten the cell rather than "
                    "pinning column widths"
                ),
                line=line,
            )
        )
    return out


def check_table_constructs(tex: str) -> list[TypographyFinding]:
    """Findings for table specs that cannot adapt to the text width."""
    out: list[TypographyFinding] = []
    for m in _TABULAR_RE.finditer(tex or ""):
        # The column spec itself contains braces (p{3cm}), so take the balanced
        # group rather than a lazy regex that stops at the first closing brace.
        spec = _balanced_group(tex, m.end() - 1)
        line = tex.count("\n", 0, m.start()) + 1
        fixed = _FIXED_COL_RE.findall(spec)
        if len(fixed) >= 2:
            out.append(
                TypographyFinding(
                    check="fixed_width_columns",
                    severity="major",
                    message=(
                        f"tabular spec pins {len(fixed)} column widths ({spec.strip()}); "
                        "hand-tuned widths overflow as soon as a cell grows — use "
                        "tabularx with X columns so the table tracks \\textwidth"
                    ),
                    line=line,
                )
            )
        if "|" in spec:
            out.append(
                TypographyFinding(
                    check="vertical_rules",
                    severity="minor",
                    message=(
                        "table uses vertical rules; booktabs style (toprule/midrule/"
                        "bottomrule, no verticals) is the norm at these venues"
                    ),
                    line=line,
                )
            )
    return out


def check_captions(tex: str) -> list[TypographyFinding]:
    """Findings for captions carrying body-length prose."""
    out: list[TypographyFinding] = []
    for m in _CAPTION_RE.finditer(tex or ""):
        body = _balanced_group(tex, m.end() - 1)
        if len(body) > CAPTION_MAX_CHARS:
            line = tex.count("\n", 0, m.start()) + 1
            out.append(
                TypographyFinding(
                    check="caption_length",
                    severity="minor",
                    message=(
                        f"caption runs {len(body)} characters (soft cap "
                        f"{CAPTION_MAX_CHARS}); move the argument into the body or a "
                        "table note and keep the caption to what the panel shows"
                    ),
                    line=line,
                )
            )
    return out


def check_paper_size(tex: str, venue_key: str | None) -> list[TypographyFinding]:
    """Findings when the preamble pins a paper size the venue does not use."""
    expected = VENUE_PAPER_SIZE.get((venue_key or "").strip().lower())
    if not expected:
        return []
    head = (tex or "")[:4000]
    actual = None
    if _PAPER_LETTER_RE.search(head):
        actual = "letter"
    elif _PAPER_A4_RE.search(head):
        actual = "a4"
    elif expected == "a4" and _BARE_ARTICLE_RE.search(head):
        # A bare \documentclass{article} with no paper option silently defaults
        # to US letter — the exact way three manuscripts shipped letter pages to
        # an A4 venue without any letterpaper string to grep for.
        return [
            TypographyFinding(
                check="paper_size",
                severity="major",
                message=(
                    f"no paper size declared, so the class defaults to US letter, "
                    f"but {venue_key} expects a4; add a4paper to \\documentclass or "
                    "the geometry options"
                ),
                line=1,
            )
        ]
    if actual and actual != expected:
        return [
            TypographyFinding(
                check="paper_size",
                severity="major",
                message=(
                    f"preamble sets {actual} paper but {venue_key} expects "
                    f"{expected}; submission systems reject or reflow mismatched pages"
                ),
                line=1,
            )
        ]
    return []


def check_typography(
    tex: str,
    log_text: str = "",
    venue_key: str | None = None,
) -> TypographyReport:
    """Run every typography check over one manuscript."""
    findings: list[TypographyFinding] = []
    findings.extend(check_overfull_boxes(log_text))
    findings.extend(check_table_constructs(tex))
    findings.extend(check_captions(tex))
    findings.extend(check_paper_size(tex, venue_key))
    findings.sort(key=lambda f: (f.severity != "major", f.line or 0))
    return TypographyReport(findings=findings)


def format_report(report: TypographyReport) -> str:
    """One line per finding, for logs and agent-facing summaries."""
    if not report.findings:
        return "typography: clean"
    lines = [
        f"typography: {len(report.majors)} major, "
        f"{len(report.findings) - len(report.majors)} minor"
    ]
    for f in report.findings:
        loc = f":{f.line}" if f.line else ""
        lines.append(f"  [{f.severity}] {f.check}{loc} — {f.message}")
    return "\n".join(lines)


def demo() -> None:
    """Self-check: each rule fires on a known-bad sample and stays quiet on a good one."""
    bad = r"""\documentclass[11pt]{article}
\usepackage[letterpaper,margin=1in]{geometry}
\begin{table}
\caption{%s}
\begin{tabular}{p{3.0cm}|p{4.0cm}|p{1.4cm}}
\toprule A & B & C \\ \bottomrule
\end{tabular}
\end{table}
""" % ("x" * 700)
    log = "warning: main.tex:42: Overfull \\hbox (93.3pt too wide) in paragraph at lines 42--43\n"
    rep = check_typography(bad, log, venue_key="hssc")
    checks = {f.check for f in rep.findings}
    assert "overfull_box" in checks, checks
    assert "fixed_width_columns" in checks, checks
    assert "vertical_rules" in checks, checks
    assert "caption_length" in checks, checks
    assert "paper_size" in checks, checks
    assert not rep.ok

    good = r"""\documentclass[11pt,a4paper]{article}
\begin{table}
\caption{Short caption.}
\begin{tabularx}{\textwidth}{lXr}
\toprule A & B & C \\ \bottomrule
\end{tabularx}
\end{table}
"""
    rep2 = check_typography(good, "", venue_key="hssc")
    assert rep2.ok, format_report(rep2)
    # A sub-threshold overfull is noise, not a finding.
    assert not check_overfull_boxes("Overfull \\hbox (1.2pt too wide) in paragraph")
    print("typography_checks demo OK")


if __name__ == "__main__":
    demo()
