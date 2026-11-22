# Publication Pack Contract

A `publication_pack` artifact should contain at least:

```json
{
  "topic_id": 1,
  "target_profile": "high-impact-general",
  "ready_for_review": true,
  "components": {
    "manuscript_sections": {
      "status": "present",
      "artifact_type": "draft_pack",
      "artifact_id": 123
    },
    "evidence_pack": {
      "status": "present",
      "artifact_type": "evidence_pack",
      "artifact_id": 124
    }
  },
  "source_artifacts": [
    {
      "component": "manuscript_sections",
      "artifact_id": 123,
      "artifact_type": "draft_pack",
      "stage": "write"
    }
  ],
  "missing_required": [],
  "missing_optional": ["figure_plan"],
  "qa_checks": [
    {
      "check": "citation_integrity",
      "passed": false,
      "severity": "warning",
      "details": "Run public consistency_check or record a final citation/integrity report before submission."
    }
  ],
  "contract": {
    "artifact_type": "publication_pack",
    "must_trace_claims_to": ["paper_id", "claim_id", "artifact_id"]
  },
  "provenance_map": {
    "manuscript_sections": {
      "artifact_id": 123,
      "artifact_type": "draft_pack",
      "status": "present"
    }
  }
}
```

## Invariants

- Required components must be present before the pack is called review-ready.
- Style profiles guide expression only; they must not add evidence.
- Claims must remain traceable to paper IDs, claim IDs, or artifact IDs.
- Missing optional components should be listed explicitly rather than silently skipped.
