---
name: paper-verify
description: Verify whether papers actually exist and match the claimed metadata before or after ingestion. Trigger on phrases like "paper-verify", "/paper-verify", "验证论文存在性", "核对 DOI arxiv", or equivalent requests to validate titles, identifiers, and source consistency.
public_suite: review
task_type: verification
data_access_level: local+external
inputs: title, DOI, arXiv ID, authors, URL, or PDF metadata
outputs: identity verdict, corrected metadata, ingestion or rejection decision
gates: do not trust unverifiable identifiers; record mismatches explicitly
artifact_schemas: paper_verification_report
estimated_runtime: 5-20 min
---

# Paper Verify

Use this skill when paper identity or metadata may be unreliable.

## Workflow

1. Collect the candidate title, DOI, arXiv ID, authors, or PDF.
2. Cross-check metadata across available sources.
3. Highlight mismatches explicitly.
4. Only recommend ingestion when identity is sufficiently verified.
