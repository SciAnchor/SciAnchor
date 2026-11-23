"""The `scianchor` PyPI wheel bundles the engine's workspace packages.

packaging/scianchor/pyproject.toml must stay a superset of what the bundled
packages declare, or `pip install scianchor` would miss a dependency, an extra
or a console command that a per-package install provides.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUNDLED = ("llm_router", "paperindex", "research_harness", "research_harness_mcp")


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text())["project"]


def _bundle() -> dict:
    return tomllib.loads((ROOT / "packaging/scianchor/pyproject.toml").read_text())


def test_bundle_bundles_every_engine_package() -> None:
    include = _bundle()["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    for name in BUNDLED:
        assert include.get(f"../../packages/{name}/{name}") == name
        assert (ROOT / "packages" / name / name).is_dir()
    assert (
        include.get("../../packages/research_harness/migrations")
        == "research_harness/migrations"
    )


def test_bundle_dependencies_cover_the_bundled_packages() -> None:
    bundle = _bundle()["project"]
    deps = set(bundle["dependencies"])
    extras = bundle.get("optional-dependencies", {})
    scripts = bundle.get("scripts", {})
    for name in BUNDLED:
        project = _project(ROOT / "packages" / name / "pyproject.toml")
        assert set(project.get("dependencies", [])) <= deps, name
        for extra, reqs in project.get("optional-dependencies", {}).items():
            if extra == "dev":
                continue
            if name == "llm_router":  # research_harness uses llm_router[all]
                assert set(reqs) <= deps, f"{name}[{extra}]"
            else:
                assert set(reqs) <= set(extras.get(extra, [])), f"{name}[{extra}]"
        for command, target in project.get("scripts", {}).items():
            assert scripts.get(command) == target, command


def test_bundle_metadata_matches_the_engine() -> None:
    bundle = _bundle()["project"]
    engine = _project(ROOT / "packages/research_harness/pyproject.toml")
    assert bundle["name"] == "scianchor"
    assert bundle["version"] == engine["version"]
    assert bundle["license"] == engine["license"]
    assert bundle["requires-python"] == engine["requires-python"]
