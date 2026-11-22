# -*- coding: utf-8 -*-
"""按子命令分发到领域处理器。"""

from __future__ import annotations

import argparse

from paperfetch.observability import get_event_logger, write_output

logger = get_event_logger("paperfetch.cli")


def dispatch(parsed_args: argparse.Namespace) -> int:
    if parsed_args.command == "system":
        from paperfetch.cli.system import run_system

        return run_system(parsed_args)

    if parsed_args.command == "paper":
        from paperfetch.cli.paper_v1 import run_paper

        return run_paper(parsed_args)

    if parsed_args.command == "seed-pack":
        from paperfetch.cli.seed_pack_v1 import run_seed_pack

        return run_seed_pack(parsed_args)

    if parsed_args.command == "doctor":
        from paperfetch.cli.doctor import run_doctor

        return run_doctor(parsed_args)

    elif parsed_args.command == "version":
        from paperfetch.runtime_info import collect_runtime_info

        runtime = collect_runtime_info()
        if parsed_args.output_format == "json":
            write_output(runtime, pretty=True)
        else:
            write_output(
                f"SPC {runtime['version']} | sha={runtime['git_sha'] or 'unknown'} | "
                f"mode={runtime['install_mode']} | path={runtime['package_path']}"
            )
        return 0

    elif parsed_args.command == "job":
        from paperfetch.jobs import cancel, list_jobs, show, wait

        handlers = {
            "list": lambda: list_jobs(parsed_args.limit),
            "show": lambda: show(parsed_args.job_id),
            "wait": lambda: wait(parsed_args.job_id, parsed_args.timeout_seconds),
            "cancel": lambda: cancel(parsed_args.job_id),
        }
        payload = handlers[parsed_args.job_action]()
        write_output(payload, pretty=True)
        if parsed_args.job_action in {"list", "show", "cancel"}:
            return 0
        status = payload.get("status")
        if payload.get("data", {}).get("timed_out"):
            return 124
        return {"completed": 0, "partial": 2, "failed": 1, "cancelled": 130}.get(
            status, 0
        )

    elif parsed_args.command == "workflow":
        from paperfetch.cli.workflow import run_workflow

        return run_workflow(parsed_args)

    elif parsed_args.command == "dataset":
        if parsed_args.dataset_action == "geo":
            from paperfetch.cli.gse import run_download_gse, run_inspect_gse

            return (
                run_download_gse(parsed_args)
                if parsed_args.dataset_source_action == "download"
                else run_inspect_gse(parsed_args)
            )
        if parsed_args.dataset_action == "ncbi":
            from paperfetch.cli.datasets import (
                run_download_ncbi_record,
                run_ncbi_validate,
            )

            return (
                run_ncbi_validate(parsed_args)
                if parsed_args.dataset_source_action == "validate"
                else run_download_ncbi_record(parsed_args)
            )
        if parsed_args.dataset_action == "dryad":
            from paperfetch.cli.datasets import run_download_dryad, run_inspect_dryad

            return (
                run_download_dryad(parsed_args)
                if parsed_args.dataset_source_action == "download"
                else run_inspect_dryad(parsed_args)
            )
        if parsed_args.dataset_action == "archive":
            from paperfetch.cli.datasets import run_archive_dataset

            return run_archive_dataset(parsed_args)
        from paperfetch.cli.biomedical import run_biomedical_dataset

        return run_biomedical_dataset(parsed_args)

    elif (
        parsed_args.command == "validate" and parsed_args.validate_action == "download"
    ):
        from paperfetch.cli.download_validation import run_download_validation_command

        return run_download_validation_command(parsed_args)

    raise ValueError(f"未知子命令: {parsed_args.command}")
