# Research Harness Zotero Panel

This is the RH-owned Zotero side-panel bridge for live Zotero ↔ RH/Codex conversations.

## Product direction

The Zotero side panel is now the primary maintained frontend for Research
Harness. New researcher-facing interaction work should target this plugin
first; the local HTTP API bridge exists to support Zotero and automation.

The target shape is a lightweight Zotero research workbench, not a second
research engine. The panel should expose clear context, a small set of
research actions, progress/receipt visibility, and stable copy/selection
behavior. RH remains responsible for semantic routing, topic/paper matching,
preview/apply planning, provenance, and workflow receipts.

## What it does

- Adds a `Research Harness` section to the Zotero item pane.
- Reads the selected Zotero item metadata, RH tags, and the current Zotero collection context.
- Sends the user question to `POST /api/zotero/chat/stream` on the local RH API.
- RH resolves the Zotero item to RH paper/topic context, then connects to `codex app-server`.
- Streams Codex deltas back into Zotero and preserves multi-turn context with a durable `conversation_id -> Codex thread_id` mapping.
- Makes replies selectable/copyable in-place.
- For supported write intents, RH intercepts the request, returns a backend-owned `action_preview`, shows a lightweight confirmation card in chat, and applies the write only after explicit confirmation.
- Supports a guarded Zotero-local folder creation action. A request such as “新建文件夹 AI discovery” returns a preview first, then the panel calls Zotero's local Collection API only after confirmation.
- Uses context-aware modes: concrete Zotero item/paper mode keeps the paper-first chat surface; collection/library mode exposes topic-init and RH→Zotero补库 prompts instead of forcing a paper UI.
- Exposes a compact action surface on the empty start page. Collection mode offers seed-paper discovery, missing-paper import, PDF/note sync, and annotation bootstrap prompts. Item mode offers deep read, PDF annotation, claim extraction, and note import prompts. These buttons only fill deterministic prompts into the composer; they do not execute writes.
- Shows explicit context chips for the active source, such as paper, folder, matched RH topic, selected reader text, and screenshots.
- Persists the latest compact `workflow_receipt` with the chat session and renders it in the context card so the researcher can see the last successful write outcome after refresh/reopen.
- Adds a compact `RH` entry to Zotero's right-side item/library pane navigation. It opens the same conversation-style RH workspace used by paper mode, so an empty folder can start RH without first selecting a paper. In this bootstrap mode, RH can search for seed papers, preview the candidates, and only ingest/sync after explicit confirmation.
- Supports adding selected Zotero/PDF text and a small number of screenshot snippets to the next question.
- Supports two first-class action transports:
  - `http_json`: server-side RH operations such as syncing selected RH papers into the current Zotero collection.
  - `zotero_local`: guarded Zotero Desktop operations such as importing a local RH PDF as an attachment under the current item.
- Reuses a long-lived Codex app-server client pool keyed by model/cwd/effort so follow-up turns avoid process initialization overhead.

The Zotero plugin remains intentionally thin. RH owns paper/topic matching, sync semantics, provenance, guarded writes, and the Codex app-server bridge.

## Codex session bridge

`/api/zotero/chat/stream` is a lightweight Codex app-server client with a
guarded write-planning step in front of normal chat. Each turn first resolves
the Zotero/RH context and available broker capabilities. A hidden planner may
return only `chat`, `capability_preview`, or `unsupported_write`: clear
allowlisted write intents become backend-owned preview cards, unsupported
mutating requests become structured unsupported messages, and ordinary reading
or discussion still streams through Codex with the current Zotero context and
capability list. Explicit UI shortcuts can still set `requested_action_type` to
request a specific allowlisted preview.

RH forwards agent deltas, reasoning/status updates, tool call starts/results,
command output, MCP progress, approval requests, user input requests, errors,
and final `done` events to the panel as SSE events when a turn enters Codex.

The panel renders these process events in a transient log while a turn is
running. They are cleared on `done` and are not persisted into chat history; the
final transcript stores only the clean assistant answer plus any backend-owned
confirmation cards or compact workflow receipts.

