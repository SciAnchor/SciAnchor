---
name: deposit-zenodo
version: 0.1.0
description: Mint Zenodo DOIs for a topic's code and data packages. Trigger on "deposit zenodo", "申请DOI", "上传数据和代码拿DOI", "code data DOI", or when a manuscript needs Data Availability repository identifiers.
public_suite: paper
task_type: packaging
data_access_level: local
inputs: topic_id or topic_name, Zenodo token (preferred) or email+password, optional deposit_root/code_path/data_path
outputs: code_doi, data_doi, record URLs
gates: code/ and data/ (or 代码/数据) must exist; publish is permanent per version
artifact_schemas: deposit_receipt
estimated_runtime: 1-5 min
---

# Deposit Zenodo

**Prefer the MCP/CLI primitive.** This skill is a thin operator guide — do not re-implement upload logic in the agent.

## Decision

| Surface | When |
|---|---|
| **MCP `deposit_zenodo`** | Agent-facing, structured I/O, provenance-friendly |
| **CLI `rh deposit zenodo`** | Shell / scripts / CI |
| **Skill (this file)** | Only to remember inputs/outputs and path conventions |

## Required inputs

1. **Topic**: `topic_id` (preferred) or `topic_name`
2. **Auth** (first match wins):
   - `token` / env `ZENODO_TOKEN` (best)
   - else `email`+`password` / `ZENODO_EMAIL`+`ZENODO_PASSWORD` → headless mint PAT (needs Playwright)
3. **Paths** if auto-discovery fails:
   - `deposit_root` containing `code/`+`data/` or `代码/`+`数据/`
   - or explicit `code_path` + `data_path`

## Call shapes

MCP:

```json
{
  "topic_id": 93,
  "token": "...",
  "creator": "Du, Hairong",
  "publish": true
}
```

CLI:

```bash
export ZENODO_TOKEN=...   # or ZENODO_EMAIL + ZENODO_PASSWORD
rh deposit zenodo --topic 93 --creator "Du, Hairong"
# draft only:
rh deposit zenodo --topic 93 --dry-run
# explicit package:
rh deposit zenodo --deposit-root /path/to/pkg --title "My paper"
```

## Expected output

```json
{
  "status": "success",
  "code_doi": "10.5281/zenodo.XXXX",
  "data_doi": "10.5281/zenodo.YYYY",
  "code_url": "https://doi.org/10.5281/zenodo.XXXX",
  "data_url": "https://doi.org/10.5281/zenodo.YYYY",
  "published": true
}
```

Paste into Data Availability:

> Code: https://doi.org/10.5281/zenodo.XXXX  
> Data: https://doi.org/10.5281/zenodo.YYYY

## Path discovery order

1. Explicit `code_path` + `data_path`
2. `deposit_root` with `code|代码|analysis_code` and `data|数据`
3. Search under `RH_DEPOSIT_SEARCH_ROOTS`, `tmp/`, `dream7_clean_drafts/`, cwd — score by topic name tokens

## Safety

- Default mental model: **publish is permanent for that version** (Zenodo versioning for fixes).
- Prefer `--dry-run` / `publish=false` on first contact with a new account.
- Never commit passwords or tokens. Do not echo them back to the user.
- Sandbox accounts are separate from production (`--sandbox`).

## Failure recovery

| Error | Fix |
|---|---|
| path_resolve / no deposit root | Pass `--deposit-root` or code/data paths |
| auth / login failed | Check account exists on prod vs sandbox; use token |
| playwright missing | `pip install playwright && playwright install chromium`, or use token |
| HTTP 400 on publish | Missing creators/license — tool sets defaults; check title/description |
