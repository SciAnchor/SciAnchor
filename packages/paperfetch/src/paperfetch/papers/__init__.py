"""SPC 1.0 论文事实模型。"""

from paperfetch.papers.models import (
    Author,
    BibliographicMetadata,
    FieldProvenance,
    FulltextState,
    IdentifierSet,
    MetadataProvenance,
    PaperRecord,
    SourceSnapshot,
    new_paper_id,
)

__all__ = [
    "Author",
    "BibliographicMetadata",
    "FieldProvenance",
    "FulltextState",
    "IdentifierSet",
    "MetadataProvenance",
    "PaperRecord",
    "SourceSnapshot",
    "new_paper_id",
]
