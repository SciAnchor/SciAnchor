from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
import requests

from paperfetch.datasets.dryad import (
    DryadAuthenticationRequired,
    DryadDataError,
    DryadDatasetStore,
    DryadLargeDownloadBlocked,
    DryadRemoteFile,
    _download_browser_http_file,
    _wait_for_browser_download,
    normalize_dryad_doi,
)


class FakeResponse:
    def __init__(self, *, payload=None, body=b"", status=200, headers=None):
        self.payload = payload
        self.content = body if body else json.dumps(payload or {}).encode("utf-8")
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        return self.payload if self.payload is not None else json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def iter_content(self, chunk_size=1024 * 1024):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self):
        return None


class RoutingSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        return None


class OAuthRoutingSession(RoutingSession):
    def __init__(self, responses, post_responses):
        super().__init__(responses)
        self.post_responses = list(post_responses)
        self.post_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


def dataset_payload():
    return {
        "identifier": "doi:10.5061/dryad.test123",
        "title": "Test Dryad data",
        "publicationDate": "2026-01-01",
        "versionStatus": "submitted",
        "_links": {"stash:version": {"href": "/api/v2/versions/42"}},
    }


def files_payload(content=b"hello"):
    return {
        "count": 1,
        "_embedded": {
            "stash:files": [
                {
                    "path": "data.txt",
                    "size": len(content),
                    "digest": hashlib.sha256(content).hexdigest(),
                    "_links": {"stash:download": {"href": "/api/v2/files/99/download"}},
                }
            ]
        },
        "_links": {},
    }


def remote(content=b"hello"):
    return DryadRemoteFile(
        file_id=99,
        path="data.txt",
        size_bytes=len(content),
        digest=hashlib.sha256(content).hexdigest(),
        api_download_url="https://datadryad.org/api/v2/files/99/download",
        public_download_url="https://datadryad.org/downloads/file_stream/99",
    )


def plan_for(content=b"hello", *, blocked=False):
    item = remote(content)
    return {
        "schema_version": "spc.dryad.plan.v1",
        "doi": "10.5061/dryad.test123",
        "title": "Test Dryad data",
        "publication_date": "2026-01-01",
        "version_status": "submitted",
        "version_id": 42,
        "license": None,
        "files": [item.to_dict()],
        "totals": {"files": 1, "known_bytes": len(content)},
        "size_gate": {
            "max_bytes": 1,
            "blocked": blocked,
            "approval_flag": "--allow-large",
        },
    }


def test_normalize_dryad_doi_accepts_common_forms():
    assert normalize_dryad_doi("doi:10.5061/dryad.Test123") == "10.5061/dryad.test123"
    assert (
        normalize_dryad_doi("https://doi.org/10.5061/dryad.Test123")
        == "10.5061/dryad.test123"
    )
    with pytest.raises(DryadDataError):
        normalize_dryad_doi("10.1234/not-dryad")


def test_discover_reads_public_metadata_and_digests(tmp_path):
    content = b"hello"
    session = RoutingSession(
        [
            FakeResponse(payload=dataset_payload()),
            FakeResponse(payload=files_payload(content)),
        ]
    )
    store = DryadDatasetStore(tmp_path, session=session)

    metadata, files = store.discover("10.5061/dryad.test123")

    assert metadata["version_id"] == 42
    assert metadata["doi"] == "10.5061/dryad.test123"
    assert files == [remote(content)]
    assert "%3A10.5061%2Fdryad.test123" in session.calls[0][0]


def test_discover_rejects_path_traversal(tmp_path):
    payload = files_payload()
    payload["_embedded"]["stash:files"][0]["path"] = "../secret.txt"
    store = DryadDatasetStore(
        tmp_path,
        session=RoutingSession(
            [FakeResponse(payload=dataset_payload()), FakeResponse(payload=payload)]
        ),
    )
    with pytest.raises(DryadDataError) as raised:
        store.discover("10.5061/dryad.test123")
    assert raised.value.error_code == "unsafe_dataset_path"


