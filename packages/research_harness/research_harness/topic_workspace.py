"""Topic workspace materialization for rh-workspace."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


STANDARD_DIRECTORIES = (
    "00-task-framing",
    "01-literature/papers",
    "01-literature/originals",
    "02-evidence-map",
    "03-proposals",
    "04-experiments",
    "05-weekly",
    "06-writing",
    "feedback",
)
_TOPIC_ID_PATTERNS = (
    re.compile(r"\btopic id:\s*`?(\d+)`?\b", re.IGNORECASE),
    re.compile(r"\bRH topic id:\s*`?(\d+)`?\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class TopicWorkspaceResult:
    topic_id: int
    topic_name: str
    workspace_path: Path
    created_files: list[Path] = field(default_factory=list)
    created_directories: list[Path] = field(default_factory=list)


def slugify_workspace_segment(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "topic"


def _write_if_missing(path: Path, content: str, created: list[Path]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(path)


def _topic_readme(
    *,
    topic_id: int,
    topic_name: str,
    description: str,
    target_venue: str,
    deadline: str,
    db_path: str,
) -> str:
    return f"""# {topic_name}

Canonical Research Harness topic: `{topic_name}`

- RH topic id: {topic_id}
- Target venue: {target_venue or "unspecified"}
- Deadline: {deadline or "unspecified"}
- RH database: `{db_path or "runtime default"}`

## Scope

{description or "No description recorded yet."}

## Directory Conventions

- `00-task-framing/`: task definition, scope, research questions.
- `01-literature/`: paper manifests, source pointers, reading notes.
- `02-evidence-map/`: evidence, claims, gaps, and positioning.
- `03-proposals/`: candidate stories and proposal drafts.
- `04-experiments/`: experiment design and evaluation plans.
- `05-weekly/`: handoff and progress logs.
- `06-writing/`: paper/report drafts and publication outputs.
- `feedback/`: RH product and workflow gaps discovered during this topic.

Research Harness remains the authoritative structured store for papers,
claims, provenance, and artifacts. Keep original PDFs in the canonical RH
store and reference them here by manifest entry or symlink.
"""


def _topic_brief(
    *,
    topic_id: int,
    topic_name: str,
    description: str,
    target_venue: str,
    deadline: str,
) -> str:
    return f"""# {topic_name} - Topic Brief v0

RH topic id: {topic_id}
Status: initialized
Target venue: {target_venue or "unspecified"}
Deadline: {deadline or "unspecified"}

## Working Definition

{description or "No description recorded yet."}

## Open Questions

1. What claim should this topic defend?
2. Which evidence artifacts are authoritative for that claim?
3. What gates must pass before the topic can move to writing or submission?
"""


def _paper_manifest(topic_id: int, topic_name: str) -> str:
    return f"""# {topic_name} Paper Manifest

RH topic id: {topic_id}

Research Harness DB is authoritative. Every paper used in reasoning should be
ingested into RH with this topic id and listed here when it becomes part of the
working corpus.

## Linked Corpus

No local paper manifest has been generated yet.
"""


def _originals_readme() -> str:
    return """# Original Paper Files

Prefer RH's canonical PDF store. Use this directory for symlinks or manifest
entries pointing to canonical absolute paths; do not scatter copied PDFs here.
"""


def _feedback_readme(topic_name: str) -> str:
    return f"""# Feedback for {topic_name}

Record reusable RH workflow, tool, or product gaps found while working on this
topic. Avoid one-off debugging logs here.
"""


def materialize_topic_workspace(
    *,
    workspace_root: Path | str | None,
    topic_id: int,
    topic_name: str,
    description: str = "",
    target_venue: str = "",
    deadline: str = "",
    db_path: Path | str | None = None,
    workspace_domain: str | None = None,
    slug: str | None = None,
) -> TopicWorkspaceResult | None:
    if workspace_root is None:
        return None

    root = Path(workspace_root).expanduser().resolve()
    topic_slug = slugify_workspace_segment(slug or topic_name)
    if workspace_domain:
        path = root / slugify_workspace_segment(workspace_domain) / topic_slug
    else:
        path = root / topic_slug

    created_dirs: list[Path] = []
    for relative in STANDARD_DIRECTORIES:
        directory = path / relative
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created_dirs.append(directory)

    created_files: list[Path] = []
    db_label = str(Path(db_path).expanduser().resolve()) if db_path else ""
    _write_if_missing(
        path / "README.md",
        _topic_readme(
            topic_id=topic_id,
            topic_name=topic_name,
            description=description,
            target_venue=target_venue,
            deadline=deadline,
            db_path=db_label,
        ),
        created_files,
    )
    _write_if_missing(
        path / "00-task-framing" / "topic-brief-v0.md",
        _topic_brief(
            topic_id=topic_id,
            topic_name=topic_name,
            description=description,
            target_venue=target_venue,
            deadline=deadline,
        ),
        created_files,
    )
    _write_if_missing(
        path / "01-literature" / "papers" / "manifest.md",
        _paper_manifest(topic_id, topic_name),
        created_files,
    )
    _write_if_missing(
        path / "01-literature" / "originals" / "README.md",
        _originals_readme(),
        created_files,
    )
    _write_if_missing(
        path / "feedback" / "README.md",
        _feedback_readme(topic_name),
        created_files,
    )

    return TopicWorkspaceResult(
        topic_id=topic_id,
        topic_name=topic_name,
        workspace_path=path,
        created_files=created_files,
        created_directories=created_dirs,
    )


def discover_topic_id_from_workspace(start: str | Path | None = None) -> int | None:
    """Infer an RH topic id from standard rh-workspace markdown metadata."""

    current = Path(start or Path.cwd()).expanduser().resolve()
    candidates = [current, *current.parents]
    if not any(directory.name == "rh-workspace" for directory in candidates):
        return None
    for directory in candidates:
        topic_id = _topic_id_from_workspace_file(directory / "README.md")
        if topic_id is not None:
            return topic_id
        topic_id = _topic_id_from_workspace_file(
            directory / "00-task-framing" / "topic-brief-v0.md"
        )
        if topic_id is not None:
            return topic_id
        if directory.name == "rh-workspace":
            break
    return None


def _topic_id_from_workspace_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for pattern in _TOPIC_ID_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        try:
            topic_id = int(match.group(1))
        except ValueError:
            continue
        if topic_id > 0:
            return topic_id
    return None