Codex-originated `item/tool/call` requests, hidden-planner previews, and
explicit shortcut previews are routed through the RH Zotero capability broker.
The broker allowlists RH/Zotero capabilities such as
`rh.paper.list`, `rh.paper.search`, `rh.topic.match`,
`rh.zotero.prepare_seed_import`, `rh.zotero.sync_papers`, `rh.zotero.attach_pdf`,
`rh.zotero.create_collection`, `rh.claim.extract`, `rh.gap.detect`, and
`rh.provenance.summary`. Read-only capabilities execute and return a dynamic
tool result. Write capabilities return an `action_preview` only; the panel must
still collect explicit user confirmation before the existing apply endpoint or
Zotero-local action can write anything. Unknown or out-of-context tools are
returned to Codex as rejected tool results and are shown in the transient
process log.

The panel includes compact target continuity in chat payloads:
`selected_items` comes from the current Zotero multi-select, and
`last_preview_targets` comes from the most recent backend preview records. Both
carry identity fields only, such as RH paper/topic IDs, Zotero item keys,
library IDs, titles, DOI/arXiv IDs, URLs, and tags. They deliberately do not
carry `pdf_path`; the backend must re-resolve or RH-materialize trusted PDF
paths before any attachment preview can become confirmable.

Review cards render backend `action_preview` metadata additively: `preview_id`,
`capability`, `target_set`, `warnings`, `blocked_records`, and
`undo_supported`. Batch cards show writable and blocked counts, default-select
writable records, let the user deselect individual writable records before
confirming, and never apply blocked records. Undo is shown only when the backend
marks the preview as supported and the local result contains resolvable Zotero
objects, such as newly imported attachments or newly created collections.

## RH → Zotero feedback contract

The panel should show research-relevant outcomes, not RH internals. Every
confirmed write action should return a compact `workflow_receipt` when RH can
summarize the outcome:

| RH outcome | Zotero feedback | Persistence |
| --- | --- | --- |
| Text answer / explanation / translation | Chat bubble or reader popup | Chat history only |
| Pending write | Confirmation card | Not persisted |
| Zotero folder creation | New Zotero collection under the selected parent/library | Zotero collection |
| Topic bootstrap | Topic subcollection under the selected Zotero collection plus receipt | RH DB + Zotero collection |
| Paper sync | Zotero item with RH tags and receipt counts | Zotero item/tags |
| Deep read | RH deep-reading note/tag when available; receipt reports count | Zotero note/tag |
| PDF sync | PDF attachment count or missing-PDF warning | Zotero attachment |
| PDF highlights/annotations | Verified annotation count, profile, and missing-anchor/failure warnings | PDF/Zotero receipt |
| Partial failure | Receipt warnings with successful counts preserved | RH provenance/receipt |

The frontend renders the receipt summary directly instead of inferring success
from assistant prose. This keeps the UI small while still answering the
researcher's practical questions: which topic folder was used, how many papers
were synced, whether notes/PDFs/annotations were actually produced, and what
needs manual follow-up.

Phase B fake/sandbox validation adds a backend `phase_b_gate_evidence` payload
for sync/apply endpoints. It records the intent plan, preview counts, receipt
counts, and rollback/recovery notes when tests inject a sandbox Zotero adapter.
This is local gate evidence only; real Zotero network sync/apply still requires
separate explicit authorization and must not be advertised as release-ready.

The panel persists only a compact receipt projection: summary, status/action
identity, simple target fields, counts, and short warnings. Large backend
payloads, debug objects, and provenance internals stay in RH storage rather
than Zotero preferences.

For seed-paper confirmation, `request_pdf_annotations=true` implies PDF
acquisition/attachment intent because Zotero can only show highlights on an
attached PDF. In the local Phase B fake/sandbox gate, provider-backed paper
acquisition, deep-read, and PDF annotation postprocessors are deferred and
reported as receipt warnings instead of being executed. A future separately
authorized real/provider-backed apply path may run the existing
`paper-reading-annotation` workflow before Zotero sync, using
`zotero-content-primitives-v2` plans and verifying the embedded `RH-PHD-v2`
annotations in the actual PDF. The receipt exposes compact counts:
`pdf_annotations`, `pdf_annotation_planned`, `pdf_annotation_missing`, and
`pdf_annotation_failures`; Zotero displays those counts plus warnings instead
of assuming completion from prompt text.

