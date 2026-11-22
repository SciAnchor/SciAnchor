"""SPC 1.0 精确论文元数据查询与字段级来源融合。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from paperfetch.papers.models import (
    Author,
    BibliographicMetadata,
    FieldProvenance,
    IdentifierSet,
    MetadataProvenance,
    PaperRecord,
    SourceSnapshot,
    VenueMetadata,
    new_paper_id,
)


@dataclass(frozen=True)
class LookupRequest:
    identifier_type: str
    value: str

    @classmethod
    def normalize(cls, identifier_type: str, value: str) -> "LookupRequest":
        mapping = {
            "doi": {"doi": value},
            "pubmed_id": {"pubmed_id": value},
            "pmc_id": {"pmc_id": value},
            "arxiv_id": {"arxiv_id": value},
        }
        if identifier_type not in mapping:
            raise PaperLookupError(
                "identifier_type_unsupported",
                "invalid_input",
                "不支持的论文标识类型",
                retryable=False,
            )
        try:
            identifiers = IdentifierSet(**mapping[identifier_type])
        except Exception as exc:
            raise PaperLookupError(
                "identifier_invalid",
                "invalid_input",
                f"{identifier_type} 格式无效",
                retryable=False,
            ) from exc
        return cls(
            identifier_type=identifier_type, value=getattr(identifiers, identifier_type)
        )

    @property
    def display_id(self) -> str:
        return f"{self.identifier_type}:{self.value}"


class PaperLookupError(RuntimeError):
    def __init__(
        self,
        code: str,
        error_class: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.error_class = error_class
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class _Candidate:
    source: str
    record_id: str | None
    priority: int
    identifiers: dict[str, str]
    fields: dict[str, Any]
    payload_sha256: str


def _compact_text(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return _compact_text(value)


def _date_parts(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    values = parts[0][:3]
    if not values:
        return None
    try:
        year = int(values[0])
        if len(values) == 1:
            return f"{year:04d}"
        month = int(values[1])
        if len(values) == 2:
            return f"{year:04d}-{month:02d}"
        return f"{year:04d}-{month:02d}-{int(values[2]):02d}"
    except (TypeError, ValueError):
        return None


def _paper_type(value: Any, *, preprint: bool = False) -> str:
    if preprint:
        return "preprint"
    normalized = str(value or "").casefold()
    if "journal" in normalized or normalized in {"research", "review-article"}:
        return "journal_article"
    if "proceedings" in normalized or "conference" in normalized:
        return "conference_paper"
    if "book" in normalized:
        return "book_chapter"
    if "preprint" in normalized or "posted-content" in normalized:
        return "preprint"
    return "other"


def _payload_digest(payload: Any) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _crossref_candidate(message: dict[str, Any]) -> _Candidate | None:
    doi = _compact_text(message.get("DOI"))
    title = _first_text(message.get("title"))
    if not doi or not title:
        return None
    authors: list[dict[str, Any]] = []
    for raw in message.get("author") or []:
        if not isinstance(raw, dict):
            continue
        given = _compact_text(raw.get("given"))
        family = _compact_text(raw.get("family"))
        display = _compact_text(" ".join(value for value in (given, family) if value))
        if not display:
            continue
        orcid = _compact_text(raw.get("ORCID"))
        if orcid:
            orcid = orcid.rsplit("/", 1)[-1]
        authors.append(
            {
                "display_name": display,
                "family_name": family,
                "given_name": given,
                "orcid": orcid,
            }
        )
    issn_print = None
    issn_electronic = None
    for raw in message.get("issn-type") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") == "print":
            issn_print = _compact_text(raw.get("value"))
        elif raw.get("type") == "electronic":
            issn_electronic = _compact_text(raw.get("value"))
    container = _first_text(message.get("container-title"))
    venue = None
    if container:
        venue = {"name": container, "issn": issn_print, "eissn": issn_electronic}
    license_value = None
    licenses = message.get("license") or []
    if licenses and isinstance(licenses[0], dict):
        license_value = _compact_text(licenses[0].get("URL"))
    fields = {
        "bibliographic.title": title,
        "bibliographic.paper_type": _paper_type(message.get("type")),
        "bibliographic.authors": authors,
        "bibliographic.abstract": _compact_text(message.get("abstract")),
        "bibliographic.publication_date": (
            _date_parts(message.get("published-online"))
            or _date_parts(message.get("published-print"))
            or _date_parts(message.get("published"))
            or _date_parts(message.get("issued"))
        ),
        "bibliographic.venue": venue,
        "bibliographic.publisher": _compact_text(message.get("publisher")),
        "bibliographic.volume": _compact_text(message.get("volume")),
        "bibliographic.issue": _compact_text(message.get("issue")),
        "bibliographic.pages": _compact_text(message.get("page")),
        "bibliographic.language": _compact_text(message.get("language")),
        "bibliographic.license": license_value,
    }
    return _Candidate(
        source="crossref",
        record_id=doi.lower(),
        priority=90,
        identifiers={"doi": doi},
        fields={
            key: value for key, value in fields.items() if value not in (None, [], {})
        },
        payload_sha256=_payload_digest(message),
    )


def _europe_pmc_candidate(result: dict[str, Any]) -> _Candidate | None:
    title = _compact_text(result.get("title"))
    if not title:
        return None
    identifiers = {
        key: value
        for key, value in {
            "doi": _compact_text(result.get("doi")),
            "pubmed_id": _compact_text(result.get("pmid")),
            "pmc_id": _compact_text(result.get("pmcid")),
        }.items()
        if value
    }
    if not identifiers:
        return None
    authors: list[dict[str, Any]] = []
    for raw in (result.get("authorList") or {}).get("author") or []:
        if not isinstance(raw, dict):
            continue
        display = _compact_text(raw.get("fullName"))
        if not display:
            continue
        authors.append(
            {
                "display_name": display,
                "family_name": _compact_text(raw.get("lastName")),
                "given_name": _compact_text(raw.get("firstName")),
                "orcid": _compact_text(raw.get("authorId"))
                if raw.get("authorIdType") == "ORCID"
                else None,
            }
        )
    venue_name = _compact_text(result.get("journalTitle"))
    venue = None
    if venue_name:
        venue = {
            "name": venue_name,
            "issn": _compact_text(result.get("journalIssn")),
            "eissn": _compact_text(result.get("journalEissn")),
        }
    raw_pub_type = result.get("pubType")
    fields = {
        "bibliographic.title": title,
        "bibliographic.paper_type": _paper_type(raw_pub_type) if raw_pub_type else None,
        "bibliographic.authors": authors,
        "bibliographic.abstract": _compact_text(result.get("abstractText")),
        "bibliographic.publication_date": (
            _compact_text(result.get("firstPublicationDate"))
            or _compact_text(result.get("electronicPublicationDate"))
            or _compact_text(result.get("pubYear"))
        ),
        "bibliographic.venue": venue,
        "bibliographic.volume": _compact_text(result.get("journalVolume")),
        "bibliographic.issue": _compact_text(result.get("issue")),
        "bibliographic.pages": _compact_text(result.get("pageInfo")),
        "bibliographic.license": _compact_text(result.get("license")),
    }
    record_id = (
        identifiers.get("pmc_id")
        or identifiers.get("pubmed_id")
        or identifiers.get("doi")
    )
    return _Candidate(
        source="europe_pmc",
        record_id=record_id,
        priority=100,
        identifiers=identifiers,
        fields={
            key: value for key, value in fields.items() if value not in (None, [], {})
        },
        payload_sha256=_payload_digest(result),
    )


_ARXIV_VERSION_SUFFIX = re.compile(r"v\d+$", re.IGNORECASE)


def _identity_key(identifier_type: str, value: str) -> str:
    """Comparison key for one identifier; arXiv ids match across versions (1706.03762 == 1706.03762v7)."""
    key = value.casefold()
    if identifier_type == "arxiv_id":
        key = _ARXIV_VERSION_SUFFIX.sub("", key)
    return key


def _arxiv_candidate(xml_text: str) -> _Candidate | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PaperLookupError(
            "metadata_response_invalid",
            "upstream_data_invalid",
            "arXiv 返回了无法解析的 XML",
            retryable=True,
        ) from exc
    atom = "{http://www.w3.org/2005/Atom}"
    arxiv = "{http://arxiv.org/schemas/atom}"
    entry = root.find(f"{atom}entry")
    if entry is None:
        return None
    entry_id = _compact_text(entry.findtext(f"{atom}id"))
    title = _compact_text(entry.findtext(f"{atom}title"))
    if not entry_id or not title:
        return None
    arxiv_id = entry_id.rstrip("/").rsplit("/", 1)[-1]
    doi = _compact_text(entry.findtext(f"{arxiv}doi"))
    authors = []
    for node in entry.findall(f"{atom}author"):
        name = _compact_text(node.findtext(f"{atom}name"))
        if name:
            authors.append({"display_name": name})
    fields = {
        "bibliographic.title": title,
        "bibliographic.paper_type": "preprint",
        "bibliographic.authors": authors,
        "bibliographic.abstract": _compact_text(entry.findtext(f"{atom}summary")),
        "bibliographic.publication_date": (
            _compact_text(entry.findtext(f"{atom}published")) or ""
        )[:10]
        or None,
        "bibliographic.venue": None,
    }
    identifiers = {"arxiv_id": arxiv_id}
    if doi:
        identifiers["doi"] = doi
    return _Candidate(
        source="arxiv",
        record_id=arxiv_id,
        priority=100,
        identifiers=identifiers,
        fields={
            key: value for key, value in fields.items() if value not in (None, [], {})
        },
        payload_sha256=hashlib.sha256(xml_text.encode("utf-8")).hexdigest(),
    )


class PaperLookupService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def lookup(self, request: LookupRequest) -> PaperRecord:
        candidates: list[_Candidate] = []
        transport_failures = 0
        last_error_class: str | None = None
        if request.identifier_type == "arxiv_id":
            try:
                response = await self.client.get(
                    "https://export.arxiv.org/api/query",
                    params={"id_list": request.value, "max_results": 1},
                )
                response.raise_for_status()
                candidate = _arxiv_candidate(response.text)
                if candidate and self._matches_request(candidate, request):
                    candidates.append(candidate)
            except PaperLookupError:
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 or exc.response.status_code in {
                    408,
                    429,
                }:
                    transport_failures += 1
                    last_error_class = f"http_{exc.response.status_code}"
            except httpx.ConnectTimeout:
                transport_failures += 1
                last_error_class = "connect_timeout"
            except httpx.ReadTimeout:
                transport_failures += 1
                last_error_class = "read_timeout"
            except httpx.ConnectError:
                transport_failures += 1
                last_error_class = "connect_failed"
            except (httpx.RequestError, UnicodeError):
                transport_failures += 1
                last_error_class = "network_error"
        else:
            query = {
                "doi": f'DOI:"{request.value}"',
                "pubmed_id": f"EXT_ID:{request.value} AND SRC:MED",
                "pmc_id": f"PMCID:{request.value}",
            }[request.identifier_type]
            try:
                response = await self.client.get(
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    params={
                        "query": query,
                        "format": "json",
                        "pageSize": 5,
                        "resultType": "core",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                for result in (payload.get("resultList") or {}).get("result") or []:
                    candidate = (
                        _europe_pmc_candidate(result)
                        if isinstance(result, dict)
                        else None
                    )
                    if candidate and self._matches_request(candidate, request):
                        candidates.append(candidate)
                        break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 or exc.response.status_code in {
                    408,
                    429,
                }:
                    transport_failures += 1
                    last_error_class = f"http_{exc.response.status_code}"
            except httpx.ConnectTimeout:
                transport_failures += 1
                last_error_class = "connect_timeout"
            except httpx.ReadTimeout:
                transport_failures += 1
                last_error_class = "read_timeout"
            except httpx.ConnectError:
                transport_failures += 1
                last_error_class = "connect_failed"
            except (httpx.RequestError, UnicodeError):
                transport_failures += 1
                last_error_class = "network_error"
            except (ValueError, TypeError) as exc:
                raise PaperLookupError(
                    "metadata_response_invalid",
                    "upstream_data_invalid",
                    "Europe PMC 返回了无效元数据",
                    retryable=True,
                ) from exc

        doi = (
            request.value
            if request.identifier_type == "doi"
            else next(
                (
                    item.identifiers.get("doi")
                    for item in candidates
                    if item.identifiers.get("doi")
                ),
                None,
            )
        )
        if doi:
            try:
                response = await self.client.get(
                    f"https://api.crossref.org/works/{quote(doi, safe='/')}",
                    headers={"User-Agent": "paperfetch/2.0"},
                )
                response.raise_for_status()
                message = response.json().get("message")
                candidate = (
                    _crossref_candidate(message) if isinstance(message, dict) else None
                )
                if candidate and self._matches_request(candidate, request):
                    candidates.append(candidate)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 or exc.response.status_code in {
                    408,
                    429,
                }:
                    transport_failures += 1
                    last_error_class = f"http_{exc.response.status_code}"
            except httpx.ConnectTimeout:
                transport_failures += 1
                last_error_class = "connect_timeout"
            except httpx.ReadTimeout:
                transport_failures += 1
                last_error_class = "read_timeout"
            except httpx.ConnectError:
                transport_failures += 1
                last_error_class = "connect_failed"
            except (httpx.RequestError, UnicodeError):
                transport_failures += 1
                last_error_class = "network_error"
            except (ValueError, TypeError) as exc:
                raise PaperLookupError(
                    "metadata_response_invalid",
                    "upstream_data_invalid",
                    "Crossref 返回了无效元数据",
                    retryable=True,
                ) from exc

        if not candidates:
            if transport_failures:
                err_class = last_error_class or "network_error"
                raise PaperLookupError(
                    "metadata_transport_failed",
                    err_class,
                    f"官方元数据服务通信异常 ({err_class})，无法确认论文身份",
                    retryable=True,
                )
            raise PaperLookupError(
                "metadata_not_resolved",
                "resource_not_found",
                "官方元数据源未找到该论文标识",
                retryable=False,
            )
        return self._merge(request, candidates)

    @staticmethod
    def _matches_request(candidate: _Candidate, request: LookupRequest) -> bool:
        observed = candidate.identifiers.get(request.identifier_type)
        if observed is None:
            # Crossref may only confirm the DOI recovered from PMID/PMCID metadata.
            return request.identifier_type != "doi"
        try:
            normalized = LookupRequest.normalize(request.identifier_type, observed)
        except PaperLookupError:
            return False
        return _identity_key(
            request.identifier_type, normalized.value
        ) == _identity_key(request.identifier_type, request.value)

    @staticmethod
    def _merge(request: LookupRequest, candidates: list[_Candidate]) -> PaperRecord:
        ordered = sorted(candidates, key=lambda item: item.priority, reverse=True)
        identifiers: dict[str, str] = {request.identifier_type: request.value}
        identifier_sources: dict[str, list[str]] = {request.identifier_type: []}
        source_ids: dict[int, str] = {}
        snapshots: list[SourceSnapshot] = []
        for index, candidate in enumerate(ordered, start=1):
            source_id = f"{candidate.source}-{index}"
            source_ids[id(candidate)] = source_id
            snapshots.append(
                SourceSnapshot(
                    source_id=source_id,
                    source=candidate.source,
                    record_id=candidate.record_id,
                    payload_sha256=candidate.payload_sha256,
                )
            )
            for field, raw_value in candidate.identifiers.items():
                try:
                    value = getattr(IdentifierSet(**{field: raw_value}), field)
                except Exception:
                    continue
                existing = identifiers.get(field)
                if existing is not None and _identity_key(
                    field, existing
                ) != _identity_key(field, value):
                    raise PaperLookupError(
                        "metadata_identity_conflict",
                        "identity_conflict",
                        f"官方元数据对 {field} 给出冲突标识",
                        retryable=False,
                    )
                if existing is None or field != "arxiv_id":
                    # Keep the caller's arXiv id as given; the API always echoes the latest "vN".
                    identifiers[field] = value
                identifier_sources.setdefault(field, []).append(source_id)

        field_values: dict[str, Any] = {}
        field_sources: dict[str, list[str]] = {}
        for candidate in ordered:
            source_id = source_ids[id(candidate)]
            for field, value in candidate.fields.items():
                if field not in field_values:
                    field_values[field] = value
                if value == field_values[field]:
                    field_sources.setdefault(field, []).append(source_id)
        title = field_values.get("bibliographic.title")
        if not title:
            raise PaperLookupError(
                "metadata_title_missing",
                "upstream_data_invalid",
                "官方记录缺少论文标题",
                retryable=False,
            )
        for field, source_list in identifier_sources.items():
            if not source_list:
                # User-supplied identifier is authoritative but also tied to every exact endpoint response.
                source_list.extend(source_ids.values())
            field_sources[f"identifiers.{field}"] = list(dict.fromkeys(source_list))
        provenance = MetadataProvenance(
            sources=snapshots,
            fields=[
                FieldProvenance(field=field, source_ids=list(dict.fromkeys(sources)))
                for field, sources in sorted(field_sources.items())
                if sources
            ],
        )
        bibliography = BibliographicMetadata(
            title=title,
            paper_type=field_values.get("bibliographic.paper_type", "other"),
            authors=[
                Author.model_validate(item)
                for item in field_values.get("bibliographic.authors", [])
            ],
            abstract=field_values.get("bibliographic.abstract"),
            publication_date=field_values.get("bibliographic.publication_date"),
            venue=(
                VenueMetadata.model_validate(field_values["bibliographic.venue"])
                if field_values.get("bibliographic.venue")
                else None
            ),
            publisher=field_values.get("bibliographic.publisher"),
            volume=field_values.get("bibliographic.volume"),
            issue=field_values.get("bibliographic.issue"),
            pages=field_values.get("bibliographic.pages"),
            language=field_values.get("bibliographic.language"),
            license=field_values.get("bibliographic.license"),
        )
        now = datetime.now(timezone.utc)
        return PaperRecord(
            paper_id=new_paper_id(),
            identifiers=IdentifierSet(**identifiers),
            bibliographic=bibliography,
            provenance=provenance,
            created_at=now,
            updated_at=now,
        )


async def lookup_many(
    client: httpx.AsyncClient,
    requests: list[LookupRequest],
) -> list[PaperRecord | PaperLookupError]:
    service = PaperLookupService(client)

    async def one(request: LookupRequest) -> PaperRecord | PaperLookupError:
        try:
            return await service.lookup(request)
        except PaperLookupError as exc:
            return exc

    return list(await asyncio.gather(*(one(request) for request in requests)))
