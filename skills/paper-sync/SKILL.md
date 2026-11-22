---
name: paper-sync
description: Check paper pool health, enrich metadata, download PDFs, and annotate — with relevance filtering to skip noise
public_suite: zotero
task_type: synchronization
data_access_level: local+external
inputs: topic name or topic_id, paper queue, acquisition policy
outputs: coverage report, acquired PDFs, dismissed noise, annotation queue
gates: avoid ingesting noise; keep paper operations topic-scoped
artifact_schemas: paper_pool, topic_paper_notes
estimated_runtime: 5-30 min
allowed-tools:
  - mcp__research-harness__paper_list
  - mcp__research-harness__paper_coverage_check
  - mcp__research-harness__paper_acquire
  - mcp__research-harness__paper_dismiss
  - mcp__research-harness__topic_show
  - mcp__research-harness__topic_list
  - Read
---

# Paper Sync

Inspect the paper pool for a topic, enrich missing metadata, download available PDFs, annotate them, and produce a prioritized report of what's still missing. Filters out low-relevance noise before downloading.

## When to Use

- After `/literature-search` or `/citation-trace` to materialize newly ingested papers
- Before `/gap-analysis` or `/claim-extraction` to ensure full-text coverage
- Periodically to check pool health
- When the user asks to "sync papers", "download papers", or "check paper coverage"

## Invocation

```
/paper-sync [topic_name_or_id]
```

If no topic is specified, list topics and ask which one to sync.

## Workflow

### Phase 1: Diagnose

1. Call `mcp__research-harness__topic_show` to get topic details
2. Call `mcp__research-harness__paper_list` with the topic to get current pool state
3. Classify papers into:
   - **Complete**: status=annotated, has PDF + structure + annotations
   - **Needs download**: status=meta_only, has identifier (arxiv_id or doi), relevance != low
   - **Needs enrichment**: missing title or abstract, has identifier
   - **Noise candidates**: meta_only, relevance=low, no direct connection to topic focus
   - **Unreachable**: no identifier, no URL, no PDF

4. Report diagnosis to user:
   ```
   Paper Pool Health for "topic-name":
   - Complete: XX papers (XX%)
   - Needs download: XX papers
   - Needs enrichment: XX papers
   - Noise candidates: XX papers (suggest dismiss)
   - Unreachable: XX papers
   ```

### Phase 2: Filter Noise

Before downloading, review noise candidates:

1. For papers with relevance=low AND no annotations AND no PDF:
   - Check if their title/abstract mentions core topic keywords
   - If clearly unrelated, call `mcp__research-harness__paper_dismiss` with reason
   - If uncertain, keep and let the user decide

2. Report dismissals:
   ```
   Dismissed X noise papers: [list with reasons]
   ```

### Phase 3: Acquire

1. Call `mcp__research-harness__paper_acquire` with `topic_id`
   - This automatically: enriches metadata → downloads PDFs → annotates → builds unable list

2. Report results:
   ```
   Acquisition complete:
   - Enriched: X papers (metadata from S2)
   - Downloaded + Annotated: X papers
   - Failed: X papers
   - Needs manual download: X papers
   ```

### Existing SPC Acquisition and Supplementary Routes

Keep `paper_acquire` as the topic-aware acquisition entry; use production SPC
for targeted diagnosis or explicit supplementary acquisition, not a second
unconditional download of the same pool. Inspect `spc schema <command path>`
before unfamiliar operations.

- Separate metadata lookup failure, no public version, subscription denial,
  human verification and network failure in the unable list. Do not label every
  failure as paywalled. Stop on CAPTCHA/MFA; do not rotate accounts to bypass it.
- For article files, use `paper download` with the appropriate `public`, `auto`
  or `cst` route. A public PDF cannot prove subscription access. Check returned
  identity and physical artifacts, not only the process exit code. Conflicting
  success/error fields require inspection of the audit report, not silent success.
- Sciverse passages (`paper sciverse`) can supplement reading evidence while a
  PDF is unavailable. Keep PDF acquisition incomplete; record document ID,
  offsets and metadata verification separately. Never upload or attribute
  third-party text as our original work.
- For Zenodo/Figshare records, use `dataset archive inspect` first to check the
  license, version, file sizes and checksums. Download only relevant authorized
  files with `dataset archive download`; `manifest_ready` does not imply
  `payload_ready`. Supplementary files are not the article PDF.
- Archive networking has its own `ARCHIVE_PROXY_MODE`/`ARCHIVE_PROXY` settings.
  Do not assume shell proxy configuration applies. Diagnose using the
  existing configured proxy; do not change shared network settings.
- Use `seed-pack` for standalone collections outside RH-managed pools; do not
  write RH database state manually. Parse verified PDFs only when needed and
  preserve source/version information. Do not re-download valid cached artifacts.
- Paid delivery requests, new subscriptions and acceptance of new license terms
  need owner approval.

### Phase 4: Report Unable-to-Acquire

If there are papers in the `unable_to_acquire` list:

1. Present them sorted by relevance (high first):
   ```
   Unable to acquire (sorted by importance):
   
   HIGH:
   - [paper_id] Title (DOI: xxx) — reason: paywalled
     Hint: https://doi.org/xxx
   
   MEDIUM:
   - [paper_id] Title — reason: no downloadable URL
   
   LOW:
   - (suggest dismissing these)
   ```

2. For high-relevance papers, suggest:
   - Manual download by the user through access they are entitled to
   - Alternative sources (preprint versions, author pages)

3. For low-relevance unable papers, suggest dismissing them

## Output

End with a summary table:

```
Paper Pool Summary (after sync):
| Status     | Count | % |
|------------|-------|---|
| Annotated  | XX    | X |
| Meta-only  | XX    | X |
| Total      | XX    |   |

Coverage: XX% of papers have full-text annotations
Next: /gap-analysis or /claim-extraction
```

## Notes

- `paper_acquire` respects S2 API rate limits (1 req/s with key)
- PDF annotation uses `skip_card=True` by default (fast, no LLM for card)
- Papers already annotated are skipped automatically (idempotent)
- Dismissed papers are excluded from future syncs and coverage checks
