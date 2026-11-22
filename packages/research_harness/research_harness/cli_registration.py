"""Ordered registration of Research Harness CLI command groups."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click


CliDeps = Mapping[str, Any]


def _dep(deps: CliDeps, name: str) -> Any:
    return deps[name]


def register_main_before_topic(main: click.Group, deps: CliDeps) -> None:
    """Register root commands that historically preceded the topic group."""
    from ._productization.cli import register as register_productization_cli
    from .cli_backend import register as register_backend_cli
    from .cli_config import register as register_config_cli
    from .cli_cs import register as register_cs_cli
    from .cli_domain import register as register_domain_cli
    from .cli_feedback import register as register_feedback_cli
    from .cli_panorama import register as register_panorama_cli
    from .cli_offload import register as register_offload_cli
    from .discover.cli import register as register_discover_cli
    from .eval.researchflowbench.cli import register as register_researchflowbench_cli
    from .longtask.cli import register as register_longtask_cli
    from .skill.cli import register as register_skill_cli
    from .cli_workspace import register as register_workspace_cli

    register_skill_cli(main)
    register_workspace_cli(main)
    register_discover_cli(main)
    register_longtask_cli(main)
    register_researchflowbench_cli(main)
    register_productization_cli(main)
    register_config_cli(
        main,
        get_runtime_config=_dep(deps, "get_runtime_config"),
        echo=_dep(deps, "echo"),
    )
    register_backend_cli(
        main,
        create_backend=_dep(deps, "create_backend"),
        echo=_dep(deps, "echo"),
    )
    register_domain_cli(
        main,
        get_db=_dep(deps, "get_db"),
        echo=_dep(deps, "echo"),
    )
    register_panorama_cli(
        main,
        get_db=_dep(deps, "get_db"),
        echo=_dep(deps, "echo"),
        create_backend=_dep(deps, "create_backend"),
    )
    register_offload_cli(
        main,
        get_runtime_config=_dep(deps, "get_runtime_config"),
    )
    register_cs_cli(
        main,
        get_db=_dep(deps, "get_db"),
        echo=_dep(deps, "echo"),
    )
    register_feedback_cli(
        main,
        get_db=_dep(deps, "get_db"),
        echo=_dep(deps, "echo"),
    )


def register_topic(topic: click.Group, deps: CliDeps) -> None:
    """Register topic subcommands in their historical insertion order."""
    from .cli_topic_knowledge import register as register_topic_knowledge_cli
    from .cli_topic_lifecycle import (
        register_export as register_topic_export_cli,
    )
    from .cli_topic_lifecycle import (
        register_init_workspace as register_topic_init_workspace_cli,
    )
    from .cli_topic_manage import register_update as register_topic_update_cli
    from .cli_topic_overview import register as register_topic_overview_cli
    from .cli_topic_read import register as register_topic_read_cli
    from .cli_topic_read import register_coverage as register_topic_coverage_cli
    from .cli_topic_state import register as register_topic_state_cli

    register_topic_coverage_cli(topic)

    register_topic_init_workspace_cli(
        topic,
        get_db=_dep(deps, "get_db"),
        get_runtime_config=_dep(deps, "get_runtime_config"),
        echo=_dep(deps, "echo"),
    )
    register_topic_read_cli(
        topic,
        invoke_service_or_exit=_dep(deps, "invoke_service_or_exit"),
        topic_list_payload_for_cli=_dep(deps, "topic_list_payload_for_cli"),
        topic_show_payload_for_cli=_dep(deps, "topic_show_payload_for_cli"),
    )
    register_topic_knowledge_cli(
        topic,
        get_db=_dep(deps, "get_db"),
        positive_topic_id_or_exit=_dep(deps, "positive_topic_id_or_exit"),
        exit_with_public_error=_dep(deps, "exit_with_public_error"),
        json_requested=_dep(deps, "json_requested"),
    )
    register_topic_update_cli(
        topic,
        get_db=_dep(deps, "get_db"),
        echo=_dep(deps, "echo"),
    )
    register_topic_overview_cli(
        topic,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        paper_status_payload=_dep(deps, "paper_status_payload"),
        paper_queue_entry=_dep(deps, "paper_queue_entry"),
        check_review_ready=_dep(deps, "check_review_ready"),
    )
    register_topic_export_cli(
        topic,
        get_db=_dep(deps, "get_db"),
        write_text_output=_dep(deps, "write_text_output"),
    )
    register_topic_state_cli(
        topic,
        get_db=_dep(deps, "get_db"),
        get_runtime_config=_dep(deps, "get_runtime_config"),
        echo=_dep(deps, "echo"),
    )


def register_main_between_topic_and_paper(main: click.Group, deps: CliDeps) -> None:
    """Register root commands that historically sat between topic and paper."""
    from .cli_search import register as register_search_cli

    register_search_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )


def register_paper_and_remaining(
    main: click.Group,
    topic: click.Group,
    paper: click.Group,
    deps: CliDeps,
) -> None:
    """Register paper subcommands and remaining root/topic commands."""
    from .cli_auto_runner import register as register_auto_runner_cli
    from .cli_bib import register as register_bib_cli
    from .cli_calibrate import register as register_calibrate_cli
    from .cli_doctor import register as register_doctor_cli
    from .cli_experiment import register as register_experiment_cli
    from .cli_paper_acquisition import (
        register_acquisition as register_paper_acquisition_cli,
    )
    from .cli_paper_acquisition import register_ingest as register_paper_ingest_cli
    from .cli_paper_acquisition import register_metadata as register_paper_metadata_cli
    from .cli_paper_annotations import register as register_paper_annotations_cli
    from .cli_paper_manage import register_link as register_paper_link_cli
    from .cli_paper_manage import register_update as register_paper_update_cli
    from .cli_paper_move import register as register_paper_move_cli
    from .cli_exemplar import register as register_exemplar_cli
    from .cli_polish import register as register_polish_cli
    from .cli_paper_production import register as register_paper_production_cli
    from .cli_paper_read import (
        register_artifacts_card as register_paper_artifacts_card_cli,
    )
    from .cli_paper_read import register_list_show as register_paper_list_show_cli
    from .cli_paper_status import register as register_paper_status_cli
    from .cli_primitive import register as register_primitive_cli
    from .cli_orchestrator import register as register_orchestrator_cli
    from .cli_provenance import register as register_provenance_cli
    from .cli_resource import register as register_resource_cli
    from .cli_publication_pack import register as register_publication_pack_cli
    from .cli_deposit import register as register_deposit_cli
    from .cli_research_state import register as register_research_state_cli
    from .cli_review import register as register_review_cli
    from .cli_self_evolution import register as register_self_evolution_cli
    from .cli_task import register as register_task_cli
    from .cli_topic_extras import register as register_topic_extras_cli
    from .cli_trends import register as register_trends_cli
    from .cli_zotero import register as register_zotero_cli

    register_paper_ingest_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_paper_list_show_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        invoke_service_or_exit=_dep(deps, "invoke_service_or_exit"),
        paper_list_payload_for_cli=_dep(deps, "paper_list_payload_for_cli"),
    )
    register_paper_update_cli(
        paper, get_db=_dep(deps, "get_db"), echo=_dep(deps, "echo")
    )
    register_paper_metadata_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
    )
    register_paper_link_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_paper_status_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        paper_status_payload=_dep(deps, "paper_status_payload"),
        paper_queue_entry=_dep(deps, "paper_queue_entry"),
    )
    register_paper_annotations_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        paper_artifact_or_exit=_dep(deps, "paper_artifact_or_exit"),
        decode_artifact_metadata=_dep(deps, "decode_artifact_metadata"),
        load_json_artifact_or_exit=_dep(deps, "load_json_artifact_or_exit"),
        draft_topic_note_from_card=_dep(deps, "draft_topic_note_from_card"),
        echo=_dep(deps, "echo"),
        note_types=_dep(deps, "note_types"),
    )
    register_paper_artifacts_card_cli(
        paper,
        get_db=_dep(deps, "get_db"),
        paper_artifact_or_exit=_dep(deps, "paper_artifact_or_exit"),
        decode_artifact_metadata=_dep(deps, "decode_artifact_metadata"),
        load_json_artifact_or_exit=_dep(deps, "load_json_artifact_or_exit"),
    )
    register_paper_acquisition_cli(paper, get_db=_dep(deps, "get_db"))
    register_paper_move_cli(paper, get_db=_dep(deps, "get_db"), echo=_dep(deps, "echo"))

    register_topic_extras_cli(
        topic, get_db=_dep(deps, "get_db"), echo=_dep(deps, "echo")
    )

    register_zotero_cli(main, get_db=_dep(deps, "get_db"))
    register_bib_cli(main, get_db=_dep(deps, "get_db"), echo=_dep(deps, "echo"))
    register_task_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
        paper_status_payload=_dep(deps, "paper_status_payload"),
        paper_queue_entry=_dep(deps, "paper_queue_entry"),
        check_review_ready=_dep(deps, "check_review_ready"),
    )
    register_review_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_primitive_cli(
        main,
        get_db=_dep(deps, "get_db"),
        create_backend=_dep(deps, "create_backend"),
        echo=_dep(deps, "echo"),
    )
    register_publication_pack_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_deposit_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_research_state_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_self_evolution_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_provenance_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        invoke_service_or_exit=_dep(deps, "invoke_service_or_exit"),
        legacy_summary_payload_for_cli=_dep(deps, "legacy_summary_payload_for_cli"),
        summary_payload_for_cli=_dep(deps, "summary_payload_for_cli"),
        legacy_export_records_for_cli=_dep(deps, "legacy_export_records_for_cli"),
        export_records_for_cli=_dep(deps, "export_records_for_cli"),
        serialize_export=_dep(deps, "serialize_export"),
        write_text_output=_dep(deps, "write_text_output"),
        echo=_dep(deps, "echo"),
    )
    register_orchestrator_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        invoke_service_or_exit=_dep(deps, "invoke_service_or_exit"),
        orchestrator_status_payload_for_cli=_dep(
            deps, "orchestrator_status_payload_for_cli"
        ),
        orchestrator_gate_check_payload_for_cli=_dep(
            deps, "orchestrator_gate_check_payload_for_cli"
        ),
        echo=_dep(deps, "echo"),
    )
    register_resource_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
        echo=_dep(deps, "echo"),
    )
    register_doctor_cli(
        main,
        get_runtime_config=_dep(deps, "get_runtime_config"),
        get_db=_dep(deps, "get_db"),
    )
    register_exemplar_cli(main, get_db=_dep(deps, "get_db"), echo=_dep(deps, "echo"))
    register_polish_cli(main, get_db=_dep(deps, "get_db"), echo=_dep(deps, "echo"))
    register_paper_production_cli(
        main,
        get_db=_dep(deps, "get_db"),
        echo=_dep(deps, "echo"),
    )
    register_auto_runner_cli(main, echo=_dep(deps, "echo"))
    register_calibrate_cli(main, get_db=_dep(deps, "get_db"))
    register_trends_cli(main, get_db=_dep(deps, "get_db"))
    register_experiment_cli(
        main,
        get_db=_dep(deps, "get_db"),
        topic_id_or_exit=_dep(deps, "topic_id_or_exit"),
    )
