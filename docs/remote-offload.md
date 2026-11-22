# Remote Offload

Research Harness can keep the local machine as the controller while using a
replaceable remote worker for batch research jobs. The local checkout remains
the source of truth for the RH database, topic workspace, provenance, and final
artifact registry. A remote machine only receives a minimal task pack and sends
back a result pack.

This feature is generic. The repository does not contain host aliases,
usernames, private paths, SSH config, credentials, or site-specific worker
setup.

## Use Cases

First-version task types:

- `paper_text_extraction_batch`
- `wiki_embedding_batch`
- `retrieval_eval_sweep`
- `researchflowbench_batch_eval`

The initial contract is optimized for semi-automatic batch work. It does not
start a daemon, expose a remote HTTP API, replicate the RH database, or let a
worker execute arbitrary RH primitives.

## Configuration

Pass worker settings at runtime:

```bash
rh offload doctor --host <ssh-host-alias> --remote-root <remote-offload-root> --timeout-seconds 120
rh offload remote-library-scan --host <ssh-host-alias> --library-root <remote-library-root> --query "<query terms>" --out .tmp/rh-offload/remote_library_snapshot.json --timeout-seconds 300
rh offload prepare --type paper_text_extraction_batch --topic <topic> --out .tmp/rh-offload/<task-id>
rh offload prepare --type paper_text_extraction_batch --topic <topic> --include-pdf-files --max-pdf-bytes 100000000 --out .tmp/rh-offload/<task-id>
rh offload prepare --type retrieval_eval_sweep --topic <topic> --library-snapshot .tmp/rh-offload/remote_library_snapshot.json --out .tmp/rh-offload/<task-id>
rh offload upload .tmp/rh-offload/<task-id> --host <ssh-host-alias> --remote-root <remote-offload-root>
rh offload command <task-id> --host <ssh-host-alias> --remote-root <remote-offload-root>
rh offload fetch <task-id> --host <ssh-host-alias> --remote-root <remote-offload-root>
rh offload import .tmp/rh-offload/<task-id> --topic <topic>
rh offload remote-status --host <ssh-host-alias> --remote-root <remote-offload-root>
rh offload remote-cleanup --host <ssh-host-alias> --remote-root <remote-offload-root> --task-id <task-id>
rh offload batch-plan .tmp/rh-offload/<task-id> --out .tmp/rh-offload/batch_plan.json --host <ssh-host-alias> --remote-root <remote-offload-root>
rh offload batch-status .tmp/rh-offload/batch_plan.json
rh offload batch-reconcile .tmp/rh-offload/batch_plan.json
rh offload batch-preflight .tmp/rh-offload/batch_plan.json --capabilities ./capabilities.json
rh offload queue-create .tmp/rh-offload/<task-id> --out .tmp/rh-offload/offload_queue.json --host <ssh-host-alias> --remote-root <remote-offload-root>
rh offload queue-status .tmp/rh-offload/offload_queue.json
rh offload queue-step .tmp/rh-offload/offload_queue.json
```

Equivalent environment variables:

- `RH_OFFLOAD_HOST`
- `RH_OFFLOAD_REMOTE_ROOT`

Use a dedicated offload root owned by the user. RH rejects dangerous roots such
as an empty path, `.`, `/`, `~`, the local home directory, or paths containing
`..`.
`upload` creates the generic `incoming/`, `runs/`, `results/`, and `cache/`
layout under the configured root before running `rsync`.

## Doctor And Capabilities

`rh offload doctor` is read-only. It does not create remote directories, write
files, mutate credentials, or run a task. With SSH enabled, it probes:

- remote Python version
- whether `incoming/`, `runs/`, `results/`, and `cache/` already exist
- disk summary near the offload root
- optional GPU visibility through `nvidia-smi -L`
- basic Python package availability, including PDF and model-worker hints
- basic command availability, currently `pdftotext`
- optional worker capabilities from `<remote-root>/capabilities.json`

The optional capability file is generic JSON:

```json
{
  "schema_version": "rh_offload_worker_capabilities.v1",
  "supported_task_types": [
    "paper_text_extraction_batch",
    "wiki_embedding_batch"
  ],
  "resources": {
    "gpu": true,
    "cpu": 16,
    "memory_gb": 64
  },
  "features": {
    "pdf_parsers": ["pypdf", "pdftotext"],
    "embedding": {
      "backends": ["sentence-transformers"],
      "models": ["generic-local-model"],
      "default_device": "cuda"
    }
  },
  "cache_policy": {
    "max_gb": 50,
    "cleanup": "manual",
    "cache_root": "cache/"
  },
  "notes": ["example generic worker"]
}
```

`resources`, `features`, and `cache_policy` are declarative. RH does not install
packages, download models, create cache directories, or trust a worker because a
capability file exists. The local controller uses the fields only for preflight
diagnostics and task scheduling decisions made by the operator.

Unknown or unsupported task types are ignored by the local controller.
`--skip-ssh` reports local static checks and the built-in task type list without
requiring a host.
For slow SSH login shells, GPU probes, or very large remote filesystems, pass
`--timeout-seconds` explicitly instead of changing repository defaults.