def test_plan_filters_files_and_blocks_large_download(tmp_path, monkeypatch):
    store = DryadDatasetStore(tmp_path, session=RoutingSession([]), max_download_gb=0)
    monkeypatch.setattr(
        store,
        "discover",
        lambda _doi: (
            {
                "doi": "10.5061/dryad.test123",
                "title": "x",
                "publication_date": None,
                "version_status": None,
                "version_id": 42,
                "license": None,
            },
            [remote()],
        ),
    )
    plan = store.plan("10.5061/dryad.test123", ["data.txt"])
    assert plan["size_gate"]["blocked"] is True
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(blocked=True))
    with pytest.raises(DryadLargeDownloadBlocked):
        store.download("10.5061/dryad.test123", route="api")


def test_api_download_resumes_and_never_reports_token(tmp_path, monkeypatch):
    content = b"abcdefghij"
    response = FakeResponse(
        body=content[4:],
        status=206,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Range": "bytes 4-9/10",
        },
    )
    session = RoutingSession([response])
    store = DryadDatasetStore(tmp_path, token="secret-token", session=session)
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(content))
    directory = tmp_path / "dryad.test123"
    directory.mkdir()
    (directory / ".data.txt.part").write_bytes(content[:4])

    result = store.download("10.5061/dryad.test123", route="api")

    assert result["status"] == "complete"
    assert (directory / "data.txt").read_bytes() == content
    assert session.calls[0][1]["headers"]["Range"] == "bytes=4-"
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer secret-token"
    state_text = (directory / "download_state.json").read_text()
    archive_text = (directory / "archive.json").read_text()
    report_text = Path(result["acquisition_report_path"]).read_text(encoding="utf-8")
    assert "secret-token" not in state_text + archive_text + report_text
    assert json.loads(archive_text)["files"][0]["resumed_from"] == 4
    report = json.loads(report_text)
    assert report["status"] == "complete"
    assert report["attempts"] == [{"route": "api", "status": "complete"}]
    assert report["spc_git_sha"]

    reused = store.download("10.5061/dryad.test123", route="api")
    assert reused["status"] == "complete"
    assert len(session.calls) == 1
    reused_report = json.loads(
        Path(reused["acquisition_report_path"]).read_text(encoding="utf-8")
    )
    assert reused_report["files"][0]["reused"] is True
    assert reused_report["coordination"]["queued"] is False


def test_api_route_requires_rotated_token(tmp_path, monkeypatch):
    monkeypatch.delenv("DRYAD_CLIENT_ID", raising=False)
    monkeypatch.delenv("DRYAD_CLIENT_SECRET", raising=False)
    store = DryadDatasetStore(tmp_path, token="", session=RoutingSession([]))
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for())
    with pytest.raises(DryadAuthenticationRequired, match="DRYAD_API_TOKEN"):
        store.download("10.5061/dryad.test123", route="api")


def test_api_route_uses_client_credentials_when_token_is_missing(tmp_path, monkeypatch):
    content = b"hello"
    session = OAuthRoutingSession(
        [FakeResponse(body=content, headers={"Content-Type": "text/plain"})],
        [FakeResponse(payload={"access_token": "fresh-token", "token_type": "Bearer"})],
    )
    store = DryadDatasetStore(
        tmp_path,
        token="",
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(content))

    result = store.download("10.5061/dryad.test123", route="auto")

    assert result["route"] == "api"
    assert session.post_calls[0][0].endswith("/oauth/token")
    assert session.post_calls[0][1]["data"] == {"grant_type": "client_credentials"}
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer fresh-token"
    reports = (tmp_path / "dryad.test123" / "archive.json").read_text()
    assert "fresh-token" not in reports
    assert "client-secret" not in reports


def test_api_route_refreshes_expired_token_once(tmp_path, monkeypatch):
    content = b"hello"
    session = OAuthRoutingSession(
        [
            FakeResponse(status=401),
            FakeResponse(body=content, headers={"Content-Type": "text/plain"}),
        ],
        [FakeResponse(payload={"access_token": "refreshed-token"})],
    )
    store = DryadDatasetStore(
        tmp_path,
        token="expired-token",
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(content))

    result = store.download("10.5061/dryad.test123", route="api")

    assert result["status"] == "complete"
    assert len(session.post_calls) == 1
    assert session.calls[1][1]["headers"]["Authorization"] == "Bearer refreshed-token"


