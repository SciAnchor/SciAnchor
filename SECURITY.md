# Security Policy

Research Harness is an open-source research workflow platform that runs local tools, stores research state, integrates with MCP clients, and may call external LLM or paper-source APIs. Please report security issues privately so maintainers can investigate before details are disclosed publicly.

## Supported Versions

Security fixes are prioritized for the latest released version and the `main` branch. Older versions may receive fixes when the issue is severe and the patch is low risk.

## Reporting a Vulnerability

Please do not open a public GitHub issue for a vulnerability. Instead, use one of these private channels:

- GitHub private vulnerability reporting for this repository, if available.
- Contact the repository maintainers via the `research-harness` GitHub organization.

Include enough detail to reproduce the issue:

- Affected version, commit, or release tag.
- Impact and affected component, such as CLI, MCP server, Zotero bridge, local API, database, or documentation workflow.
- Reproduction steps, proof-of-concept input, logs, or screenshots.
- Whether credentials, local files, PDFs, or private research data may be exposed.

We will acknowledge valid reports as soon as practical, triage severity, and coordinate disclosure timing for confirmed issues.

## Security Scope

Reports are especially useful when they involve:

- Secret exposure, including API keys, tokens, local environment files, or model credentials.
- Unsafe local file access or path traversal.
- Command injection or unsafe subprocess execution.
- MCP tool misuse that can mutate data unexpectedly or bypass provenance checks.
- Local API or Zotero bridge access control issues.
- Database corruption, unauthorized reads, or provenance tampering.
- Prompt-injection paths that can exfiltrate local data or trigger unintended tool calls.

## Operational Guidance

Do not commit secrets to this repository. Use environment variables or local configuration files that are ignored by Git. If a secret is exposed, rotate it immediately and review the repository history and local logs for secondary exposure.