## Task Pack Contract

Each task pack contains:

- `task_manifest.json`
- `inputs/`
- `runner.sh`
- `README.md`

The manifest records `task_id`, `task_type`, `created_at`, `input_hashes`,
`expected_outputs`, `resource_hint`, `timeout`, and `cleanup_policy`.

Inputs are minimized. RH does not copy `.research-harness/pool.db`, local PDF
paths, artifact local paths, full artifact payloads, or benchmark gold by
default.

For `paper_text_extraction_batch`, the default worker processes explicit text
that RH packages into the task pack from an existing local
`paperindex_structure` artifact. The pack includes the text, its SHA-256 hash,
page count, and safe paper metadata; it does not include `pdf_path`, PDF
binaries, PaperIndex artifact paths, or the RH database by default.

PDF binary packaging is opt-in through `--include-pdf-files`. When enabled, RH
copies only safe local `.pdf` files under the local RH database root into
`inputs/pdfs/` with hash-derived names. The input JSON stores only the relative
packaged PDF path, file size, and SHA-256 hash. It still does not store the
original local `pdf_path`, filename, parent directory, artifact path, or RH
database. The bundled worker tries remote PDF text extraction with an already
installed `pypdf`, `PyPDF2`, or `pdftotext`; if no parser is available or
parsing fails, the result remains a `partial` diagnostic instead of pretending
to succeed.

## Remote Library Snapshots

If a worker machine already has a large paper corpus, keep that corpus outside
RH and first create a redacted local snapshot:

```bash
rh offload remote-library-scan --host <ssh-host-alias> --library-root <remote-library-root> --query "time series forecasting" --out .tmp/rh-offload/time_series_snapshot.json --timeout-seconds 300
```

The scan is read-only. It walks the remote directory, samples matching filenames,
and writes a local `remote_library_snapshot.v1` JSON file. The snapshot contains
counts, extension distribution, basename-only samples, file sizes, matched query
terms, basename-derived token statistics, relative-path hashes, and a hash of the
host/root values. It does not store the SSH alias, username, absolute remote
path, relative path, file content, or RH database.

The snapshot can then be attached to task packs that need external corpus
context, for example:

```bash
rh offload prepare --type retrieval_eval_sweep --topic <topic> --library-snapshot .tmp/rh-offload/time_series_snapshot.json --out .tmp/rh-offload/<task-id>
```

This makes the local topic aware that a remote corpus exists without treating the
remote corpus as RH source-of-truth data. Import still only records result packs
that pass the normal result-manifest and hash checks.

For `wiki_embedding_batch`, the bundled worker uses deterministic hash features
over explicitly packaged, path-scrubbed wiki/context text. It writes:

- `outputs/wiki_embeddings.jsonl`
- `outputs/summary.json`

This worker can return a `succeeded` result and is useful as an end-to-end
sanity check that local RH context artifacts can be offloaded and imported
without copying the RH database or artifact paths. It is not a neural embedding
quality claim. A task pack may carry an explicit model policy; the bundled
worker currently supports a deterministic `fake_model` backend for schema and
integration testing without downloading models. Real model-backed embedding must
be added behind the same task/result contract with explicit worker capability
and cache policy.

For `retrieval_eval_sweep`, the bundled worker uses a deterministic BM25-style
rerank over redacted snapshot samples and basename-derived token statistics. It
writes:

- `outputs/predictions.jsonl`
- `outputs/retrieval_eval_report.json`

This worker can return a `succeeded` result and is useful as an end-to-end sanity
check that local topic metadata and remote corpus summaries are connected. It is
not a semantic retrieval-quality claim. The same explicit `fake_model` policy
can exercise model/rerank output schema without asserting retrieval quality or
downloading a model.

## Result Pack Contract

Each result pack contains:

- `result_manifest.json`
- `task_manifest.json` for succeeded results
- `outputs/`
- `logs/stdout.log`
- `logs/stderr.log`

Allowed statuses are `prepared`, `uploaded`, `running`, `succeeded`, `failed`,
`partial`, and `abandoned`. A `succeeded` result must have `exit_code == 0`,
matching output hashes, exact expected outputs, and no symlink anywhere in the
result package.

Remote fields such as `server_hostname` and `git_commit` are stored only as
untrusted metadata. They are not used as proof that the worker was trusted.

## Local Import

`rh offload import` always records a topic-level receipt artifact:

- `remote_offload_result` for succeeded results
- `remote_offload_diagnostic` for failed or partial results

For `paper_text_extraction_batch`, succeeded results can also create
`paper_artifacts` entries with `artifact_type = paperindex_structure`. This
uses the existing PaperIndex structure shape with `raw.pages_text`, so existing
deep-read consumers can reuse imported page text.

For `retrieval_eval_sweep`, succeeded results can also create a conservative
topic-level `remote_retrieval_eval_result` artifact. The artifact stores the
validated report, compact prediction summaries, output hashes, and provenance
links. It is evidence that a remote retrieval sweep ran; it is not a benchmark
promotion or retrieval-quality claim.

