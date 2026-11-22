"""LaTeX compiler — assemble and compile papers with conference templates.

Supports: NeurIPS, ICML, ICLR, ACL, EMNLP templates.
Features: BibTeX assembly from paper pool, pdflatex 3-pass, auto-fix
(escape special chars, missing packages, Unicode fallback).
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import re
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .typography_checks import check_typography

logger = logging.getLogger(__name__)


# -- Author field parsing -----------------------------------------------------


def parse_authors_field(raw: str | None) -> list[str]:
    """Parse the ``papers.authors`` DB field into a clean list of author names.

    The field appears in four formats across the pool:
    - ``'[]'`` or ``None`` or ``''`` — empty
    - ``'""'`` — empty (artifact from some ingest paths)
    - ``'["A", "B", ...]'`` — clean JSON array
    - ``'"[\\"A\\", \\"B\\", ...]"'`` — JSON-string-wrapped JSON array
    - ``'A; B; C'`` — legacy semicolon-separated
    """
    if not raw or raw in ("[]", '""', "null", '""'):
        return []

    text = raw.strip()

    # Unwrap outer JSON string quotes: '"[...]"' → '[...]'
    if text.startswith('"') and text.endswith('"'):
        try:
            text = _json.loads(text)
            if isinstance(text, str):
                text = text.strip()
        except (ValueError, TypeError):
            pass

    # Try JSON array
    if isinstance(text, str) and text.startswith("["):
        try:
            parsed = _json.loads(text)
            if isinstance(parsed, list):
                return [str(a).strip() for a in parsed if str(a).strip()]
        except (ValueError, TypeError):
            pass

    # Semicolon-separated fallback
    if isinstance(text, str) and ";" in text:
        return [a.strip() for a in text.split(";") if a.strip()]

    # Single author
    if isinstance(text, str) and text.strip():
        return [text.strip()]

    return []


def authors_to_bibtex(raw: str | None) -> str:
    """Convert DB authors field to BibTeX ``author`` value (``A and B and C``)."""
    names = parse_authors_field(raw)
    # ponytail: T1 fontenc has no ogonek or fullwidth punctuation; a bibliography
    # entry carrying them fails the compile. ISSUE-figure-package-not-wired-2026-09-30.
    return (" and ".join(names) if names else "Anonymous").translate(
        str.maketrans("ąś：", "as:")
    )


# -- Conference templates ------------------------------------------------------

TEMPLATES: dict[str, str] = {
    "neurips": r"""\documentclass{article}
\usepackage[preprint]{neurips_2024}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{nicefrac}
\usepackage{microtype}
\usepackage{graphicx}
%(extra_packages)s
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
    "icml": r"""\documentclass[accepted]{icml2024}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
%(extra_packages)s
\usepackage{natbib}

\icmltitlerunning{%(title)s}

\begin{document}
\twocolumn[
\icmltitle{%(title)s}
\icmlsetsymbol{equal}{*}
\begin{icmlauthorlist}
%(icml_authors)s
\end{icmlauthorlist}
]

%(abstract_block)s

%(body)s

\bibliography{references}
\bibliographystyle{icml2024}

\end{document}
""",
    "iclr": r"""\documentclass{article}
\usepackage{iclr2025_conference}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
%(extra_packages)s
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliography{references}
\bibliographystyle{iclrnatbib}

\end{document}
""",
    "acl": r"""\documentclass[11pt]{article}
\usepackage{acl}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
%(extra_packages)s
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliography{references}
\bibliographystyle{acl_natbib}

\end{document}
""",
    # Generic fallback — works without any special .sty files
    "generic": r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1in]{geometry}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}
\usepackage{graphicx}
%(extra_packages)s
\usepackage{natbib}
\newtheorem{remark}{Remark}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
    # Self-contained AAAI-style draft template. This deliberately avoids the
    # official aaai*.sty dependency so RH can compile review PDFs in clean
    # environments; venue_compliance_check must still be used for final
    # venue-specific submission claims.
    "aaai": r"""\documentclass[letterpaper]{article}
\usepackage[letterpaper,top=0.75in,bottom=1in,left=0.75in,right=0.75in]{geometry}
\usepackage{times}
\usepackage{helvet}
\usepackage{courier}
\usepackage[hyphens]{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}
\usepackage{graphicx}
%(extra_packages)s
\usepackage{microtype}
\usepackage{natbib}
\usepackage{balance}
\usepackage[compact]{titlesec}
\setlength{\columnsep}{0.25in}
\setlength{\abovedisplayskip}{4pt}
\setlength{\belowdisplayskip}{4pt}
\emergencystretch=2em
\titlespacing*{\section}{0pt}{1.0ex plus .2ex}{0.6ex}
\titlespacing*{\subsection}{0pt}{0.8ex plus .2ex}{0.4ex}
\titlespacing*{\subsubsection}{0pt}{0.6ex plus .2ex}{0.3ex}
\newtheorem{remark}{Remark}

\title{%(title)s}
\author{%(authors)s}
\date{}

\begin{document}
\twocolumn[
\maketitle

%(abstract_block)s
]

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
    # arXiv preprint style — single column, generous margins, no external .sty
    # This is the recommended default since draft papers typically go to arXiv first.
    "arxiv": r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{times}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}
\usepackage{nicefrac}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{multirow}
\usepackage{xcolor}
\usepackage{colortbl}
%(extra_packages)s
\usepackage{natbib}
\usepackage{float}
\usepackage[normalem]{ulem}
\newtheorem{remark}{Remark}

\title{%(title)s}
\author{%(authors)s}
\date{}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
    # -- Journal templates -----------------------------------------------------
    # Bound to venues that RH has already shipped a finished manuscript to, so
    # the next paper for the same venue starts in the right class instead of
    # defaulting to the generic article (which is how an npj submission once
    # went out as a plain 11pt article).
    "springer_nature": r"""\documentclass[pdflatex,sn-nature]{sn-jnl}
