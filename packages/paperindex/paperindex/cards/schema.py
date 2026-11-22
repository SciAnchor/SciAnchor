"""Open-field PaperCard schema with legacy v2 read compatibility."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


PAPER_CARD_SCHEMA_VERSION = "papercard/v3"
SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS: tuple[str, ...] = (
    "papercard/v2",
    PAPER_CARD_SCHEMA_VERSION,
)


class PaperCardSchemaError(ValueError):
    """A card payload declared a schema_version this package cannot read."""


def _entry_text(data: dict[str, Any], key: str, *, required: bool = False) -> str:
    value = data.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()):
        requirement = "a non-empty string" if required else "a string"
        raise PaperCardSchemaError(f"PaperCard entry {key!r} must be {requirement}")
    return value


@dataclass(frozen=True)
class OpenField:
    """One domain-defined field grounded in source text."""

    name: str
    value: str
    insight: str = ""
    quote: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "value": self.value,
            "insight": self.insight,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenField:
        return cls(
            name=_entry_text(data, "name", required=True),
            value=_entry_text(data, "value", required=True),
            insight=_entry_text(data, "insight"),
            quote=_entry_text(data, "quote"),
        )


@dataclass(frozen=True)
class OpenRelation:
    """One domain-defined relation grounded in source text."""

    source: str
    relation: str
    target: str
    insight: str = ""
    quote: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "insight": self.insight,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenRelation:
        return cls(
            source=_entry_text(data, "source", required=True),
            relation=_entry_text(data, "relation", required=True),
            target=_entry_text(data, "target", required=True),
            insight=_entry_text(data, "insight"),
            quote=_entry_text(data, "quote"),
        )


# Retained as import-compatible v2 helpers. New cards use OpenField/OpenRelation.
@dataclass(frozen=True)
class MathFormulation:
    objective: str | None = None
    constraints: list[str] = field(default_factory=list)
    key_equations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "constraints": list(self.constraints),
            "key_equations": list(self.key_equations),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MathFormulation | None:
        if data is None:
            return None
        return cls(
            objective=data.get("objective"),
            constraints=list(data.get("constraints") or []),
            key_equations=list(data.get("key_equations") or []),
        )


@dataclass(frozen=True)
class StructuredResult:
    metric: str
    value: str
    baseline: str | None = None
    delta: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "baseline": self.baseline,
            "delta": self.delta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuredResult:
        return cls(
            metric=str(data.get("metric") or ""),
            value=str(data.get("value") or ""),
            baseline=data.get("baseline"),
            delta=data.get("delta"),
        )


@dataclass(frozen=True)
class EvidenceEntry:
    section: str
    confidence: float = 0.0
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "confidence": self.confidence,
            "snippet": self.snippet,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceEntry:
        raw = data.get("confidence", 0.0)
        confidence = (
            {"high": 0.9, "medium": 0.6, "low": 0.3}.get(raw.strip().lower(), 0.0)
            if isinstance(raw, str)
            else float(raw or 0.0)
        )
        return cls(
            str(data.get("section") or ""), confidence, str(data.get("snippet") or "")
        )


_IDENTITY_FIELDS = (
    "paper_id",
    "title",
    "authors",
    "venue",
    "year",
    "pdf_path",
    "source_url",
    "artifact_links",
    "domain_tags",
    "technical_tags",
)
_V2_RELATIONS = {"datasets": "evaluated_on", "baselines": "compared_against"}
_V2_ALIASES = {
    "research_background": "motivation",
    "target_problem": "problem_definition",
    "method_type": "method_family",
    "main_contributions": "contributions",
    "claimed_novelties": "contributions",
    "citation_anchors": "key_references",
}


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise PaperCardSchemaError(f"PaperCard {key!r} must be a list")
    return value


def _objects(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = _list(data, key)
    if not all(isinstance(item, dict) for item in values):
        raise PaperCardSchemaError(f"PaperCard {key!r} entries must be objects")
    return values


def _legacy_fields(data: dict[str, Any]) -> list[OpenField]:
    fields: list[OpenField] = []
    for raw_name, raw_value in data.items():
        if (
            raw_name in _IDENTITY_FIELDS
            or raw_name in _V2_RELATIONS
            or raw_name == "schema_version"
        ):
            continue
        name = _V2_ALIASES.get(raw_name, raw_name)
        if name == "limitations":
            name = "self_declared_limitation"
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in values:
            if value is not None and value != "":
                fields.append(OpenField(name, _text(value)))
    return fields


def _legacy_relations(data: dict[str, Any]) -> list[OpenRelation]:
    return [
        OpenRelation("paper", relation, _text(value))
        for key, relation in _V2_RELATIONS.items()
        for value in _list(data, key)
        if value is not None and value != ""
    ]


@dataclass(frozen=True)
class PaperCard:
    """A paper identity plus ordered, domain-open evidence fields and relations."""

    paper_id: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: str | None = None
    pdf_path: str | None = None
    source_url: str | None = None
    artifact_links: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    technical_tags: list[str] = field(default_factory=list)
    fields: list[OpenField] = field(default_factory=list)
    relations: list[OpenRelation] = field(default_factory=list)
    independent_defects: list[OpenField] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()

    def values(self):
        return self.to_dict().values()

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(PAPER_CARD_FIELDS)

    def __getattr__(self, name: str) -> Any:
        """Keep owner-repo readers working while persisted output moves to v3."""
        aliases = {
            "core_idea": ("core_method", "core_idea"),
            "method_summary": ("method_component", "method_summary"),
            "method_family": ("method_family",),
            "key_results": ("result", "results", "key_result", "key_results"),
            "limitations": ("self_declared_limitation",),
        }
        names = aliases.get(name)
        if names:
            matches = [item.value for item in self.fields if item.name in names]
            return (
                matches
                if name in {"key_results", "limitations"}
                else next(iter(matches), None)
            )
        raise AttributeError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_CARD_SCHEMA_VERSION,
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": list(self.authors),
            "venue": self.venue,
            "year": self.year,
            "pdf_path": self.pdf_path,
            "source_url": self.source_url,
            "artifact_links": list(self.artifact_links),
            "domain_tags": list(self.domain_tags),
            "technical_tags": list(self.technical_tags),
            "fields": [item.to_dict() for item in self.fields],
            "relations": [item.to_dict() for item in self.relations],
            "independent_defects": [
                item.to_dict() for item in self.independent_defects
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperCard:
        if not isinstance(data, dict):
            raise PaperCardSchemaError("PaperCard payload must be an object")
        version = str(data.get("schema_version") or "")
        if version and version not in SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS:
            raise PaperCardSchemaError(
                f"unsupported PaperCard schema_version {version!r}; supported: "
                f"{', '.join(SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS)}"
            )
        is_v3 = version == PAPER_CARD_SCHEMA_VERSION
        if is_v3:
            allowed = {
                "schema_version",
                *_IDENTITY_FIELDS,
                "fields",
                "relations",
                "independent_defects",
            }
            unexpected = sorted(set(data) - allowed)
            if unexpected:
                raise PaperCardSchemaError(
                    f"PaperCard v3 has unexpected fields: {', '.join(unexpected)}"
                )
        authors = _list(data, "authors")
        artifact_links = _list(data, "artifact_links")
        domain_tags = _list(data, "domain_tags")
        technical_tags = _list(data, "technical_tags")
        open_fields = _objects(data, "fields") if is_v3 else []
        open_relations = _objects(data, "relations") if is_v3 else []
        defects = _objects(data, "independent_defects") if is_v3 else []
        return cls(
            paper_id=data.get("paper_id"),
            title=data.get("title"),
            authors=[str(item) for item in authors],
            venue=data.get("venue"),
            year=data.get("year"),
            pdf_path=data.get("pdf_path"),
            source_url=data.get("source_url"),
            artifact_links=[str(item) for item in artifact_links],
            domain_tags=[str(item) for item in domain_tags],
            technical_tags=[str(item) for item in technical_tags],
            fields=(
                [OpenField.from_dict(item) for item in open_fields]
                if is_v3
                else _legacy_fields(data)
            ),
            relations=(
                [OpenRelation.from_dict(item) for item in open_relations]
                if is_v3
                else _legacy_relations(data)
            ),
            independent_defects=[OpenField.from_dict(item) for item in defects],
        )


PAPER_CARD_FIELDS: tuple[str, ...] = _IDENTITY_FIELDS + (
    "fields",
    "relations",
    "independent_defects",
)


def build_empty_paper_card() -> PaperCard:
    return PaperCard()
