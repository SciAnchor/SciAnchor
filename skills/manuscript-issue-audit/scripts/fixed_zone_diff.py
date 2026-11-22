#!/usr/bin/env python3
"""Non-model guardrail for manuscript edits.

An agent that revises a manuscript states what it intends to change. This
script decides, independently, whether the change stayed inside its declared
bounds. Both halves get logged, which is what makes the edit auditable rather
than merely instructed:
harness-engineering/wiki/patterns/agent-permissions-and-guardrails.md
("Do not rely on a model instruction as the only control for a high-risk
action"; "The trace should show both the model request and the independent
guardrail decision").

It answers four questions a numeric-only check cannot:

  1. Did any cross-reference lose its target?  (renders as "??" in the PDF)
  2. Did a structural unit disappear?          (theorem/definition merged away)
  3. Did a protected number change?            (results the edit must not touch)
  4. Did protected environments change?        (tables, figures, equations)

Run over the whole document set, not one section: a label deleted in one file
is referenced from another, and a section-scoped check cannot see it.

    # integrity of a single tree (no baseline needed)
    fixed_zone_diff.py --new paper/

    # before/after an edit
    fixed_zone_diff.py --old versions/ --new paper/

Exit 0 clean, 1 violations found, 2 bad usage.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Environments whose body an edit is not allowed to alter. These carry the
# measured results; prose around them is fair game, the numbers inside are not.
PROTECTED_ENVS = ("table", "tabular", "figure", "equation", "align", "align*")

# Structural units whose disappearance is a content loss even when every
# sentence around them survives. Merging two theorems into one keeps the words
# and destroys a referable result.
STRUCTURAL_ENVS = ("theorem", "definition", "lemma", "proposition", "corollary", "assumption")

TEX_GLOB = "*.tex"


@dataclass
class Findings:
    dangling: list[str] = field(default_factory=list)
    lost_labels: list[str] = field(default_factory=list)
    env_deltas: list[str] = field(default_factory=list)
    number_deltas: list[str] = field(default_factory=list)

    def violations(self) -> int:
        return len(self.dangling) + len(self.lost_labels) + len(self.env_deltas) + len(self.number_deltas)


def _strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def _read_tree(root: Path) -> dict[str, str]:
    if root.is_file():
        return {root.name: _strip_comments(root.read_text(errors="ignore"))}
    return {
        p.name: _strip_comments(p.read_text(errors="ignore"))
        for p in sorted(root.rglob(TEX_GLOB))
    }


def _labels(tree: dict[str, str]) -> set[str]:
    return {m for t in tree.values() for m in re.findall(r"\\label\{([^}]+)\}", t)}


def _refs(tree: dict[str, str]) -> dict[str, str]:
    """Every referenced key -> the file that references it."""
    out: dict[str, str] = {}
    for fname, t in tree.items():
        for key in re.findall(r"\\(?:ref|eqref|autoref|cref|Cref)\{([^}]+)\}", t):
            out.setdefault(key, fname)
    return out


def _env_counts(tree: dict[str, str], envs: tuple[str, ...]) -> dict[str, int]:
    joined = "\n".join(tree.values())
    return {e: len(re.findall(r"\\begin\{" + re.escape(e) + r"\}", joined)) for e in envs}


def _protected_numbers(tree: dict[str, str]) -> set[str]:
    """Numbers appearing inside protected environments.

    Prose numbers move around legitimately when text is tightened; a number
    inside a results table is a measurement and must survive verbatim.
    """
    joined = "\n".join(tree.values())
    found: set[str] = set()
    for env in PROTECTED_ENVS:
        pattern = r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}"
        for body in re.findall(pattern, joined, re.S):
            found |= set(re.findall(r"\d+(?:[.,]\d+)*", body))
    return found


def audit(new_root: Path, old_root: Path | None) -> Findings:
    f = Findings()
    new = _read_tree(new_root)
    if not new:
        print(f"no .tex found under {new_root}", file=sys.stderr)
        sys.exit(2)

    # 1. Reference integrity. Checked on the new tree alone: a dangling ref is
    #    a defect whether or not an edit introduced it, and LaTeX only whispers
    #    about it in a log nobody reads.
    labels, refs = _labels(new), _refs(new)
    for key, where in sorted(refs.items()):
        if key not in labels:
            f.dangling.append(f"{where}: \\ref{{{key}}} has no \\label (renders as ??)")

    if old_root is None:
        return f

    old = _read_tree(old_root)
    if not old:
        print(f"no .tex found under {old_root}", file=sys.stderr)
        sys.exit(2)

    # 2. Labels that existed and no longer do. A merged theorem keeps the prose
    #    and drops the anchor; this is the signal that catches it.
    for lost in sorted(_labels(old) - labels):
        f.lost_labels.append(f"\\label{{{lost}}} existed before this edit and is gone")

    # 3. Structural units. Counts only: a drop means a result was absorbed.
    before, after = _env_counts(old, STRUCTURAL_ENVS), _env_counts(new, STRUCTURAL_ENVS)
    for env in STRUCTURAL_ENVS:
        if after[env] < before[env]:
            f.env_deltas.append(f"{env}: {before[env]} -> {after[env]}")

    # 4. Protected environments and the numbers they carry.
    pb, pa = _env_counts(old, PROTECTED_ENVS), _env_counts(new, PROTECTED_ENVS)
    for env in PROTECTED_ENVS:
        if pa[env] != pb[env]:
            f.env_deltas.append(f"{env} (protected): {pb[env]} -> {pa[env]}")

    for gone in sorted(_protected_numbers(old) - _protected_numbers(new)):
        f.number_deltas.append(f"{gone} no longer appears in any protected environment")

    return f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", required=True, type=Path, help="revised .tex file or directory")
    ap.add_argument("--old", type=Path, help="baseline; omit to check integrity only")
    a = ap.parse_args()

    f = audit(a.new, a.old)

    for title, items in (
        ("DANGLING REFERENCES", f.dangling),
        ("LOST LABELS", f.lost_labels),
        ("STRUCTURAL LOSS", f.env_deltas),
        ("PROTECTED NUMBERS CHANGED", f.number_deltas),
    ):
        if items:
            print(f"\n{title}")
            for i in items:
                print(f"  - {i}")

    n = f.violations()
    print(f"\n{'FAIL' if n else 'PASS'}: {n} violation(s)")
    return 1 if n else 0


def _demo() -> None:
    """Self-check on damage this script is meant to catch."""
    import tempfile

    base = r"""
