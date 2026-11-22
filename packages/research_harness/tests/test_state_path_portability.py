"""State goes where this install keeps state, not where the caller happened to be standing.

A module-level ``Path(".research-harness") / x`` resolves against the current working
directory. On a development checkout the cwd is the workspace root, so it coincides with the
real state tree and nothing looks wrong for as long as the code never leaves that machine.
Anywhere else the cwd is whatever directory invoked the process: the write lands in a stray
`.research-harness` beside the caller and the real tree never sees it. `rh paper acquire` had
never once run on a multi-tenant host for exactly this reason — it died on
``PermissionError: [Errno 13] Permission denied: '.research-harness'`` in a home directory the
service account could traverse but not write, and the topic pool stayed metadata-only, which
is what an exemplar pack was being curated from.

`default_state_dir` already resolved this correctly for the database and the auto-runner. These
tests keep everything else on the same resolver.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_harness.config import default_state_dir, state_path

PACKAGE = Path(__file__).resolve().parent.parent / "research_harness"
#: Constructing a state path from a bare relative literal. A comparison against the same string
#: is not this defect, and neither is naming it in help text, so the pattern is the constructor.
CWD_RELATIVE_STATE = re.compile(r'Path\(\s*f?"\.research-harness')


def test_no_module_constructs_state_from_the_working_directory():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if (
                CWD_RELATIVE_STATE.search(line)
                and "state_path" not in line
                and '"""' not in line
            ):
                offenders.append(
                    f"{path.relative_to(PACKAGE)}:{number}: {line.strip()}"
                )
    assert not offenders, (
        "these resolve state against the caller's working directory; use "
        "research_harness.config.state_path(...) instead:\n  " + "\n  ".join(offenders)
    )


def test_state_path_is_absolute_and_follows_the_database(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "RESEARCH_HARNESS_DB_PATH", str(tmp_path / ".research-harness" / "pool.db")
    )
    monkeypatch.chdir(tmp_path.parent)
    resolved = state_path("downloads")
    assert resolved.is_absolute()
    assert resolved == tmp_path / ".research-harness" / "downloads"
    assert resolved.parent == default_state_dir()


@pytest.mark.parametrize(
    "module, attribute",
    [
        ("research_harness.acquisition.pipeline", "DEFAULT_DOWNLOAD_DIR"),
        ("research_harness.acquisition.pipeline", "DEFAULT_MANUAL_DIR"),
        ("research_harness.acquisition.yield_monitor", "DEFAULT_LEDGER"),
    ],
)
def test_acquisition_defaults_are_absolute(module, attribute):
    """Acquisition is the one the host actually tripped over, so it is named explicitly."""
    import importlib

    value = Path(str(getattr(importlib.import_module(module), attribute)))
    assert value.is_absolute(), (
        f"{module}.{attribute} is relative to the caller's cwd: {value}"
    )
