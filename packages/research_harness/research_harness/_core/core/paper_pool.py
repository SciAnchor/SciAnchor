"""Paper pool management."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import Any

from research_harness._core.storage.db import write_transaction
from research_harness._core.storage.models import Paper, PaperAnnotation, TopicPaperNote

logger = logging.getLogger(__name__)

# Columns that carry a paper's identity and are protected by a UNIQUE index.
IDENTITY_COLUMNS = ("doi", "arxiv_id", "s2_id", "pmid", "pmcid")


class PaperIdentityConflict(sqlite3.IntegrityError):
    """Ingesting this paper would break a ``papers`` identity UNIQUE index.

    Two pool rows can legitimately describe the same paper under different
    identifier families (one known by DOI, one by arXiv id). A record carrying
    both cannot be merged without handing one row an identifier the other
    already owns. Subclassing ``sqlite3.IntegrityError`` keeps existing callers
    working, while ``field``/``value`` let batch importers skip exactly one
    record — and say why — instead of aborting the whole run.
    """

    def __init__(self, message: str, *, field: str, value: str | None = None) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


def _identity_conflict_field(exc: sqlite3.IntegrityError) -> str | None:
    """Return the ``papers`` identity column named by a UNIQUE constraint error."""
    message = str(exc)
    marker = "UNIQUE constraint failed: "
    if marker not in message:
        return None
    for column in message.split(marker, 1)[1].split(","):
        table, _, name = column.strip().partition(".")
        if table == "papers" and name in IDENTITY_COLUMNS:
            return name
    return None


def _canonical_doi(value: str | None) -> str:
    """Strip a resolver prefix from a DOI for case-insensitive dedup lookup.

    DOIs are case-insensitive by spec, and providers deliver them with or
    without the ``https://doi.org/`` prefix. Combined with ``COLLATE NOCASE`` in
    ``_find_existing`` this prevents ``10.1/AB`` / ``10.1/ab`` /
    ``https://doi.org/10.1/ab`` from creating duplicate paper rows.
    """
    cleaned = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return cleaned


def _canonical_arxiv(value: str | None) -> str:
    """Version-stripped, prefix-free arXiv id for dedup lookup.

    The arXiv API reports ``2608.14036v1``, Semantic Scholar reports
    ``2608.14036``, and older ingest paths stored ``arxiv:2608.14036``. Matching
    those exactly made each shape a separate paper row — the same defect
    ``_canonical_doi`` already prevents on the DOI side.
    """
    from research_harness.paper_sources import normalize_arxiv_id

    return normalize_arxiv_id(value or "")


def _parse_authors_for_enrich(raw: str | None) -> list[str]:
    """Check if the DB authors field contains actual author names.

    Recognises the same empty patterns as ``latex_compiler.parse_authors_field``
    without importing it (avoids cross-layer dependency).
    """
    if not raw or raw.strip() in ("[]", '""', "null", '""', ""):
        return []
    text = raw.strip()
    # Unwrap outer JSON string quotes
    if text.startswith('"') and text.endswith('"'):
        try:
            text = json.loads(text)
            if isinstance(text, str):
                text = text.strip()
        except (ValueError, TypeError):
            pass
    # Try JSON array
    if isinstance(text, str) and text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(a).strip() for a in parsed if str(a).strip()]
        except (ValueError, TypeError):
            pass
    # Semicolon-separated
    if isinstance(text, str) and ";" in text:
        return [a.strip() for a in text.split(";") if a.strip()]
    if isinstance(text, str) and text.strip():
        return [text.strip()]
    return []


class PaperPool:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def _optional_identifier(self, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    def ingest(
        self,
        paper: Paper,
        topic_id: int | None = None,
        relevance: str = "medium",
        screening_status: str = "screened_in",
        evidence_role: str = "unreviewed",
        manuscript_eligible: bool = True,
        screening_reason: str = "",
        candidate_source: str = "",
    ) -> int:
        # The dedup lookup and the insert/update must share one write
        # transaction, otherwise concurrent ingests of the same paper can both
        # miss the lookup and create duplicate rows.
        try:
            with write_transaction(self._conn):
                return self._ingest_in_txn(
                    paper,
                    topic_id=topic_id,
                    relevance=relevance,
                    screening_status=screening_status,
                    evidence_role=evidence_role,
                    manuscript_eligible=manuscript_eligible,
                    screening_reason=screening_reason,
                    candidate_source=candidate_source,
                )
        except sqlite3.IntegrityError as exc:
            # write_transaction already rolled back, so the connection is clean
            # and the caller can skip this one record and keep importing.
            field = _identity_conflict_field(exc)
            if field is None:
                raise
            raise PaperIdentityConflict(
                str(exc),
                field=field,
                value=self._optional_identifier(getattr(paper, field, None)),
            ) from exc

    def _ingest_in_txn(
        self,
        paper: Paper,
        topic_id: int | None,
        relevance: str,
        screening_status: str,
        evidence_role: str,
        manuscript_eligible: bool,
        screening_reason: str,
        candidate_source: str,
    ) -> int:
        # Lookup normalizes the identifier; storage retains the requested version.
        existing = self._find_existing(paper)
        authors_json = json.dumps(paper.authors, ensure_ascii=False)
        affiliations_json = json.dumps(paper.affiliations, ensure_ascii=False)
        if existing:
            paper_id = existing["id"]
            if paper.arxiv_id and re.search(r"v\d+$", paper.arxiv_id):
                stored_id = self._conn.execute(
                    "SELECT arxiv_id FROM papers WHERE id = ?", (paper_id,)
                ).fetchone()[0]
                if stored_id and stored_id != paper.arxiv_id:
                    raise ValueError(
                        "paper_version_conflict: existing arXiv version differs"
                    )
            self._conn.execute(
                """
                UPDATE papers
                SET title = CASE WHEN title = '' OR title IS NULL THEN ? ELSE title END,
                    authors = CASE WHEN (authors = '' OR authors = '[]') AND ? != '' THEN ? ELSE authors END,
                    affiliations = CASE WHEN (affiliations = '' OR affiliations = '[]') AND ? != '' THEN ? ELSE affiliations END,
                    year = COALESCE(year, ?),
                    venue = CASE WHEN venue = '' THEN ? ELSE venue END,
                    abstract = CASE WHEN (abstract = '' OR abstract IS NULL) AND ? != '' THEN ? ELSE abstract END,
                    doi = CASE WHEN (doi IS NULL OR TRIM(doi) = '') THEN ? ELSE doi END,
                    arxiv_id = CASE WHEN (arxiv_id IS NULL OR TRIM(arxiv_id) = '') THEN ? ELSE arxiv_id END,
                    s2_id = CASE WHEN (s2_id IS NULL OR TRIM(s2_id) = '') THEN ? ELSE s2_id END,
                    pmid = CASE WHEN (pmid IS NULL OR TRIM(pmid) = '') THEN ? ELSE pmid END,
                    pmcid = CASE WHEN (pmcid IS NULL OR TRIM(pmcid) = '') THEN ? ELSE pmcid END,
                    url = CASE WHEN ? != '' THEN ? ELSE url END,
                    concepts_json = CASE WHEN (concepts_json = '' OR concepts_json IS NULL) AND ? != '' THEN ? ELSE concepts_json END
                WHERE id = ?
                """,
                (
                    paper.title,
                    authors_json,
                    authors_json,
                    affiliations_json,
                    affiliations_json,
                    paper.year,
                    paper.venue,
                    paper.abstract,
                    paper.abstract,
                    # '' would be stored as a regular value that only one row
                    # may hold: papers.(doi, arxiv_id, s2_id) are plain UNIQUE
                    # (migration 064). Absent identifiers must stay NULL, exactly
                    # as on the INSERT branch below.
                    self._optional_identifier(paper.doi),
                    self._optional_identifier(paper.arxiv_id),
                    self._optional_identifier(paper.s2_id),
                    self._optional_identifier(paper.pmid),
                    self._optional_identifier(paper.pmcid),
                    paper.url,
                    paper.url,
                    paper.concepts_json,
                    paper.concepts_json,
                    paper_id,
                ),
            )
        else:
            cur = self._conn.execute(
                """
                INSERT INTO papers (title, authors, affiliations, year, venue, abstract, doi, arxiv_id, s2_id, pmid, pmcid, url, pdf_path, pdf_hash, status, concepts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper.title,
                    authors_json,
                    affiliations_json,
                    paper.year,
                    paper.venue,
                    paper.abstract,
                    self._optional_identifier(paper.doi),
                    self._optional_identifier(paper.arxiv_id),
                    self._optional_identifier(paper.s2_id),
                    self._optional_identifier(paper.pmid),
                    self._optional_identifier(paper.pmcid),
                    self._optional_identifier(paper.url),
                    paper.pdf_path,
                    paper.pdf_hash,
                    paper.status,
                    paper.concepts_json,
                ),
            )
            paper_id = int(cur.lastrowid)

        if topic_id is not None:
            self._conn.execute(
                """
                INSERT INTO paper_topics (
                    paper_id, topic_id, relevance, screening_status, evidence_role,
                    manuscript_eligible, screening_reason, candidate_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id, topic_id) DO UPDATE SET
                    relevance = CASE
                        WHEN paper_topics.screening_status = 'screened_in'
                             AND excluded.screening_status = 'candidate'
                        THEN paper_topics.relevance
                        ELSE excluded.relevance
                    END,
                    screening_status = CASE
                        WHEN paper_topics.screening_status = 'screened_in'
                             AND excluded.screening_status = 'candidate'
                        THEN paper_topics.screening_status
                        ELSE excluded.screening_status
                    END,
                    evidence_role = CASE
                        WHEN paper_topics.screening_status = 'screened_in'
                             AND excluded.screening_status = 'candidate'
                        THEN paper_topics.evidence_role
                        ELSE excluded.evidence_role
                    END,
                    manuscript_eligible = CASE
                        WHEN paper_topics.screening_status = 'screened_in'
                             AND excluded.screening_status = 'candidate'
                        THEN paper_topics.manuscript_eligible
                        ELSE excluded.manuscript_eligible
                    END,
                    screening_reason = CASE
                        WHEN paper_topics.screening_status = 'screened_in'
                             AND excluded.screening_status = 'candidate'
                        THEN paper_topics.screening_reason
                        ELSE excluded.screening_reason
                    END,
                    candidate_source = CASE
                        WHEN paper_topics.screening_status = 'screened_in'
                             AND excluded.screening_status = 'candidate'
                        THEN paper_topics.candidate_source
                        ELSE excluded.candidate_source
                    END
                """,
                (
                    paper_id,
                    topic_id,
                    relevance,
                    screening_status,
                    evidence_role,
                    1 if manuscript_eligible else 0,
                    screening_reason,
                    candidate_source,
                ),
            )

        return paper_id

    def get(self, paper_id: int) -> Paper | None:
        row = self._conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_paper(row)

    def list_papers(
        self, topic_id: int | None = None, status: str | None = None
    ) -> list[Paper]:
        query = "SELECT p.* FROM papers p"
        params: list[object] = []
        if topic_id is not None:
            query += " JOIN paper_topics pt ON p.id = pt.paper_id WHERE pt.topic_id = ?"
            params.append(topic_id)
            if status:
                query += " AND p.status = ?"
                params.append(status)
        elif status:
            query += " WHERE p.status = ?"
            params.append(status)
        query += " ORDER BY p.created_at DESC, p.id DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_paper(row) for row in rows]

    def upsert_annotation(self, annotation: PaperAnnotation) -> int:
        with write_transaction(self._conn):
            cur = self._conn.execute(
                """
                INSERT INTO paper_annotations
                (paper_id, section, content, source, confidence, extractor_version, pdf_hash_at_extraction)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (paper_id, section)
                DO UPDATE SET
                    content = excluded.content,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    extractor_version = excluded.extractor_version,
                    pdf_hash_at_extraction = excluded.pdf_hash_at_extraction,
                    updated_at = datetime('now')
                """,
                (
                    annotation.paper_id,
                    annotation.section,
                    annotation.content,
                    annotation.source,
                    annotation.confidence,
                    annotation.extractor_version,
                    annotation.pdf_hash_at_extraction,
                ),
            )
        return int(cur.lastrowid or 0)

    def get_annotations(self, paper_id: int) -> list[PaperAnnotation]:
        rows = self._conn.execute(
            "SELECT * FROM paper_annotations WHERE paper_id = ? ORDER BY section",
            (paper_id,),
        ).fetchall()
        return [self._row_to_annotation(row) for row in rows]

    def upsert_topic_note(self, note: TopicPaperNote) -> int:
        with write_transaction(self._conn):
            linked = self._conn.execute(
                "SELECT 1 FROM paper_topics WHERE paper_id = ? AND topic_id = ?",
                (note.paper_id, note.topic_id),
            ).fetchone()
            if linked is None:
                raise ValueError(
                    f"paper {note.paper_id} is not linked to topic {note.topic_id}"
                )

            existing = self._conn.execute(
                """
                SELECT id FROM topic_paper_notes
                WHERE paper_id = ? AND topic_id = ? AND note_type = ?
                ORDER BY CASE WHEN source LIKE 'zotero:%' THEN 1 ELSE 0 END, id
                LIMIT 1
                """,
                (note.paper_id, note.topic_id, note.note_type),
            ).fetchone()
            if existing is None:
                cursor = self._conn.execute(
                    """
                    INSERT INTO topic_paper_notes
                        (paper_id, topic_id, note_type, content, source)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        note.paper_id,
                        note.topic_id,
                        note.note_type,
                        note.content,
                        note.source,
                    ),
                )
                note_id = int(cursor.lastrowid)
            else:
                self._conn.execute(
                    """
                    UPDATE topic_paper_notes
                    SET content = ?, source = ?, created_at = datetime('now')
                    WHERE id = ?
                    """,
                    (note.content, note.source, int(existing["id"])),
                )
                note_id = int(existing["id"])
        return note_id

    def get_topic_notes(
        self,
        paper_id: int,
        topic_id: int | None = None,
        note_type: str | None = None,
    ) -> list[TopicPaperNote]:
        query = "SELECT * FROM topic_paper_notes WHERE paper_id = ?"
        params: list[object] = [paper_id]
        if topic_id is not None:
            query += " AND topic_id = ?"
            params.append(topic_id)
        if note_type is not None:
            query += " AND note_type = ?"
            params.append(note_type)
        query += " ORDER BY created_at DESC, id DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_topic_note(row) for row in rows]

    def enrich_metadata(self, paper_id: int) -> dict[str, str]:
        """Fill missing metadata from identity-matched managed search results."""
        from research_harness.paper_source_clients import build_provider_suite
        from research_harness.paper_sources import SearchAggregator, SearchQuery

        row = self._conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Paper {paper_id} not found")
        query = row["doi"] or row["arxiv_id"] or row["title"]
        if not query:
            return {}
        # An identifier resolves by exact lookup; searching on the bare DOI string finds
        # nothing on SPC (a0096: 18 MDPI/AAAI DOIs ingested with no title).
        providers = build_provider_suite()
        records = []
        spc = next(
            (
                p
                for p in providers
                if getattr(p, "name", "") == "spc" and hasattr(p, "_lookup")
            ),
            None,
        )
        if spc is not None and (row["doi"] or row["arxiv_id"]):
            kind, identifier = (
                ("doi", row["doi"]) if row["doi"] else ("arxiv", row["arxiv_id"])
            )
            try:
                records = [spc._lookup(identifier, kind)]
            except RuntimeError as exc:
                if not any(
                    cls.__name__ == "SPCAcquisitionError" for cls in type(exc).__mro__
                ):
                    raise
                # the search below reports any outage under its own failure contract
        if not records:
            records = (
                SearchAggregator(providers)
                .search(SearchQuery(query=query, limit=5))
                .results
            )
        for record in records:
            if row["doi"]:
                matches = _canonical_doi(record.doi) == _canonical_doi(row["doi"])
            elif row["arxiv_id"]:
                matches = _canonical_arxiv(record.arxiv_id) == _canonical_arxiv(
                    row["arxiv_id"]
                )
            else:
                matches = (
                    record.title.strip().casefold()
                    == (row["title"] or "").strip().casefold()
                )
            if not matches:
                continue
            values = {
                "title": record.title,
                "abstract": record.abstract,
                "venue": record.venue,
                "year": record.year,
                "doi": record.doi,
                "arxiv_id": record.arxiv_id,
                "citation_count": record.citation_count,
            }
            if record.authors and not _parse_authors_for_enrich(row["authors"] or ""):
                values["authors"] = json.dumps(record.authors, ensure_ascii=False)
            updates = {
                key: value
                for key, value in values.items()
                if value and (not row[key] or key == "authors")
            }
            if updates:
                fields = ", ".join(f"{key} = ?" for key in updates)
                self._conn.execute(
                    f"UPDATE papers SET {fields} WHERE id = ?",
                    [*updates.values(), paper_id],
                )
                self._conn.commit()
            return {key: str(value) for key, value in updates.items()}
        return {}

    def _enrich_from_pubmed(self, paper_id: int, row: Any) -> dict[str, str]:
        """Enrich medical papers via PubMed by PMID or DOI."""

        keys = row.keys() if hasattr(row, "keys") else []
        pmid = (row["pmid"] or "").strip() if "pmid" in keys else ""
        doi = (row["doi"] or "").strip()
        if not pmid and not doi:
            return {}

        try:
            from research_harness.paper_source_clients import PubMedProvider

            provider = PubMedProvider(
                email=os.environ.get("PUBMED_EMAIL", "").strip(),
                tool=os.environ.get("PUBMED_TOOL", "research_harness").strip()
                or "research_harness",
            )
            record = (
                provider.fetch_by_pmid(pmid) if pmid else provider.fetch_by_doi(doi)
            )
        except Exception:
            return {}

        if record is None:
            return {}

        set_clauses: list[str] = []
        params: list[Any] = []
        updates: dict[str, str] = {}

        def set_field(field_name: str, value: object, label: str | None = None) -> None:
            if value is None or value == "":
                return
            set_clauses.append(f"{field_name} = ?")
            params.append(value)
            updates[field_name] = str(label if label is not None else value)

        old_title = (row["title"] or "").strip()
        if record.title and (
            not old_title
            or old_title.lower().startswith(("doi:", "pmid:", "s2:", "pdf:"))
        ):
            set_field("title", record.title)
        if record.authors and not _parse_authors_for_enrich(row["authors"] or ""):
            set_field(
                "authors",
                json.dumps(record.authors, ensure_ascii=False),
                str(len(record.authors)),
            )
        if record.year and row["year"] is None:
            set_field("year", int(record.year))
        if record.venue and not (row["venue"] or "").strip():
            set_field("venue", record.venue)
        if record.abstract and not (row["abstract"] or "").strip():
            set_field("abstract", record.abstract, record.abstract[:80] + "...")

        for field_name, value in (
            ("doi", record.doi),
            ("pmid", record.pmid),
            ("pmcid", record.pmcid),
        ):
            if not value or field_name not in keys:
                continue
            current = (row[field_name] or "").strip()
            if current:
                continue
            duplicate = self._conn.execute(
                f"SELECT id FROM papers WHERE {field_name} = ? AND id != ?",
                (value, paper_id),
            ).fetchone()
            if duplicate is None:
                set_field(field_name, value)

        if record.url and not (row["url"] or "").strip():
            set_field("url", record.url)
        if (
            record.concepts
            and "concepts_json" in keys
            and not (row["concepts_json"] or "").strip()
        ):
            set_field(
                "concepts_json",
                json.dumps(record.concepts, ensure_ascii=False),
                str(len(record.concepts)),
            )

        if set_clauses:
            params.append(paper_id)
            self._conn.execute(
                f"UPDATE papers SET {', '.join(set_clauses)} WHERE id = ?", params
            )
            self._conn.commit()
        return updates

    def _enrich_from_s2(self, paper_id: int, row: Any) -> dict[str, str]:
        """Enrich via Semantic Scholar API. Rate-limited (~1 req/sec externally)."""
        import urllib.request
        import urllib.error

        arxiv_id = (row["arxiv_id"] or "").strip()
        doi = (row["doi"] or "").strip()
        s2_id = (row["s2_id"] or "").strip()
        title_raw = (row["title"] or "").strip()

        lookup_id = None
        if arxiv_id:
            import re

            clean = re.sub(
                r"v\d+$", "", arxiv_id.removeprefix("arxiv:").removeprefix("arXiv:")
            )
            lookup_id = f"ARXIV:{clean}"
        elif doi:
            lookup_id = f"DOI:{doi.removeprefix('doi:').removeprefix('DOI:')}"
        elif s2_id:
            lookup_id = s2_id.removeprefix("s2:").removeprefix("S2:")
        elif title_raw.startswith(("doi:", "DOI:")):
            lookup_id = f"DOI:{title_raw.removeprefix('doi:').removeprefix('DOI:')}"
        elif title_raw.startswith(("s2:", "S2:")):
            lookup_id = title_raw.removeprefix("s2:").removeprefix("S2:")

        if not lookup_id:
            return {}

        url = f"https://api.semanticscholar.org/graph/v1/paper/{lookup_id}?fields=title,authors.name,authors.affiliations,year,venue,abstract,externalIds,citationCount,openAccessPdf"
        try:
            headers = {"User-Agent": "research-harness/1.0"}  # keyless public API
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            return {}

        updates: dict[str, str] = {}
        set_clauses: list[str] = []
        params: list[object] = []

        new_title = (data.get("title") or "").strip()
        old_title = (row["title"] or "").strip()
        if new_title and (
            not old_title or old_title.startswith(("doi:", "s2:", "pdf:"))
        ):
            set_clauses.append("title = ?")
            params.append(new_title)
            updates["title"] = new_title

        new_abstract = (data.get("abstract") or "").strip()
        if new_abstract and not (row["abstract"] or "").strip():
            set_clauses.append("abstract = ?")
            params.append(new_abstract)
            updates["abstract"] = new_abstract[:80] + "..."

        new_authors = [
            a.get("name", "") for a in (data.get("authors") or []) if a.get("name")
        ]
        if new_authors and not _parse_authors_for_enrich(row["authors"] or ""):
            set_clauses.append("authors = ?")
            params.append(json.dumps(new_authors, ensure_ascii=False))
            updates["authors"] = str(len(new_authors))

        new_affiliations: list[str] = []
        _aff_seen: set[str] = set()
        for a in data.get("authors") or []:
            for aff in a.get("affiliations") or [] if isinstance(a, dict) else []:
                name = (aff if isinstance(aff, str) else "").strip()
                if name and name not in _aff_seen:
                    _aff_seen.add(name)
                    new_affiliations.append(name)
        old_affiliations = row["affiliations"] if "affiliations" in row.keys() else "[]"
        if new_affiliations and (old_affiliations or "[]") in ("", "[]"):
            set_clauses.append("affiliations = ?")
            params.append(json.dumps(new_affiliations, ensure_ascii=False))
            updates["affiliations"] = str(len(new_affiliations))

        new_year = data.get("year")
        if new_year and row["year"] is None:
            set_clauses.append("year = ?")
            params.append(new_year)
            updates["year"] = str(new_year)

        new_venue = (data.get("venue") or "").strip()
        old_venue = (row["venue"] or "").strip().lower()
        if new_venue and old_venue in ("", "arxiv", "arxiv.org", "arxiv preprint"):
            set_clauses.append("venue = ?")
            params.append(new_venue)
            updates["venue"] = new_venue

        ext_ids = data.get("externalIds") or {}
        new_doi = ext_ids.get("DOI", "")
        if new_doi and not (row["doi"] or "").strip():
            if not self._conn.execute(
                "SELECT id FROM papers WHERE doi = ? AND id != ?", (new_doi, paper_id)
            ).fetchone():
                set_clauses.append("doi = ?")
                params.append(new_doi)
                updates["doi"] = new_doi

        new_arxiv = ext_ids.get("ArXiv", "")
        if new_arxiv and not (row["arxiv_id"] or "").strip():
            if not self._conn.execute(
                "SELECT id FROM papers WHERE arxiv_id = ? AND id != ?",
                (new_arxiv, paper_id),
            ).fetchone():
                set_clauses.append("arxiv_id = ?")
                params.append(new_arxiv)
                updates["arxiv_id"] = new_arxiv

        new_s2 = data.get("paperId", "")
        if new_s2 and not (row["s2_id"] or "").strip():
            if not self._conn.execute(
                "SELECT id FROM papers WHERE s2_id = ? AND id != ?", (new_s2, paper_id)
            ).fetchone():
                set_clauses.append("s2_id = ?")
                params.append(new_s2)
                updates["s2_id"] = new_s2

        new_citation_count = data.get("citationCount")
        if new_citation_count is not None:
            old_count = (
                row["citation_count"] if "citation_count" in row.keys() else None
            )
            if old_count is None or old_count == 0:
                set_clauses.append("citation_count = ?")
                params.append(int(new_citation_count))
                updates["citation_count"] = str(new_citation_count)

        oa_pdf = data.get("openAccessPdf") or {}
        if isinstance(oa_pdf, dict):
            oa_url = (oa_pdf.get("url") or "").strip()
            old_url = (row["url"] or "").strip() if "url" in row.keys() else ""
            if oa_url and not old_url:
                set_clauses.append("url = ?")
                params.append(oa_url)
                updates["open_access_pdf"] = oa_url

        if set_clauses:
            params.append(paper_id)
            self._conn.execute(
                f"UPDATE papers SET {', '.join(set_clauses)} WHERE id = ?", params
            )
            self._conn.commit()

        return updates

    def _enrich_from_openalex(self, paper_id: int, row: Any) -> dict[str, str]:
        """Fallback enrichment via OpenAlex by DOI (preferred) or title search.

        OpenAlex is free, unmetered, and especially strong for venue normalization
        and citation counts on DOI-bearing papers.
        """
        import urllib.parse
        import urllib.request

        doi = (row["doi"] or "").strip()
        title = (row["title"] or "").strip()
        item: dict[str, Any] | None = None
        mailto = os.environ.get("OPENALEX_MAILTO", "").strip()

        def _fetch(url: str) -> dict[str, Any] | None:
            params = []  # keyless public API
            if mailto:
                params.append(f"mailto={urllib.parse.quote(mailto)}")
            sep = "&" if "?" in url else "?"
            full_url = url + (sep + "&".join(params) if params else "")
            try:
                req = urllib.request.Request(
                    full_url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "research-harness/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            except Exception:
                return None

        if doi:
            clean = (
                doi.removeprefix("https://doi.org/")
                .removeprefix("http://doi.org/")
                .removeprefix("doi:")
                .removeprefix("DOI:")
            )
            item = _fetch(f"https://api.openalex.org/works/doi:{clean}")

        if (
            item is None
            and title
            and len(title) > 15
            and not title.startswith(("doi:", "s2:", "pdf:"))
        ):
            search = _fetch(
                f"https://api.openalex.org/works?search={urllib.parse.quote(title)}&per-page=1"
            )
            if isinstance(search, dict):
                results = search.get("results") or []
                if results and isinstance(results[0], dict):
                    candidate = results[0]
                    cand_title = (candidate.get("title") or "").strip().lower()
                    if cand_title and self._title_matches(title.lower(), cand_title):
                        item = candidate

        if not isinstance(item, dict):
            return {}

        set_clauses: list[str] = []
        params: list[Any] = []
        updates: dict[str, str] = {}

        # venue
        old_venue = (row["venue"] or "").strip().lower()
        venue_placeholder = old_venue in ("", "arxiv", "arxiv.org", "arxiv preprint")
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        new_venue = (source.get("display_name") or "").strip()
        if new_venue and venue_placeholder:
            set_clauses.append("venue = ?")
            params.append(new_venue)
            updates["venue"] = new_venue

        # citation_count
        new_cite = item.get("cited_by_count")
        old_cite = row["citation_count"] if "citation_count" in row.keys() else None
        if isinstance(new_cite, int) and (old_cite is None or old_cite == 0):
            set_clauses.append("citation_count = ?")
            params.append(int(new_cite))
            updates["citation_count"] = str(new_cite)

        # year
        new_year = item.get("publication_year")
        if new_year and row["year"] is None:
            set_clauses.append("year = ?")
            params.append(int(new_year))
            updates["year"] = str(new_year)

        # abstract from inverted_index
        if not (row["abstract"] or "").strip():
            inv = item.get("abstract_inverted_index")
            if isinstance(inv, dict) and inv:
                positions: dict[int, str] = {}
                for word, idxs in inv.items():
                    if isinstance(idxs, list):
                        for i in idxs:
                            if isinstance(i, int):
                                positions[i] = word
                if positions:
                    abstract = " ".join(positions[i] for i in sorted(positions))
                    if abstract:
                        set_clauses.append("abstract = ?")
                        params.append(abstract)
                        updates["abstract"] = abstract[:80] + "..."

        # doi (if missing)
        new_doi = (item.get("doi") or "").strip()
        if new_doi:
            new_doi = new_doi.removeprefix("https://doi.org/").removeprefix(
                "http://doi.org/"
            )
        if new_doi and not (row["doi"] or "").strip():
            dup = self._conn.execute(
                "SELECT id FROM papers WHERE doi = ? AND id != ?", (new_doi, paper_id)
            ).fetchone()
            if not dup:
                set_clauses.append("doi = ?")
                params.append(new_doi)
                updates["doi"] = new_doi

        if set_clauses:
            params.append(paper_id)
            self._conn.execute(
                f"UPDATE papers SET {', '.join(set_clauses)} WHERE id = ?",
                params,
            )
            self._conn.commit()

        return updates

    @staticmethod
    def _title_matches(a: str, b: str) -> bool:
        """Loose title match: normalized identical, or one is prefix of the other."""
        import re

        def norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", s)[:80]

        na, nb = norm(a), norm(b)
        if not na or not nb:
            return False
        return na == nb or na.startswith(nb[:60]) or nb.startswith(na[:60])

    def _find_existing(self, paper: Paper) -> dict[str, int] | None:
        # doi/arxiv_id/pmcid are matched case-insensitively (COLLATE NOCASE)
        # and are canonicalized (DOI resolver prefix stripped, arXiv version
        # suffix and "arxiv:" prefix stripped) so that shape variants from
        # different providers dedup to one row instead of inserting
        # duplicates. s2_id/pmid stay exact.
        for field_name, value, case_insensitive in (
            ("doi", _canonical_doi(paper.doi), True),
            ("arxiv_id", _canonical_arxiv(paper.arxiv_id), True),
            ("s2_id", paper.s2_id, False),
            ("pmid", paper.pmid, False),
            ("pmcid", paper.pmcid, True),
        ):
            if not value:
                continue
            collate = " COLLATE NOCASE" if case_insensitive else ""
            row = self._conn.execute(
                f"SELECT id FROM papers WHERE {field_name} = ?{collate}",
                (value,),
            ).fetchone()
            if row:
                return {"id": row["id"]}
            if field_name == "doi" and value != (paper.doi or "").strip():
                # also match a stored prefixed/raw form of the same DOI
                row = self._conn.execute(
                    "SELECT id FROM papers WHERE doi = ? COLLATE NOCASE",
                    ((paper.doi or "").strip(),),
                ).fetchone()
                if row:
                    return {"id": row["id"]}
            if field_name == "arxiv_id":
                # Databases predating arXiv canonicalization still hold
                # "2608.14036v1" / "arxiv:2608.14036", which the canonical
                # lookup above cannot reach. All three patterns are
                # prefix-anchored, so the arxiv_id index still applies.
                row = self._conn.execute(
                    "SELECT id FROM papers WHERE arxiv_id LIKE ? COLLATE NOCASE"
                    " OR arxiv_id LIKE ? COLLATE NOCASE"
                    " OR arxiv_id LIKE ? COLLATE NOCASE",
                    (f"{value}v%", f"arxiv:{value}", f"arxiv:{value}v%"),
                ).fetchone()
                if row:
                    return {"id": row["id"]}
        return None

    @staticmethod
    def _row_to_paper(row: sqlite3.Row) -> Paper:
        keys = row.keys() if hasattr(row, "keys") else []
        return Paper(
            id=row["id"],
            title=row["title"],
            authors=json.loads(row["authors"]) if row["authors"] else [],
            affiliations=json.loads(row["affiliations"])
            if "affiliations" in keys and row["affiliations"]
            else [],
            year=row["year"],
            venue=row["venue"],
            abstract=row["abstract"] if "abstract" in keys else "",
            doi=row["doi"] or "",
            arxiv_id=row["arxiv_id"] or "",
            s2_id=row["s2_id"] or "",
            pmid=row["pmid"] or "" if "pmid" in keys else "",
            pmcid=row["pmcid"] or "" if "pmcid" in keys else "",
            url=row["url"] or "",
            pdf_path=row["pdf_path"],
            pdf_hash=row["pdf_hash"],
            status=row["status"],
            created_at=row["created_at"],
            concepts_json=row["concepts_json"] if "concepts_json" in keys else "",
        )

    @staticmethod
    def _row_to_annotation(row: sqlite3.Row) -> PaperAnnotation:
        return PaperAnnotation(
            id=row["id"],
            paper_id=row["paper_id"],
            section=row["section"],
            content=row["content"],
            source=row["source"],
            confidence=row["confidence"],
            extractor_version=row["extractor_version"],
            pdf_hash_at_extraction=row["pdf_hash_at_extraction"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_topic_note(row: sqlite3.Row) -> TopicPaperNote:
        return TopicPaperNote(
            id=row["id"],
            paper_id=row["paper_id"],
            topic_id=row["topic_id"],
            note_type=row["note_type"],
            content=row["content"],
            source=row["source"],
            created_at=row["created_at"],
        )
