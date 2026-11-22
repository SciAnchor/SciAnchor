"""One developer's checkout is not a path: committed code may not reach one un-frozen.

This guard exists because a path literal under a developer's home passes every test run
before it ships -- on that machine the file is there. RH needed its own, because the engine now runs unattended on a
multi-tenant host where none of these directories exist and a seat cannot create them.

RH's debt is mostly not in string constants, so a literal-only scan reports five entries and
misses every one that matters. `Path.home() / "code" / "sibling-repo"` names a
developer's checkout just as precisely as `/Users/someone/code/sibling-repo`, and it is
the form RH actually uses. Both shapes are scanned.

`Path.home()` joined with a dotted first segment is not debt: `~/.research-harness` is the
state-tree convention and resolves on any host. Joined with anything else, it is a claim
about how a particular person arranges their home directory.

The rule is not "no such path": `eval/researchflowbench/release_readiness.py` carries one
inside a detector's own pattern. It is that the set may only shrink, so a new one is a
decision someone makes in the open rather than a machine the code quietly requires.

Committed files only. Scratch scripts in a working tree are nobody else's problem.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCANNED = (
    "packages/research_harness/research_harness",
    "packages/research_harness_mcp/research_harness_mcp",
)
DEVELOPER_MARKERS = ("/Users/", "/opt/homebrew", "code/rh-workspace", "~/code")
DEBT = Path(__file__).resolve().parent / "portability_debt.json"


def _tracked_modules() -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", *SCANNED],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / name for name in listed if name.endswith(".py")]


def _home_join_segments(node: ast.AST) -> list[str]:
    """The literal segments of a ``Path.home() / "a" / "b"`` chain, innermost first.

    Returns an empty list for anything that is not such a chain. The walk is over the left
    spine only: ``Path.home() / a / b`` parses as ``((home / a) / b)``, so the base call is
    reached by descending ``.left`` and the segments come back in source order.
    """
    segments: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if not (
            isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)
        ):
            return []  # a computed segment is not a claim about anyone's home layout
        segments.insert(0, node.right.value)
        node = node.left
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Path"
        and not node.args
    ):
        return segments
    return []


def developer_paths() -> dict[str, list[str]]:
    """Every committed path that only exists in one person's home, by path → where it is.

    An AST walk, so a comment is out of scope. A docstring is a string
    constant and stays in: a path written there is documentation only one machine can follow,
    which rots the same way the code does.
    """
    found: dict[str, list[str]] = {}
    for path in _tracked_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Only the outermost chain: ast.walk also visits the left spine, and reporting
        # ~/code, ~/code/x and ~/code/x/y for one expression freezes three entries where
        # there is one path, so removing that path would leave two of them stale forever.
        inner = {
            id(node.left)
            for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        }
        for node in ast.walk(tree):
            site = (
                f"{path.relative_to(ROOT)}:{node.lineno}"
                if hasattr(node, "lineno")
                else str(path)
            )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if any(marker in node.value for marker in DEVELOPER_MARKERS):
                    found.setdefault(node.value, []).append(site)
                continue
            if id(node) in inner:
                continue
            segments = _home_join_segments(node)
            if segments and not segments[0].startswith("."):
                found.setdefault("~/" + "/".join(segments), []).append(site)
    return found


def test_no_new_developer_path():
    debt = json.loads(DEBT.read_text(encoding="utf-8"))["developer_path_debt"]
    new = {path: sites for path, sites in developer_paths().items() if path not in debt}
    assert not new, (
        "a committed path that exists on one developer's machine only:\n"
        + "\n".join(f"  {sites} -> {path}" for path, sites in sorted(new.items()))
        + "\n\nResolve it through state_path()/an environment override the host sets, or add "
        "it to tests/portability_debt.json developer_path_debt with the reason it has to stay."
    )


def test_the_frozen_list_may_only_shrink():
    """An entry nobody reaches any more is removed, not kept as cover for the next one."""
    debt = json.loads(DEBT.read_text(encoding="utf-8"))["developer_path_debt"]
    stale = sorted(set(debt) - set(developer_paths()))
    assert not stale, (
        f"frozen developer paths that no longer appear; delete them: {stale}"
    )


def test_the_detector_reads_constants_and_not_comments():
    tree = ast.parse(
        '# /Users/someone/comment\n"""/Users/someone/doc"""\nP = "/Users/someone/code"\n'
    )
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(m in node.value for m in DEVELOPER_MARKERS)
    }
    assert literals == {"/Users/someone/doc", "/Users/someone/code"}


def test_the_detector_reads_a_home_join_and_spares_the_state_tree():
    """The shape that carries RH's real debt, and the one that is not debt."""
    tree = ast.parse(
        "from pathlib import Path\n"
        'A = Path.home() / "code" / "sibling-repo"\n'
        'B = Path.home() / ".research-harness" / "tickets"\n'
        'C = Path("x") / "code" / "sibling-repo"\n'
    )
    joins = [_home_join_segments(node) for node in ast.walk(tree)]
    assert ["code", "sibling-repo"] in joins
    assert [".research-harness", "tickets"] in joins
    # C has no Path.home() base; the two real chains each also yield their left spine.
    assert all(
        segments[0] in {"code", ".research-harness"} for segments in joins if segments
    )


def test_a_computed_segment_is_not_a_home_layout_claim():
    """``Path.home() / CONFIG_DIRNAME`` says nothing about how a home is arranged."""
    tree = ast.parse("from pathlib import Path\nD = Path.home() / CONFIG_DIRNAME\n")
    assert all(_home_join_segments(node) == [] for node in ast.walk(tree))
