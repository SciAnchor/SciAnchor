---
name: spc-research-acquisition
description: Use the SPC CLI to search or look up papers, download and verify open-access PDFs, parse local PDFs, manage Seed Packs, and inspect or download supported public datasets. Do not use for paper review, citation formatting, CAPTCHA handling, or arbitrary web browsing.
---

# SPC research acquisition

SPC is a Linux CLI. This Skill chooses commands and interprets their results; it does not implement
download routing, authentication, jobs, parsing, or Seed Pack transactions. There is no SPC MCP.

## Runtime

- Use the `spc` executable from the environment where SPC is installed (for a source checkout,
  `<checkout>/.venv/bin/spc`). Do not mix interpreters, secret files, or state roots from different
  installs, and never fall back to another `spc` that happens to be on `PATH`.
- Run `spc system preflight --profile <development|production> --capability <name>` before work.
  `development` is a source checkout (editable install); `production` is an installed release.
  The same value is `SPC_ENVIRONMENT`. When a checkout is pinned, also pass
  `--expected-git-sha` and `--expected-source-root`.
- Use `spc schema <command path>` when an argument or execution mode is uncertain, and
  `spc schema config` for configuration names.

## Result

JSON is the default. Read only `schema`, `status`, `job_id`, `data`, `files`, `results`, and `error`.

- `completed`: requested work completed.
- `partial`: usable data or files exist, but a later stage failed.
- `failed`: requested contract was not satisfied.
- `queued|running|cancelling`: background task is not terminal.
- `cancelled`: the task and its owned processes were cancelled.

On failure, report one sentence plus `error.code`, `error.message`, and `error.retryable` when present.
Do not read internal logs or debug records unless diagnosing a failure.

## Papers

- Search: `spc paper search --query <query> --detach`.
- Graph: `spc paper graph --doi <doi> --direction references --detach`.
- Lookup: `spc paper lookup --doi <doi> --detach`.
- Download and parse: `spc paper download --doi <doi> --output-dir <new-dir>`.
- Download without MinerU: add `--no-parse`.
- Parse an unbound PDF: `spc paper parse --pdf <pdf> --output-dir <dir> --detach`.

For detached work, run `spc job wait <job_id> --timeout-seconds <seconds>`. It returns the original
command result. Use `spc job show` only for a snapshot and `spc job cancel` only when cancellation was
requested.

`paper parse` does not verify paper identity or write `papers.jsonl`; Markdown alone is not official
paper fulltext.

## Download routes

`data.download.route` is the successful, identity-verified route only. `identity_verified` must be
true for PDF success. A local cache hit (`route=local`) proves the cached file and identity check only.

- `--route auto`: use the best legal route available in this install.
- `--route public`: restrict to open-access / public routes.

paperfetch does not ship institutional library or subscription access. If a paper has no legal open
copy, report the failure; do not look for unofficial mirrors.
Never solve or bypass CAPTCHA, MFA, Turnstile, or human verification.

For a failed download, report `error.code`, `error.message`, `error.stage`, and `error.next`.
Network-class errors should be followed by `spc doctor --probe-traffic-classes --output-format json`.
Read only `data.verdict`, `data.checks`, and `data.blockers`:

- an unreachable proxy endpoint or HTTP 407 is a confirmed cause;
- an ok proxy-path check only proves the probe, not that a specific PDF is obtainable.

## Seed Pack

- Initialize: `spc seed-pack init --seed-pack <dir>`.
- Inspect: `spc seed-pack show --seed-pack <dir>`.
- Add metadata: `spc seed-pack add --seed-pack <dir> --doi <doi> --detach`.
- Acquire files: `spc seed-pack enrich --seed-pack <dir> --doi <doi> --detach`.

Never edit `papers.jsonl` by hand. If a verified PDF exists but parsing failed, retry only parsing.

## Public datasets

- GEO: `spc dataset geo inspect|download`.
- NCBI: `spc dataset ncbi validate|download`.
- Dryad: `spc dataset dryad inspect|download`.
- Archives: start with `spc dataset archive capabilities`, then use `inspect` or an explicitly requested
  `download --file <key> --resume --verify-checksum`.

Do not start an unrequested large download. A remote manifest does not prove local payload readiness.
Supporting information or a dataset ZIP is never the article PDF.

## Hard boundaries

SPC does not choose topics, review papers, or run research methods. Do not expose API keys, cookies,
proxy endpoints, signed URLs, or exit IPs. Do not install another checkout into the current runtime;
if the reported source root is wrong, stop and report the mismatch.
