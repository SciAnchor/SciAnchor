from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_root_license_is_agpl_verbatim() -> None:
    """LICENSE holds only the AGPL-3.0 text so GitHub can detect the license."""
    license_text = (ROOT / "LICENSE").read_text()

    assert license_text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in license_text
    assert "Research Harness" not in license_text


def test_notice_carries_copyright_and_commercial_option() -> None:
    notice = (ROOT / "NOTICE").read_text()

    assert "Copyright (c) 2026 Research Harness Contributors" in notice
    assert "AGPL-3.0-only" in notice
    assert "commercial license" in notice


def test_third_party_notices_keep_adapted_mit_code_attributed() -> None:
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    marker = (
        "Adapted from " + "AutoResearchClaw (MIT license)"
    )  # not matching this file
    adapted = [
        path
        for path in (ROOT / "packages").rglob("*.py")
        if marker in path.read_text(errors="ignore")
    ]
    assert adapted
    assert "Copyright (c) 2026 Aiming Lab" in notices
    for path in adapted:
        assert str(path.relative_to(ROOT)) in notices


def test_python_package_license_metadata_matches_root_license() -> None:
    expected = "AGPL-3.0-only"
    pyprojects = sorted((ROOT / "packages").glob("*/pyproject.toml"))

    assert pyprojects, "expected at least one package pyproject"
    for pyproject in pyprojects:
        data = tomllib.loads(pyproject.read_text())
        project = data.get("project", {})
        assert project.get("license") == expected, (
            f"{pyproject.relative_to(ROOT)} must not advertise a license "
            "different from the repository root"
        )
