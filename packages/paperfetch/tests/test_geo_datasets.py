from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
import requests

from paperfetch.cli import run
from paperfetch.datasets.geo import (
    GeoDataError,
    GeoDatasetLock,
    GeoDatasetStore,
    GeoFilesystemError,
    GeoLargeDownloadBlocked,
    GeoRemoteFile,
    _new_http_session,
    geo_ftp_prefix,
    normalize_gse_id,
)


class FakeResponse:
    def __init__(self, *, status=200, body=b"", text=None, headers=None):
        self.status_code = status
        self.body = body
        self.text = text if text is not None else body.decode("utf-8", errors="replace")
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def iter_content(self, chunk_size=1024 * 1024):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class RoutingSession:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)

    def close(self):
        return None


def test_gse_accession_and_ftp_prefix():
    assert normalize_gse_id(" gse123456 ") == "GSE123456"
    assert geo_ftp_prefix("GSE1") == "GSEnnn"
    assert geo_ftp_prefix("GSE1234") == "GSE1nnn"
    assert geo_ftp_prefix("GSE123456") == "GSE123nnn"
    with pytest.raises(GeoDataError):
        normalize_gse_id("SRP123")


def test_geo_session_maps_download_proxy(monkeypatch):
    monkeypatch.setenv("SPC_GEO_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("SPC_GEO_PROXY_MODE", "proxy")

    session = _new_http_session()
    try:
        assert session.proxies == {
            "http": "http://127.0.0.1:7897",
            "https": "http://127.0.0.1:7897",
        }
        assert session.trust_env is False
        assert session.headers["Accept-Encoding"] == "identity"
    finally:
        session.close()


def test_geo_session_direct_mode_disables_spc_proxy(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7898")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7899")
    monkeypatch.setenv("SPC_GEO_PROXY_MODE", "direct")

    session = _new_http_session()
    try:
        assert session.proxies == {}
        assert session.trust_env is False
    finally:
        session.close()


def test_discover_lists_soft_matrix_and_supplementary(tmp_path):
    listing = """
    <html><table>
      <tr><td><a href="GSE123-GPL1_series_matrix.txt.gz">matrix</a></td><td>2026-01-01</td><td>2.0M</td></tr>
      <tr><td><a href="../">Parent</a></td><td>-</td><td>-</td></tr>
    </table><a href="https://example.org/index.html">external policy</a></html>
    """
    supplementary = """
    <html><table>
      <tr><td><a href="GSE123_RAW.tar">raw</a></td><td>2026-01-01</td><td>3.0G</td></tr>
    </table></html>
    """

    def handler(method, url, kwargs):
        if method == "HEAD":
            return FakeResponse(headers={"Content-Length": "100"})
        if "/matrix/" in url:
            return FakeResponse(text=listing)
        if "/suppl/" in url:
            return FakeResponse(text=supplementary)
        raise AssertionError((method, url))

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    files = store.discover("GSE123")

    assert [(item.kind, item.filename) for item in files] == [
        ("series_matrix", "GSE123-GPL1_series_matrix.txt.gz"),
        ("soft", "GSE123_family.soft.gz"),
        ("supplementary", "GSE123_RAW.tar"),
    ]
    assert (
        next(item for item in files if item.kind == "series_matrix").size_bytes
        == 2 * 1024**2
    )
    assert (
        next(item for item in files if item.kind == "supplementary").size_bytes
        == 3 * 1024**3
    )


def test_discover_parses_apache_pre_listing_size(tmp_path):
    listing = """
    <pre>Name Last modified Size
    <a href="GSE123_series_matrix.txt.gz">GSE123_series_matrix.txt.gz</a> 2026-07-04 18:57 73K
    </pre>
    <a href="https://www.hhs.gov/policy/index.html">Policy</a>
    """

    def handler(method, url, kwargs):
        if method == "HEAD":
            return FakeResponse(headers={"Content-Length": "100"})
        if "/matrix/" in url:
            return FakeResponse(text=listing)
        if "/suppl/" in url:
            return FakeResponse(status=404)
        raise AssertionError((method, url))

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    files = store.discover("GSE123")

    matrix = next(item for item in files if item.kind == "series_matrix")
    assert matrix.size_bytes == 73 * 1024
    assert all(item.filename != "index.html" for item in files)


def test_probe_falls_back_to_streaming_get_when_head_is_forbidden(tmp_path):
    calls = []

    def handler(method, url, kwargs):
        calls.append((method, kwargs))
        if method == "HEAD":
            return FakeResponse(status=403)
        return FakeResponse(status=200, headers={"Content-Length": "123"})

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    size, _, _ = store._probe("https://example/file")

    assert size == 123
    assert calls == [
        ("HEAD", {"allow_redirects": True, "timeout": (15.0, 300.0)}),
        ("GET", {"stream": True, "allow_redirects": True, "timeout": (15.0, 300.0)}),
    ]


def test_plan_file_filter_and_size_gate(tmp_path, monkeypatch):
    store = GeoDatasetStore(
        tmp_path, session=RoutingSession(lambda *_: None), max_download_gb=1
    )
    monkeypatch.setattr(
        store,
        "discover",
        lambda _gse: [
            GeoRemoteFile(
                "GSE123_family.soft.gz",
                "soft",
                "https://example/soft",
                100,
                size_exact=True,
            ),
            GeoRemoteFile(
                "GSE123_RAW.tar",
                "supplementary",
                "https://example/raw",
                2 * 1024**3,
                size_exact=True,
            ),
        ],
    )

    plan = store.plan("GSE123")
    assert plan["size_gate"]["blocked"] is True
    assert plan["size_gate"]["approval_flag"] == "--allow-large"

    selected = store.plan("GSE123", ["GSE123_family.soft.gz"])
    assert selected["size_gate"]["blocked"] is False
    assert selected["totals"]["files"] == 1

    with pytest.raises(GeoDataError):
        store.plan("GSE123", ["missing.txt"])
    with pytest.raises(GeoLargeDownloadBlocked):
        store.download("GSE123")


def test_plan_expands_filelist_entries_into_selectable_catalog(tmp_path, monkeypatch):
    manifest_url = (
        "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE216nnn/GSE216050/suppl/filelist.txt"
    )
    manifest = "\n".join(
        [
            "Type\tName\tModified\tSize\tType",
            "File\tGSM6657904_data1.txt.gz\t10/18/2022 19:02:15\t42510361\tTXT",
            "File\tGSM6657905_data2.txt.gz\t10/18/2022 19:02:15\t39123456\tTXT",
        ]
    )

    def handler(method, url, kwargs):
        assert method == "GET"
        assert url == manifest_url
        return FakeResponse(status=200, text=manifest)

    store = GeoDatasetStore(
        tmp_path, session=RoutingSession(handler), max_download_gb=1
    )
    monkeypatch.setattr(
        store,
        "discover",
        lambda _gse: [
            GeoRemoteFile(
                "filelist.txt",
                "supplementary",
                manifest_url,
                466,
                size_exact=True,
            ),
            GeoRemoteFile(
                "GSE216050_RAW.tar",
                "supplementary",
                "https://example/GSE216050_RAW.tar",
                279_111_680,
                size_exact=True,
            ),
        ],
    )

    plan = store.plan("GSE216050", ["GSM6657904_data1.txt.gz"])

    assert plan["totals"]["files"] == 1
    assert plan["totals"]["known_bytes"] == 42_510_361
    assert plan["discovery"]["filelist"]["status"] == "expanded"
    assert plan["discovery"]["filelist"]["entries"] == 2
    selected = plan["files"][0]
    assert selected["discovery_source"] == "filelist"
    assert selected["source_manifest_url"] == manifest_url
    assert selected["url"].endswith(
        "/geo/samples/GSM6657nnn/GSM6657904/suppl/GSM6657904_data1.txt.gz"
    )


def test_plan_reports_filelist_expansion_failure_as_selection_error(
    tmp_path, monkeypatch
):
    manifest_url = "https://example/filelist.txt"
    store = GeoDatasetStore(
        tmp_path,
        session=RoutingSession(
            lambda method, url, kwargs: (_ for _ in ()).throw(
                requests.ConnectionError("manifest unavailable")
            )
        ),
    )
    monkeypatch.setattr(
        store,
        "discover",
        lambda _gse: [
            GeoRemoteFile(
                "filelist.txt", "supplementary", manifest_url, 10, size_exact=True
            )
        ],
    )

    with pytest.raises(GeoDataError) as raised:
        store.plan("GSE123", ["GSM1001_data.txt.gz"])

    assert raised.value.error_code == "filelist_entries_not_expanded"
    assert raised.value.error_class == "source_manifest_error"


def test_plan_reports_unknown_selection_without_filelist_as_selection_error(
    tmp_path, monkeypatch
):
    store = GeoDatasetStore(tmp_path, session=RoutingSession(lambda *_: None))
    monkeypatch.setattr(store, "discover", lambda _gse: [])

    with pytest.raises(GeoDataError) as raised:
        store.plan("GSE123", ["missing.txt"])

    assert raised.value.error_code == "selection_resolution_failed"
    assert raised.value.error_class == "selection_error"


def test_plan_blocks_unknown_remote_size(tmp_path, monkeypatch):
    store = GeoDatasetStore(
        tmp_path, session=RoutingSession(lambda *_: None), max_download_gb=1
    )
    remote = GeoRemoteFile(
        "GSE123_RAW.tar",
        "supplementary",
        "https://example/raw",
        size_bytes=None,
        size_exact=False,
    )
    monkeypatch.setattr(store, "discover", lambda _gse: [remote])
    monkeypatch.setattr(store, "_probe", lambda _url: (None, None, None))

    plan = store.plan("GSE123")
    assert plan["size_gate"]["blocked"] is True
    assert plan["size_gate"]["reasons"] == ["unknown_remote_size"]
    with pytest.raises(GeoLargeDownloadBlocked) as raised:
        store.download("GSE123")
    assert raised.value.error_code == "large_download_approval_required"
    assert "远端文件大小未知" in str(raised.value)


def test_plan_blocks_approximate_size_when_exact_probe_fails(tmp_path, monkeypatch):
    store = GeoDatasetStore(
        tmp_path, session=RoutingSession(lambda *_: None), max_download_gb=1
    )
    remote = GeoRemoteFile(
        "GSE123_RAW.tar",
        "supplementary",
        "https://example/raw",
        size_bytes=512,
        size_exact=False,
    )
    monkeypatch.setattr(store, "discover", lambda _gse: [remote])
    monkeypatch.setattr(
        store, "_probe", lambda _url: (_ for _ in ()).throw(requests.ConnectionError())
    )

    plan = store.plan("GSE123")
    assert plan["totals"]["known_bytes"] == 512
    assert plan["totals"]["unknown_size_files"] == ["GSE123_RAW.tar"]
    assert plan["size_gate"]["blocked"] is True


def test_discover_does_not_hide_directory_network_failure(tmp_path):
    def handler(method, url, kwargs):
        if method == "HEAD":
            return FakeResponse(headers={"Content-Length": "100"})
        if "/matrix/" in url:
            raise requests.ConnectionError("offline")
        raise AssertionError((method, url))

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    with pytest.raises(GeoDataError) as raised:
        store.discover("GSE123")
    assert raised.value.error_code == "geo_file_listing_failed"
    assert raised.value.error_class == "network_error"


def test_download_builds_state_archive_and_verifies(tmp_path, monkeypatch):
    soft_text = "\n".join(
        [
            "^SERIES = GSE123",
            "!Series_title = Test single-cell series",
            "!Series_summary = First sentence.",
            "!Series_summary = Second sentence.",
            "!Series_overall_design = Public cohort",
            "!Series_type = Expression profiling by high throughput sequencing",
            "!Series_pubmed_id = 12345678",
            "^SAMPLE = GSM1001",
            "!Sample_title = Tumor sample",
            "!Sample_source_name_ch1 = pancreas",
            "!Sample_organism_ch1 = Homo sapiens",
            "!Sample_characteristics_ch1 = disease: pancreatic cancer",
            "!Sample_library_strategy = RNA-Seq",
            "!Sample_relation = SRA: SRR9001",
            "!Sample_relation = BioProject: PRJNA420",
            "",
        ]
    )
    payload = gzip.compress(soft_text.encode("utf-8"))

    def handler(method, url, kwargs):
        assert method == "GET"
        return FakeResponse(
            status=200, body=payload, headers={"Content-Length": str(len(payload))}
        )

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    remote = GeoRemoteFile(
        "GSE123_family.soft.gz",
        "soft",
        "https://example/GSE123_family.soft.gz",
        len(payload),
        size_exact=True,
    )
    monkeypatch.setattr(store, "discover", lambda _gse: [remote])

    result = store.download("GSE123")
    assert result["status"] == "complete"
    assert result["sample_count"] == 1
    assert result["linked_accessions"]["sra_runs"] == ["SRR9001"]
    assert result["linked_accessions"]["bioprojects"] == ["PRJNA420"]
    report = json.loads(
        Path(result["acquisition_report_path"]).read_text(encoding="utf-8")
    )
    assert report["status"] == "complete"
    assert report["route"]["resolved_route"] == "direct"
    assert report["spc_git_sha"]

    state = json.loads((tmp_path / "GSE123" / "download_state.json").read_text())
    archive = json.loads((tmp_path / "GSE123" / "archive.json").read_text())
    assert state["files"][remote.filename]["sha256"]
    assert archive["metadata"]["samples"][0]["gsm_id"] == "GSM1001"
    assert (
        archive["metadata"]["series"]["summary"] == "First sentence. Second sentence."
    )

    reused = store.download("GSE123")
    assert reused["status"] == "complete"
    assert reused["files"]["complete"] == 1
    reused_report = json.loads(
        Path(reused["acquisition_report_path"]).read_text(encoding="utf-8")
    )
    assert reused_report["files"][0]["reused"] is True
    assert reused_report["coordination"]["queued"] is False

    verified = store.inspect("GSE123", verify=True)
    assert verified["status"] == "complete"

    downloaded = tmp_path / "GSE123" / remote.filename
    downloaded.write_bytes(b"corrupt")
    invalid = store.inspect("GSE123", verify=True)
    assert invalid["status"] == "invalid"
    assert invalid["files"]["failed"] == 1

    downloaded.write_bytes(payload)
    recovered = store.inspect("GSE123", verify=True)
    assert recovered["status"] == "complete"
    assert recovered["last_error"] is None


def test_download_resumes_partial_file(tmp_path):
    content = b"abcdefghij"
    directory = tmp_path / "GSE123"
    directory.mkdir()
    partial = directory / ".matrix.txt.part"
    partial.write_bytes(content[:4])

    def handler(method, url, kwargs):
        assert method == "GET"
        assert kwargs["headers"] == {"Range": "bytes=4-"}
        return FakeResponse(
            status=206, body=content[4:], headers={"Content-Length": "6"}
        )

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    result = store._download_file(
        GeoRemoteFile(
            "matrix.txt",
            "series_matrix",
            "https://example/matrix",
            len(content),
            size_exact=True,
        ),
        directory,
        force=False,
    )

    assert result["status"] == "complete"
    assert (directory / "matrix.txt").read_bytes() == content
    assert not partial.exists()


def test_download_resume_uses_if_range_validator(tmp_path):
    content = b"abcdefghij"
    directory = tmp_path / "GSE123"
    directory.mkdir()
    (directory / ".matrix.txt.part").write_bytes(content[:4])

    def handler(method, url, kwargs):
        assert kwargs["headers"] == {"Range": "bytes=4-", "If-Range": '"etag-1"'}
        return FakeResponse(
            status=206, body=content[4:], headers={"Content-Length": "6"}
        )

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    result = store._download_file(
        GeoRemoteFile(
            "matrix.txt",
            "series_matrix",
            "https://example/matrix",
            len(content),
            etag='"etag-1"',
            size_exact=True,
        ),
        directory,
        force=False,
    )

    assert result["status"] == "complete"
    assert (directory / "matrix.txt").read_bytes() == content


def test_download_restarts_when_server_rejects_range(tmp_path):
    content = b"abcdefghij"
    directory = tmp_path / "GSE123"
    directory.mkdir()
    (directory / ".matrix.txt.part").write_bytes(content[:4])
    calls = []

    def handler(method, url, kwargs):
        calls.append(kwargs["headers"])
        if len(calls) == 1:
            return FakeResponse(status=403)
        return FakeResponse(
            status=200, body=content, headers={"Content-Length": str(len(content))}
        )

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    result = store._download_file(
        GeoRemoteFile(
            "matrix.txt",
            "series_matrix",
            "https://example/matrix",
            len(content),
            size_exact=True,
        ),
        directory,
        force=False,
    )

    assert calls == [{"Range": "bytes=4-"}, {}]
    assert result["status"] == "complete"
    assert (directory / "matrix.txt").read_bytes() == content


def test_download_stops_when_server_exceeds_declared_size(tmp_path):
    directory = tmp_path / "GSE123"
    directory.mkdir()

    def handler(method, url, kwargs):
        assert method == "GET"
        return FakeResponse(
            status=200, body=b"too much", headers={"Content-Length": "3"}
        )

    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    with pytest.raises(GeoDataError) as raised:
        store._download_file(
            GeoRemoteFile(
                "matrix.txt",
                "series_matrix",
                "https://example/matrix",
                3,
                size_exact=True,
            ),
            directory,
            force=False,
        )
    assert raised.value.error_code == "download_size_overrun"

    assert not (directory / "matrix.txt").exists()
    assert (directory / ".matrix.txt.part").stat().st_mode & 0o020


def test_download_retries_inside_one_invocation_and_resumes(tmp_path, monkeypatch):
    content = b"abcdefghij"
    directory = tmp_path / "GSE123"
    directory.mkdir()
    calls = []

    class StalledResponse(FakeResponse):
        def iter_content(self, chunk_size=1024 * 1024):
            yield content[:4]
            raise requests.ReadTimeout("simulated stall")

    def handler(method, url, kwargs):
        calls.append(kwargs["headers"])
        if len(calls) == 1:
            return StalledResponse(
                status=200, headers={"Content-Length": str(len(content))}
            )
        return FakeResponse(
            status=206,
            body=content[4:],
            headers={"Content-Length": "6", "Content-Range": "bytes 4-9/10"},
        )

    monkeypatch.setattr("paperfetch.datasets.geo.time.sleep", lambda _seconds: None)
    store = GeoDatasetStore(tmp_path, session=RoutingSession(handler))
    store.progress_interval_bytes = 1
    snapshots = []
    result = store._download_file(
        GeoRemoteFile(
            "matrix.txt", "series_matrix", "https://example/matrix", 10, size_exact=True
        ),
        directory,
        force=False,
        progress_callback=snapshots.append,
    )

    assert calls == [{}, {"Range": "bytes=4-"}]
    assert result["retry_count"] == 1
    assert snapshots[-1]["downloaded_bytes"] == 10
    assert snapshots[-1]["retry_count"] == 1
    assert (directory / "matrix.txt").read_bytes() == content


def test_checkpoint_io_failure_preserves_partial_and_dataset_error_class(
    tmp_path, monkeypatch
):
    import paperfetch.datasets.geo as geo_module

    content = b"x" * (2 * 1024 * 1024)
    remote = GeoRemoteFile(
        "matrix.bin",
        "supplementary",
        "https://example/matrix.bin",
        len(content),
        size_exact=True,
    )
    store = GeoDatasetStore(
        tmp_path,
        session=RoutingSession(
            lambda method, url, kwargs: FakeResponse(
                status=200,
                body=content,
                headers={"Content-Length": str(len(content))},
            )
        ),
    )
    store.progress_interval_bytes = 1
    monkeypatch.setattr(store, "discover", lambda _gse: [remote])
    original_atomic_write = geo_module.atomic_write_json
    state_writes = 0

    def fail_first_progress_checkpoint(path, value):
        nonlocal state_writes
        if path.name == "download_state.json":
            state_writes += 1
            if state_writes == 3:
                raise GeoFilesystemError(
                    "checkpoint_replace",
                    path,
                    OSError(13, "simulated sharing violation"),
                )
        return original_atomic_write(path, value)

    monkeypatch.setattr(geo_module, "atomic_write_json", fail_first_progress_checkpoint)

    result = store.download("GSE123")
    report = json.loads(
        Path(result["acquisition_report_path"]).read_text(encoding="utf-8")
    )
    state = json.loads(
        (tmp_path / "GSE123" / "download_state.json").read_text(encoding="utf-8")
    )
    partial = tmp_path / "GSE123" / ".matrix.bin.part"

    assert result["status"] == "incomplete"
    assert partial.exists()
    assert partial.stat().st_size == 1024 * 1024
    assert report["error"]["error_class"] == "io_error"
    assert report["files"][0]["error_class"] == "io_error"
    diagnostics = report["files"][0]["error_diagnostics"]
    assert diagnostics["operation"] == "checkpoint_replace"
    assert diagnostics["errno"] == 13
    assert state["files"]["matrix.bin"]["status"] == "failed"


def test_download_accepts_safe_get_when_head_size_is_stale(tmp_path):
    directory = tmp_path / "GSE123"
    directory.mkdir()
    content = b"fresh metadata"
    store = GeoDatasetStore(
        tmp_path,
        session=RoutingSession(
            lambda method, url, kwargs: FakeResponse(
                status=200,
                body=content,
                headers={"Content-Type": "text/plain"},
            )
        ),
    )

    result = store._download_file(
        GeoRemoteFile(
            "filelist.txt",
            "supplementary",
            "https://example/filelist.txt",
            3,
            size_exact=True,
        ),
        directory,
        force=False,
    )

    assert result["downloaded_bytes"] == len(content)
    assert (directory / "filelist.txt").read_bytes() == content


def test_download_does_not_compare_decoded_body_to_compressed_length(tmp_path):
    directory = tmp_path / "GSE123"
    directory.mkdir()
    decoded = b"decoded metadata"
    store = GeoDatasetStore(
        tmp_path,
        session=RoutingSession(
            lambda method, url, kwargs: FakeResponse(
                status=200,
                body=decoded,
                headers={
                    "Content-Type": "text/plain",
                    "Content-Encoding": "gzip",
                    "Content-Length": "3",
                },
            )
        ),
    )

    result = store._download_file(
        GeoRemoteFile(
            "filelist.txt",
            "supplementary",
            "https://example/filelist.txt",
            3,
            size_exact=True,
        ),
        directory,
        force=False,
    )

    assert result["downloaded_bytes"] == len(decoded)
    assert (directory / "filelist.txt").read_bytes() == decoded


def test_download_rejects_html_proxy_body(tmp_path):
    directory = tmp_path / "GSE123"
    directory.mkdir()
    store = GeoDatasetStore(
        tmp_path,
        session=RoutingSession(
            lambda method, url, kwargs: FakeResponse(
                status=200,
                body=b"<html>proxy challenge</html>",
                headers={"Content-Type": "text/html"},
            )
        ),
    )

    with pytest.raises(GeoDataError) as raised:
        store._download_file(
            GeoRemoteFile(
                "matrix.txt",
                "series_matrix",
                "https://example/matrix",
                10,
                size_exact=True,
            ),
            directory,
            force=False,
        )
    assert raised.value.error_code == "unexpected_content"
    assert raised.value.error_class == "identity_mismatch"


def test_inspect_gse_cli_reports_missing_dataset(tmp_path, capsys):
    code = run(
        [
            "dataset",
            "geo",
            "inspect",
            "GSE123",
            "--output-dir",
            str(tmp_path),
            "--output-format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["status"] == "failed"
    assert payload["results"][0]["status"] == "failed"
    assert payload["results"][0]["data"]["gse_id"] == "GSE123"


def test_dataset_lock_rejects_second_writer(tmp_path):
    lock_path = tmp_path / ".locks" / "GSE123.lock"
    with GeoDatasetLock(lock_path):
        with pytest.raises(GeoDataError) as raised:
            with GeoDatasetLock(lock_path, timeout_seconds=0.01):
                pass
        assert raised.value.error_code == "resource_busy"


def test_download_gse_cli_rejects_non_positive_size_gate(capsys):
    code = run(["dataset", "geo", "download", "GSE123", "--max-size-gb", "0"])
    capsys.readouterr()
    assert code == 1
