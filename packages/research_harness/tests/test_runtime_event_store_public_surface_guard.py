from __future__ import annotations

from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)

PUBLIC_SURFACE_FILES = (
    "packages/research_harness/research_harness/__init__.py",
    "packages/research_harness/research_harness/api.py",
    "packages/research_harness/research_harness/cli.py",
    "packages/research_harness/research_harness/runtime/__init__.py",
    "packages/research_harness/research_harness/skill/__init__.py",
    "packages/research_harness/research_harness/skill/cli.py",
    "packages/research_harness/research_harness/zotero_resource.py",
    "packages/research_harness/research_harness/zotero_sync.py",
    "packages/research_harness_mcp/research_harness_mcp/__init__.py",
    "packages/research_harness_mcp/research_harness_mcp/http_api.py",
    "packages/research_harness_mcp/research_harness_mcp/tools.py",
)

PUBLIC_SKILL_DIRS = (
    "skills",
    "docs/skills",
    "site/skills",
)

FORBIDDEN_PRIVATE_EVENT_STORE_TOKENS = (
    "research_harness.runtime.event_store",
    "_append_runtime_event",
    "_read_runtime_event_by_event_id",
    "_read_runtime_events",
    "_diagnose_runtime_event_store",
    "RuntimeEventWriteResult",
    "RuntimeEventStoreRecord",
    "RuntimeEventStoreHealth",
)


def test_runtime_event_store_helpers_are_absent_from_public_surfaces() -> None:
    offenders: list[str] = []
    for path in _public_surface_paths():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_PRIVATE_EVENT_STORE_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} exposes {token}")

    assert offenders == []


def _public_surface_paths() -> tuple[Path, ...]:
    paths = [REPO_ROOT / relative for relative in PUBLIC_SURFACE_FILES]
    for relative_dir in PUBLIC_SKILL_DIRS:
        root = REPO_ROOT / relative_dir
        if not root.exists():
            continue
        paths.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in {".md", ".json", ".toml", ".yaml", ".yml"}
        )
    return tuple(path for path in paths if path.exists())
