# External Acquisition via paperfetch (SPC)

paperfetch (`packages/paperfetch` in this repository) is the public SPC; its CLI is `paperfetch`, with `spc` as an alias that RH calls.

Research Harness can hand its hard-to-acquire paper tail to
paperfetch
(SPC) and import the results through an audited boundary. SPC is an
**optional external provider**: RH never imports its code, never requires it
to be installed, and degrades gracefully when it is absent.


---

## Architecture: Contract Decoupling

```text
Layer 1 — RH-native (always on)
  OA acquisition routes · import-boundary validation (identity audit,
  %PDF/size/sha256, URL ownership) · failure-taxonomy mapping · provenance

Layer 2 — Contract layer
  RH -> SPC : wants-list export (SPC manual-seed JSON)
  SPC -> RH : seed pack import (seed_papers.jsonl / run_report.json /
              pdf/ / mineru/)

Layer 3 — SPC-owned (never enters RH)
  browser/mirror/captcha stacks · publisher API backends ·
  SPC-side download caching
```

The integration point is SPC's **seed pack contract**
(`seed_papers.jsonl` + `run_report.json` with
`report_version: seed-paper-curator.run-report.v1`), not SPC's code. RH
fails deterministically on unknown contract versions instead of guessing.

---

## Round-Trip Workflow

```bash
# 1. Native acquisition first
rh paper acquire <topic_id>

# 2. Export what RH could not get, shaped as SPC manual seeds
rh paper export-spc-wants <topic_id>
#    -> .research-harness/spc/wants-topic<id>.json
#    Feed manual_seeds into an SPC Search Brief and run `spc curate`
#    on the machine that has SPC (and its credentials) configured.

# 3. Import the resulting seed pack back into RH
rh paper import-seed-pack /path/to/seed_pack_dir --topic <topic_id>

# 4. Inspect coverage and failure clustering at any point
rh paper diagnose-acquisition <topic_id>
```

All three commands support the global `--json` flag.

### What import enforces

Every seed pack passes RH's own boundary checks — SPC output is treated as
untrusted input:

- papers land with `screening_status=candidate`; screening stays RH-owned;
- field-level provenance, recall hits, and field conflicts from
  `seed_papers.jsonl` are preserved as `paper_metadata_facts` artifacts;
- PDFs are accepted only after `%PDF` magic + minimum size + sha256 +
  identity audit (title/DOI/PMID against extracted text), with
  path-traversal guards; source URLs matching figure/supplement patterns
  are rejected even when the identity audit passes;
- SPC's per-route download history is recorded as `external_route_audit`
  artifacts, with SPC failure classes mapped onto RH's taxonomy (originals
  preserved; `subscription_required` means do not auto-retry);
- parsed `mineru/<doi>/full.md` files are imported as
  `rh.paper_parse_artifact.v1` (pack-relative resolution only, symlink
  escapes refused, archives never extracted);
- repro-audit fields (`code_url`, `reproducibility_status`,
  `repo_metadata`) surface into `curation_signals` — signals, never
  quality scores.

---

## PaperVault Local Metadata Source

SPC syncs PaperVault (a curated CS/AI top-venue corpus, ~660k papers) into
a local SQLite/FTS5 database via `spc sync-papervault`. RH reads that file
directly — zero network, millisecond recall — while syncing stays SPC's
job. RH opens it read-only and treats the schema as a frozen contract.

```bash
export RESEARCH_HARNESS_PAPERVAULT_DB=/path/to/.spc_cache/papervault.db
```

When configured and present, `papervault` joins the search provider suite
first (search priority 119; metadata field merges stay below online
canonical sources at 108). Unset or missing file means the provider is
silently skipped.

---

## Venue Facts (journal_master.db)

SPC also derives `journal_master.db` (~22k journals with CCF/CAS/JCR
facts). RH's single venue-fact lookup service
(`research_harness.venue_facts`) opens it read-only for exact journal
lookups; conferences and the offline baseline stay in RH's hardcoded
registry. Unset or missing file silently degrades to the hardcoded
registry (same pattern as PaperVault).