## Local service startup

Normal Zotero use no longer requires manually starting the local Research Harness service. When the panel loads or when the first question is sent, the plugin:

1. checks `http://127.0.0.1:8000/api/health`;
2. if nothing is listening and the URL is loopback-only (`127.*`, `localhost`, or `::1`), starts the local Python service from Zotero via Mozilla/Zotero `Subprocess`;
3. waits for health to pass, then calls `POST /api/zotero/warmup` so the Codex app-server pool starts before the first real question.

Default Zotero preferences:

```text
extensions.researchharness.zotero.apiURL    = http://127.0.0.1:8000
extensions.researchharness.zotero.autoStart = true
extensions.researchharness.zotero.repoRoot  = /path/to/scianchor
extensions.researchharness.zotero.pythonBin = /path/to/scianchor/.venv/bin/python
extensions.researchharness.zotero.model     = gpt-5.3-codex-spark
```

Security boundary: auto-start is disabled automatically for non-loopback URLs and for non-HTTP URLs. The plugin uses fixed preference paths for `repoRoot`/`pythonBin`, passes arguments as an argv array rather than through a shell, and sends the optional local token via environment variable rather than command-line text.

Manual fallback from the repository root is still:

```bash
PYTHONPATH=packages/research_harness:packages/research_harness_mcp \
.venv/bin/python -m research_harness_mcp.http_api
```

If your shell already activated the project virtualenv, `python -m research_harness_mcp.http_api` is equivalent.

The default local API URL is:

```text
http://127.0.0.1:8000
```

Codex requirements:

- `codex` must be installed and logged in.
- The bridge defaults to `/opt/homebrew/bin/codex` on Apple Silicon Homebrew when present, otherwise `codex` from `PATH`.
- The Zotero panel opportunistically calls `POST /api/zotero/warmup` when Zotero/the panel loads. This starts and initializes the local `codex app-server` process in the RH pool before the first user question. It does not start a Codex thread or consume model tokens; the first real question still pays thread creation and first-token latency.
- Override if needed:

```bash
export RESEARCH_HARNESS_CODEX_BIN="/path/to/codex"
# Optional backend default if Zotero does not send a model.
export RESEARCH_HARNESS_ZOTERO_CODEX_MODEL="gpt-5.3-codex-spark"
export RESEARCH_HARNESS_ZOTERO_CODEX_EFFORT="low"
export RESEARCH_HARNESS_ZOTERO_CODEX_TIMEOUT_SECONDS=240
```

Optional token gate:

```bash
export RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN="choose-a-local-token"
```

If you set this token, also set Zotero preference
`extensions.researchharness.zotero.token` to the same value.

## Build and install the Zotero plugin

The Zotero side-panel plugin is maintained as an optional external package
outside this base repository. If you have a checkout of the plugin repository,
build it from the plugin repo root:

```bash
./build-xpi.sh
```

Then in Zotero:

1. Tools → Add-ons
2. Gear icon → Install Add-on From File…
3. Select `dist/research-harness-zotero-panel.xpi` from the plugin repo
4. Restart Zotero if Zotero asks.

## Development mode: load from source and refresh quickly

For local development, Zotero does not need a fresh `.xpi` install on every
change. Zotero supports loading a plugin directly from its source directory via
an extension proxy file in the active profile's `extensions/` directory.

The plugin repo includes a helper script (run from the plugin repo root):

```bash
./scripts/zotero-dev-refresh.sh
```

What it does:

1. reads the plugin id from the plugin repo's `manifest.json`;
2. writes/updates the Zotero extension proxy file so the active profile points
   at the plugin source directory;
3. removes `extensions.lastAppBuildId` and `extensions.lastAppVersion` from the
   profile `prefs.js` so Zotero re-reads extension state when needed;
4. restarts Zotero with `-purgecaches` so plugin code changes are picked up.

Useful variants:

