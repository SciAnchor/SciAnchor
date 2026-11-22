from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "src" / "paperfetch" / "data" / "reference"


def test_spc_wheel_declares_runtime_data() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    patterns = set(project["tool"]["setuptools"]["package-data"]["paperfetch"])
    assert {
        "data/reference/*.json",
        "data/workflow/manifests/*.json",
        "data/workflow/schemas/*.json",
        "data/workflow/fixtures/*.json",
    } <= patterns
    assert not any("venue_ana" in item or "manuscript" in item for item in patterns)
    assert not any("journal_master" in item for item in patterns)


def test_only_openly_licensed_reference_data_is_shipped() -> None:
    assert (REFERENCE_ROOT / "ccf_ranks_2026.json").is_file()
    shipped = {
        path.relative_to(REFERENCE_ROOT).as_posix()
        for path in REFERENCE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    for restricted in (
        "derived/journal_master.db",
        "derived/jcr_2025.json",
        "derived/cas_zones_2025.json",
        "derived/xr_zones_2026.json",
        "derived/warning_journals_2025.json",
        "xr_conferences_2026.json",
        "journal_master_2025.json",
        "cas_zones_2025.sources.json",
        "active_special_issues.jsonl",
        "runtime/monitored_journals.json",
    ):
        assert restricted not in shipped
    assert not any(item.startswith("runtime/") for item in shipped)