\begin{theorem}[A]\label{thm:a}Body.\end{theorem}
\begin{theorem}[B]\label{thm:b}Body.\end{theorem}
See \ref{thm:a} and \ref{thm:b}.
\begin{table}\begin{tabular}{c} 0.857 \\ 22840 \end{tabular}\end{table}
"""
    # Two theorems merged into one, second label destroyed, its ref left behind.
    merged = r"""
\begin{theorem}[A and B]\label{thm:a}Body. Body.\end{theorem}
See \ref{thm:a} and \ref{thm:b}.
\begin{table}\begin{tabular}{c} 0.857 \\ 22840 \end{tabular}\end{table}
"""
    # A measured value silently altered.
    tampered = base.replace("0.857", "0.957")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "old").mkdir()
        (root / "old" / "m.tex").write_text(base)

        for name, content, want in (("merged", merged, True), ("tampered", tampered, True)):
            case = root / name
            case.mkdir()
            (case / "m.tex").write_text(content)
            f = audit(case, root / "old")
            assert (f.violations() > 0) == want, f"{name}: expected violations, got {f}"

        assert any("thm:b" in x for x in audit(root / "merged", root / "old").lost_labels)
        assert any("theorem" in x for x in audit(root / "merged", root / "old").env_deltas)
        assert audit(root / "merged", root / "old").dangling, "dangling ref not caught"
        assert audit(root / "tampered", root / "old").number_deltas, "number change not caught"

        clean = root / "clean"
        clean.mkdir()
        (clean / "m.tex").write_text(base)
        assert audit(clean, root / "old").violations() == 0, "false positive on identical trees"

    print("demo: all damage classes caught, no false positive on a no-op edit")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        sys.exit(main())