```bash
# Only (re)link the profile to the source directory
./scripts/zotero-dev-refresh.sh --link-only

# If multiple profiles exist, choose one explicitly
./scripts/zotero-dev-refresh.sh --profile-dir "/path/to/profile"
```

For release/distribution builds, keep using `build-xpi.sh`. The refresh script
is for local development only.

## Expected first visible effect

Select one of the papers that RH already pushed into `Research Harness/自动科研`.

In the item pane you should see a `Research Harness` section. Ask:

```text
这篇论文对自动科研主题有什么启发？
```

The panel should show:

- a llm-for-zotero-inspired paper-first chat shell: compact header, status pill, new-chat control, and a single context summary card instead of multiple status blocks;
- a start page with suggested prompts and the model picker embedded in the composer;
- live streamed Codex text, not the old fixed “我已匹配到…” response;
- copyable/selectable assistant text;
- a retained multi-turn conversation for follow-up questions on the same Zotero item; previous turns stay in the chat transcript above the input instead of a separate history popover.

Try a write intent while a Zotero collection is selected:

```text
把这个主题里精读过的 3 篇论文导入当前目录
```

RH should show a confirmation card in chat first, then execute the import only after you click confirm.

Try the empty-folder bootstrap flow while a newly created Zotero collection is selected:

```text
帮我找到最开始的 5 篇种子论文
```

Click the small `RH` button in Zotero's right-side navigation. RH should open a full conversation-style workspace with the same compact header, context card, suggestions, chat transcript, model picker, and composer used by the paper pane. It should search from the collection/topic name, return a candidate preview card, and wait for confirmation before creating/reusing the RH topic, ingesting the candidate papers, and syncing them into the current Zotero collection.

Try a PDF attachment write intent while a concrete Zotero item is selected and
the matched RH paper either already has a safe local `pdf_path` or has a
downloadable DOI/arXiv/URL source:

```text
下载并附加 PDF 到当前条目，先 dry-run，确认后 apply
```

RH should first re-resolve the local PDF. If the PDF is missing, RH attempts to
materialize it through the RH download pipeline, records the trusted local path,
and then shows a PDF attachment preview. Confirming it runs the plugin-local
Zotero handler, which calls `Zotero.Attachments.importFromFile` under the matched
parent item. The preview/apply payload is generated by the RH API; the frontend
does not infer write targets from model text.

## Safety model

The panel-side Codex bridge starts/resumes Codex threads with read-only sandbox and `approvalPolicy=never`. Free-form chat answers stay read-only by default. RH-owned write actions in the sidebar must go through an explicit confirmation flow (for example dry-run/import preview -> user confirm -> apply).

Local service auto-start has additional guards:

- only loopback URLs are eligible;
- process launch uses a fixed Python binary and repository root from Zotero preferences;
- no shell command string is constructed from chat/model text;
- optional local auth token is passed through process environment, not command-line arguments;
- if Zotero cannot load `Subprocess`, the panel falls back to a clear manual-start error.

The frontend only executes backend-provided `apply` specs:

- `http_json` specs post to the supplied local RH API path/payload.
- `zotero_local` specs dispatch to a small allow-list of plugin handlers, including `zotero_import_file_attachment` and `zotero_import_file_attachments`.
- PDF attachment previews require the final local PDF path to resolve under RH's configured `PDF_ROOTS`; arbitrary filesystem paths from chat/model text are not executed, and downloaded PDFs are re-checked before any apply payload is produced.

## Current limitations

- This release intentionally focuses on the llm-for-zotero interaction subset we need most: paper-first chat, model selection, start-page suggestions, selected-text/screenshot context, streaming, and the current chat transcript.
- Human note/highlight import remains handled by the existing RH Zotero sync pull path and is not wired to a dedicated chat action yet.
- PDF attachment materialization depends on RH being able to download from the paper's DOI/arXiv/URL metadata. If no source exists or every download candidate fails, the preview returns a blocked record with the failure reason instead of asking Zotero to write.
- If the local Python service is not already running, the first panel load/question may spend a few seconds on auto-start. The first answer for a given model can still take several seconds because RH must initialize an app-server client and wait for the first model token. Follow-up turns on the same model/cwd reuse the pooled client and should avoid that startup cost.
