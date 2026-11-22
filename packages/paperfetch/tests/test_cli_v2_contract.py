"""SPC 2.0 精简公共 CLI 契约。"""

from __future__ import annotations

import argparse
import json

import pytest

from paperfetch.cli.root import build_parser, main
from paperfetch.cli.schema import command_schema
from paperfetch.core.public_result import to_public_result


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _leaves(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()):
    action = next(
        (
            item
            for item in parser._actions
            if isinstance(item, argparse._SubParsersAction)
        ),
        None,
    )
    if action is None:
        yield prefix
        return
    for name, child in action.choices.items():
        yield from _leaves(child, (*prefix, name))


def test_every_leaf_help_is_clean(capsys):
    for path in _leaves(build_parser()):
        with pytest.raises(SystemExit) as caught:
            main([*path, "--help"])
        assert caught.value.code == 0, path
        captured = capsys.readouterr()
        assert captured.out.startswith("usage:"), path
        assert captured.err == "", path


def test_top_level_surface_is_small_and_has_no_removed_entry(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    output = capsys.readouterr().out
    for name in (
        "paper",
        "seed-pack",
        "dataset",
        "job",
        "validate",
        "system",
        "doctor",
        "schema",
    ):
        assert name in output
    for removed in (
        "mcp",
        "agent-guide",
        "download-gse",
        "cstcloud-validate",
        "venue-recommend",
    ):
        assert removed not in output
    assert "AGENT QUICKSTART" in output


def test_leaf_help_exposes_risk_execution_and_schema_path(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["paper", "download", "--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "Risk: write" in output
    assert "Execution: detachable" in output
    assert "Machine contract: spc schema paper download" in output


def test_every_leaf_schema_is_json_serializable():
    parser = build_parser()

    for path in _leaves(parser):
        payload = command_schema(parser, list(path))
        json.dumps(payload, ensure_ascii=False)


def test_schema_preserves_list_defaults_without_crashing(capsys):
    assert main(["schema", "system", "preflight"]) == 0
    payload = json.loads(capsys.readouterr().out)

    arguments = {item["name"]: item for item in payload["data"]["arguments"]}
    assert arguments["capability"]["default"] == []


def test_unknown_schema_path_is_stable_json(capsys):
    assert main(["schema", "system", "missing"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "invalid_command_path"


def test_invalid_arguments_are_one_json_document_on_stdout(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["paper", "download", "--output-dir", "/tmp/paper"])
    assert caught.value.code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema": "spc.result.v2",
        "status": "failed",
        "error": {
            "code": "invalid_arguments",
            "message": "one of the arguments --doi --pubmed-id --pmc-id --arxiv-id is required",
        },
    }
    assert captured.err == ""


def test_v1_download_projection_is_minimal_and_preserves_route_fact():
    payload = to_public_result(
        {
            "schema_version": "spc.command-result.v1",
            "command": "paper.download",
            "run_id": "run",
            "status": "completed",
            "summary": {"selected": 1, "succeeded": 1},
            "items": [
                {
                    "entity": {"type": "paper", "id": "paper-1"},
                    "status": "completed",
                    "data": {
                        "paper_id": "paper-1",
                        "identifiers": {"doi": "10.1000/example"},
                        "citation": {"title": "Example"},
                        "download": {
                            "status": "available",
                            "route": "elsevier_api",
                            "identity_verified": True,
                            "attempted": [
                                {"route": "public_http", "outcome": "failed"}
                            ],
                        },
                    },
                    "artifacts": [
                        {
                            "kind": "paper_pdf",
                            "path": "/tmp/article.pdf",
                            "size_bytes": 10,
                            "sha256": "a" * 64,
                        }
                    ],
                }
            ],
        }
    )
    assert payload == {
        "schema": "spc.result.v2",
        "status": "completed",
        "data": {
            "paper": {"doi": "10.1000/example", "title": "Example"},
            "citation": {"title": "Example"},
            "download": {
                "route": "publisher_api",
                "access": "public",
                "identity_verified": True,
            },
        },
        "files": [
            {
                "type": "pdf",
                "path": "/tmp/article.pdf",
                "size": 10,
                "sha256": "a" * 64,
            }
        ],
    }


def test_archive_manifest_inspection_is_completed_without_payload_download():
    payload = to_public_result(
        {
            "schema_version": "spc.archive-dataset-record.v1",
            "source": "zenodo",
            "record": "123",
            "status": "manifest_ready",
            "readiness": {"manifest_ready": True, "payload_ready": False},
        }
    )

    assert payload == {
        "schema": "spc.result.v2",
        "status": "completed",
        "data": {
            "source": "zenodo",
            "record": "123",
            "readiness": {"manifest_ready": True, "payload_ready": False},
        },
    }


def test_schema_is_generated_from_live_parser(capsys):
    assert main(["schema", "paper", "download"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "spc.result.v2"
    assert payload["data"]["command"] == "paper download"
    assert payload["data"]["execution"] == "detachable"
    assert (
        payload["data"]["description"]
        == "反查元数据，在输出目录建单篇包，下载并校验 PDF，默认再解析正文"
    )
    route = next(
        item for item in payload["data"]["arguments"] if item["name"] == "route"
    )
    assert route["choices"] == ["auto", "public"]
    assert payload["data"]["constraints"] == [
        {
            "type": "exactly_one",
            "arguments": ["doi", "pubmed-id", "pmc-id", "arxiv-id"],
        }
    ]


def test_cache_hit_is_local_and_cannot_claim_current_access():
    payload = to_public_result(
        {
            "schema_version": "spc.command-result.v1",
            "command": "paper.download",
            "status": "completed",
            "summary": {"selected": 1, "succeeded": 1},
            "items": [
                {
                    "entity": {"type": "paper", "id": "paper-1"},
                    "status": "completed",
                    "data": {
                        "paper_id": "paper-1",
                        "download": {
                            "status": "available",
                            "route": "global_cache",
                            "identity_verified": True,
                        },
                    },
                }
            ],
        }
    )
    assert payload["data"]["download"] == {
        "route": "local",
        "access": "local",
        "identity_verified": True,
    }


def test_v2_failure_keeps_error_not_hops():
    payload = to_public_result(
        {
            "schema_version": "spc.command-result.v1",
            "command": "paper.download",
            "status": "failed",
            "items": [
                {
                    "entity": {"type": "paper", "id": "paper-1"},
                    "status": "failed",
                    "data": {
                        "paper_id": "paper-1",
                        "identifiers": {"doi": "10.3389/fmed.2023.1208866"},
                        "download": {
                            "status": "failed",
                            "identity_verified": False,
                            "stage": "pdf_transfer",
                            "challenge_mode": "automatic_verification",
                            "hops": [
                                {
                                    "status": 403,
                                    "method": "GET",
                                    "host": "www.frontiersin.org",
                                    "path": "/articles/pdf",
                                },
                            ],
                        },
                    },
                    "error": {
                        "code": "publisher_challenge",
                        "error_class": "publisher_challenge",
                        "stage": "pdf_transfer",
                        "message": "出版社自动验证未在有限等待内放行",
                        "next": "稍后重试或改用其他公开来源",
                    },
                }
            ],
            "error": {
                "code": "publisher_challenge",
                "error_class": "publisher_challenge",
                "stage": "pdf_transfer",
                "message": "出版社自动验证未在有限等待内放行",
                "next": "稍后重试或改用其他公开来源",
            },
        }
    )
    assert payload["error"] == {
        "code": "publisher_challenge",
        "message": "出版社自动验证未在有限等待内放行",
        "stage": "pdf_transfer",
        "next": "稍后重试或改用其他公开来源",
    }
    assert payload["data"]["download"] == {"identity_verified": False}