def test_auto_route_falls_back_to_browser_when_token_is_rejected(tmp_path, monkeypatch):
    content = b"hello"
    acquired_sources = []

    def browser_downloader(**kwargs):
        item = kwargs["files"][0]
        target = kwargs["dataset_dir"] / item.path
        target.write_bytes(content)
        return [
            {
                "path": item.path,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "format_status": "utf8_ok",
                "route": "browser",
                "status": "complete",
            }
        ]

    store = DryadDatasetStore(
        tmp_path,
        token="expired-token",
        session=RoutingSession([]),
        browser_downloader=browser_downloader,
    )
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(content))
    monkeypatch.setattr(
        store,
        "_download_api_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DryadAuthenticationRequired("expired")
        ),
    )

    @contextmanager
    def acquire_source(source):
        acquired_sources.append(source)
        yield {"source": source}

    monkeypatch.setattr(store.coordinator, "acquire_source", acquire_source)

    result = store.download("10.5061/dryad.test123", route="auto")

    assert result["status"] == "complete"
    assert result["route"] == "browser"
    assert acquired_sources == ["browser-global"]
    archive = json.loads((tmp_path / "dryad.test123" / "archive.json").read_text())
    assert archive["route"] == "browser"


def test_api_resume_rejects_wrong_content_range(tmp_path, monkeypatch):
    content = b"abcdefghij"
    session = RoutingSession(
        [
            FakeResponse(
                body=content[4:],
                status=206,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Range": "bytes 5-9/10",
                },
            )
        ]
    )
    store = DryadDatasetStore(tmp_path, token="secret-token", session=session)
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(content))
    directory = tmp_path / "dryad.test123"
    directory.mkdir()
    (directory / ".data.txt.part").write_bytes(content[:4])

    with pytest.raises(DryadDataError) as raised:
        store.download("10.5061/dryad.test123", route="api")
    assert raised.value.error_code == "resume_range_mismatch"
    assert raised.value.error_class == "integrity_mismatch"


def test_browser_route_is_injectable_and_inspect_detects_corruption(
    tmp_path, monkeypatch
):
    content = b"hello"

    def browser_downloader(**kwargs):
        item = kwargs["files"][0]
        target = kwargs["dataset_dir"] / item.path
        target.write_bytes(content)
        return [
            {
                "path": item.path,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "format_status": "utf8_ok",
                "route": "browser",
                "status": "complete",
                "elapsed_ms": 10,
            }
        ]

    store = DryadDatasetStore(
        tmp_path,
        session=RoutingSession([]),
        browser_downloader=browser_downloader,
    )
    monkeypatch.setattr(store, "plan", lambda *_args, **_kwargs: plan_for(content))
    result = store.download("10.5061/dryad.test123", route="browser")
    assert result["status"] == "complete"
    assert store.inspect("10.5061/dryad.test123", verify=True)["status"] == "complete"

    (tmp_path / "dryad.test123" / "data.txt").write_bytes(b"bad")
    invalid = store.inspect("10.5061/dryad.test123", verify=True)
    assert invalid["status"] == "invalid"
    assert invalid["files"]["failed"] == 1


def test_browser_download_wait_pumps_playwright_events():
    import queue

    downloads = queue.Queue()

    class Page:
        calls = 0

        def wait_for_timeout(self, _milliseconds):
            self.calls += 1
            downloads.put("download-event")

    page = Page()
    assert _wait_for_browser_download(downloads, page, 1) == "download-event"
    assert page.calls == 1


def test_browser_http_stream_resumes_and_verifies(tmp_path):
    content = b"abcdefghij"
    response = FakeResponse(
        body=content[4:],
        status=206,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Range": "bytes 4-9/10",
        },
    )
    session = RoutingSession([response])
    directory = tmp_path / "dataset"
    directory.mkdir()
    (directory / ".data.txt.part").write_bytes(content[:4])

    result = _download_browser_http_file(
        session,
        remote(content),
        directory,
        force=False,
        timeout_seconds=30,
    )

    assert result["route"] == "browser_http"
    assert result["resumed_from"] == 4
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    assert (directory / "data.txt").read_bytes() == content
    assert session.calls[0][1]["headers"]["Range"] == "bytes=4-"