\usepackage{manyfoot}
\usepackage{xcolor}
\usepackage{colortbl}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsfonts}
\usepackage{amsthm}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{algorithm}
\usepackage{algpseudocode}
\usepackage{cleveref}
%(extra_packages)s
\raggedbottom

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{sn-nature}
\bibliography{references}

\end{document}
""",
    "elsevier": r"""\documentclass[final,3p,times,number]{elsarticle}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsfonts}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{xcolor}
\usepackage{colortbl}
\usepackage{algorithm}
\usepackage{algpseudocode}
\usepackage{cleveref}
\usepackage{microtype}
%(extra_packages)s

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{elsarticle-num}
\bibliography{references}

\end{document}
""",
    "hssc": r"""\documentclass[11pt]{article}
\usepackage[a4paper,margin=0.82in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{times}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{natbib}
\usepackage{microtype}
\usepackage{setspace}
\usepackage{cleveref}
%(extra_packages)s

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{apalike}
\bibliography{references}

\end{document}
""",
}


def resolve_template_key(template: str) -> str:
    """Map a template name or venue string onto a known template key.

    Venue strings arrive in arbitrary shapes ("AAAI", "AAAI 2026",
    "NeurIPS'25"); silently falling through to the generic a4paper template
    on an unmatched string is how an AAAI target once shipped as an A4
    single-column article.
    """
    key = str(template or "").strip().lower()
    if key in TEMPLATES:
        return key
    # Journal bindings first: these venues have shipped finished manuscripts,
    # and the class they were accepted in is the class the next one starts in.
    for marker in (
        "npj",
        "nature communications",
        "scientific reports",
        "springer",
        "sn-jnl",
        "nature medicine",
    ):
        if marker in key:
            return "springer_nature"
    for marker in (
        "humanities and social sciences communications",
        "hssc",
        "palgrave communications",
    ):
        if marker in key:
            return "hssc"
    for marker in (
        "elsevier",
        "elsarticle",
        "pattern recognition",
        "information fusion",
        "expert systems with applications",
        "neurocomputing",
        "knowledge-based systems",
        "biomedical signal processing",
    ):
        if marker in key:
            return "elsevier"
    for family in ("aaai", "neurips", "icml", "iclr", "arxiv"):
        if family in key:
            return family
    if "nips" in key:
        return "neurips"
    if any(marker in key for marker in ("acl", "emnlp", "naacl")):
        return "acl"
    # Standing owner rule (2026-08-17): a pure computer-science manuscript with
    # no venue-specific class defaults to Elsevier, not the generic article.
    if any(
        marker in key
        for marker in (
            "computer science",
            "computer vision",
            "computer graphics",
            "cs journal",
            "pure cs",
            "machine learning journal",
        )
    ):
        return "elsevier"
    return "generic"


def template_fingerprint(template: str) -> str:
    """Return a stable fingerprint for a LaTeX template policy."""
    template = resolve_template_key(template)
    template_text = TEMPLATES[template]
    digest = hashlib.sha1(template_text.encode("utf-8")).hexdigest()[:12]
    return f"{template}:{digest}"


# Section ordering for paper assembly
SECTION_ORDER = [
    "introduction",
    "related_work",
    "related work",
    "background",
    "preliminaries",
    "method",
    "methodology",
    "approach",
    "experiments",
    "experiment",
    "experimental_setup",
    "results",
    "main_results",
    "ablation",
    "ablation_study",
    "analysis",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "acknowledgments",
    "appendix",
]

_LOST_BACKSLASH_TEXT_COMMANDS = {
    "extbf": "textbf",
    "extit": "textit",
    "exttt": "texttt",
    # A leading "\f" (form-feed, JSON/Python's \f escape) is swallowed the
    # same way when a JSON-encoded response contains a bare "\frac{...}"
    # instead of the properly doubled "\\frac{...}", leaving a literal
    # form-feed byte + "rac{" in the decoded text (observed corrupting
    # \frac{...}{...} in generated Methods sections with equations).
    "rac": "frac",
}
_LOST_BACKSLASH_TEXT_COMMAND_RE = re.compile(
    r"(?P<prefix>^|[^\w\\])[\t\f](?P<command>extbf|extit|exttt|rac)\{"
)


@dataclass
class ValidationFinding:
    """A single finding from pre-compilation validation."""

    level: str  # "error" or "warning"
    category: str  # "cite_missing", "placeholder", "env_mismatch", "figure_missing"
    message: str
    line_number: int = 0


@dataclass
class CompileResult:
    """Result of LaTeX compilation."""

    success: bool = False
    pdf_path: str = ""
    log_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages: int = 0
    auto_fixes: list[str] = field(default_factory=list)
    validation_findings: list[ValidationFinding] = field(default_factory=list)
    typography: dict[str, Any] = field(default_factory=dict)


def _compile_environment() -> dict[str, str]:
    """Document subprocesses never receive the executor's publication authority."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("RH_DEPOSIT_", "ZENODO_"))
        and key not in {"RH_DOI_PUBLICATION", "ARINA_DOI_ACCOUNTS_JSON"}
    }


def _populate_page_count(pdf_file: Path, result: CompileResult) -> None:
    """Populate ``result.pages`` from ``pdfinfo`` when available."""
    try:
        proc = subprocess.run(
            ["pdfinfo", str(pdf_file)],
            capture_output=True,
            text=True,
            timeout=5,
            env=_compile_environment(),
        )
        for line in proc.stdout.splitlines():
            if line.startswith("Pages:"):
                result.pages = int(line.split(":")[1].strip())
                return
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            from PyPDF2 import PdfReader

        result.pages = len(PdfReader(str(pdf_file)).pages)
    except Exception:
        return


