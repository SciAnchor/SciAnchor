# paperfetch

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Linux-success.svg)](#install)

paperfetch is a Linux-first command-line tool that gives researchers and AI agents a reliable way to
**find papers, fetch legal open-access PDFs, verify them, parse them, and bundle them into Seed
Packs**, plus inspect and download public research datasets.

Every command prints exactly one JSON document (`spc.result.v2`) on stdout, so it can be driven by
scripts and agents as easily as by hand. The agent architecture is simply:

```text
Skill -> spc CLI -> domain services
```

The command is `paperfetch`; `spc` is an equivalent alias (and the `SPC_*` environment
variables keep their names), so existing scripts keep working.

There is no MCP server; the live CLI parser plus `spc schema` is the machine-readable contract.

> Most CLI help text and the design docs under `docs/` are written in Chinese. The commands,
> flags, JSON fields, and error codes are in English.

## What paperfetch does

- **Metadata search and lookup** across OpenAlex, Crossref, Semantic Scholar, and PubMed /
  Europe PMC, by DOI, PMID, PMCID, or arXiv ID, with reference / citation / similar-paper graphs.
- **Legal full-text acquisition**: local cache, Europe PMC / PMC, arXiv, open-access links,
  publisher APIs for which you hold your own key, and public HTTP.
- **PDF verification**: real `%PDF-` header, non-empty bytes, SHA-256, paper identity check, and
  atomic write before anything counts as success.
- **Parsing** of PDFs to Markdown/JSON via the MinerU API (requires your own MinerU token).
- **Seed Packs**: an atomic, lock-protected paper bundle with `papers.jsonl` as its single source
  of truth.
- **Public datasets**: GEO, NCBI, Dryad, and Zenodo / Figshare archives (inspect, resumable
  download, checksum verification).
- **Background jobs** with `--detach` and `spc job wait|show|list|cancel`.
- **Diagnostics**: `spc doctor`, `spc system preflight`, and `spc system source-status`.

## What is NOT included

- **No institutional library or subscription access.** paperfetch has no campus-VPN, library proxy,
  or institutional SSO routes, and it never uses unofficial mirrors. If no legal open copy exists,
  the download fails with a stable error code.
- **No commercial journal metrics.** Proprietary journal rankings and impact data are not
  distributed with paperfetch. If you are licensed to use such data, you can supply your own data
  files.
- **No CAPTCHA, MFA, or human-verification handling.** Pages that require human action return
  `unattended_auth_blocked`.
- **No research judgment.** SPC does not choose topics, review papers, or write. That is the
  job of the agent or the user.

## Install

Requires Linux and Python 3.12.

```bash
git clone https://github.com/scianchor/research-harness.git
cd research-harness/packages/paperfetch
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .              # core CLI
pip install -e ".[test]"      # + pytest / ruff
pip install -e ".[browser]"   # + optional browser-assisted open-access downloads
```

A minimal container image is also provided:

```bash
docker build -t paperfetch .
docker run --rm -v "$PWD/out:/work" paperfetch paper lookup --doi 10.1038/s41586-020-2649-2
```

## Quickstart

```bash
spc --help                      # command domains
spc schema paper download       # machine-readable arguments for one command
spc schema config               # every configuration variable, type, default, and secrecy
spc version
spc system preflight --profile development --capability system.core
spc doctor

# Search and look up papers
spc paper search --query "graph neural networks for molecules" --limit 10
spc paper lookup --doi 10.1038/s41586-020-2649-2
spc paper graph  --doi 10.1038/s41586-020-2649-2 --direction references

# Download and verify a PDF (parses with MinerU by default; --no-parse to skip)
spc paper download --doi 10.1038/s41586-020-2649-2 --output-dir ./out/numpy --route auto

# Long work can run in the background
spc paper lookup --doi 10.1038/s41586-020-2649-2 --detach
spc job wait <job-id> --timeout-seconds 300

# Parse a local PDF (not bound to a paper identity)
spc paper parse --pdf ./paper.pdf --output-dir ./out/parsed

# Seed Packs
spc seed-pack init   --seed-pack ./my-pack
spc seed-pack add    --seed-pack ./my-pack --doi 10.1038/s41586-020-2649-2
spc seed-pack enrich --seed-pack ./my-pack
spc seed-pack show   --seed-pack ./my-pack

# Public datasets
spc dataset archive capabilities
spc dataset geo --help
```

`--route auto` uses the best legal route available; `--route public` restricts to open/public
routes. A successful download reports `data.download.route`, `data.download.access`, and
`data.download.identity_verified`.

### Output contract

The default output is a single JSON document whose top level contains only
`schema status job_id data files results error`. `status` is one of
`queued running cancelling completed partial failed cancelled`. `partial` means usable output
exists but a later stage failed (for example, the PDF was verified but parsing failed). stderr is
empty by default; use `-v`, `--debug`, or `--log-file` for diagnostics.

## Configuration and optional API keys

SPC works without any keys, but anonymous API pools are heavily rate limited. You may configure
your own keys. Copy `.env.example` to `~/.config/spc/secrets.env` (loaded automatically), or pass
`--env-file <path>` to any command. The repository-root `.env` is not loaded automatically.

| Purpose | Variables |
| --- | --- |
| Semantic Scholar | `SEMANTIC_SCHOLAR_API_KEY`, `SEMANTIC_SCHOLAR_API_KEYS` (comma-separated pool) |
| OpenAlex / Crossref | `OPENALEX_API_KEY`, `OPENALEX_API_KEYS`, `OPENALEX_MAILTO`, `CROSSREF_MAILTO` |
| Unpaywall | `UNPAYWALL_EMAIL` |
| NCBI / PubMed | `NCBI_API_KEY`, `NCBI_EMAIL` |
| Publisher APIs | `ELSEVIER_API_KEY`, `SPRINGER_API_KEY` (only for content your key is entitled to) |
| MinerU parsing | `MINERU_API_TOKEN`, `MINERU_BASE_URL` |
| LLM (optional, any OpenAI-compatible endpoint) | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| Proxies (optional, independent per capability) | `METADATA_PROXY`, `DOWNLOAD_PROXY`, `MINERU_PROXY`, `ARCHIVE_PROXY` |

Run `spc schema config` for the authoritative list. Keys are never echoed to stdout, stderr,
events, or logs. State and caches default to `~/.spc/` and can be moved with `SPC_STATE_ROOT`,
`SPC_CACHE_ROOT`, and `SPC_DATA_ROOT`.

## Agent skills

- `plugins/spc/skills/spc-research-acquisition/SKILL.md`: an English skill describing how an agent
  should drive the CLI. `plugins/spc` packages it as a Codex plugin (`codex plugin marketplace add .`
  then `codex plugin add spc@paperfetch`).
- `.agents/skills/curate-paper/SKILL.md`: a short Chinese variant.

## Development

```bash
pip install -e ".[test]"
python -m pytest -q -m "not online and not live and not release and not browser"
ruff check src tests scripts
```

Tests marked `online` / `live` hit real networks and run only when explicitly requested
(`SPC_RUN_ONLINE_TESTS=1`). `scripts/build_release.py` builds a single wheel plus a SHA-256
manifest from a clean, committed checkout; `scripts/verify_release.py` installs and checks it in
a fresh venv.

Design documents are indexed in [docs/README.md](docs/README.md). See [AGENTS.md](AGENTS.md)
for the rules coding agents should follow in this repository.

## Safety boundaries

SPC only uses legal public sources and official APIs. Pages that declare an automatic check may be
waited on passively within a hard deadline; checkbox challenges, CAPTCHA, Turnstile interaction,
MFA, QR scans, or other human confirmation stop the task without clicking or bypassing.
Credentials, cookies, proxy credentials, signed URLs, and research data never belong in Git,
stdout, stderr, or logs.

## License

Part of Research Harness and released under the [GNU AGPL-3.0](../../LICENSE); a commercial license is available, see [NOTICE](../../NOTICE).
