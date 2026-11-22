"""RH -> SPC direction of the paperfetch contract bridge.

Two capabilities, both free of any ``paperfetch`` import:

- a wants-list export: papers RH could not acquire natively, shaped as SPC
  manual seeds so the operator can hand them to ``spc curate`` unchanged;
- an SPC provider readiness probe for ``rh doctor`` (CLI on PATH, shared
  PaperVault database configured), reported as an optional provider — SPC
  being absent is never a failure.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..papervault_source import PAPERVAULT_DB_ENV
from ..storage.db import Database
from .._workflow.orchestrator.artifacts import ArtifactManager
from .pipeline import _build_candidates

logger = logging.getLogger(__name__)

WANTS_LIST_SCHEMA_VERSION = "rh.spc_wants_list.v1"


def _latest_failure_taxonomy(conn: Any, paper_id: int) -> str | None:
    row = conn.execute(
        "SELECT metadata FROM paper_artifacts"
        " WHERE paper_id = ? AND artifact_type IN"
        " ('pdf_route_audit', 'external_route_audit')"
        " ORDER BY id DESC LIMIT 1",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["metadata"])
    except (json.JSONDecodeError, TypeError):
        return None
    value = payload.get("failure_taxonomy")
    return str(value) if value else None


def build_spc_wants_list(
    db: Database, topic_id: int, *, limit: int | None = None
) -> dict[str, Any]:
    """Papers still needing fulltext, shaped as SPC manual seeds.

    Seed entries carry only contract fields (``title``, ``doi``,
    ``arxiv_id``, ``reason``, ``source``); RH context lives in ``reason`` so
    unknown keys never risk tripping SPC-side validation.
    """
    candidates = _build_candidates(db, topic_id, limit=limit)
    seeds: list[dict[str, Any]] = []
    conn = db.connect()
    try:
        for candidate in candidates:
            taxonomy = _latest_failure_taxonomy(conn, candidate.paper_id)
            reason = "rh needs fulltext"
            if taxonomy:
                reason += f"; native acquisition failed: {taxonomy}"
            seed: dict[str, Any] = {
                "title": candidate.title,
                "reason": reason,
                "source": "user_supplied",
            }
            if candidate.doi:
                seed["doi"] = candidate.doi
            if candidate.arxiv_id:
                seed["arxiv_id"] = candidate.arxiv_id
            seeds.append(seed)
    finally:
        conn.close()

    return {
        "schema_version": WANTS_LIST_SCHEMA_VERSION,
        "topic_id": topic_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_count": len(seeds),
        "manual_seeds": seeds,
        "notes": (
            "Feed manual_seeds into an SPC Search Brief; import the resulting"
            " seed pack with research_harness.acquisition.seed_pack_import."
        ),
    }


def export_spc_wants_list(
    db: Database,
    topic_id: int,
    output_path: str | Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Write the wants-list JSON and record it as a topic artifact."""
    payload = build_spc_wants_list(db, topic_id, limit=limit)
    target = Path(output_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="acquisition",
        artifact_type="spc_wants_list",
        title=f"SPC wants-list export ({payload['paper_count']} papers)",
        payload=payload,
        metadata={
            "rh_schema_version": WANTS_LIST_SCHEMA_VERSION,
            "output_path": str(target),
        },
    )
    if artifact.id is None:
        logger.warning("failed to record spc_wants_list artifact")
    return payload


# SPC 2.0 is the first retrieval lane. Public candidates use data or
# results[].data; internal compatibility output uses items[].data.
SPC_MIN_VERSION = (2, 0, 0)


