"""Field-level metadata packaging for acquired paper records."""

from __future__ import annotations

import copy
import json
from typing import Any

from ..paper_sources import PaperRecord


SCHEMA_VERSION = "rh.paper_metadata_facts.v1"


def paper_metadata_package_from_record(record: PaperRecord) -> dict[str, Any]:
    recorded_facts = copy.deepcopy(record.recorded_facts)
    recorded_facts.setdefault("venue", record.venue)
    recorded_facts.setdefault("journal", record.journal)
    recorded_facts.setdefault("publisher", record.publisher)
    recorded_facts.setdefault("document_type", record.document_type)
    recorded_facts.setdefault("citation_count", record.citation_count)
    recorded_facts.setdefault("reference_count", record.reference_count)
    recorded_facts.setdefault("venue_metadata", {})

    curation_signals = copy.deepcopy(record.curation_signals)
    curation_signals["selection_basis"] = list(record.selection_basis)
    curation_signals.setdefault("selection_rank", record.selection_rank)
    curation_signals.setdefault("selection_bucket", record.selection_bucket)
    curation_signals["quality_score"] = None

    return {
        "schema_version": SCHEMA_VERSION,
        "paper_identity": {
            "title": record.title,
            "doi": record.doi,
            "arxiv_id": record.arxiv_id,
            "s2_id": record.s2_id,
            "openalex_id": record.openalex_id,
            "openreview_id": record.openreview_id,
            "pmid": record.pmid,
            "pmcid": record.pmcid,
        },
        "source_refs": copy.deepcopy(record.source_refs),
        "recall_hits": copy.deepcopy(record.recall_hits),
        "institution_signals": copy.deepcopy(record.institution_signals),
        "recorded_facts": recorded_facts,
        "available_files": copy.deepcopy(record.available_files),
        "field_conflicts": copy.deepcopy(record.field_conflicts),
        "merged_from": list(record.merged_from),
        "curation_signals": curation_signals,
        "requires_agent_review": list(record.requires_agent_review),
    }


def stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