For `wiki_embedding_batch`, succeeded results can also create a topic-level
`remote_wiki_embedding_index` artifact. The artifact links remote embedding
rows back to local `project_artifacts:<id>` source refs when the worker output
contains safe artifact ids. It is a candidate Topic Knowledge retrieval-index
artifact and does not replace a canonical local vector store or local knowledge
snapshot.

The importer is conservative:

- It only writes paper-side artifacts for succeeded task results.
- It records retrieval and embedding outputs as non-canonical project artifacts.
- It skips malformed rows and records warnings in the receipt.
- It does not overwrite an existing canonical `paperindex_structure`.
- It does not supersede existing local canonical project artifacts.
- Re-importing the same result is idempotent.

## Recovery

The workflow is retryable:

- Re-running `upload` copies the same task pack to `incoming/<task_id>/`.
- Re-running the printed SSH command replaces `runs/<task_id>/` and writes a
  fresh `results/<task_id>/`.
- Re-running `fetch` copies `results/<task_id>/` back to the local results
  directory.
- Re-running `import` records another topic receipt but does not duplicate or
  overwrite existing canonical paper structure artifacts or remote-derived
  retrieval/embedding artifacts with the same task id and output hashes.

Each local lifecycle operation appends a local sidecar receipt named
`offload_receipt.json` in the task or result directory. The receipt records
controller-side attempts such as `prepare`, `upload`, `run_local`, `fetch`, and
`import`. It is for auditing and resume decisions only; it is not part of the
task or result manifest hash contract.

## Remote Status And Cleanup

`rh offload remote-status` summarizes the configured offload root. It reports
the generic `incoming/`, `runs/`, `results/`, and `cache/` sections, task ids,
manifest statuses where available, sizes, ages, and relative section paths. It
does not read task payload contents, copy files, import results, mutate the
remote machine, or expose site-specific defaults.

`rh offload remote-cleanup` is dry-run by default. It requires an explicit
filter, either one or more `--task-id` values or `--older-than-days`. Without
`--execute`, it only reports candidates. With `--execute`, it deletes only
validated directories inside selected offload sections under the configured
remote root. The default sections are `incoming`, `runs`, and `results`; include
`--section cache` explicitly to inspect or clean cache entries.

Cleanup never follows symlinks and rejects unsafe task ids, unsafe sections, and
remote roots that fail the normal `remote-root` policy.

## Batch Planning

`rh offload batch-plan` writes a local JSON plan with schema
`remote_offload_batch_plan.v1`. The plan can contain prepared task packs and
fetched result packs. Task entries include the same printable SSH command that
`rh offload command` would show for that task; result entries are counted for
local import readiness.

`rh offload batch-status` summarizes the saved plan by status and reports how
many items are ready to upload or import. It reads the plan file only. It does
not contact a remote worker, refresh package directories, run SSH, run `rsync`,
or import results.

`rh offload batch-reconcile` re-reads the local task/result package paths
referenced by a saved plan and reports drift, missing packages, invalid
packages, and resume buckets. It is still local-only: it does not upload,
fetch, import, run SSH, run `rsync`, or modify remote state.

`rh offload batch-preflight` compares task resource hints and task inputs against
an optional local worker capabilities JSON file. It reports unsupported task
types, resource mismatches such as a GPU-required task on a worker declared as
GPU-unavailable, packaged-PDF tasks without declared PDF parsers, model-heavy
tasks without declared embedding/eval capability, and missing or invalid
model-cache cleanup policy.

Without a capabilities file, preflight allows tasks with a warning instead of
guessing remote capacity. It does not run `doctor`, SSH, `rsync`, or any remote
probe. To use read-only doctor evidence in preflight, save or copy a generic
capabilities JSON file locally and pass it with `--capabilities`.

## Queue And Retry

`rh offload queue-create` writes a local queue file with schema
`remote_offload_queue.v1`. Queue items reference prepared task packs or fetched
result packs by local relative path and record `queue_status`, `next_action`,
and controller-side `attempts`.

`rh offload queue-status` reads only the local queue file and summarizes the
next actions. It does not contact the remote worker.

`rh offload queue-step` performs one explicit next action for the first eligible
queue item. It can upload a prepared task, fetch a remote result, or mark a
result as ready for manual import. It is not a daemon, does not poll forever, and
does not execute arbitrary RH primitives on the worker. Failed upload/fetch
steps append a retryable attempt and keep the next action unchanged so the
operator can retry after restoring VPN/SSH or after the remote run finishes.

Import remains explicit through `rh offload import`; queue state may point to an
import-ready result but does not overwrite canonical local artifacts.

## Testing Boundary

Automated tests use a local fake remote to verify task preparation, local
upload/fetch, runner execution, import, provenance linkage, hash checks,
symlink rejection, unsafe path rejection, and idempotency.

Real SSH, real `rsync`, remote shell differences, GPU visibility, disk quota,
remote permissions, and shared-server cleanup are manual smoke tests. They are
external actions and should only be run with explicit authorization, using
non-sensitive inputs and a dedicated temporary remote root.
