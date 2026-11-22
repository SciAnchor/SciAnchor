import io
import hashlib
import json
import zipfile
from types import SimpleNamespace

import pytest
import requests

from paperfetch.cli.datasets import _archive_failure, run_archive_dataset
from paperfetch.datasets.archive import (
    ArchiveDatasetError,
    FigshareArchiveStore,
    ZenodoArchiveStore,
    _archive_record_lock,
)


def _zip_bytes() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dataset/info.txt", "public images only")
        archive.writestr(
            "dataset/manifest.json",
            json.dumps({"labels": {}, "numTraining": 2, "numTest": 0}),
        )
        archive.writestr("dataset/imagesTr/a.nii.gz", b"image-a")
        archive.writestr("dataset/imagesTr/b.nii.gz", b"image-b")
    return payload.getvalue()


def _zip_bytes_with_non_utf8_text() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "dataset/manifest.json",
            b'\xef\xbb\xbf{"labels": {}, "numTraining": 1, "numTest": 0}',
        )
        archive.writestr("dataset/legacy.txt", b"header\n\xc7broken-utf8")
        archive.writestr("dataset/imagesTr/a.nii.gz", b"image-a")
    return payload.getvalue()


def _zip_bytes_with_macos_artifacts() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dataset/info.txt", "scientific text")
        archive.writestr("dataset/scan.nii.gz", b"image")
        archive.writestr("dataset/.DS_Store", b"finder")
        archive.writestr("__MACOSX/dataset/._info.txt", b"\x00\x05\xc7apple-double")
        archive.writestr("__MACOSX/dataset/._scan.nii.gz", b"resource-fork")
    return payload.getvalue()


def test_remote_zip_inventory_reads_only_ranges_and_small_text(tmp_path):
    body = _zip_bytes()
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    calls = []

    def range_read(_url, start, end):
        calls.append((start, end))
        return body[start : end + 1]

    store._range = range_read
    inventory = store._remote_zip_inventory(
        {
            "key": "dataset.zip",
            "bytes": len(body),
            "_url": "https://example.invalid/content",
        },
        1024,
    )

    assert inventory["entry_count"] == 4
    assert inventory["entry_type_counts"] == {"txt": 1, "json": 1, "nii.gz": 2}
    assert inventory["manifest_summaries"] == [
        {
            "name": "dataset/manifest.json",
            "labels": {},
            "numTraining": 2,
            "numTest": 0,
        }
    ]
    assert sum(end - start + 1 for start, end in calls) < len(body) * 2


def test_remote_zip_inventory_preserves_inventory_when_text_decode_fails(tmp_path):
    body = _zip_bytes_with_non_utf8_text()
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store._range = lambda _url, start, end: body[start : end + 1]

    inventory = store._remote_zip_inventory(
        {
            "key": "dataset.zip",
            "bytes": len(body),
            "_url": "https://example.invalid/content",
        },
        1024,
    )

    assert inventory["entry_count"] == 3
    assert inventory["entry_type_counts"] == {"json": 1, "txt": 1, "nii.gz": 1}
    assert inventory["manifest_summaries"] == [
        {"name": "dataset/manifest.json", "labels": {}, "numTraining": 1, "numTest": 0}
    ]
    assert inventory["small_text_summary"] == {"selected": 2, "decoded": 1, "failed": 1}
    error = inventory["entry_errors"][0]
    assert error == {
        "entry_path": "dataset/legacy.txt",
        "error_code": "archive_entry_decode_failed",
        "error_class": "archive_entry_decode_error",
        "encoding_attempts": ["utf-8-sig"],
        "failure_byte_offset": 7,
    }
    failed = next(
        item
        for item in inventory["small_text_entries"]
        if item["name"].endswith("legacy.txt")
    )
    assert failed["decode_status"] == "failed"
    assert failed["sha256"]
    assert failed["raw_path"].endswith(".raw")
    assert (tmp_path / "remote_inventory_entries").is_dir()


