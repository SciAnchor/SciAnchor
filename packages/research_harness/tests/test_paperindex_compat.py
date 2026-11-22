"""Compatibility guards for the research_harness.paperindex shim.

The paperindex engine lives as a workspace sibling package under
packages/paperindex; research_harness.paperindex is a compatibility shim.
These tests pin the shim's aliasing behavior and the PaperCard schema
contract the monorepo consumes.
"""

import paperindex
import pytest

from paperindex.cards.schema import (
    PAPER_CARD_SCHEMA_VERSION,
    SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS,
    PaperCard,
    PaperCardSchemaError,
)


def test_shim_top_level_exports():
    import research_harness.paperindex as shim

    assert shim.PaperIndexer is paperindex.PaperIndexer
    assert shim.PaperRecord is paperindex.PaperRecord
    assert shim.__version__ == paperindex.__version__


def test_shim_deep_imports_share_module_identity():
    # Legacy deep imports must resolve to the *same* module objects as
    # paperindex.* — otherwise dataclass/isinstance identity splits.
    from research_harness.paperindex.cards import schema as shim_schema
    from research_harness.paperindex.retrieval import bm25 as shim_bm25

    import paperindex.cards.schema as real_schema
    import paperindex.retrieval.bm25 as real_bm25

    assert shim_schema is real_schema
    assert shim_bm25 is real_bm25
    assert shim_schema.PaperCard is PaperCard


def test_monorepo_supports_pinned_schema_version():
    # Bumping the paperindex pin past a schema break must fail loudly here;
    # update the consumers (adapter stamp, topic_layer readers) alongside.
    assert PAPER_CARD_SCHEMA_VERSION == "papercard/v3"
    assert "papercard/v2" in SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS


def test_unsupported_card_stamp_rejected():
    with pytest.raises(PaperCardSchemaError):
        PaperCard.from_dict({"schema_version": "papercard/v999"})
