"""Importers for Papers-with-Code archive dumps (offline ``.json.gz`` files).

Both importers are bounded on purpose: code links are only imported for papers
already present in the store (never the full 300k-link dump), and evaluation
tables are filtered by domain keywords before anything is created.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..store import PanoramaStore

_LINKS_FILE = "links-between-papers-and-code.json.gz"
_EVAL_FILE = "evaluation-tables.json.gz"
_SUMMARY_MAX = 600
_ARXIV_VERSION_RE = re.compile(r"v\d+$")


def _truncate(text: str | None, limit: int = _SUMMARY_MAX) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _load_gz_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _norm_arxiv(value: str | None) -> str:
    value = (value or "").strip().lower()
    return _ARXIV_VERSION_RE.sub("", value)


def _repo_name(repo_url: str) -> str:
    """Return the repo URL path (e.g. ``owner/repo``), falling back to the URL."""
    path = urlparse(repo_url).path.strip("/")
    name = path or repo_url
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name


def import_pwc_code_links(
    store: PanoramaStore,
    direction_id: int,
    archive_dir: Path | str,
) -> dict[str, int]:
    """Link already-imported papers (by arxiv ext id) to their code repos.

    Parses ``links-between-papers-and-code.json.gz`` and creates one
    ``code_repo`` entity plus a ``repo --implements--> paper`` edge per link
    whose arxiv id matches a paper entity in the store. Records with missing
    keys are skipped.
    """
    archive = Path(archive_dir).expanduser()
    records = _load_gz_json(archive / _LINKS_FILE)
    by_arxiv: dict[str, list[dict[str, Any]]] = {}
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        arxiv_id = _norm_arxiv(record.get("paper_arxiv_id"))
        repo_url = (record.get("repo_url") or "").strip()
        if not arxiv_id or not repo_url:
            continue
        by_arxiv.setdefault(arxiv_id, []).append(record)

    counts = {"papers_matched": 0, "repos_imported": 0, "edges": 0}
    for paper in store.entities(direction_id, kind="paper"):
        arxiv_id = _norm_arxiv((paper.get("ext_ids") or {}).get("arxiv"))
        if not arxiv_id or arxiv_id not in by_arxiv:
            continue
        counts["papers_matched"] += 1
        for record in by_arxiv[arxiv_id]:
            repo_url = record["repo_url"].strip()
            name = _repo_name(repo_url)
            if "github" in (urlparse(repo_url).netloc or ""):
                ext_ids = {"github": name}
            else:
                ext_ids = {"repo": repo_url}
            attrs = {
                "url": repo_url,
                "is_official": bool(record.get("is_official")),
                "framework": record.get("framework") or "",
            }
            repo_id = store.upsert_entity(
                direction_id,
                "code_repo",
                name,
                attrs=attrs,
                ext_ids=ext_ids,
                source="pwc",
            )
            counts["repos_imported"] += 1
            store.add_edge(direction_id, repo_id, paper["id"], "implements")
            counts["edges"] += 1
    return counts


def import_pwc_benchmarks(
    store: PanoramaStore,
    direction_id: int,
    archive_dir: Path | str,
    keywords: list[str] | tuple[str, ...],
) -> dict[str, int]:
    """Import benchmark tasks (and their datasets) matching domain keywords.

    Walks the nested task tree in ``evaluation-tables.json.gz``; a task
    matches when any keyword is a case-insensitive substring of its name or
    description. Matching tasks become ``benchmark`` entities, their datasets
    become ``dataset`` entities with ``dataset --derived_from--> benchmark``
    edges. Non-matching tasks are still walked so matching subtasks are found.
    """
    archive = Path(archive_dir).expanduser()
    tasks = _load_gz_json(archive / _EVAL_FILE)
    needles = [k.strip().casefold() for k in keywords if k and k.strip()]
    counts = {
        "tasks_matched": 0,
        "benchmarks_imported": 0,
        "datasets_imported": 0,
        "edges": 0,
    }
    if not needles:
        return counts

    seen_tasks: set[str] = set()
    stack = [
        r for r in (tasks if isinstance(tasks, list) else []) if isinstance(r, dict)
    ]
    while stack:
        record = stack.pop()
        subtasks = record.get("subtasks")
        if isinstance(subtasks, list):
            stack.extend(r for r in subtasks if isinstance(r, dict))
        task_name = (record.get("task") or "").strip()
        if not task_name or task_name in seen_tasks:
            continue
        haystack = f"{task_name} {record.get('description') or ''}".casefold()
        if not any(needle in haystack for needle in needles):
            continue
        seen_tasks.add(task_name)
        counts["tasks_matched"] += 1
        attrs = {
            key: value
            for key, value in (
                ("categories", record.get("categories")),
                ("source_link", record.get("source_link")),
            )
            if value
        }
        bench_id = store.upsert_entity(
            direction_id,
            "benchmark",
            task_name,
            summary=_truncate(record.get("description")),
            attrs=attrs,
            source="pwc",
        )
        counts["benchmarks_imported"] += 1
        datasets = record.get("datasets")
        for dataset in datasets if isinstance(datasets, list) else []:
            if not isinstance(dataset, dict):
                continue
            ds_name = (dataset.get("dataset") or "").strip()
            if not ds_name:
                continue
            ds_id = store.upsert_entity(
                direction_id,
                "dataset",
                ds_name,
                summary=_truncate(dataset.get("description")),
                source="pwc",
            )
            counts["datasets_imported"] += 1
            store.add_edge(direction_id, ds_id, bench_id, "derived_from")
            counts["edges"] += 1
    return counts
