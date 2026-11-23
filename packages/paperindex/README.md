# paperindex

PDF parsing, paper-card extraction, indexing, and retrieval engine for
[Research Harness](https://github.com/scianchor/scianchor).

Maintained as an independent workspace package under `packages/paperindex/` so
it can be developed, tested, and installed alongside `packages/llm_router/` and
`packages/research_harness/` without cross-repo SHA pinning.

## Layout

```text
paperindex/
  cards/       Paper Card schema (versioned contract) + LLM extraction/assembly
  extraction/  Section extractors and prompts
  indexing/    Page index, section text, markdown outlines
  library/     Local paper library store (sqlite)
  parsing/     PDF parser backends (pymupdf default, docling optional)
  retrieval/   BM25 search, structure matching, rerankers
  cli.py       `paperindex` console script
tests/
```

## Install

```bash
pip install -e ../llm_router"[all]"
pip install -e ".[dev]"
pytest tests/ -q
```

Optional rich PDF parsing: `pip install -e ".[docling]"`.

## PaperCard schema contract

`paperindex.cards.schema` declares `PAPER_CARD_SCHEMA_VERSION` and
`SUPPORTED_PAPER_CARD_SCHEMA_VERSIONS`. Producers stamp `schema_version`
into persisted card payloads; `PaperCard.from_dict` rejects unsupported
versions with `PaperCardSchemaError`. Unstamped payloads are accepted as
legacy (pre-versioning) cards. Bump the version on any breaking field
change and keep the consumer-side guard in the monorepo
(`tests/test_paperindex_compat.py`) in sync.