```bash
# example local path (SPC checkout)
export RESEARCH_HARNESS_JOURNAL_MASTER_DB=/path/to/your/journal_master.db
```

`rh doctor` reports this as the `venue_facts` check
(`not_configured` / `ready` with row count / `missing`); it is optional,
so the check never fails.

---

## Native Acquisition Caches (opt-in)

Independent of SPC, the RH downloader gains two caches, both disabled
unless the cache directory is set:

```bash
export RESEARCH_HARNESS_PDF_CACHE_DIR=~/.research-harness/pdf-cache
export RESEARCH_HARNESS_PDF_FAILURE_TTL_SEC=86400   # optional; 0 disables
```

- **Verified PDF cache** — only files that passed magic/size checks are
  stored; hits are re-identity-audited against the requesting paper before
  being served. Cache filenames use the same key scheme as SPC seed-pack
  PDFs (`doi_…` / `arxiv_…` / `title_<hash>`), so the two stay mutually
  recognizable.
- **Failure TTL cache** — remembers (paper, route, host) failures so
  reruns skip known-bad routes until the TTL expires (audited as skipped
  attempts with `decision_reason=failure_cache_ttl`).

---

## Diagnostics

`rh doctor` includes an `spc_provider` check reporting whether the `spc`
CLI is on PATH and whether `RESEARCH_HARNESS_PAPERVAULT_DB` points at an
existing file. SPC being absent is never a failure (`ok` is always true).

`rh paper diagnose-acquisition <topic_id>` aggregates both audit streams
(`pdf_route_audit` from native downloads, `external_route_audit` from
imports): coverage rate, failure-taxonomy histograms split by origin,
publisher and DOI-prefix failure clustering, slowest attempts, and the
list of still-uncovered papers with their latest failure class.

---

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `RESEARCH_HARNESS_PAPERVAULT_DB` | Path to the spc-synced `papervault.db` (read-only) | unset = provider skipped |
| `RESEARCH_HARNESS_JOURNAL_MASTER_DB` | Path to SPC's `journal_master.db` for venue CCF/CAS facts (read-only) | unset = hardcoded registry only |
| `RESEARCH_HARNESS_PDF_CACHE_DIR` | Root for verified PDF cache + failure cache | unset = caches disabled |
| `RESEARCH_HARNESS_PDF_FAILURE_TTL_SEC` | Failure-cache TTL in seconds | `86400`; `0` disables |

### Shared scholarly-source config

For RH and SPC on the same machine, keep shared metadata/search credentials and
contact metadata in `~/.config/research-harness/private.env`.

- RH loads that file directly.
- SPC loads its own `.env` first, then falls back to the RH file with
  `override=False`, so SPC-local overrides still win.
- Scope of the shared file: S2 / Semantic Scholar, OpenAlex, Crossref polite
  mailto, and Sciverse credentials.
- Scope of SPC-local `.env`: MinerU, mirror/download routes,
  browser settings, Semantic Scholar throttling, and other SPC-only execution
  config. RH currently uses provider-internal S2 pacing, so SPC's
  `SEMANTIC_SCHOLAR_*` throttling variables do not configure RH.

This keeps RH as the search orchestrator while SPC keeps its standalone
search-metadata and download execution surfaces.

---

## Safety Boundaries

- RH never imports `paperfetch` (`rg paperfetch packages/`
  must stay empty).
- No credentials, browser login state, mirror, or captcha handling
  exist in RH; those stay in SPC on the operator's machine.
- Imported files pass the same SSRF-safe local handling and identity audit
  as natively downloaded ones.
- Contract mismatches (`SeedPackContractError`) abort the import with a
  deterministic reason (`pack_dir_missing`, `seed_papers_invalid_json`,
  `run_report_version_unsupported`, …) instead of partially importing.
