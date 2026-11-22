---
name: rh-zotero-plugin-adapter
description: Maintain and debug the Research Harness Zotero plugin adapter. Trigger on Zotero side panel, Zotero reader, Zotero copy/clipboard, local RH API bridge, PDF attachment, RH-to-Zotero sync, seed-paper previews, plugin restart/dev-refresh, or requests to align Zotero plugin behavior with RH CLI/MCP skills without duplicating existing research workflow skills.
public_suite: zotero
task_type: adapter-maintenance
data_access_level: local-files
inputs: Zotero plugin state, bridge logs, local API URL, user action
outputs: adapter diagnosis, code patch, verification result, sync guidance
gates: preserve user Zotero data; do not duplicate research workflow semantics
artifact_schemas: zotero_sync_report
estimated_runtime: 10-60 min
---

# RH Zotero Plugin Adapter

Use this skill when changing, debugging, or reviewing the Research Harness Zotero
Desktop plugin and its local HTTP bridge.

This skill is an adapter maintenance guide, not a research workflow. Reuse the
existing RH skills for research semantics:

- New topic or project bootstrap: `research-init`
- Literature discovery and seed expansion: `literature-search`, `citation-trace`
- Paper pool health, PDF acquisition, metadata, sync: `paper-sync`, `paper-verify`
- PDF marginalia and deep reading: `paper-reading-annotation`
- Claims, gaps, sections, publication package: `claim-extraction`, `gap-analysis`,
  `section-drafting`, `publication-pack`

## Operating Principle

Do not rely on a skill, prompt, or hardcoded query to make the running plugin
stable. Runtime stability belongs in typed context models, capability contracts,
preview/confirm/apply guardrails, traces, and tests.

Use this skill to keep future agent edits inside those boundaries.

This follows the large-lab agent design pattern: keep workflows simple and
composable, expose clear tool/capability interfaces, add guardrails around
high-impact actions, and verify behavior with traces/tests rather than relying
on prose instructions alone.

## Read First

Before changing Zotero plugin behavior, read the smallest relevant set:

1. `docs/zotero-rh-panel.md`
2. `content/rh-zotero-panel.js` in the plugin repo checkout
   (an optional external Zotero side-panel plugin checkout, if installed)
3. `packages/research_harness_mcp/research_harness_mcp/http_api.py`
4. `packages/research_harness/research_harness/zotero_sync.py`
5. `packages/research_harness/research_harness/zotero_resource.py`
6. For platform behavior, read `references/zotero-platform-checklist.md`.
7. For action routing or write behavior, read `references/intent-routing-contract.md`.
8. For agent-system design rationale, read `references/agent-design-principles.md`.

## Architecture Boundary

- Zotero plugin JavaScript captures Zotero context, renders UI, handles reader
  selection affordances, and executes only allowlisted local Zotero actions.
- RH HTTP API resolves paper/topic context, selects typed capabilities, builds
  action previews, owns write semantics, and records provenance where applicable.
- `zotero_sync.py` owns RH/Zotero sync semantics.
- `zotero_resource.py` owns Web API vs local connector resource adapters.
- Research primitives must keep using MCP/RH service paths. Do not bypass
  provenance by reimplementing primitive logic in the plugin.

## Context Modes

Classify the Zotero state before interpreting natural language:

- `library`: no selected collection or item; show library-level guidance.
- `collection`: current Zotero collection/folder; supports topic bootstrap,
  seed-paper search, and RH-to-Zotero import previews.
- `item`: concrete Zotero item or parent item; supports paper chat, PDF attach,
  item sync, note/annotation flows.
- `reader_selection`: selected text or screenshot from Zotero Reader; supports
  explain, translate, append-to-composer, and copy.
- `service_dev`: local API startup, warmup, restart, XPI/source refresh, health.

Mode gates come before keyword matching. Example: a collection-mode message that
asks for a new research direction and mentions PDFs should route to seed/topic
bootstrap, not item-level PDF attachment.

## Capability Contract

Every plugin action should be represented as a capability with:

- required context mode
- required RH/Zotero state
- read-only vs write
- action preview schema
- apply transport: `http_json` or `zotero_local`
- failure message when preconditions are missing
- unit/API/panel tests

Write capabilities must follow:

```text
detect -> action_preview -> explicit confirm -> apply
```

Never execute a Zotero/RH write based only on model text. Never let frontend code
infer write targets from streamed assistant prose.

## Routing Rules

1. Resolve Zotero mode and matched RH paper/topic first.
2. Check capability preconditions second.
3. Use user text to choose among allowed capabilities third.
4. Use LLM/free text only for extraction or explanation, not authorization.
5. Do not hardcode a user's real topic/query in production logic. Tests may use
   generic fixture phrases, but production behavior must generalize.

## Verification

For Zotero plugin changes, run the focused matrix:

```bash
# In this repo:
pytest packages/research_harness_mcp/tests/test_zotero_api.py -q
pytest packages/research_harness/tests/test_zotero_sync.py -q
# In the plugin repo checkout:
node --test tests/rh-zotero-panel.test.js
node --check content/rh-zotero-panel.js
pytest tests/test_panel_assets.py -q
```

When plugin packaging or source loading changed, also run (in the plugin repo):

```bash
./build-xpi.sh
./scripts/zotero-dev-refresh.sh --link-only
```

If startup behavior changed, verify `GET /api/health`, auto-start guardrails, and
`POST /api/zotero/warmup`.

## Anti-Patterns

- Adding phrase-order fixes without a context/capability test.
- Adding another research workflow inside the Zotero plugin instead of invoking
  existing RH skills/service behavior.
- Treating collection-level initialization as item-level PDF attach because the
  user mentioned PDF or Zotero.
- Writing Zotero data without preview and explicit confirmation.
- Using arbitrary filesystem paths from chat/model output for attachments.
- Relying on DOM hacks where Zotero exposes an official plugin API.
