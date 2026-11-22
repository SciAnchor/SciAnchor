#!/usr/bin/env python3
"""Build non-gold AutoResearchBench candidate metadata from public queries.

The script reads only adapter-visible task inputs. It never opens gold files or
the official plaintext benchmark rows, and it writes paper metadata suitable for
`rh researchflowbench build-autoresearchbench-candidate-source`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "packages" / "research_harness"
sys.path.insert(0, str(PACKAGE_ROOT))

from research_harness.paper_source_clients import ArxivProvider, OpenAlexProvider  # noqa: E402
from research_harness.paper_sources import PaperRecord, SearchQuery  # noqa: E402


STOPWORDS = {
    "about",
    "across",
    "after",
    "algorithm",
    "also",
    "analysis",
    "another",
    "based",
    "because",
    "before",
    "being",
    "between",
    "contain",
    "containing",
    "contains",
    "dataset",
    "describes",
    "different",
    "exact",
    "experiments",
    "find",
    "finding",
    "from",
    "have",
    "into",
    "looking",
    "materials",
    "method",
    "methods",
    "model",
    "models",
    "paper",
    "papers",
    "performance",
    "publication",
    "published",
    "research",
    "results",
    "specific",
    "study",
    "supplementary",
    "table",
    "task",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "three",
    "where",
    "which",
    "with",
}

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}")
ARXIV_ID_RE = re.compile(r"(?i)(\d{4}\.\d{4,5})(?:v\d+)?")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-pack", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--task-limit", type=int, default=None)
    parser.add_argument("--provider", choices=("openalex", "arxiv"), default="openalex")
    parser.add_argument("--variant-passes", type=int, default=6)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--arxiv-min-interval-sec", type=float, default=10.0)
    parser.add_argument("--openalex-min-interval-sec", type=float, default=1.0)
    parser.add_argument("--include-raw-visible", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.task_limit is not None and args.task_limit < 1:
        raise ValueError("--task-limit must be positive")
    if args.variant_passes < 1:
        raise ValueError("--variant-passes must be positive")
    if args.max_results < 1:
        raise ValueError("--max-results must be positive")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    tasks = load_visible_tasks(args.task_pack, limit=args.task_limit)
    raw_path = args.out_dir / f"{args.provider}_metadata.jsonl"
    trace_path = args.out_dir / "query_trace.jsonl"
    summary_path = args.out_dir / "summary.json"

    completed = load_completed_queries(trace_path) if args.resume else set()
    records = load_existing_records(raw_path) if args.resume else {}
    if args.provider == "arxiv":
        provider = ArxivProvider(fetcher=polite_text_fetcher)
        provider._min_interval = args.arxiv_min_interval_sec
        provider_interval = 0.0
    else:
        provider = OpenAlexProvider()
        provider_interval = args.openalex_min_interval_sec

    planned = []
    for task in tasks:
        variants = task_query_variants(
            task["question"], include_raw=args.include_raw_visible
        )
        for variant in variants[: args.variant_passes]:
            key = (task["task_id"], variant["variant_id"])
            if key not in completed:
                planned.append((task, variant))

    started_at = utc_now()
    write_summary(
        summary_path,
        started_at=started_at,
        finished_at="",
        task_count=len(tasks),
        planned_query_count=len(planned),
        completed_query_count=len(completed),
        unique_record_count=len(records),
        error_count=0,
        status="dry_run" if args.dry_run else "running",
    )
    print(
        json.dumps(
            {
                "status": "planned",
                "task_count": len(tasks),
                "planned_query_count": len(planned),
                "existing_record_count": len(records),
                "out_dir": str(args.out_dir),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.dry_run:
        return 0

    errors = 0
    with (
        raw_path.open("a", encoding="utf-8") as raw_handle,
        trace_path.open("a", encoding="utf-8") as trace_handle,
    ):
        for index, (task, variant) in enumerate(planned, 1):
            trace: dict[str, Any] = {
                "schema_version": (
                    "researchflowbench.autoresearchbench_public_query_trace.v0.1"
                ),
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "variant_id": variant["variant_id"],
                "query": variant["query"],
                "provider": args.provider,
                "max_results": args.max_results,
                "started_at": utc_now(),
                "result_count": 0,
                "new_record_count": 0,
                "error": "",
            }
            try:
                results = provider.search(
                    SearchQuery(
                        query=variant["query"],
                        limit=args.max_results,
                        per_provider_limit=args.max_results,
                    )
                )
                for record in results:
                    payload = paper_record_to_candidate(record)
                    if not payload:
                        continue
                    fingerprint = candidate_fingerprint(payload)
                    if fingerprint in records:
                        continue
                    records[fingerprint] = payload
                    trace["new_record_count"] += 1
                    raw_handle.write(
                        json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
                    )
                trace["result_count"] = len(results)
            except Exception as exc:  # noqa: BLE001 - keep long run resilient.
                errors += 1
                trace["error"] = f"{type(exc).__name__}: {exc}"
                time.sleep(min(args.arxiv_min_interval_sec * 2, 30.0))
            trace["finished_at"] = utc_now()
            trace_handle.write(
                json.dumps(trace, sort_keys=True, ensure_ascii=False) + "\n"
            )
            raw_handle.flush()
            trace_handle.flush()
            if provider_interval > 0:
                time.sleep(provider_interval)

            if index % 25 == 0 or index == len(planned):
                write_summary(
                    summary_path,
                    started_at=started_at,
                    finished_at="",
                    task_count=len(tasks),
                    planned_query_count=len(planned),
                    completed_query_count=len(completed) + index,
                    unique_record_count=len(records),
                    error_count=errors,
                    status="running",
                )
                print(
                    json.dumps(
                        {
                            "status": "progress",
                            "completed": index,
                            "planned": len(planned),
                            "unique_records": len(records),
                            "errors": errors,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    write_summary(
        summary_path,
        started_at=started_at,
        finished_at=utc_now(),
        task_count=len(tasks),
        planned_query_count=len(planned),
        completed_query_count=len(completed) + len(planned),
        unique_record_count=len(records),
        error_count=errors,
        status="complete",
    )
    return 0


def load_visible_tasks(task_pack: Path, *, limit: int | None) -> list[dict[str, str]]:
    task_files = sorted((task_pack / "tasks").glob("*/input.json"))
    tasks: list[dict[str, str]] = []
    for path in task_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        question = str(
            payload.get("question")
            or (payload.get("input") or {}).get("question")
            or ""
        ).strip()
        if not question:
            continue
        tasks.append(
            {
                "task_id": str(payload.get("task_id") or path.parent.name),
                "task_type": str(payload.get("task_type") or "unknown"),
                "question": question,
            }
        )
        if limit is not None and len(tasks) >= limit:
            break
    return tasks


def task_query_variants(question: str, *, include_raw: bool) -> list[dict[str, str]]:
    tokens = keyword_tokens(question)
    raw = compact_query(question, max_chars=220)
    candidates = []
    if include_raw:
        candidates.append(("raw_visible", raw))
    candidates.extend(
        [
            ("keywords12", " ".join(tokens[:12])),
            ("keywords8", " ".join(tokens[:8])),
            ("keywords5", " ".join(tokens[:5])),
            ("keywords3", " ".join(tokens[:3])),
            ("keywords_tail8", " ".join(tokens[-8:])),
            ("keywords_tail5", " ".join(tokens[-5:])),
        ]
    )
    if not any(query for _, query in candidates):
        candidates.append(("raw_visible_fallback", raw))
    variants: list[dict[str, str]] = []
    seen: set[str] = set()
    for variant_id, query in candidates:
        normalized = compact_query(query, max_chars=220)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        variants.append({"variant_id": variant_id, "query": normalized})
    return variants


def keyword_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("-_")
        if len(token) < 4 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def compact_query(text: str, *, max_chars: int) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(" ", 1)[0]


def paper_record_to_candidate(record: PaperRecord) -> dict[str, Any] | None:
    title = (record.title or "").strip()
    abstract = (record.abstract or "").strip()
    if not title and not abstract:
        return None
    doi = (record.doi or "").strip()
    openalex_id = (record.openalex_id or "").strip()
    url = (record.url or "").strip()
    arxiv_id = extract_arxiv_id(record.arxiv_id, require_marker=False) or (
        extract_arxiv_id(doi, url, openalex_id, require_marker=True)
    )
    paper_id = (
        arxiv_id
        or doi
        or openalex_id
        or hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    )
    return {
        "paper_id": paper_id,
        "title": title,
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "openalex_id": openalex_id,
        "provider": (record.provider or "").strip(),
        "url": url,
        "year": record.year,
    }


def extract_arxiv_id(*values: Any, require_marker: bool) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if require_marker and "arxiv" not in text.lower():
            continue
        match = ARXIV_ID_RE.search(text)
        if match:
            return match.group(1)
    return ""


def polite_text_fetcher(url: str, headers: dict[str, str]) -> str:
    request_headers = {
        **headers,
        "User-Agent": "ResearchHarness/AutoResearchBenchCandidateBuilder "
        "(metadata-only; contact: local)",
    }
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 429 and exc.code < 500:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            wait = float(retry_after) if retry_after and retry_after.isdigit() else 60.0
            time.sleep(min(wait * (attempt + 1), 300.0))
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(min(15.0 * (attempt + 1), 120.0))
    raise RuntimeError(f"arXiv request failed after retries: {last_error}")


def candidate_fingerprint(record: dict[str, Any]) -> str:
    for key in ("arxiv_id", "doi", "paper_id"):
        value = str(record.get(key) or "").strip().lower()
        if value:
            return f"{key}:{value}"
    title = str(record.get("title") or "").strip().lower()
    return "title:" + hashlib.sha256(title.encode("utf-8")).hexdigest()


def load_existing_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records[candidate_fingerprint(payload)] = payload
    return records


def load_completed_queries(path: Path) -> set[tuple[str, str]]:
    completed: set[tuple[str, str]] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                completed.add(
                    (
                        str(payload.get("task_id") or ""),
                        str(payload.get("variant_id") or ""),
                    )
                )
    return completed


def write_summary(path: Path, **payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
