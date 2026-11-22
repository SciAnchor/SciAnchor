# Zotero Platform Checklist

Use official Zotero documentation before changing platform-facing plugin code.

## Official Docs To Check

- Plugin development:
  `https://www.zotero.org/support/dev/client_coding/plugin_development`
- Zotero 7 developer notes:
  `https://www.zotero.org/support/dev/zotero_7_for_developers`
- JavaScript API:
  `https://www.zotero.org/support/dev/client_coding/javascript_api`
- Web API basics:
  `https://www.zotero.org/support/dev/web_api/v3/basics`
- Web API write requests:
  `https://www.zotero.org/support/dev/web_api/v3/write_requests`
- Zotero Connector local HTTP server:
  `https://www.zotero.org/support/dev/client_coding/http_server`

## Platform Rules

- Prefer Zotero 7 bootstrapped plugin lifecycle hooks and window hooks over
  ad hoc global initialization.
- Clean up registered UI, event listeners, observers, and global references on
  shutdown/window unload.
- Prefer `Zotero.ItemPaneManager.registerSection()` for item pane UI.
- Prefer `Zotero.Reader.registerEventListener()` for reader integrations.
- Keep plugin UI code resilient to multiple main windows and delayed Zotero UI
  readiness promises.
- Use Zotero preferences for user-local configuration such as API URL, token,
  repo root, Python binary, and model.
- Keep auto-start limited to loopback HTTP URLs.
- Launch local processes with argv arrays, never shell strings built from chat
  or model text.
- Pass sensitive local tokens through environment/config, not command-line
  arguments or logs.
- For Web API writes, require an API key with write permission.
- For local Desktop writes, use the connector/local adapter path deliberately
  and test the fallback when no Web API key is present.
- For file attachments, use only trusted RH PDF roots and existing or
  RH-materialized local files.

## Clipboard And Selection

For copy failures, verify each fallback in order:

1. Zotero utility clipboard helper if available.
2. Mozilla/XPCOM clipboard helper.
3. `navigator.clipboard.writeText` when supported.
4. temporary textarea + `execCommand("copy")` fallback.

Selection capture should not mutate the current chat input unless the user picks
append/copy/ask explicitly.

Do not add document-level `copy`/`cut`/`paste` listeners for new panel
interactions unless the `shouldHandlePanelSelectionCopy` test matrix is updated
in the same change.

## Dev Refresh

- Use `./scripts/zotero-dev-refresh.sh` (in the plugin repo) for
  source-directory development.
- Use `./build-xpi.sh` (in the plugin repo) for package verification.
- Restart Zotero with cache purge when platform code or manifest behavior is
  not being reloaded reliably.