def _remove_stale_latex_outputs(out_path: Path, filename: str) -> None:
    """Remove stale outputs before a compile so old PDFs cannot mask failures."""
    for suffix in (
        ".aux",
        ".bbl",
        ".blg",
        ".log",
        ".out",
        ".pdf",
        ".toc",
        ".fls",
        ".fdb_latexmk",
        ".synctex.gz",
    ):
        try:
            (out_path / f"{filename}{suffix}").unlink()
        except FileNotFoundError:
            continue


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in plain text."""
    replacements = [
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _fix_unicode(text: str) -> str:
    """Replace common Unicode characters with LaTeX equivalents."""
    replacements = [
        ("\u2010", "-"),  # hyphen
        ("\u2013", "--"),  # en-dash
        ("\u2014", "---"),  # em-dash
        ("\u2018", "`"),  # left single quote
        ("\u2019", "'"),  # right single quote
        ("\u201c", "``"),  # left double quote
        ("\u201d", "''"),  # right double quote
        ("\u2026", r"\ldots"),  # ellipsis
        ("\u00e9", r"\'e"),  # é
        ("\u00e8", r"\`e"),  # è
        ("\u00fc", r"\"u"),  # ü
        ("\u00f6", r"\"o"),  # ö
        ("\u00e4", r"\"a"),  # ä
        ("\u00a0", "~"),  # nbsp
        ("\u011f", r"\u{g}"),  # ğ
        ("\u0131", r"\i{}"),  # ı
        ("\u0141", r"\L{}"),  # Ł
        ("\u0142", r"\l{}"),  # ł
        ("\u015e", r"\c{S}"),  # Ş
        ("\u015f", r"\c{s}"),  # ş
        ("\u0161", r"\v{s}"),  # š
        ("\u03b1", r"$\alpha$"),
        ("\u03b2", r"$\beta$"),
        ("\u03b3", r"$\gamma$"),
        ("\u03b4", r"$\delta$"),
        ("\u2264", r"$\leq$"),
        ("\u2265", r"$\geq$"),
        ("\u00d7", r"$\times$"),
        ("\u2192", r"$\rightarrow$"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _escape_latex_code_span(text: str) -> str:
    r"""Escape inline-code text for use inside ``\texttt{...}``."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _normalize_markdownish_latex(text: str) -> str:
    """Normalize common Markdown fragments that appear in generated drafts.

    RH section drafts are often mostly LaTeX but may retain Markdown inline code
    for tool names such as ``gap_detect``. Converting only conservative inline
    forms keeps authored LaTeX environments and equations intact.
    """

    def code_repl(match: re.Match[str]) -> str:
        return r"\texttt{" + _escape_latex_code_span(match.group(1)) + "}"

    def heading_repl(match: re.Match[str]) -> str:
        level = len(match.group(1))
        title = match.group(2).strip()
        command = "subsection" if level <= 2 else "subsubsection"
        if level >= 4:
            command = "paragraph"
        return f"\\{command}{{{title}}}"

    text = _restore_python_escaped_text_commands(text)
    text = re.sub(r"(?m)^(#{2,6})\s+(.+?)\s*$", heading_repl, text)
    text = re.sub(r"`([^`\n]+)`", code_repl, text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\\textbf{\1}", text)
    return text


_TABLE_ENV_RE = re.compile(
    r"\\begin\{table\}(?P<option>\[[^\]]*\])?(?P<body>.*?)\\end\{table\}",
    re.DOTALL,
)


def _normalize_template_layout(text: str, template: str) -> str:
    """Normalize layout constructs that become unsafe in venue templates."""
    if template != "aaai":
        return text

    def repl(match: re.Match[str]) -> str:
        body = match.group("body")
        if r"\begin{tabularx}{\textwidth}" not in body:
            return match.group(0)
        option = match.group("option") or ""
        return rf"\begin{{table*}}{option}{body}\end{{table*}}"

    return _TABLE_ENV_RE.sub(repl, text)


def _restore_python_escaped_text_commands(text: str) -> str:
    """Repair common LaTeX text commands damaged by Python string escapes."""

    def repl(match: re.Match[str]) -> str:
        command = _LOST_BACKSLASH_TEXT_COMMANDS[match.group("command")]
        return f"{match.group('prefix')}\\{command}{{"

    return _LOST_BACKSLASH_TEXT_COMMAND_RE.sub(repl, text)


def _extra_packages_for_content(content: str) -> str:
    """Return optional LaTeX packages only when the content needs them."""
    packages: list[str] = []
    if r"\begin{tabularx}" in content:
        packages.extend(
            [
                r"\usepackage{array}",
                r"\usepackage{tabularx}",
                r"\newcolumntype{Y}{>{\raggedright\arraybackslash}X}",
            ]
        )
    if r"\begin{algorithm" in content:
        packages.extend([r"\usepackage{algorithm}", r"\usepackage{algpseudocode}"])
    if r"\begin{algorithmic" in content:
        packages.extend([r"\usepackage{algorithm}", r"\usepackage{algpseudocode}"])
    if any(
        command in content for command in (r"\rowcolor", r"\cellcolor", r"\columncolor")
    ):
        # A0114 froze a manuscript whose results table shaded its header rows. The
        # generic template loads neither package, so the whole stage failed at compile
        # on "! Undefined control sequence" after every section had been paid for.
        packages.extend([r"\usepackage[table]{xcolor}", r"\usepackage{colortbl}"])
    if r"\multirow" in content:
        packages.append(r"\usepackage{multirow}")
    if r"\cref{" in content or r"\Cref{" in content:
        # cleveref must load after hyperref/amsmath, which the templates
        # already place before the extra_packages slot.
        packages.append(r"\usepackage{cleveref}")
    packages.append(FLOAT_TUNING_PREAMBLE)
    return "\n".join(dict.fromkeys(packages))


# Owner-supplied float-placement tuning (2026-08-23): keep figures on text
# pages, avoid half-empty float pages; emergencystretch absorbs overfull lines.
FLOAT_TUNING_PREAMBLE = r"""\setlength{\emergencystretch}{3em}
\renewcommand{\topfraction}{0.9}
\renewcommand{\bottomfraction}{0.6}
\renewcommand{\textfraction}{0.07}
\renewcommand{\floatpagefraction}{0.85}
\setcounter{topnumber}{3}
\setcounter{totalnumber}{5}"""


def _section_sort_key(section_name: str) -> int:
    """Return sort index for a section name."""
    lower = section_name.lower().strip()
    try:
        return SECTION_ORDER.index(lower)
    except ValueError:
        return 999  # unknown sections go to the end


# Owner-mandated placeholder byline for drafts with no real author list: three
# authors across two departments, the third corresponding. "Anonymous" produced
# submission-shaped drafts that then had to be hand-edited into this form every
# time (owner directive, 2026-08-17).
# Owner-supplied byline shape (2026-08-23): superscript affiliation marks on one
# author line, department lines + corresponding-author line beneath it. Authors
# 1-2 share Department A, Author 3 sits in Department B and corresponds.
PLACEHOLDER_AUTHOR_BLOCK = (
    "Author 1$^{1}$ \\quad Author 2$^{1}$ \\quad Author 3$^{2,*}$\\\\[6pt]\n"
    "\\small $^{1}$Department A, University Name, City, Country\\\\\n"
    "\\small $^{2}$Department B, University Name, City, Country\\\\[2pt]\n"
    "\\small $^{*}$Corresponding author: Author 3. "
    "Email: \\texttt{corresponding.author@institution.edu}"
)

# Standard CRediT taxonomy roles, split across the same three placeholder
# authors. Roles are a starting split, not a fixed one: the writing stage must
# reassign them to match what the paper actually reports.
DEFAULT_CREDIT_ROLES = (
    "Conceptualization, Methodology, Software, Formal analysis, Visualization, "
    "Writing -- original draft",
    "Methodology, Validation, Investigation, Data curation, Resources, "
    "Writing -- review \\& editing",
    "Conceptualization, Formal analysis, Supervision, Project administration, "
    "Writing -- review \\& editing",
)


def credit_authorship_block(roles: tuple[str, str, str] | None = None) -> str:
    """Render the CRediT authorship contribution statement.

    One bolded author per paragraph followed by a comma-separated role list, the
    form Elsevier and most journals print. No prose gloss: reviewers read the
    role list, and a narrative restatement of it is redundant.
    """
    a1, a2, a3 = roles or DEFAULT_CREDIT_ROLES
    return (
        "\\section*{CRediT authorship contribution statement}\n\n"
        f"\\textbf{{Author 1:}} {a1}.\n\n"
        f"\\textbf{{Author 2:}} {a2}.\n\n"
        f"\\textbf{{Author 3:}} {a3}.\n\n"
        "All authors have read and agreed to the submitted version of the manuscript.\n"
    )


def _after_title_block(tex: str, title_at: int, insertion: str) -> str:
    """Insert ``insertion`` where the main text starts after the \\maketitle at ``title_at``: after it,
    or after the closing bracket of a \\twocolumn[...] that holds it (its optional argument is typeset
    in a box, where a page-length change would not reach page 1's first column)."""
    opening = tex.rfind("\\twocolumn[", 0, title_at)
    if opening != -1:
        depth, index = 0, opening + len("\\twocolumn")
        while index < len(tex):
            char = tex[index]
            if char == "\\":  # a control sequence or an escaped bracket
                index += 2
                continue
            depth += (char in "[{") - (char in "]}")
            if depth == 0:
                break
            index += 1
        if title_at < index < len(tex):
            return tex[: index + 1] + "\n" + insertion + tex[index + 1 :]
    end = title_at + len("\\maketitle")
    return tex[:end] + "\n" + insertion + tex[end:]


def _format_authors_latex(authors: list[str], template: str) -> str:
    """Format author list for the given template."""
    if not authors:
        return PLACEHOLDER_AUTHOR_BLOCK

    if template == "icml":
        # ICML uses \icmlauthor format
        lines = []
        for a in authors:
            lines.append(f"\\icmlauthor{{{a}}}{{aff1}}")
        return "\n".join(lines)

    return " \\and ".join(authors)


def _strip_leading_section_header(content: str, sec_name: str) -> str:
    """Remove a leading ``\\section{...}`` and ``\\label{...}`` if already present.

    LLM-generated drafts sometimes include their own section header; since
    ``assemble_latex`` always prepends one, the duplicate must be removed.
    Also strips plain-text headers like ``Section 3 Method: ...`` or ``3.1 Problem Formulation``.
    """
    stripped = content.lstrip()

    # Remove leading \section{...} (possibly with \label{...} on the next line)
    m = re.match(
        r"\\section\*?\{[^}]*\}\s*(?:\\label\{[^}]*\}\s*)?",
        stripped,
    )
    if m:
        stripped = stripped[m.end() :].lstrip()

    # Remove plain-text headers like "Section 3 Method: ..." at the very start
    m = re.match(
        r"Section\s+\d+[\s.:]+[^\n]*\n",
        stripped,
        re.IGNORECASE,
    )
    if m:
        stripped = stripped[m.end() :].lstrip()

    # Remove leading Markdown section headers, e.g. "## 4 Case Study".
    m = re.match(r"#{1,6}\s+[^\n]*\n", stripped)
    if m:
        stripped = stripped[m.end() :].lstrip()

    return stripped


def assemble_latex(
    title: str,
    authors: list[str],
    abstract: str,
    sections: dict[str, str],
    bibliography_entries: list[str] | None = None,
    template: str = "generic",
    *,
    preserve_section_order: bool = False,
    venue_profile: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Assemble LaTeX document from sections.

    Returns (tex_content, bib_content) tuple.
    """
    template = resolve_template_key(template)
    tmpl = TEMPLATES[template]

    sorted_sections = (
        list(sections.items())
        if preserve_section_order
        else sorted(sections.items(), key=lambda x: _section_sort_key(x[0]))
    )
    profile_titles = {}
    bibliography = ""
    structure = (venue_profile or {}).get("structure") or []
    if structure:
        profile_titles = {name.lower(): name for name in structure}
        credit_titles = {
            "author contributions",
            "credit authorship contribution statement",
        }
        declared = [*structure, *(venue_profile.get("declarations_block") or [])]
        credit_title = next(
            (name for name in declared if name.lower() in credit_titles), None
        )
        if credit_title is None and (venue_profile.get("byline") or {}).get(
            "contributions_required"
        ):
            credit_title = "Author contributions"
        drafted_titles = {name.replace("_", " ").lower() for name, _ in sorted_sections}
        drafted_titles.update(
            name.lower()
            for _, content in sorted_sections
            for name in re.findall(r"\\(?:sub)*section\*?\{([^{}]+)\}", content)
        )
        if credit_title and not drafted_titles.intersection(credit_titles):
            sorted_sections = [
                *sorted_sections,
                (credit_title, credit_authorship_block()),
            ]
        # References is a real bibliography seat, not an LLM-authored prose section.
        bibliography = "\n".join(
            re.findall(r"^\\bibliograph(?:y|ystyle)\{[^}]+\}", tmpl, re.M)
        )
        tmpl = re.sub(r"^\\bibliograph(?:y|ystyle)\{[^}]+\}\n?", "", tmpl, flags=re.M)
        if not any(
            name.replace("_", " ").lower() == "references"
            for name, _ in sorted_sections
        ):
            sorted_sections = [*sorted_sections, ("references", "")]
        order = {name.lower(): index for index, name in enumerate(structure)}
        sorted_sections = sorted(
            sorted_sections,
            key=lambda item: order.get(item[0].replace("_", " ").lower(), len(order)),
        )

    # Build body
    body_parts: list[str] = []
    for sec_name, content in sorted_sections:
        display_name = sec_name.replace("_", " ").title()
        if structure:
            normalized = sec_name.replace("_", " ").lower()
            display_name = profile_titles.get(normalized, sec_name.replace("_", " "))
            if normalized == "references":
                body_parts.append(bibliography)
                continue
        content = _restore_python_escaped_text_commands(content)
        content = _strip_leading_section_header(content, sec_name)
        content = _fix_unicode(content)
        content = _normalize_markdownish_latex(content)
        content = _normalize_template_layout(content, template)
        body_parts.append(
            f"\\section{{{display_name}}}\n\\label{{sec:{sec_name.lower().replace(' ', '_')}}}\n\n{content}\n"
        )

    body = "\n".join(body_parts)

    # Legacy templates append the default; profiles seat it with their sections.
    if not structure and "CRediT authorship contribution" not in body:
        body = f"{body}\n\n{credit_authorship_block()}"

    # Abstract block
    abstract_block = ""
    if abstract:
        abstract = _fix_unicode(abstract)
        abstract = _normalize_markdownish_latex(abstract)
        abstract_block = f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}\n"

    # Format authors
    authors_str = _format_authors_latex(authors, template)
    corresponding_note = corresponding_reserve = ""
    if venue_profile is not None and (venue_profile.get("byline") or {}).get(
        "placeholders_required"
    ):
        byline = venue_profile["byline"]
        tokens = byline.get("placeholder_tokens")
        if (
            not isinstance(tokens, list)
            or len(tokens) != 6
            or tokens[:3] != ["Author 1", "Author 2", "Author 3"]
            or any(
                not isinstance(token, str) or not token.strip() or "\\" in token
                for token in tokens
            )
        ):
            raise ValueError(
                "venue placeholder tokens must name three authors, two institutions and one email"
            )
        institution_one, institution_two, email = map(_escape_latex, tokens[3:])
        corresponding_note = "Corresponding author: Author 3. Email: " + email
        authors_str = (
            "Author 1$^{1}$ \\quad Author 2$^{1}$ \\quad Author 3$^{2,*}$\\\\[6pt]\n"
            f"\\small $^{{1}}$Department A, {institution_one}\\\\\n"
            f"\\small $^{{2}}$Department B, {institution_two}"
        )
        if byline.get("corresponding_marker") == "bottom_left":
            # Stamped on page 1 when it ships out: not a footnote (its smaller font is one a cached
            # toolchain may never have loaded, which stops the build under a T1 + lmodern 11pt
            # preamble), not a figure (a caption-less float counts toward the figure floors), and no
            # optional argument (a template that sets \\maketitle inside \\twocolumn[...] would read
            # a "]" as its close). The note is set a column wide and placed from the text block, not
            # the paper edge: its last line on the text block's last baseline, flush with the first
            # column's left edge. Page 1's first column is shortened by the note's height plus a
            # line (corresponding_reserve, placed after the title block), so the body ends above it
            # whatever the margins, running foot or column layout. The box and the hook are set up
            # before \\maketitle so that a title page (the titlepage option ships one inside
            # \\maketitle) carries the note. A kernel older than 2020-10 has no shipout hook and gets
            # the footnote.
            corresponding_note = (
                "\\begingroup\n\\ifdefined\\AddToHookNext\n"
                "\\ifx\\rhcorrespondingbox\\undefined\\newsavebox{\\rhcorrespondingbox}\\fi\n"
                "\\global\\setbox\\rhcorrespondingbox\\vbox{\\hsize\\columnwidth\\normalfont\\normalsize"
                f"\\noindent\\raggedright$^{{*}}${corresponding_note}}}\n"
                "\\AddToHookNext{shipout/foreground}{\\put(\\dimexpr\\hoffset+1in+\\oddsidemargin\\relax,"
                "-\\dimexpr\\voffset+1in+\\topmargin+\\headheight+\\headsep+\\textheight\\relax)"
                "{\\box\\rhcorrespondingbox}}\n"
                "\\else\n\\renewcommand{\\thefootnote}{*}\n"
                f"\\footnotetext{{{corresponding_note}}}\n\\fi\n\\endgroup\n"
            )
            corresponding_reserve = (
                "\\ifdefined\\AddToHookNext\\enlargethispage{-\\dimexpr\\ht\\rhcorrespondingbox"
                "+\\dp\\rhcorrespondingbox+\\baselineskip\\relax}\\fi\n"
            )
        else:
            authors_str += "\\\\[2pt]\n\\small $^{*}$" + corresponding_note
            corresponding_note = ""
    icml_authors = _format_authors_latex(authors, "icml") if template == "icml" else ""

    tex = tmpl % {
        "title": _fix_unicode(title) if title else "Untitled",
        "authors": authors_str,
        "icml_authors": icml_authors,
        "abstract_block": abstract_block,
        "body": body,
        "extra_packages": _extra_packages_for_content(f"{abstract_block}\n{body}"),
    }
    if corresponding_note:
        title_at = tex.index("\\maketitle")
        tex = tex[:title_at] + corresponding_note + tex[title_at:]
        if corresponding_reserve:
            tex = _after_title_block(
                tex, tex.index("\\maketitle", title_at), corresponding_reserve
            )

    # Build bibliography
    bib = "\n\n".join(bibliography_entries) if bibliography_entries else ""

    return tex, bib


def _validate_before_compile(
    tex_content: str,
    bib_content: str,
    output_dir: str = "",
) -> list[ValidationFinding]:
    """Pre-compilation validation gate.

    Catches deterministic errors before invoking the TeX engine:
    1. ``\\cite{key}`` references not present in bib_content
    2. Placeholder patterns (X%, TODO, TBD, [?], ??) in body text
    3. Unmatched ``\\begin{env}`` / ``\\end{env}`` pairs
    4. Missing ``\\includegraphics`` targets (when output_dir is provided)
    """
    findings: list[ValidationFinding] = []
    lines = tex_content.splitlines()

    # --- 0. Python-escaped LaTeX command audit ---
    for lineno, line in enumerate(lines, start=1):
        for match in _LOST_BACKSLASH_TEXT_COMMAND_RE.finditer(line):
            command = match.group("command")
            restored = _LOST_BACKSLASH_TEXT_COMMANDS[command]
            findings.append(
                ValidationFinding(
                    level="error",
                    category="malformed_latex_command",
                    message=(
                        "Possible Python-escaped LaTeX command: "
                        f"tab + {command}{{ at line {lineno}; expected "
                        f"\\{restored}{{...}}."
                    ),
                    line_number=lineno,
                )
            )

    # --- 1. Citation key audit ---
    bib_keys: set[str] = set()
    if bib_content:
        for m in re.finditer(r"@\w+\{(\w+)\s*,", bib_content):
            bib_keys.add(m.group(1))

    for lineno, line in enumerate(lines, start=1):
        for m in re.finditer(r"\\cite[tp]?\{([^}]+)\}", line):
            for key in m.group(1).split(","):
                key = key.strip()
                if key and key not in bib_keys:
                    findings.append(
                        ValidationFinding(
                            level="error",
                            category="cite_missing",
                            message=f"\\cite{{{key}}} not found in references.bib",
                            line_number=lineno,
                        )
                    )

    # --- 2. Placeholder detection ---
    # Only scan body text (between \begin{document} and \end{document})
    in_body = False
    placeholder_re = re.compile(
        r"(?<![\\])\b(?:TODO|TBD|FIXME|XXX)\b"  # explicit markers
        r"|(?<![\\0-9.])\b[XY]\\?%"  # X% or Y% (not 4.5%)
        r"|\[\?\]"  # [?]
        r"|\?\?(?!\?)",  # ?? but not ???
        re.IGNORECASE,
    )
    for lineno, line in enumerate(lines, start=1):
        if r"\begin{document}" in line:
            in_body = True
            continue
        if r"\end{document}" in line:
            in_body = False
            continue
        if not in_body:
            continue
        # Skip comment lines
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        for m in placeholder_re.finditer(line):
            findings.append(
                ValidationFinding(
                    level="warning",
                    category="placeholder",
                    message=f"Possible placeholder: '{m.group()}' in body text",
                    line_number=lineno,
                )
            )

    # --- 3. Unmatched \begin/\end environments ---
    env_stack: list[tuple[str, int]] = []
    env_re = re.compile(r"\\(begin|end)\{(\w+\*?)\}")
    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        for m in env_re.finditer(line):
            action, env_name = m.group(1), m.group(2)
            if action == "begin":
                env_stack.append((env_name, lineno))
            elif action == "end":
                if env_stack and env_stack[-1][0] == env_name:
                    env_stack.pop()
                elif env_stack:
                    opened = env_stack.pop()
                    findings.append(
                        ValidationFinding(
                            level="error",
                            category="env_mismatch",
                            message=(
                                f"\\end{{{env_name}}} at line {lineno} does not match "
                                f"\\begin{{{opened[0]}}} at line {opened[1]}"
                            ),
                            line_number=lineno,
                        )
                    )
                else:
                    findings.append(
                        ValidationFinding(
                            level="error",
                            category="env_mismatch",
                            message=f"\\end{{{env_name}}} without matching \\begin",
                            line_number=lineno,
                        )
                    )
    for env_name, lineno in env_stack:
        if env_name == "document":
            continue  # sometimes \end{document} is absent in partial content
        findings.append(
            ValidationFinding(
                level="error",
                category="env_mismatch",
                message=f"\\begin{{{env_name}}} at line {lineno} never closed",
                line_number=lineno,
            )
        )

    # --- 4. Missing \includegraphics targets ---
    if output_dir:
        out = Path(output_dir)
        for lineno, line in enumerate(lines, start=1):
            for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", line):
                fig_path = m.group(1)
                candidates = [
                    out / fig_path,
                    out / f"{fig_path}.png",
                    out / f"{fig_path}.pdf",
                    out / f"{fig_path}.jpg",
                ]
                if not any(c.exists() for c in candidates):
                    findings.append(
                        ValidationFinding(
                            level="warning",
                            category="figure_missing",
                            message=f"\\includegraphics target '{fig_path}' not found in {output_dir}",
                            line_number=lineno,
                        )
                    )

    return findings


def _infer_venue_key(tex_content: str) -> str | None:
    """Best-effort venue family from the preamble, for the paper-size check."""
    head = tex_content[:2000]
    for marker, key in (
        ("sn-jnl", "springer_nature"),
        ("elsarticle", "elsevier"),
        ("icml", "icml"),
        ("iclr", "iclr"),
        ("neurips", "neurips"),
        ("aaai", "aaai"),
        ("acl", "acl"),
    ):
        if marker in head:
            return key
    return None


def compile_latex(
    tex_content: str,
    bib_content: str,
    output_dir: str,
    filename: str = "paper",
    venue_key: str | None = None,
    *,
    preserve_source: bool = False,
) -> CompileResult:
    """Compile LaTeX to PDF using pdflatex + bibtex (3-pass).

    Preserve mode disables template fallback and checks source integrity. Its
    process flags are local hardening, not network or process isolation.
    """
    if not isinstance(filename, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", filename
    ):
        raise ValueError("filename must be a single safe LaTeX filename stem")
    if filename == "references":
        raise ValueError("filename must not conflict with the references bibliography")
    result = _compile_latex(
        tex_content,
        bib_content,
        output_dir,
        filename,
        venue_key,
        preserve_source=preserve_source,
    )
    if preserve_source:
        out_path = Path(output_dir)
        log_path = out_path / f"{filename}.log"
        log_text = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.is_file()
            else ""
        )
        if re.search(r"Missing character:", log_text, re.IGNORECASE):
            result.success = False
            result.pdf_path = ""
            result.errors.append(
                "missing character in rendered manuscript; use a font covering the source text"
            )
            (out_path / f"{filename}.pdf").unlink(missing_ok=True)
        changed = []
        sources = (
            (out_path / f"{filename}.tex", tex_content.encode("utf-8")),
            (
                out_path / "references.bib",
                bib_content.encode("utf-8") if bib_content else None,
            ),
        )
        for path, expected in sources:
            try:
                intact = (
                    (not path.exists() and not path.is_symlink())
                    if expected is None
                    else (
                        not path.is_symlink()
                        and path.is_file()
                        and path.read_bytes() == expected
                    )
                )
            except OSError:
                intact = False
            if not intact:
                changed.append(path.name)
                if path.is_symlink() or path.is_file():
                    path.unlink()
                if expected is not None:
                    path.write_bytes(expected)
        if changed:
            result.success = False
            result.pdf_path = ""
            result.errors.append(
                "compiler changed protected source: " + ", ".join(changed)
            )
            (out_path / f"{filename}.pdf").unlink(missing_ok=True)
    return result


def _compile_latex(
    tex_content: str,
    bib_content: str,
    output_dir: str,
    filename: str,
    venue_key: str | None,
    *,
    preserve_source: bool,
) -> CompileResult:
    result = CompileResult()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # --- Pre-compilation validation gate ---
    validation = _validate_before_compile(tex_content, bib_content, output_dir)
    result.validation_findings = validation
    val_errors = [f for f in validation if f.level == "error"]
    val_warnings = [f for f in validation if f.level == "warning"]
    for f in val_warnings:
        result.warnings.append(f"[pre-compile] {f.category}: {f.message}")
    if val_errors:
        for f in val_errors:
            result.errors.append(f"[pre-compile] {f.category}: {f.message}")
        logger.warning(
            "Pre-compile validation found %d error(s) — proceeding with compilation "
            "but output may have issues: %s",
            len(val_errors),
            "; ".join(f.message for f in val_errors[:5]),
        )

    tex_file = out_path / f"{filename}.tex"
    bib_file = out_path / "references.bib"
    pdf_file = out_path / f"{filename}.pdf"

    _remove_stale_latex_outputs(out_path, filename)

    # Write files
    tex_file.write_text(tex_content, encoding="utf-8")
    if bib_content:
        bib_file.write_text(bib_content, encoding="utf-8")
    else:
        try:
            bib_file.unlink()
        except FileNotFoundError:
            pass

    # Engine preference: pdflatex > tectonic > skip
    engine = None
    if shutil.which("pdflatex"):
        engine = "pdflatex"
    elif shutil.which("tectonic"):
        engine = "tectonic"

    if not engine:
        result.log_summary = (
            "No LaTeX engine found — .tex/.bib written but not compiled"
        )
        result.warnings.append("Neither pdflatex nor tectonic available on this system")
        # Fail closed: success=True here discarded every pre-compile validation
        # error and let a stale PDF on disk masquerade as a fresh verified
        # build (the tectonic-missing silent-failure mode). The .tex/.bib
        # artifacts are still written and reported for manual compilation.
        result.errors.append(
            "no LaTeX engine available: compilation and its validation gate "
            "did not run; install tectonic (or pdflatex) and re-run"
        )
        result.success = False
        result.pdf_path = ""
        return result

    env = _compile_environment()
    env["TEXINPUTS"] = f".:{out_path}:"
    if preserve_source:
        env = {**env, "openin_any": "p", "openout_any": "p", "shell_escape": "f"}

    # Use tectonic for single-pass auto-download compilation when pdflatex is not present
    if engine == "tectonic":
        try:
            proc = subprocess.run(
                [
                    "tectonic",
                    *(["--untrusted"] if preserve_source else []),
                    "--keep-logs",
                    "--keep-intermediates",
                    "-r",
                    "2",
                    f"{filename}.tex",
                ],
                cwd=str(out_path),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except subprocess.TimeoutExpired:
            result.errors.append("tectonic timed out")
            return result
        log_file = out_path / f"{filename}.log"
        if log_file.exists():
            _parse_log(log_file.read_text(encoding="utf-8", errors="replace"), result)
        if proc.returncode != 0 and not result.errors:
            result.errors.append("tectonic failed")
        if pdf_file.exists():
            result.pdf_path = str(pdf_file)
            _populate_page_count(pdf_file, result)
            result.success = not result.errors
        else:
            # Auto-fix: retry with arxiv template if .sty missing
            stderr_text = (proc.stderr or "") + (proc.stdout or "")
            if (
                not preserve_source
                and "File " in stderr_text
                and ".sty' not found" in stderr_text
            ):
                result.auto_fixes.append("Switched to arxiv template (missing .sty)")
                tex_content_fixed = re.sub(
                    r"\\documentclass\[.*?\]\{article\}\s*\\usepackage[^\n]*\{[a-z_\d]+\}",
                    r"\\documentclass[11pt]{article}\n\\usepackage[margin=1in]{geometry}",
                    tex_content,
                    count=1,
                )
                tex_file.write_text(tex_content_fixed, encoding="utf-8")
                _remove_stale_latex_outputs(out_path, filename)
                proc = subprocess.run(
                    [
                        "tectonic",
                        "--keep-logs",
                        "--keep-intermediates",
                        "-r",
                        "2",
                        f"{filename}.tex",
                    ],
                    cwd=str(out_path),
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )
                log_file = out_path / f"{filename}.log"
                if log_file.exists():
                    _parse_log(
                        log_file.read_text(encoding="utf-8", errors="replace"),
                        result,
                    )
                if proc.returncode != 0 and not result.errors:
                    result.errors.append("tectonic failed")
                if pdf_file.exists():
                    result.pdf_path = str(pdf_file)
                    _populate_page_count(pdf_file, result)
                    result.success = not result.errors
                    return result
            result.errors.append("tectonic produced no PDF")
        return result

    # 3-pass compilation: pdflatex → bibtex → pdflatex → pdflatex
    passes = ["pdflatex", "bibtex", "pdflatex", "pdflatex"]
    for i, cmd in enumerate(passes):
        if cmd == "bibtex":
            if not bib_content:
                continue
            args = [cmd, filename]
        else:
            args = [
                cmd,
                *(["-no-shell-escape"] if preserve_source else []),
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"{filename}.tex",
            ]

        try:
            proc = subprocess.run(
                args,
                cwd=str(out_path),
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        except subprocess.TimeoutExpired:
            result.errors.append(f"Pass {i + 1} ({cmd}) timed out")
            break
        except FileNotFoundError:
            if cmd == "bibtex":
                if preserve_source:
                    result.errors.append(
                        "bibtex not found; bibliography compilation did not run"
                    )
                    break
                result.warnings.append("bibtex not found, skipping bibliography")
                continue
            result.errors.append(f"{cmd} not found")
            break

        if preserve_source and proc.returncode != 0:
            result.errors.append(f"Pass {i + 1} ({cmd}) exited {proc.returncode}")

        # Parse log for warnings/errors on final pass
        if i == len(passes) - 1 or proc.returncode != 0:
            log_file = out_path / f"{filename}.log"
            if log_file.exists():
                log_text = log_file.read_text(encoding="utf-8", errors="replace")
                _parse_log(log_text, result)

            if (
                not preserve_source
                and proc.returncode != 0
                and cmd == "pdflatex"
                and i == 0
            ):
                # Try auto-fix: switch to generic template
                if "! LaTeX Error: File" in (proc.stdout + proc.stderr):
                    result.auto_fixes.append(
                        "Switched to generic template (missing .sty)"
                    )
                    # Rewrite with generic template
                    tex_content_fixed = re.sub(
                        r"\\documentclass.*?\n",
                        r"\\documentclass[11pt,a4paper]{article}\n",
                        tex_content,
                    )
                    tex_file.write_text(tex_content_fixed, encoding="utf-8")
                    continue

    # Check for PDF
    if pdf_file.exists():
        result.pdf_path = str(pdf_file)
        _populate_page_count(pdf_file, result)
        result.success = not result.errors
    else:
        result.success = False
        result.log_summary = "PDF not generated"

    _attach_typography_findings(
        result,
        tex_content,
        out_path,
        filename,
        venue_key or _infer_venue_key(tex_content),
    )

    return result


def _attach_typography_findings(
    result: CompileResult,
    tex_content: str,
    out_path: Path,
    filename: str,
    venue_key: str | None,
) -> None:
    """Record layout defects (overflow, pinned columns, paper size) on the result.

    A clean exit code says nothing about whether tables fit the text block, so
    these findings surface as warnings that downstream gates can act on. They do
    not flip ``success``: layout is fixable copy-editing, not a build failure.
    """
    log_file = out_path / f"{filename}.log"
    log_text = ""
    if log_file.exists():
        log_text = log_file.read_text(encoding="utf-8", errors="replace")

    report = check_typography(tex_content, log_text, venue_key=venue_key)
    result.typography = report.to_dict()
    for finding in report.findings:
        result.validation_findings.append(
            ValidationFinding(
                level="warning",
                category=f"typography_{finding.check}",
                message=finding.message,
                line_number=finding.line or 0,
            )
        )
    if report.majors:
        result.warnings.append(
            f"[typography] {len(report.majors)} major layout finding(s): "
            + "; ".join(f.check for f in report.majors[:4])
        )


def _parse_log(log_text: str, result: CompileResult) -> None:
    """Parse pdflatex log file for warnings and errors.

    TeX prints an error over several lines: the "! ..." headline, then what it had
    just read and the line it was on. Keeping only the headline turns every one of
    them into "! Undefined control sequence." with no command and no location, and
    the reader has to recompile to learn what the compiler already said. A0114
    parked there with `\\rowcolor` on line 145 named in the log and in no refusal.
    """
    lines = log_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("! "):
            context = [
                following.strip()
                for following in lines[index + 1 : index + 6]
                if following.startswith(("<", "l.")) and following.strip()
            ]
            result.errors.append(" ".join([line.strip()] + context[:2]))
        elif "Warning:" in line and len(line) < 200:
            result.warnings.append(line.strip())

    # Keep log summary short
    if result.errors:
        result.log_summary = (
            f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)"
        )
    elif result.warnings:
        result.log_summary = f"No errors, {len(result.warnings)} warning(s)"
    else:
        result.log_summary = "Clean compilation"
