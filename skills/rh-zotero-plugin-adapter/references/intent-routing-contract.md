# Intent Routing Contract

This contract keeps the Zotero plugin flexible without turning routing into a
pile of demo-specific keyword patches.

## Runtime Layers

1. Context model: derive Zotero mode from Desktop state.
2. Capability registry: list allowed actions and their preconditions.
3. Hidden write planner: classify clear mutating intent into only `chat`,
   `capability_preview`, or `unsupported_write`.
4. Preview builder: return typed action previews for writes.
5. Apply executor: execute only confirmed, allowlisted specs.

The local deterministic router must not classify ordinary natural language. It
is only for explicit UI/compat calls that carry `requested_action_type`. The
hidden planner may classify clear write intent, but it does not authorize a
write: it can only choose an allowlisted broker capability and arguments. The
broker still validates context mode, target identity, trusted local PDF roots,
preview shape, and apply transport before a confirmation card is shown.
Ordinary read/discussion turns still enter Codex with the same capability list.

## Canonical Capabilities

| Capability | Mode | Write behavior | Owner |
| --- | --- | --- | --- |
| `rh.zotero.prepare_seed_import` | `collection` | Preview only; confirm/apply ingests and syncs | RH broker + Zotero local handler |
| `rh.zotero.sync_papers` | `collection` / `item` | Preview only | RH broker + Zotero resource |
| `rh.zotero.attach_pdf` | `item` / selected preview targets | Preview only | RH broker + Zotero local handler |
| `rh.zotero.create_collection` | `library` / `collection` | Preview only | RH broker + Zotero local handler |
| `import_human_notes` | `item` | Yes | RH sync path |
| `paper_chat` | `item` | No | Codex bridge |
| `reader_explain_selection` | `reader_selection` | No | Codex bridge |
| `reader_translate_selection` | `reader_selection` | No | Codex bridge |
| `copy_message_text` | `reader_selection` or `item` | Local clipboard | Zotero plugin |
| `service_restart` | `service_dev` | Local process | Zotero plugin guarded launch |
| `dev_refresh` | `service_dev` | Local profile proxy | Script |

## Priority Rules

Use deterministic capability gates before Codex chooses a tool:

1. Reject capabilities whose required context mode is absent.
2. Reject writes whose target identity is missing or ambiguous.
3. Prefer collection bootstrap/import over item PDF attach in collection mode.
4. Prefer item-level PDF attach only when there is a concrete parent Zotero item
   and a matched RH paper; the broker may materialize a missing local PDF
   through RH acquisition before preview, then must re-check trusted PDF roots.
5. Return a precise unsupported-action message rather than letting Codex imply a
   nonexistent confirmation button.
6. For phrases like "这 5 篇", prefer compact `last_preview_targets`; for current
   Zotero multi-select, prefer compact `selected_items`. Both are identity hints
   only and must be re-resolved by the backend.

## Required Test Scenarios

For router changes, cover at least:

- collection mode: new topic + seed papers + mentions PDF/notes -> seed preview
- collection mode: import existing RH papers -> import preview
- item mode: attach PDF with trusted `pdf_path` -> attachment preview
- item mode: attach PDF without trusted `pdf_path` but with a downloadable
  source -> materialize local PDF then attachment preview
- item mode: attach PDF without trusted `pdf_path` and without a downloadable
  source -> actionable failure
- item mode: metadata/note/tag write not implemented -> unsupported write
- batch PDF attach from `last_preview_targets` -> writable records plus blocked
  records, with blocked records excluded from apply
- reader selection: explain/translate/copy does not require paper context
- service startup: loopback-only auto-start and warmup behavior

Use generic fixture strings such as `topic phrase`; do not encode a real user's
topic as a production special case.

## Action Preview Requirements

Every write preview should include:

- `action_type`
- user-visible title/message
- target Zotero library/collection/item identity
- source RH topic/paper identity
- planned count and records where applicable
- `preview_id`, `capability`, and `target_set` review metadata where available
- `warnings` and `blocked_records` for partial or unsafe targets
- `undo_supported` only when a local session undo is actually offered
- precondition or trust boundary notes
- `confirm_label` and `cancel_label`
- `apply` spec with transport and payload

Allowed transports:

- `http_json`: local RH API path and JSON body
- `zotero_local`: allowlisted Zotero Desktop handler

No other transport should be added without a security review.
