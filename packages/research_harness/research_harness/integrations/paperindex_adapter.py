from __future__ import annotations

import json
import logging
from pathlib import Path

from paperindex import PaperIndexer
from paperindex.cards.schema import PAPER_CARD_SCHEMA_VERSION
from paperindex.parsing import MinerUArtifactParser
from paperindex.types import (
    SectionNode,
    SectionResult,
    StructureResult,
)
from paperindex.utils import sha256_file

from ..core.paper_pool import PaperPool
from ..storage.models import PaperAnnotation

logger = logging.getLogger(__name__)


class PaperIndexAdapter:
    def __init__(self, conn, artifacts_root: str | Path):
        self._conn = conn
        self._artifacts_root = Path(artifacts_root)

    def annotate_paper(
        self,
        paper_id: int,
        pdf_path: str | Path,
        sections: list[str] | None = None,
        *,
        skip_card: bool = False,
    ) -> dict[str, object]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

        selected_sections = sections or [
            "summary",
            "methodology",
            "experiments",
            "equations",
            "limitations",
            "reproduction_notes",
        ]
        current_pdf_hash = sha256_file(pdf_path)
        artifact_dir = self._artifacts_root / f"paper_{paper_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        structure_path = artifact_dir / "structure.json"
        card_path = artifact_dir / "card.json"
        indexer = PaperIndexer(parser=self._mineru_parser(paper_id))
        parser_name = indexer.parser_name

        structure = self._load_cached_structure(
            structure_path, current_pdf_hash, parser_name
        )
        structure_source = "cache"
        if structure is None:
            structure = indexer.extract_structure(pdf_path)
            structure_source = "fresh"
            structure_path.write_text(
                json.dumps(structure.to_dict(), ensure_ascii=False, indent=2)
            )

        pool = PaperPool(self._conn)
        cached_annotations = {
            item.section: item
            for item in pool.get_annotations(paper_id)
            if item.pdf_hash_at_extraction == current_pdf_hash
        }
        reused_sections = [
            section for section in selected_sections if section in cached_annotations
        ]
        extracted_sections = [
            section
            for section in selected_sections
            if section not in cached_annotations
        ]

        extracted_results: dict[str, SectionResult] = {}
        for section_name in extracted_sections:
            result = indexer.extract_section(structure, section_name)
            extracted_results[section_name] = result
            pool.upsert_annotation(
                PaperAnnotation(
                    paper_id=paper_id,
                    section=result.section,
                    content=result.content,
                    source="paperindex:rule-based",
                    confidence=result.confidence,
                    extractor_version=result.extractor_version,
                    pdf_hash_at_extraction=result.source_pdf_hash,
                )
            )

        merged_sections: dict[str, SectionResult] = {}
        for annotation in pool.get_annotations(paper_id):
            if annotation.pdf_hash_at_extraction != current_pdf_hash:
                continue
            merged_sections[annotation.section] = SectionResult(
                section=annotation.section,
                content=annotation.content,
                confidence=annotation.confidence,
                extractor_version=annotation.extractor_version,
                source_pdf_hash=annotation.pdf_hash_at_extraction,
                model_used="",
            )
        merged_sections.update(extracted_results)

        card_ok = False
        card = None
        if skip_card:
            logger.debug("Skipping build_card for paper %d (skip_card=True)", paper_id)
        else:
            try:
                card = indexer.build_card(
                    structure,
                    [merged_sections[name] for name in sorted(merged_sections)],
                )
                card_payload = {
                    "schema_version": PAPER_CARD_SCHEMA_VERSION,
                    **card.to_dict(),
                }
                card_path.write_text(
                    json.dumps(card_payload, ensure_ascii=False, indent=2)
                )
                card_ok = True
            except Exception as card_err:
                logger.warning(
                    "build_card failed for paper %d (section annotations still saved): %s",
                    paper_id,
                    card_err,
                )

        self._conn.execute(
            "DELETE FROM paper_artifacts WHERE paper_id = ? AND artifact_type IN (?, ?)",
            (paper_id, "paperindex_structure", "paperindex_card"),
        )
        self._conn.execute(
            "INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata) VALUES (?, ?, ?, ?)",
            (
                paper_id,
                "paperindex_structure",
                str(structure_path),
                json.dumps(
                    {
                        "pdf_hash": structure.pdf_hash,
                        "page_count": structure.page_count,
                        "source": structure_source,
                        "parser": structure.raw.get("parser", parser_name),
                    }
                ),
            ),
        )
        if card_ok and card is not None:
            self._conn.execute(
                "INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata) VALUES (?, ?, ?, ?)",
                (
                    paper_id,
                    "paperindex_card",
                    str(card_path),
                    json.dumps(
                        {
                            "fields": sorted(card.keys()),
                            "section_count": len(merged_sections),
                        }
                    ),
                ),
            )
        self._conn.execute(
            "UPDATE papers SET pdf_path = ?, pdf_hash = ?, status = ? WHERE id = ?",
            (str(pdf_path), current_pdf_hash, "annotated", paper_id),
        )
        self._conn.commit()

        return {
            "paper_id": paper_id,
            "pdf_path": str(pdf_path),
            "annotation_count": len(selected_sections),
            "artifact_dir": str(artifact_dir),
            "structure_path": str(structure_path),
            "card_path": str(card_path) if card_ok else None,
            "sections": selected_sections,
            "requested_sections": selected_sections,
            "extracted_sections": extracted_sections,
            "reused_sections": reused_sections,
            "structure_source": structure_source,
            "card_ok": card_ok,
            "status": "annotated",
        }

    def _mineru_parser(self, paper_id: int) -> MinerUArtifactParser | None:
        """Prefer an imported MinerU parse artifact over re-parsing the PDF.

        Returning None keeps the default parser resolution (pymupdf), so
        papers without a parse artifact behave exactly as before. A parser
        switch invalidates the cached structure via the parser-name check.
        """
        row = self._conn.execute(
            "SELECT metadata FROM paper_artifacts"
            " WHERE paper_id = ? AND artifact_type = 'paper_parse_artifact'"
            " ORDER BY id DESC LIMIT 1",
            (paper_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            return None
        if payload.get("provider") != "mineru" or payload.get("status") != "parsed":
            return None
        markdown_path = Path(str(payload.get("markdown_path") or ""))
        if not markdown_path.is_file():
            logger.warning(
                "paper %d has a MinerU parse artifact but %s is missing; "
                "falling back to the default parser",
                paper_id,
                markdown_path,
            )
            return None
        content_list = str(payload.get("content_list_path") or "")
        return MinerUArtifactParser(
            markdown_path,
            content_list if content_list and Path(content_list).is_file() else None,
        )

    @staticmethod
    def _load_cached_structure(
        structure_path: Path, expected_pdf_hash: str, expected_parser: str
    ) -> StructureResult | None:
        if not structure_path.exists():
            return None
        try:
            payload = json.loads(structure_path.read_text())
        except json.JSONDecodeError:
            return None
        if payload.get("pdf_hash") != expected_pdf_hash:
            return None
        raw = payload.get("raw", {})
        parser = raw.get("parser") if isinstance(raw, dict) else None
        if parser is not None and parser != expected_parser:
            return None
        if parser is None and expected_parser != "pymupdf":
            return None
        return StructureResult(
            doc_name=payload.get("doc_name", structure_path.stem),
            tree=[SectionNode.from_dict(item) for item in payload.get("structure", [])],
            pdf_hash=payload.get("pdf_hash", ""),
            page_count=int(payload.get("page_count", 0) or 0),
            raw=payload.get("raw", {}),
        )
