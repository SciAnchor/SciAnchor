# Showcase Bundle

Use a showcase bundle when you want a public, reviewable proof of what RH did
for one research topic. The bundle is file-based: it copies existing artifacts
into one directory and records checksums in `manifest.json`. It does not query
private databases, call model providers, or publish anything.

## Required Slots

| Slot | Purpose |
|---|---|
| `final_pdf` | Final paper, report, or proposal PDF |
| `provenance_export` | Tool and artifact provenance export |
| `citation_integrity_report` | Citation, DOI/arXiv, and support-status checks |
| `paper_pool_summary` | Topic paper pool summary |
| `claim_evidence_graph` | Claim/evidence graph or exported map |
| `zotero_screenshot` | Screenshot proving the researcher-facing Zotero workflow |
| `researchflowbench_score_report` | ResearchFlowBench score report or replay summary |

## Build A Draft Bundle

This creates a bundle even when some artifacts are missing. Use it early to see
the checklist:

```bash
scripts/build_showcase_bundle.py \
  --output .tmp/showcase/rh-public-launch \
  --title "Research Harness Public Launch Showcase" \
  --artifact final_pdf=path/to/final.pdf \
  --artifact provenance_export=path/to/provenance.json
```

The output contains:

- `manifest.json` with slot status, source paths, bundled paths, byte counts,
  and SHA-256 checksums;
- `README.md` with a human-readable checklist;
- `artifacts/` with copied files for every present slot.

## Add The Productization Boundary Preview

Use `--productization-boundary` only when you want the local manifest to carry
the public-productization boundary preview. The flag adds
`productization_boundary` with `scope=public-showcase-opt-in-preview` to
`manifest.json`. It does not publish, query private databases, call model
providers, or change default bundle output.

```bash
scripts/build_showcase_bundle.py \
  --output .tmp/showcase/rh-public-launch \
  --title "Research Harness Public Launch Showcase" \
  --artifact final_pdf=path/to/final.pdf \
  --productization-boundary
```

## Require A Complete Bundle

Use `--require-complete` before publishing or linking a bundle from release
notes:

```bash
scripts/build_showcase_bundle.py \
  --output .tmp/showcase/rh-public-launch \
  --title "Research Harness Public Launch Showcase" \
  --artifact final_pdf=path/to/final.pdf \
  --artifact provenance_export=path/to/provenance.json \
  --artifact citation_integrity_report=path/to/citations.json \
  --artifact paper_pool_summary=path/to/paper-pool.md \
  --artifact claim_evidence_graph=path/to/claim-graph.json \
  --artifact zotero_screenshot=path/to/zotero.png \
  --artifact researchflowbench_score_report=path/to/rfb-score.json \
  --require-complete
```

The command exits nonzero if any required slot is missing, while still writing
the incomplete manifest for inspection.

## Publishing Rule

Do not commit private research data, private PDFs, credentials, private Zotero
screenshots, or unpublished reviewer material. Use `.tmp/showcase/` for local
assembly, sanitize every artifact, then copy only approved public assets into
the documentation or release area.