def test_remote_zip_inventory_marks_and_skips_macos_packaging_artifacts(tmp_path):
    body = _zip_bytes_with_macos_artifacts()
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store._range = lambda _url, start, end: body[start : end + 1]

    inventory = store._remote_zip_inventory(
        {
            "key": "dataset.zip",
            "bytes": len(body),
            "_url": "https://example.invalid/content",
        },
        1024,
    )

    assert inventory["entry_count"] == 5
    assert inventory["scientific_entry_count"] == 2
    assert inventory["packaging_artifact_count"] == 3
    assert inventory["entry_type_counts"] == {
        "txt": 1,
        "nii.gz": 1,
        "packaging_artifact": 3,
    }
    assert inventory["small_text_summary"] == {"selected": 1, "decoded": 1, "failed": 0}
    assert inventory["entry_errors"] == []
    assert {
        item["packaging_artifact_type"] for item in inventory["packaging_artifacts"]
    } == {
        "macos_ds_store",
        "apple_double",
    }


def test_range_rejects_full_response_before_reading_body():
    class Response:
        status_code = 200
        headers = {"Content-Length": "3199189599"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_content(self, _size):
            raise AssertionError("200 full payload must never be read")

    class Session:
        def get(self, *_args, **_kwargs):
            assert _kwargs["stream"] is True
            return Response()

    store = object.__new__(ZenodoArchiveStore)
    store.session = Session()

    with pytest.raises(ArchiveDatasetError) as captured:
        store._range("https://example.invalid/archive.zip", 100, 200)

    assert captured.value.error_code == "remote_range_not_supported"


def test_zenodo_redirect_to_deleted_record_preserves_resolution_evidence(tmp_path):
    redirect = requests.Response()
    redirect.status_code = 302
    redirect.url = "https://zenodo.org/api/records/20208546"
    redirect.headers["Location"] = "/api/records/20208547"
    response = requests.Response()
    response.status_code = 410
    response.url = "https://zenodo.org/api/records/20208547"
    response.history = [redirect]
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(
        {
            "status": 410,
            "message": "Record deleted",
            "tombstone": {
                "removal_date": "2026-05-16T09:34:34+00:00",
                "is_visible": True,
                "removal_reason": {"id": "test-record"},
                "deletion_policy": {"id": "grace-period-v1"},
            },
        }
    ).encode()

    class Session:
        def get(self, url, **kwargs):
            assert url == "https://zenodo.org/api/records/20208546"
            assert kwargs == {"timeout": 30}
            return response

    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.session = Session()

    with pytest.raises(ArchiveDatasetError) as captured:
        store._metadata("20208546")

    error = captured.value
    assert error.error_code == "archive_record_gone"
    assert error.error_class == "record_withdrawn"
    assert error.diagnostics["requested_record"] == "20208546"
    assert error.diagnostics["resolved_record"] == "20208547"
    assert error.diagnostics["record_resolution"] == [
        {
            "kind": "http_redirect",
            "status": 302,
            "from_record": "20208546",
            "to_record": "20208547",
        },
        {
            "kind": "terminal_response",
            "status": 410,
            "record": "20208547",
            "state": "record_deleted",
        },
    ]
    assert error.diagnostics["tombstone"]["removal_reason"] == "test-record"


def test_archive_cli_persists_structured_gone_terminal(monkeypatch, tmp_path, capsys):
    diagnostics = {
        "status": "record_gone",
        "requested_record": "20208546",
        "resolved_record": "20208547",
        "record_resolution": [{"kind": "http_redirect", "status": 302}],
        "readiness": {"manifest_ready": False, "payload_ready": False},
    }

    class Store:
        def __init__(self, output_dir):
            self.output_dir = output_dir

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def inspect(self, *_args, **_kwargs):
            raise ArchiveDatasetError(
                "Zenodo record 已删除",
                error_code="archive_record_gone",
                error_class="record_withdrawn",
                diagnostics=diagnostics,
            )

    monkeypatch.setattr("paperfetch.cli.datasets.ZenodoArchiveStore", Store)
    args = SimpleNamespace(
        output_dir=str(tmp_path),
        source="zenodo",
        record="20208546",
        archive_action="inspect",
        remote_inventory=True,
        max_small_text_bytes=1024,
        output_format="json",
    )

    assert run_archive_dataset(args) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["record"] == "20208546"
    assert output["requested_record"] == "20208546"
    assert output["resolved_record"] == "20208547"
    assert output["error_code"] == "archive_record_gone"
    assert output["error_class"] == "record_withdrawn"
    assert output["readiness"] == {
        "manifest_ready": False,
        "payload_ready": False,
    }
    persisted = json.loads(
        (tmp_path / "archive_dataset_record.json").read_text(encoding="utf-8")
    )
    assert persisted == output


def test_inspect_readiness_requires_checksum_verified_payload(monkeypatch, tmp_path):
    body = _zip_bytes()
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.session = None
    monkeypatch.setattr(
        store,
        "_metadata",
        lambda _record: (
            {
                "doi": "10.5281/zenodo.1",
                "metadata": {
                    "title": "Dataset",
                    "version": "1",
                    "license": {"id": "cc-by-4.0"},
                    "access_right": "open",
                },
            },
            [
                {
                    "key": "dataset.zip",
                    "bytes": len(body),
                    "checksum": {"algorithm": "md5", "value": "not-materialized"},
                    "_url": "https://example.invalid/content",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        store,
        "_remote_zip_inventory",
        lambda *_args: {"entry_count": 4},
    )

    result = store.inspect("1", remote_inventory=True)

    assert result["status"] == "manifest_ready"
    assert result["readiness"] == {"manifest_ready": True, "payload_ready": False}
    assert not (tmp_path / "dataset.zip").exists()
    assert (tmp_path / "archive_dataset_record.json").is_file()


def test_inspect_keeps_manifest_ready_with_entry_warning(monkeypatch, tmp_path):
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.session = None
    monkeypatch.setattr(
        store,
        "_metadata",
        lambda _record: (
            {"metadata": {"title": "Dataset", "version": "2.0"}},
            [
                {
                    "key": "dataset.zip",
                    "bytes": 123,
                    "checksum": {"algorithm": "md5", "value": "digest"},
                    "_url": "https://example.invalid/content",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        store,
        "_remote_zip_inventory",
        lambda *_args: {
            "entry_count": 3,
            "entry_errors": [
                {
                    "entry_path": "legacy.txt",
                    "error_code": "archive_entry_decode_failed",
                    "error_class": "archive_entry_decode_error",
                    "encoding_attempts": ["utf-8-sig"],
                }
            ],
        },
    )

    result = store.inspect("1", remote_inventory=True)

    assert result["status"] == "manifest_ready"
    assert result["readiness"] == {"manifest_ready": True, "payload_ready": False}
    assert result["warning_count"] == 1
    assert result["warnings"][0]["archive_key"] == "dataset.zip"
    assert result["warnings"][0]["error_code"] == "archive_entry_decode_failed"


def test_inspect_preserves_restricted_record_metadata_when_files_are_hidden(
    monkeypatch, tmp_path
):
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.session = None
    monkeypatch.setattr(
        store,
        "_metadata",
        lambda _record: (
            {
                "id": 17522191,
                "conceptrecid": "15621811",
                "doi": "10.5281/zenodo.17522191",
                "metadata": {
                    "title": "WAW-Glioma",
                    "version": "v2",
                    "access_right": "restricted",
                },
            },
            [],
        ),
    )

    result = store.inspect("17522191", remote_inventory=True)

    assert result["status"] == "access_restricted"
    assert result["record_exists"] is True
    assert result["title"] == "WAW-Glioma"
    assert result["version"] == "v2"
    assert result["access"] == "restricted"
    assert result["files"] == []
    assert result["files_visible"] is False
    assert result["error_code"] == "archive_access_restricted"
    assert result["error_class"] == "access_restricted"
    assert result["access_requirement"] == "authentication_required"
    assert result["readiness"] == {"manifest_ready": False, "payload_ready": False}
    persisted = json.loads(
        (tmp_path / "archive_dataset_record.json").read_text(encoding="utf-8")
    )
    assert persisted == result


def test_public_version_uses_unauthenticated_zenodo_page_when_api_omits_it():
    class Response:
        text = '<span class="label text-muted"> | Version v2</span>'

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        headers = {}

        def get(self, url, **kwargs):
            assert url == "https://zenodo.org/records/17522191"
            assert kwargs == {"timeout": 30}
            assert "Authorization" not in self.headers
            return Response()

    store = object.__new__(ZenodoArchiveStore)
    store.session = Session()

    assert store._public_version({"metadata": {}}, "17522191") == (
        "v2",
        "zenodo_public_page",
    )


def test_download_restricted_record_does_not_accept_hidden_file_selection(
    monkeypatch, tmp_path
):
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.session = None
    monkeypatch.setattr(
        store,
        "_metadata",
        lambda _record: ({"metadata": {"access_right": "restricted"}}, []),
    )

    with pytest.raises(ArchiveDatasetError) as captured:
        store.download("17522191", "hidden.zip", resume=True, verify_checksum=True)

    assert captured.value.error_code == "archive_access_restricted"
    assert captured.value.error_class == "access_restricted"


def test_inspect_then_download_preserves_matching_remote_inventory(
    monkeypatch, tmp_path
):
    metadata_body = _zip_bytes()
    metadata_digest = hashlib.md5(metadata_body).hexdigest()
    files = [
        {
            "key": "BraTioUS - Metadata.zip",
            "bytes": len(metadata_body),
            "checksum": {"algorithm": "md5", "value": metadata_digest},
            "_url": "https://example.invalid/metadata.zip",
        },
        {
            "key": "BraTioUS - ioUS.zip",
            "bytes": 9_999_999,
            "checksum": {"algorithm": "md5", "value": "a" * 32},
            "_url": "https://example.invalid/ious.zip",
        },
    ]
    payload = {
        "id": 16887363,
        "doi": "10.5281/zenodo.16887363",
        "metadata": {"title": "BraTioUS", "version": "1.0", "access_right": "open"},
    }

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def iter_content(_size):
            yield metadata_body

    class Session:
        def get(self, url, **_kwargs):
            assert url == "https://example.invalid/metadata.zip"
            return Response()

    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.lock_timeout_seconds = 0.2
    store.session = Session()
    monkeypatch.setattr(store, "_metadata", lambda _record: (payload, files))
    monkeypatch.setattr(
        store,
        "_remote_zip_inventory",
        lambda file, _limit: {
            "entry_count": 1669 if "ioUS" in file["key"] else 3,
            "manifest_summaries": [{"name": "manifest.json", "numTraining": 1669}],
            "entry_errors": (
                [
                    {
                        "error_code": "archive_entry_decode_failed",
                        "entry_path": "legacy.txt",
                    }
                ]
                if "Metadata" in file["key"]
                else []
            ),
        },
    )

    inspected = store.inspect("16887363", remote_inventory=True)
    downloaded = store.download(
        "16887363",
        "BraTioUS - Metadata.zip",
        resume=True,
        verify_checksum=True,
    )

    assert downloaded["remote_archives"] == inspected["remote_archives"]
    assert downloaded["warnings"] == inspected["warnings"]
    assert downloaded["remote_archives"]["BraTioUS - ioUS.zip"]["entry_count"] == 1669
    assert downloaded["readiness"] == {"manifest_ready": True, "payload_ready": False}
    assert downloaded["download"]["checksum"]["verified"] is True
    persisted = json.loads(
        (tmp_path / "archive_dataset_record.json").read_text(encoding="utf-8")
    )
    assert persisted == downloaded


def test_archive_download_resumes_after_stream_interruption(monkeypatch, tmp_path):
    body = b"deterministic-archive-body" * 100
    first = len(body) // 2
    digest = hashlib.md5(body).hexdigest()
    files = [
        {
            "key": "small.zip",
            "bytes": len(body),
            "checksum": {"algorithm": "md5", "value": digest},
            "_url": "https://example.invalid/small.zip",
        }
    ]
    payload = {"metadata": {"title": "small", "version": "1", "access_right": "open"}}

    class Response:
        def __init__(self, chunks, *, fail=False, status_code=200):
            self.chunks = chunks
            self.fail = fail
            self.status_code = status_code

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, _size):
            yield from self.chunks
            if self.fail:
                raise requests.exceptions.ChunkedEncodingError("incomplete")

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, _url, **kwargs):
            self.calls.append(kwargs.get("headers") or {})
            if len(self.calls) == 1:
                return Response([body[:first]], fail=True)
            return Response([body[first:]], status_code=206)

    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.lock_timeout_seconds = 0.2
    store.session = Session()
    monkeypatch.setattr(store, "_metadata", lambda _record: (payload, files))

    result = store.download("small", "small.zip", resume=True, verify_checksum=True)

    assert (tmp_path / "small.zip").read_bytes() == body
    assert result["download"]["stream_attempts"] == 2
    assert store.session.calls[1] == {"Range": f"bytes={first}-"}
    assert result["download"]["checksum"]["verified"] is True


def test_archive_cli_failure_preserves_matching_manifest(monkeypatch, tmp_path, capsys):
    existing = {
        "schema_version": "spc.archive-dataset-record.v1",
        "source": "zenodo",
        "record": "10117967",
        "status": "manifest_ready",
        "remote_archives": {"code.zip": {"entry_count": 6}},
        "warnings": [],
        "warning_count": 0,
        "readiness": {"manifest_ready": True, "payload_ready": False},
    }
    (tmp_path / "archive_dataset_record.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )

    class Store:
        def __init__(self, _output_dir):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, *_args, **_kwargs):
            raise requests.ConnectionError("interrupted")

    monkeypatch.setattr("paperfetch.cli.datasets.ZenodoArchiveStore", Store)
    args = SimpleNamespace(
        archive_action="download",
        source="zenodo",
        record="10117967",
        file="code.zip",
        resume=True,
        verify_checksum=True,
        output_dir=str(tmp_path),
        output_format="json",
    )

    assert run_archive_dataset(args) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["previous_status"] == "manifest_ready"
    assert result["remote_archives"] == existing["remote_archives"]
    assert result["readiness"] == {"manifest_ready": True, "payload_ready": False}


@pytest.mark.parametrize("conflict", ["record", "version", "checksum"])
def test_download_rejects_stale_remote_inventory_identity(
    monkeypatch, tmp_path, conflict
):
    body = _zip_bytes()
    digest = hashlib.md5(body).hexdigest()
    existing = {
        "schema_version": "spc.archive-dataset-record.v1",
        "source": "zenodo",
        "record": "16887363" if conflict != "record" else "other-record",
        "version": "1.0" if conflict != "version" else "0.9",
        "files": [
            {
                "key": "BraTioUS - Metadata.zip",
                "bytes": len(body),
                "checksum": {
                    "algorithm": "md5",
                    "value": digest if conflict != "checksum" else "0" * 32,
                },
            }
        ],
        "remote_archives": {"BraTioUS - Metadata.zip": {"entry_count": 3}},
    }
    (tmp_path / "archive_dataset_record.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )
    files = [
        {
            "key": "BraTioUS - Metadata.zip",
            "bytes": len(body),
            "checksum": {"algorithm": "md5", "value": digest},
            "_url": "https://example.invalid/metadata.zip",
        }
    ]
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.lock_timeout_seconds = 0.2
    store.session = None
    monkeypatch.setattr(
        store,
        "_metadata",
        lambda _record: ({"metadata": {"version": "1.0"}}, files),
    )

    with pytest.raises(ArchiveDatasetError) as captured:
        store.download(
            "16887363",
            "BraTioUS - Metadata.zip",
            resume=True,
            verify_checksum=True,
        )

    assert captured.value.error_code == "archive_state_identity_conflict"
    assert not (tmp_path / "BraTioUS - Metadata.zip").exists()
    assert (
        json.loads(
            (tmp_path / "archive_dataset_record.json").read_text(encoding="utf-8")
        )
        == existing
    )


def test_archive_record_lock_rejects_concurrent_same_directory(monkeypatch, tmp_path):
    store = object.__new__(ZenodoArchiveStore)
    store.output_dir = tmp_path
    store.lock_timeout_seconds = 0.05
    store.session = None
    monkeypatch.setattr(store, "_metadata", lambda _record: ({}, []))

    with _archive_record_lock(tmp_path, 0.2):
        with pytest.raises(ArchiveDatasetError) as captured:
            store.inspect("16887363")

    assert captured.value.error_code == "archive_state_busy"
    assert captured.value.error_class == "state_conflict"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            UnicodeDecodeError("utf-8", b"\xc7", 0, 1, "invalid"),
            ("archive_entry_decode_failed", "archive_entry_decode_error"),
        ),
        (OSError("disk"), ("archive_filesystem_operation_failed", "io_error")),
        (ValueError("format"), ("archive_dataset_invalid", "archive_format_error")),
        (
            requests.ConnectionError("offline"),
            ("archive_transport_failed", "network_error"),
        ),
    ],
)
def test_archive_cli_fallback_classification_is_not_all_network_error(exc, expected):
    assert _archive_failure(exc) == expected


def test_figshare_metadata_normalizes_public_file_checksum(tmp_path):
    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "id": 25246570,
                "title": "ACS supporting information",
                "doi": "10.1021/example.s001",
                "resource_doi": "10.1021/example",
                "version": 1,
                "license": {"name": "CC BY-NC 4.0"},
                "files": [
                    {
                        "name": "support.zip",
                        "size": 123,
                        "download_url": "https://ndownloader.figshare.com/files/1",
                        "supplied_md5": "a" * 32,
                    }
                ],
            }

    class Session:
        @staticmethod
        def get(*_args, **_kwargs):
            return Response()

    store = object.__new__(FigshareArchiveStore)
    store.output_dir = tmp_path
    store.session = Session()
    payload, files = store._metadata("25246570")

    assert payload["resource_doi"] == "10.1021/example"
    assert files == [
        {
            "key": "support.zip",
            "bytes": 123,
            "checksum": {"algorithm": "md5", "value": "a" * 32},
            "_url": "https://ndownloader.figshare.com/files/1",
        }
    ]


def test_archive_session_does_not_inherit_ambient_proxy(monkeypatch):
    from paperfetch.datasets.archive import _session

    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-proxy.invalid:7890")
    session = _session()
    try:
        assert session.trust_env is False
        assert session.proxies == {}
    finally:
        session.close()


def test_zenodo_primary_session_uses_explicit_archive_proxy(monkeypatch, tmp_path):
    captured = []

    class Session:
        def close(self):
            return None

    monkeypatch.setenv("ARCHIVE_PROXY_MODE", "proxy")
    monkeypatch.setenv("ARCHIVE_PROXY", "http://archive-proxy.invalid:7890")
    monkeypatch.setattr(
        "paperfetch.datasets.archive._session",
        lambda proxy=None: captured.append(proxy) or Session(),
    )

    store = ZenodoArchiveStore(tmp_path)
    try:
        assert captured == ["http://archive-proxy.invalid:7890"]
        assert store._transport == {
            "route": "archive_proxy",
            "trust_env": False,
            "proxy_configured": True,
        }
    finally:
        store.close()


def test_archive_proxy_mode_requires_dedicated_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHIVE_PROXY_MODE", "proxy")
    monkeypatch.delenv("ARCHIVE_PROXY", raising=False)

    with pytest.raises(ArchiveDatasetError) as captured:
        ZenodoArchiveStore(tmp_path)

    assert captured.value.error_code == "archive_proxy_not_configured"


def test_figshare_403_uses_explicit_archive_proxy_fallback(monkeypatch, tmp_path):
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

        def json(self):
            return self._payload

    class Session:
        def __init__(self, response):
            self.response = response
            self.closed = False

        def get(self, *_args, **_kwargs):
            return self.response

        def close(self):
            self.closed = True

    payload = {
        "id": 25246570,
        "title": "ACS supporting information",
        "version": 1,
        "license": {"name": "CC BY-NC 4.0"},
        "files": [
            {
                "name": "support.zip",
                "size": 123,
                "download_url": "https://ndownloader.figshare.com/files/1",
                "supplied_md5": "a" * 32,
            }
        ],
    }
    direct = Session(Response(403))
    fallback = Session(Response(200, payload))
    store = object.__new__(FigshareArchiveStore)
    store.output_dir = tmp_path
    store.session = direct
    store._transport = {
        "route": "direct",
        "trust_env": False,
        "proxy_configured": False,
    }
    monkeypatch.setenv("ARCHIVE_PROXY_MODE", "proxy")
    monkeypatch.setenv("ARCHIVE_PROXY", "http://archive-proxy.invalid:7890")
    monkeypatch.setattr(
        "paperfetch.datasets.archive._session", lambda _proxy=None: fallback
    )

    _payload, files = store._metadata("25246570")

    assert files[0]["key"] == "support.zip"
    assert store.session is fallback
    assert direct.closed is True
    assert store._transport["route"] == "archive_proxy_fallback"
    assert store._transport_attempts == [
        {"route": "direct", "status": 403},
        {
            "route": "archive_proxy_fallback",
            "status": 200,
            "trigger": "figshare_rest_http_403",
        },
    ]


def test_figshare_403_without_explicit_fallback_is_access_blocked(
    monkeypatch, tmp_path
):
    class Response:
        status_code = 403

    class Session:
        @staticmethod
        def get(*_args, **_kwargs):
            return Response()

    store = object.__new__(FigshareArchiveStore)
    store.output_dir = tmp_path
    store.session = Session()
    store._transport = {
        "route": "direct",
        "trust_env": False,
        "proxy_configured": False,
    }
    monkeypatch.delenv("ARCHIVE_PROXY_MODE", raising=False)
    monkeypatch.delenv("ARCHIVE_PROXY", raising=False)
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)

    with pytest.raises(ArchiveDatasetError) as captured:
        store._metadata("25246570")

    assert captured.value.error_code == "archive_repository_access_forbidden"
    assert captured.value.error_class == "access_blocked"
    assert captured.value.diagnostics["transport_attempts"] == [
        {"route": "direct", "status": 403}
    ]


def test_archive_capabilities_and_unsupported_source_are_structured(tmp_path, capsys):
    capabilities = SimpleNamespace(
        archive_action="capabilities",
        output_format="json",
    )
    assert run_archive_dataset(capabilities) == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload["supported_sources"]) == ["figshare", "zenodo"]
    assert (
        payload["unsupported_sources"]["iprox"] == "repository_adapter_not_implemented"
    )

    unsupported = SimpleNamespace(
        archive_action="inspect",
        source="iprox",
        record="PXD047852",
        output_dir=str(tmp_path),
        remote_inventory=False,
        max_small_text_bytes=1024,
        output_format="json",
    )
    assert run_archive_dataset(unsupported) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["error_code"] == "archive_source_capability_unsupported"
    assert failure["error_class"] == "capability_unsupported"
    assert failure["requested_source"] == "iprox"
