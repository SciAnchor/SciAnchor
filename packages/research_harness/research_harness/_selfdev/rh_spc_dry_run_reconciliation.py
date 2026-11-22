"""Private in-memory RH/SPC reconciliation with no canonical writes."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


class ReconciliationError(ValueError):
    """Raised when source observations cannot be compared safely."""


@dataclass(frozen=True)
class ReconciliationObservation:
    source: str
    source_key: str
    title: str | None
    year: int | None
    doi: str | None
    arxiv_id: str | None
    content_hash: str | None


@dataclass(frozen=True)
class ReconciliationOutcome:
    relation: str
    left_key: str | None
    right_keys: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ReconciliationReport:
    outcomes: tuple[ReconciliationOutcome, ...]
    counts: dict[str, int]
    conservation_total: int
    stable_evidence_sha256: str
    left_observations: int
    right_observations: int

    def to_portable(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "conservation_total": self.conservation_total,
            "left_observations": self.left_observations,
            "right_observations": self.right_observations,
            "stable_evidence_sha256": self.stable_evidence_sha256,
            "outcomes": [asdict(outcome) for outcome in self.outcomes],
            "persistent_write": False,
        }


def reconcile_observations(
    left: Iterable[ReconciliationObservation],
    right: Iterable[ReconciliationObservation],
) -> ReconciliationReport:
    """Classify source observations conservatively and deterministically."""

    left_rows = tuple(left)
    right_rows = tuple(right)
    _validate_sources(left_rows, right_rows)
    indexes = _build_indexes(right_rows)
    outcomes: list[ReconciliationOutcome] = []
    represented_right: set[int] = set()

    for row in left_rows:
        strong_candidates, strong_evidence = _strong_candidates(row, indexes)
        if len(strong_candidates) > 1:
            represented_right.update(strong_candidates)
            candidate_rows = tuple(right_rows[index] for index in strong_candidates)
            incompatible = any(
                _metadata_contradictions(row, candidate) for candidate in candidate_rows
            ) or _incompatible_candidates(candidate_rows)
            relation = "conflict" if incompatible else "manual_review"
            outcomes.append(
                _outcome(
                    relation,
                    row,
                    right_rows,
                    strong_candidates,
                    (
                        "ambiguous_strong_identifier",
                        *strong_evidence,
                        *(("incompatible_strong_matches",) if incompatible else ()),
                    ),
                )
            )
            continue
        if len(strong_candidates) == 1:
            index = next(iter(strong_candidates))
            matched = right_rows[index]
            represented_right.add(index)
            contradictions = _metadata_contradictions(row, matched)
            relation = "conflict" if contradictions else "same"
            outcomes.append(
                _outcome(
                    relation,
                    row,
                    right_rows,
                    (index,),
                    (*strong_evidence, *contradictions),
                )
            )
            continue

        hash_candidates = _lookup(indexes["hash"], _hash_value(row))
        if len(hash_candidates) > 1:
            represented_right.update(hash_candidates)
            outcomes.append(
                _outcome(
                    "manual_review",
                    row,
                    right_rows,
                    hash_candidates,
                    ("ambiguous_content_hash",),
                )
            )
            continue
        if len(hash_candidates) == 1:
            index = next(iter(hash_candidates))
            matched = right_rows[index]
            represented_right.add(index)
            contradictions = _metadata_contradictions(row, matched)
            relation = "manual_review" if contradictions else "same"
            evidence = ("content_hash_exact", *contradictions)
            outcomes.append(_outcome(relation, row, right_rows, (index,), evidence))
            continue

        title_year_candidates = _lookup(indexes["title_year"], _title_year_key(row))
        if len(title_year_candidates) == 1:
            index = next(iter(title_year_candidates))
            represented_right.add(index)
            outcomes.append(
                _outcome(
                    "related",
                    row,
                    right_rows,
                    (index,),
                    ("title_year_match",),
                )
            )
        elif title_year_candidates:
            represented_right.update(title_year_candidates)
            outcomes.append(
                _outcome(
                    "manual_review",
                    row,
                    right_rows,
                    title_year_candidates,
                    ("ambiguous_title_year",),
                )
            )
        else:
            outcomes.append(
                _outcome("manual_review", row, right_rows, (), ("unmatched",))
            )

    for index, row in enumerate(right_rows):
        if index not in represented_right:
            outcomes.append(
                ReconciliationOutcome(
                    relation="manual_review",
                    left_key=None,
                    right_keys=(row.source_key,),
                    evidence=("unmatched_right",),
                )
            )

    counts = dict(sorted(Counter(outcome.relation for outcome in outcomes).items()))
    stable_rows = [asdict(outcome) for outcome in outcomes]
    stable_digest = hashlib.sha256(
        json.dumps(stable_rows, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ReconciliationReport(
        outcomes=tuple(outcomes),
        counts=counts,
        conservation_total=len(left_rows) + len(right_rows),
        stable_evidence_sha256=stable_digest,
        left_observations=len(left_rows),
        right_observations=len(right_rows),
    )


def reconcile_real_sources(
    *,
    rh_root: Path,
    spc_seed_pack_root: Path,
    snapshot_id: str,
    observed_at: str,
    scan_host_id: str,
) -> ReconciliationReport:
    """Read the frozen RH/SPC sources and return an in-memory report."""

    del snapshot_id, observed_at, scan_host_id
    left = _load_rh_observations(Path(rh_root))
    right = _load_spc_observations(Path(spc_seed_pack_root))
    return reconcile_observations(left, right)


def _validate_sources(
    left: tuple[ReconciliationObservation, ...],
    right: tuple[ReconciliationObservation, ...],
) -> None:
    if any(row.source != "rh" for row in left):
        raise ReconciliationError("left_source_must_be_rh")
    if any(row.source != "spc" for row in right):
        raise ReconciliationError("right_source_must_be_spc")
    keys = [row.source_key for row in (*left, *right)]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ReconciliationError("source_keys_must_be_unique")


def _build_indexes(
    rows: tuple[ReconciliationObservation, ...],
) -> dict[str, dict[str, list[int]]]:
    indexes: dict[str, dict[str, list[int]]] = {
        "doi": defaultdict(list),
        "arxiv": defaultdict(list),
        "hash": defaultdict(list),
        "title_year": defaultdict(list),
    }
    for index, row in enumerate(rows):
        for name, value in (
            ("doi", _doi_value(row)),
            ("arxiv", _arxiv_value(row)),
            ("hash", _hash_value(row)),
            ("title_year", _title_year_key(row)),
        ):
            if value:
                indexes[name][value].append(index)
    return indexes


def _strong_candidates(
    row: ReconciliationObservation, indexes: dict[str, dict[str, list[int]]]
) -> tuple[set[int], tuple[str, ...]]:
    candidates: set[int] = set()
    evidence: list[str] = []
    for name, value, label in (
        ("doi", _doi_value(row), "doi_exact"),
        ("arxiv", _arxiv_value(row), "arxiv_exact"),
    ):
        if value:
            found = _lookup(indexes[name], value)
            if found:
                candidates.update(found)
                evidence.append(label)
    return candidates, tuple(evidence)


def _lookup(index: dict[str, list[int]], value: str | None) -> set[int]:
    return set(index.get(value, ())) if value else set()


def _outcome(
    relation: str,
    left: ReconciliationObservation,
    right: tuple[ReconciliationObservation, ...],
    indexes: Iterable[int],
    evidence: Iterable[str],
) -> ReconciliationOutcome:
    return ReconciliationOutcome(
        relation=relation,
        left_key=left.source_key,
        right_keys=tuple(sorted(right[index].source_key for index in indexes)),
        evidence=tuple(dict.fromkeys(sorted(evidence))),
    )


def _metadata_contradictions(
    left: ReconciliationObservation, right: ReconciliationObservation
) -> tuple[str, ...]:
    contradictions: list[str] = []
    if (
        _title_value(left)
        and _title_value(right)
        and _title_value(left) != _title_value(right)
    ):
        contradictions.append("title_conflict")
    if left.year is not None and right.year is not None and left.year != right.year:
        contradictions.append("year_conflict")
    return tuple(contradictions)


def _incompatible_candidates(
    candidates: tuple[ReconciliationObservation, ...],
) -> bool:
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if _metadata_contradictions(left, right):
                return True
    return False


def _title_year_key(row: ReconciliationObservation) -> str | None:
    title = _title_value(row)
    return f"{title}|{row.year}" if title and row.year is not None else None


def _title_value(row: ReconciliationObservation) -> str:
    value = unicodedata.normalize("NFKC", row.title or "").casefold()
    return "".join(char for char in value if char.isalnum())


def _doi_value(row: ReconciliationObservation) -> str | None:
    value = (row.doi or "").strip().casefold()
    value = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:", "", value).strip()
    return value or None


def _arxiv_value(row: ReconciliationObservation) -> str | None:
    value = (row.arxiv_id or "").strip().casefold()
    value = re.sub(r"^arxiv:", "", value)
    value = re.sub(r"v\d+$", "", value)
    return value or None


def _hash_value(row: ReconciliationObservation) -> str | None:
    value = (row.content_hash or "").strip().casefold()
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


def _load_rh_observations(root: Path) -> tuple[ReconciliationObservation, ...]:
    state = root / ".research-harness"
    database = state / "pool.db"
    downloads = state / "downloads"
    uri = f"file:{database}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT id,title,year,doi,arxiv_id,pdf_hash,pdf_path FROM papers ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    observations = []
    for paper_id, title, year, doi, arxiv_id, pdf_hash, pdf_path in rows:
        content_hash = _valid_hash(pdf_hash)
        if not content_hash:
            path = _resolve_rh_pdf(root, state, downloads, pdf_path)
            if path is not None:
                content_hash = _sha256_file(path)
        observations.append(
            ReconciliationObservation(
                source="rh",
                source_key=f"rh:{paper_id}",
                title=title,
                year=year if isinstance(year, int) else None,
                doi=doi,
                arxiv_id=arxiv_id,
                content_hash=content_hash,
            )
        )
    return tuple(observations)


def _load_spc_observations(root: Path) -> tuple[ReconciliationObservation, ...]:
    observations = []
    for seed_file in sorted(root.rglob("seed_papers.jsonl")):
        pack_dir = seed_file.parent
        pdf_hashes = _pdf_hashes(pack_dir / "pdf")
        with seed_file.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                facts = record.get("recorded_facts") or {}
                doi = record.get("doi") or facts.get("doi")
                arxiv_id = record.get("arxiv_id") or facts.get("arxiv_id")
                title = record.get("title") or facts.get("title")
                year = record.get("year") or facts.get("year")
                content_hash = _hash_for_record(pdf_hashes, doi, arxiv_id)
                observations.append(
                    ReconciliationObservation(
                        source="spc",
                        source_key=f"spc:{pack_dir.relative_to(root).as_posix()}:{line_no}",
                        title=title,
                        year=year if isinstance(year, int) else None,
                        doi=doi,
                        arxiv_id=arxiv_id,
                        content_hash=content_hash,
                    )
                )
    return tuple(observations)


def _resolve_rh_pdf(
    root: Path, state: Path, downloads: Path, raw: object
) -> Path | None:
    if not isinstance(raw, str) or not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        first = root / candidate
        candidate = first if first.exists() else state / candidate
    if candidate.is_symlink() or not candidate.is_file():
        return None
    try:
        candidate.relative_to(downloads)
    except ValueError:
        return None
    return candidate


def _valid_hash(value: object) -> str | None:
    return (
        value.casefold()
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
        else None
    )


def _pdf_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    hashes = {}
    for path in sorted(root.glob("*.pdf")):
        if path.is_symlink():
            raise ReconciliationError("spc_pdf_symlink")
        hashes[path.stem] = _sha256_file(path)
    return hashes


def _hash_for_record(
    hashes: dict[str, str], doi: object, arxiv_id: object
) -> str | None:
    for prefix, value in (("doi", doi), ("arxiv", arxiv_id)):
        if not isinstance(value, str) or not value.strip():
            continue
        if prefix == "doi":
            value = _doi_text(value)
        else:
            value = _arxiv_text(value)
        slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
        key = f"{prefix}_{slug}"
        if key in hashes:
            return hashes[key]
    return None


def _doi_text(value: str) -> str:
    value = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", value.strip(), flags=re.I)
    return re.sub(r"^doi:", "", value, flags=re.I).strip()


def _arxiv_text(value: str) -> str:
    value = re.sub(r"^arxiv:", "", value.strip(), flags=re.I)
    return re.sub(r"v\d+$", "", value, flags=re.I)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
