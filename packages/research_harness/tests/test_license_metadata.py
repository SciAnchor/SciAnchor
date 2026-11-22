from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_root_license_is_cc_by_nc() -> None:
    license_text = (ROOT / "LICENSE").read_text()

    assert "Copyright (c) 2026 Research Harness Contributors" in license_text
    assert "SPDX-License-Identifier: CC-BY-NC-4.0" in license_text
    assert "Attribution-NonCommercial 4.0 International" in license_text
    assert (
        "NonCommercial means not primarily intended for or directed towards"
        in license_text
    )


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
    expected = "CC-BY-NC-4.0"
    pyprojects = sorted((ROOT / "packages").glob("*/pyproject.toml"))

    assert pyprojects, "expected at least one package pyproject"
    for pyproject in pyprojects:
        data = tomllib.loads(pyproject.read_text())
        project = data.get("project", {})
        assert project.get("license") == expected, (
            f"{pyproject.relative_to(ROOT)} must not advertise a license "
            "different from the repository root"
        )
