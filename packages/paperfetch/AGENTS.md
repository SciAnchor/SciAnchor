# paperfetch

This file defines the working rules for agents (Codex, Claude Code, Cursor, and similar) that
change or operate SPC in this repository. Product and information contracts are described in
`docs/SPC2.0架构与迁移基线.md` and `docs/SPC2.0CLI与Skill重构契约.md`; the live CLI
(`spc --help`, `spc schema`) is the final authority.

## 1. Runtime

| `SPC_ENVIRONMENT` | Meaning | Entry point |
| --- | --- | --- |
| `development` (default) | Source checkout with `pip install -e .` | `<checkout>/.venv/bin/spc` |
| `production` | An installed release wheel | the `spc` of that install |

- Requires Linux and Python 3.12. Always call the `spc` from the virtualenv you are working in;
  do not rely on whatever `spc` happens to be on `PATH`.
- Secrets load from `~/.config/spc/secrets.env` or an explicit `--env-file`. The repo-root `.env`
  is never loaded automatically. State and caches default to `~/.spc/` (`SPC_STATE_ROOT`,
  `SPC_CACHE_ROOT`, `SPC_DATA_ROOT` override them).
- Public command domains: `paper`, `seed-pack`, `dataset`, `job`, `validate`, `system`, `doctor`,
  `schema`, `workflow`, `version`. There is no MCP and no `agent-guide`. Background commands use
  `--detach` and finish with `spc job wait`. `paper parse` is identity-free parsing; its success is
  not evidence of a paper's official full text.

## 2. First checks

```bash
.venv/bin/python --version
.venv/bin/spc version
.venv/bin/spc system preflight \
  --profile development \
  --capability system.core \
  --expected-git-sha "$(git rev-parse HEAD)" \
  --expected-source-root "$PWD"
.venv/bin/spc doctor
.venv/bin/spc schema config
```

`doctor` reports only `data.verdict` / `data.checks` / `data.blockers`; a passing check does not
mean a particular download will succeed.

## 3. Network, credentials, and acquisition boundaries

- SPC consumes only explicitly configured proxies. `METADATA_PROXY`, `DOWNLOAD_PROXY`,
  `MINERU_PROXY`, and `ARCHIVE_PROXY` are independent and must not be reused implicitly.
- API keys are optional and user-supplied. Keys, cookies, proxy credentials, exit IPs, and signed
  URLs must never enter the repository, stdout, stderr, events, logs, or test fixtures.
- paperfetch acquires full text only from legal open-access sources, official publisher APIs the
  user holds keys for, and public HTTP. Do not add institutional-access, library-proxy, or
  unofficial-mirror routes.
- Never handle or bypass CAPTCHA, MFA, Turnstile, or human verification. A page that only shows an
  automatic "Verifying..." state may be polled passively within a hard deadline; anything that needs
  human action returns `unattended_auth_blocked`.

## 4. Development and tests

1. When a public command, schema, or capability changes, update the CLI registrar, `spc schema`
   output, the skills (`plugins/spc/skills/`, `.agents/skills/`), and the docs in the same change.
   Remove obsolete commands and their documentation instead of keeping compatibility shims.
2. Run the affected unit/contract tests while iterating. The standard offline suite is:

   ```bash
   .venv/bin/python -m pytest -q -p no:cacheprovider \
     -m "not online and not live and not release and not browser"
   ```

   `online` / `live` / `browser` / `release` tests need real network, browsers, or release
   artifacts and are run only on purpose.
3. A PDF counts as downloaded only with a real `%PDF-` header, non-zero bytes, SHA-256, a verified
   paper identity, and an atomic write. A landing page or PDF viewer is not success.
4. `job cancel` may record `cancelled` only after the job's worker and any browser process tree
   have exited.
5. stdout carries exactly one final JSON document. Diagnostic logs go to stderr only with `-v`,
   `--debug`, or `--log-file`. Stable English is used for schema names, statuses, and error codes.
6. Never edit a Seed Pack's `papers.jsonl` by hand; go through `spc seed-pack`.
7. Lint touched Python with `ruff check`.

## 5. Building a release

`scripts/build_release.py` builds exactly one wheel from a clean, committed Python 3.12 checkout
(via `git archive`) and writes a manifest with the Git SHA, wheel name, size, and SHA-256.
`scripts/verify_release.py --manifest <path> --venv <new-dir>` installs that wheel into a fresh
virtualenv and checks version, schema, and `system.core`.

## 6. Documentation

- Index: `docs/README.md`
- Architecture: `docs/SPC2.0架构与迁移基线.md`
- CLI and skill contract: `docs/SPC2.0CLI与Skill重构契约.md`
- Full-text download: `docs/论文全文下载架构.md`
- Seed Pack contract: `docs/智能体种子包契约.md`

Conflict priority: current code and live `spc schema` > this file > docs.
