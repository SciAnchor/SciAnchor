"""Deterministic download support for the current miRBase FASTA exports.

miRBase currently serves its FASTA exports inside a small HTML wrapper instead
of returning raw FASTA bytes.  This module decodes that representation, checks
the FASTA structure, and writes files atomically with a validation report.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


MIRBASE_CURRENT_ROOT = "https://www.mirbase.org/download/CURRENT"
MIRBASE_FASTA_FILES = ("mature.fa", "hairpin.fa")


class MirbaseDownloadError(RuntimeError):
    """Raised when a miRBase response cannot be validated as FASTA."""


def _parse_fasta_records(payload: str, *, filename: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    current_header: Optional[str] = None
    sequence_chunks: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_header is not None:
                records.append((current_header, "".join(sequence_chunks)))
            current_header = line
            sequence_chunks = []
            continue
        if current_header is None:
            raise MirbaseDownloadError(
                f"{filename}: sequence before first FASTA header"
            )
        sequence_chunks.append(line)
    if current_header is not None:
        records.append((current_header, "".join(sequence_chunks)))
    if not records:
        raise MirbaseDownloadError(f"{filename}: no FASTA records found")
    for header, sequence in records:
        if not sequence:
            raise MirbaseDownloadError(f"{filename}: empty sequence for {header}")
        if not re.fullmatch(r"[A-Za-z.*-]+", sequence):
            raise MirbaseDownloadError(
                f"{filename}: invalid sequence alphabet for {header}"
            )
    return records


def decode_mirbase_fasta(source: str, *, filename: str) -> tuple[bytes, int, str]:
    """Decode a raw or HTML-wrapped miRBase FASTA response.

    Returns the normalized UTF-8 bytes, record count, and first header.
    """

    stripped = source.lstrip()
    if stripped.startswith(">"):
        decoded = stripped
    elif stripped.lower().startswith("<p>"):
        decoded = re.sub(r"(?i)<br\s*/?>", "\n", stripped)
        decoded = re.sub(r"(?i)</?p>", "", decoded)
        decoded = html.unescape(decoded)
    else:
        raise MirbaseDownloadError(
            f"{filename}: response is neither raw FASTA nor the expected miRBase HTML wrapper"
        )
    normalized = decoded.strip() + "\n"
    records = _parse_fasta_records(normalized, filename=filename)
    return normalized.encode("utf-8"), len(records), records[0][0]


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _new_session(proxy: Optional[str]) -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.trust_env = False
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "SPC-miRBase/0.3",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def download_mirbase_current(
    output_dir: str | os.PathLike[str],
    *,
    proxy: Optional[str] = None,
    timeout_seconds: float = 90.0,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    """Download and validate the current miRBase mature and hairpin FASTA files."""

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    owned_session = session is None
    client = session or _new_session(proxy)
    report: dict[str, Any] = {
        "schema_version": "spc.mirbase.download.v1",
        "source": MIRBASE_CURRENT_ROOT,
        "proxy_mode": "explicit" if proxy else "direct",
        "files": [],
    }
    try:
        for filename in MIRBASE_FASTA_FILES:
            url = f"{MIRBASE_CURRENT_ROOT}/{filename}"
            response = client.get(url, timeout=(10.0, timeout_seconds))
            response.raise_for_status()
            payload, record_count, first_header = decode_mirbase_fasta(
                response.text, filename=filename
            )
            target = root / filename
            _atomic_write(target, payload)
            report["files"].append(
                {
                    "filename": filename,
                    "url": url,
                    "source_content_type": response.headers.get("content-type"),
                    "source_bytes": len(response.content),
                    "decoded_bytes": len(payload),
                    "records": record_count,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "first_header": first_header,
                }
            )
        report_payload = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        _atomic_write(root / "validation-report.json", report_payload)
        return report
    finally:
        if owned_session:
            client.close()
