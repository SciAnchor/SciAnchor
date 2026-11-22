# Paper search and acquisition

RH owns topic state, source records and annotations. Scholarly search runs on
public sources that need no credentials. SPC (paperfetch) is an optional
component: when its `spc` CLI is installed, RH also uses it for search fallback,
exact identifier lookup, citation graphs and PDF acquisition.

## Sources

`paper_source_clients.build_provider_suite` is the one place that decides which
sources run. Workflow entry points never construct a source directly.

| Source | Name | Notes |
|---|---|---|
| Local cache | `papervault` | When `RESEARCH_HARNESS_PAPERVAULT_DB` points at a PaperVault database |
| Semantic Scholar | `semantic_scholar` | Public Graph API, keyless rate limit |
| OpenAlex | `openalex` | Public works API |
| Crossref | `crossref` | Public REST API |
| arXiv | `arxiv` | Public export API |
| PubMed | `pubmed` | NCBI E-utilities, keyless rate limit |
| OpenReview | `openreview` | Public API v2 |
| SPC | `spc` | Optional; joins only when the `spc` CLI is on `PATH` |

No source reads an API key. Keys in the environment are ignored, so every
checkout searches the same way at the sources' public rate limits. Set
`<NAME>_ENABLE=0` (for example `PUBMED_ENABLE=0`) to turn a public source off.
`rh --json search providers` shows the current suite.

## Routes

| Operation | Runtime entry | Route |
|---|---|---|
| Primitive search / novelty evidence | `paper_search` | Local pool, then the public sources in parallel; SPC when installed and the fan-out found nothing |
| CLI, discovery, panorama and exemplar discovery | Shared provider suite | Every enabled source |
| Metadata enrichment | `PaperPool.enrich_metadata` | SPC exact lookup when installed, then identity-matched search results |
| Citation verification | `verify_citation` | Search with metadata conflict checks |
| Citation expansion / frontier | SPC bridge | SPC graph (requires SPC) |
| PDF acquisition | `download_single` | Verified local cache, then SPC PDF acquisition (requires SPC) |

Without SPC, PDFs enter through `rh paper ingest-manual` (rename the file
`<paper_id>_*.pdf`) or a seed pack import.

## Failure semantics

A source being unavailable, timing out, rate-limiting, or returning no matching
record is not proof that a paper does not exist.

- Each failing source is reported in `provider_errors`; results from the
  sources that answered are kept.
- An empty answer is not an outage. When no source answered at all, search
  raises instead of returning a silent empty result.
- Citation verification never marks a citation as invented because sources
  were unavailable; an absent hit is `not_found`.
- An unresolved identifier is not an empty citation graph. A DOI supplied by a
  user is not itself verification.

PDF success requires contained file paths, actual PDF bytes, minimum size,
identity validation and a recorded hash.

## Identifier-free URLs

When a record has no identifier fields, first recover an embedded DOI from its
supplied URL. Otherwise use exact-title discovery with version evidence (year,
venue or matching source URL); do not select an arbitrary first hit. Same-title
conference slides and journal articles are different resources. Ambiguous or
unresolved identity is returned as `ambiguous_paper_identity` or
`paper_identity_unresolved`, not a successful download.

Exact lookup preserves `metadata_not_resolved` separately from
`metadata_transport_failed` and its retryability.