def spc_search(
    query: str,
    *,
    limit: int = 20,
    min_year: int | None = None,
    ccf_rank: str = "",
    min_citations: int = 0,
    timeout_s: float = 180,
    errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Papers from SPC 2.0; unavailable, failed and empty searches fail closed."""
    import subprocess

    def failed(reason: str) -> list[dict[str, Any]]:
        if errors is not None:
            errors.append(f"spc: {reason}")
        raise SPCAcquisitionError("search", {"error": {"code": reason}})

    cli = shutil.which("spc")
    if not cli:
        return failed("unavailable")
    if not query.strip():
        return failed("empty_query")
    try:
        version = subprocess.run(
            [cli, "version"], capture_output=True, text=True, timeout=30
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return failed(f"version_probe:{type(exc).__name__}")
    try:
        version_payload = json.loads(version.stdout)
        if not isinstance(version_payload, dict) or not isinstance(
            version_payload.get("data"), dict
        ):
            return failed("invalid_version_response")
        reported = version_payload["data"].get("version", "")
        parts = tuple(int(p) for p in str(reported).split(".")[:3])
    except (json.JSONDecodeError, TypeError, ValueError):
        return failed("invalid_version_response")
    if getattr(version, "returncode", 0):
        return failed("version_probe_failed")
    if parts < SPC_MIN_VERSION:
        return failed("unsupported_version")
    argv = [
        cli,
        "paper",
        "search",
        "--query",
        query,
        "--limit",
        str(limit),
        "--no-progress",
    ]
    if min_year:
        argv += ["--min-year", str(min_year)]
    if ccf_rank:
        argv += ["--ccf-rank", ccf_rank]
    if min_citations:
        argv += ["--min-citations", str(min_citations)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
        payload = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        return failed(type(exc).__name__)
    if not isinstance(payload, dict):
        return failed("invalid_response")
    if (
        getattr(proc, "returncode", 0)
        or payload.get("status") != "completed"
        or payload.get("error")
    ):
        raise SPCAcquisitionError("search", payload)
    # Production SPC projects a single result to data and multiple results to
    # results[].data; the host compatibility wrapper still emits items[].data.
    items = payload.get("items") or payload.get("results") or []
    if not items and isinstance(payload.get("data"), dict):
        items = [{"data": payload["data"]}]
    records = [
        item["data"]
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("data"), dict)
        and str(item["data"].get("title") or "").strip()
    ]
    if not records:
        return failed("no_results")
    return records


class SPCAcquisitionError(RuntimeError):
    """Machine-readable acquisition failure without upstream secrets."""

    def __init__(self, operation: str, payload: dict[str, Any]):
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        self.code = str(error.get("code") or "spc_operation_failed")
        self.retryable = bool(error.get("retryable", False))
        super().__init__(f"SPC {operation}: {self.code}")


def spc_lookup(identifier: str, *, kind: str) -> dict[str, Any]:
    """Resolve an exact identifier using SPC's public lookup contract."""
    import subprocess

    flags = {
        "doi": "--doi",
        "arxiv": "--arxiv-id",
        "pmid": "--pubmed-id",
        "pmcid": "--pmc-id",
    }
    if kind not in flags:
        raise ValueError("unsupported SPC identifier kind")
    cli = shutil.which("spc")
    if not cli:
        raise SPCAcquisitionError("lookup", {"error": {"code": "unavailable"}})
    try:
        proc = subprocess.run(
            [cli, "paper", "lookup", flags[kind], identifier, "--no-progress"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        payload = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        raise SPCAcquisitionError(
            "lookup",
            {
                "error": {
                    "code": type(exc).__name__,
                    "retryable": True,
                }
            },
        ) from exc
    if not isinstance(payload, dict):
        raise SPCAcquisitionError("lookup", {"error": {"code": "invalid_response"}})
    if proc.returncode or payload.get("status") != "completed" or payload.get("error"):
        raise SPCAcquisitionError("lookup", payload)
    data = payload.get("data") or {}
    if not data and payload.get("items"):
        item = payload["items"][0]
        data = item.get("data") if isinstance(item, dict) else {}
    if not isinstance(data, dict) or not data:
        raise SPCAcquisitionError("lookup", {"error": {"code": "no_results"}})
    return data


def spc_graph(doi: str, *, direction: str, limit: int = 50) -> list[dict[str, Any]]:
    """Expand an exact DOI through production SPC, never a direct RH API."""
    import subprocess

    if direction not in {"references", "citations", "similar"}:
        raise ValueError("invalid citation direction")
    if limit <= 0:
        return []
    cli = shutil.which("spc")
    if not cli:
        raise SPCAcquisitionError("graph", {"error": {"code": "unavailable"}})
    try:
        proc = subprocess.run(
            [
                cli,
                "paper",
                "graph",
                "--doi",
                doi,
                "--direction",
                direction,
                "--limit",
                str(limit),
                "--no-progress",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        payload = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        raise SPCAcquisitionError(
            "graph",
            {
                "error": {
                    "code": type(exc).__name__,
                    "retryable": True,
                }
            },
        ) from exc
    if not isinstance(payload, dict):
        raise SPCAcquisitionError("graph", {"error": {"code": "invalid_response"}})
    if proc.returncode or payload.get("status") != "completed" or payload.get("error"):
        raise SPCAcquisitionError("graph", payload)
    items = payload.get("items") or payload.get("results") or []
    if not items and isinstance(payload.get("data"), dict):
        items = [{"data": payload["data"]}]
    records = [
        item["data"]
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("data"), dict)
        and item["data"].get("title")
    ]
    if not records:
        raise SPCAcquisitionError("graph", {"error": {"code": "no_results"}})
    return records


def spc_download(candidate: Any, output_dir: Path) -> Path:
    """Acquire into an SPC seed pack and return only a contained, regular PDF."""
    import subprocess

    cli = shutil.which("spc")
    if not cli:
        raise RuntimeError("SPC unavailable for PDF acquisition")
    identifier = next(
        (
            (flag, str(value))
            for flag, value in (
                ("--doi", candidate.doi),
                ("--arxiv-id", candidate.arxiv_id),
                ("--pubmed-id", candidate.pmid),
                ("--pmc-id", candidate.pmcid),
            )
            if value
        ),
        None,
    )
    if identifier is None:
        import re
        from urllib.parse import unquote

        for url in (candidate.url, *candidate.extra_urls):
            match = re.search(r"10\.\d{4,9}/[^\s?&#]+", unquote(url or ""))
            if match:
                identifier = ("--doi", match.group(0))
                break
    if identifier is None and candidate.title.strip():
        # Resolve URL-only records by exact title, never by the first fuzzy hit.
        from ..paper_source_clients import build_provider_suite
        from ..paper_sources import SearchAggregator, SearchQuery
        import re

        def normalize(text: str) -> str:
            return re.sub(r"\W+", "", text.casefold())

        records = (
            SearchAggregator(build_provider_suite())
            .search(
                SearchQuery(query=candidate.title, limit=10),
                output_limit=10,
            )
            .results
        )
        identities = set()
        for record in records:
            if normalize(record.title) != normalize(candidate.title):
                continue
            if candidate.year and record.year != candidate.year:
                continue
            if candidate.venue and normalize(record.venue) != normalize(
                candidate.venue
            ):
                continue
            # Title alone cannot distinguish a journal paper from same-title slides.
            if not candidate.year and not candidate.venue and candidate.url:
                if not record.url or record.url.rstrip("/") != candidate.url.rstrip(
                    "/"
                ):
                    continue
            identity = next(
                (
                    (flag, value)
                    for flag, value in (
                        ("--doi", record.doi),
                        ("--arxiv-id", record.arxiv_id),
                        ("--pubmed-id", record.pmid),
                        ("--pmc-id", record.pmcid),
                    )
                    if value
                ),
                None,
            )
            if identity:
                identities.add(identity)
        if len(identities) == 1:
            identifier = identities.pop()
        elif len(identities) > 1:
            raise SPCAcquisitionError(
                "download", {"error": {"code": "ambiguous_paper_identity"}}
            )
    if identifier is None:
        raise SPCAcquisitionError(
            "download", {"error": {"code": "paper_identity_unresolved"}}
        )
    try:
        proc = subprocess.run(
            [
                cli,
                "paper",
                "download",
                *identifier,
                "--output-dir",
                str(output_dir),
                "--no-parse",
                "--no-progress",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        payload = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        raise SPCAcquisitionError(
            "download",
            {
                "error": {
                    "code": type(exc).__name__,
                    "retryable": True,
                }
            },
        ) from exc
    if not isinstance(payload, dict):
        raise SPCAcquisitionError("download", {"error": {"code": "invalid_response"}})
    if proc.returncode or payload.get("status") != "completed" or payload.get("error"):
        raise SPCAcquisitionError("download", payload)
    files = list(payload.get("files") or [])
    for item in payload.get("items") or []:
        files.extend(item.get("artifacts") or [])
    root = output_dir.resolve()
    for ref in files:
        if not isinstance(ref, dict) or not ref.get("path"):
            continue
        path = Path(ref["path"])
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        if path.suffix.lower() == ".pdf":
            return path
    raise RuntimeError("SPC returned no contained PDF artifact")


def spc_provider_status() -> dict[str, Any]:
    """Readiness snapshot of the optional SPC external provider."""
    import os

    cli_path = shutil.which("spc")
    papervault_raw = os.environ.get(PAPERVAULT_DB_ENV, "").strip()
    if not papervault_raw:
        papervault_state = "not_configured"
    elif Path(papervault_raw).expanduser().is_file():
        papervault_state = "ready"
    else:
        papervault_state = "missing"
    return {
        "cli_path": cli_path,
        "cli_on_path": cli_path is not None,
        "papervault_db": papervault_raw or None,
        "papervault_state": papervault_state,
    }


def build_spc_provider_check() -> dict[str, object]:
    """``rh doctor`` check entry; SPC is optional so ``ok`` is always True."""
    status = spc_provider_status()
    return {
        "check": "spc_provider",
        "cli": status["cli_path"] or "not installed",
        "papervault_db": status["papervault_db"] or "not configured",
        "papervault_state": status["papervault_state"],
        "ok": True,
        "note": "optional external acquisition provider (paperfetch)",
    }
