"""Tier-aware pytest configuration for backend_stability tests.

Adds a ``--tier`` CLI option that auto-translates to pytest marker
filters. Without ``--tier``, runs the smoke tier (safest default).

Usage:
    pytest packages/research_harness/tests/backend_stability --tier smoke
    pytest packages/research_harness/tests/backend_stability --tier pre_merge
    pytest packages/research_harness/tests/backend_stability --tier nightly

Tier semantics live in packages/research_harness/pyproject.toml.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .replay.recorder import install_replay_hook, uninstall_replay_hook

_VALID_TIERS = ("smoke", "pre_merge", "nightly", "all")

# Tier gating must apply ONLY to backend_stability tests. pytest invokes every
# ``pytest_collection_modifyitems`` hook with the full session item list,
# regardless of which conftest declared it, so without this scope the tier
# filter silently skips the entire unit/integration suite during a plain
# ``pytest packages/`` run (defaulting to the smoke tier).
_BACKEND_STABILITY_DIR = Path(__file__).resolve().parent


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--tier",
        action="store",
        default=os.environ.get("RH_TEST_TIER", "smoke"),
        choices=_VALID_TIERS,
        help=(
            "Which test tier to run. smoke=<3min structural checks, "
            "pre_merge=<15min with record-or-replay, nightly=full E2E with "
            "live LLM. Default: smoke."
        ),
    )
    parser.addoption(
        "--replay-mode",
        action="store",
        default=os.environ.get("RH_REPLAY_MODE", "replay"),
        choices=("record", "replay", "auto"),
        help="LLM replay mode: record hits real LLM, replay is cache-only, auto stubs on miss.",
    )
    parser.addoption(
        "--replay-file",
        action="store",
        default=os.environ.get(
            "RH_REPLAY_FILE",
            str(_default_replay_path()),
        ),
        help="Path to jsonl replay cache.",
    )


def _default_replay_path() -> str:
    from pathlib import Path

    return str(Path(__file__).parent / "replay" / "cache" / "default.jsonl")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip tests that don't match the selected tier.

    Selection rules:
      smoke     → only items marked @pytest.mark.smoke OR @pytest.mark.regression
      pre_merge → smoke + pre_merge + regression
      nightly   → everything
      all       → everything (explicit override)
    """
    tier = config.getoption("--tier")
    if tier == "all" or tier == "nightly":
        return  # collect everything

    allowed: set[str]
    if tier == "smoke":
        allowed = {"smoke", "regression"}
    else:  # pre_merge
        allowed = {"smoke", "pre_merge", "regression"}

    skip_marker = pytest.mark.skip(
        reason=f"tier={tier} — this test needs a higher tier"
    )
    for item in items:
        if not _is_backend_stability_item(item):
            continue  # tier gating is scoped to backend_stability tests only
        marks = {m.name for m in item.iter_markers()}
        # Un-marked tests default to pre_merge (must be explicit about tier)
        if not marks & {"smoke", "pre_merge", "nightly", "regression"}:
            marks.add("pre_merge")
        if not marks & allowed:
            item.add_marker(skip_marker)


def _is_backend_stability_item(item: pytest.Item) -> bool:
    """True only for items collected from under ``backend_stability/``."""
    raw_path = getattr(item, "path", None) or getattr(item, "fspath", None)
    if raw_path is None:
        return False
    item_path = Path(str(raw_path)).resolve()
    return _BACKEND_STABILITY_DIR in item_path.parents


@pytest.fixture(autouse=True)
def _install_llm_replay(request: pytest.FixtureRequest):
    """Install record/replay only around backend_stability tests.

    A session-scoped hook leaked into later non-backend tests during full-suite
    runs, causing ordinary LLM unit tests to fail on unrelated replay misses.
    """
    mode = request.config.getoption("--replay-mode")
    cache_file = request.config.getoption("--replay-file")
    try:
        install_replay_hook(cache_path=cache_file, mode=mode)
    except Exception as exc:  # noqa: BLE001 — hook is best-effort at collection
        pytest.skip(f"cannot install LLM replay hook: {exc}")
    yield
    uninstall_replay_hook()
