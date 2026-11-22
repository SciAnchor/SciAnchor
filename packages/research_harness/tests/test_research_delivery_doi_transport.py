"""Offline publication/recovery checks against documented Zenodo response shapes."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

from research_harness.deposit import research_delivery as delivery


class Zenodo:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.fail_create = False
        self.fail_publish = False
        self.access = "restricted"
        self.bad_checksum = False
        self.denied = True

    def request(self, method, url, *, token=None, json_body=None, data=None, **kwargs):
        self.calls.append((method, url, token))
        path = urlsplit(url).path
        if path == "/api/deposit/depositions":
            if method == "GET":
                return copy.deepcopy(list(self.records.values()))
            rid = len(self.records) + 11
            record = {
                "id": rid,
                "record_id": rid,
                "owner": 7,
                "submitted": False,
                "state": "unsubmitted",
                "files": [],
                "metadata": copy.deepcopy(json_body["metadata"]),
                "links": {"bucket": f"https://zenodo.org/api/files/bucket-{rid}"},
            }
            self.records[rid] = record
            if self.fail_create:
                self.fail_create = False
                raise RuntimeError("secret MUST NOT APPEAR")
            return copy.deepcopy(record)
        if path.startswith("/api/files/"):
            rid = int(path.split("/")[-2].split("-")[-1])
            raw = data.read() if hasattr(data, "read") else data
            checksum = hashlib.md5(raw).hexdigest()
            if self.bad_checksum:
                checksum = "0" * 32
            entry = {
                "filename": path.split("/")[-1],
                "filesize": len(raw),
                "checksum": checksum,
            }
            self.records[rid]["files"] = [entry]
            return {
                "key": entry["filename"],
                "size": len(raw),
                "checksum": "md5:" + checksum,
            }
        rid = int(path.split("/")[4] if "/deposit/" in path else path.split("/")[3])
        record = self.records[rid]
        if path.endswith("/actions/publish"):
            record.update(submitted=True, state="done", doi=f"10.5281/zenodo.{rid}")
            if self.fail_publish:
                self.fail_publish = False
                raise RuntimeError("secret MUST NOT APPEAR")
        elif method == "PUT":
            record["metadata"] = copy.deepcopy(json_body["metadata"])
        elif path.endswith("/files"):
            return copy.deepcopy(record["files"])
        elif "/api/records/" in path:
            assert not token
            return {
                "id": rid,
                "doi": record["doi"],
                "files": [],
                "metadata": {**record["metadata"], "access_right": self.access},
            }
        return copy.deepcopy(record)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    packages = {}
    for kind in ("code", "data"):
        path = tmp_path / f"{kind}.zip"
        path.write_bytes(f"frozen {kind}".encode())
        packages[kind] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    remote = Zenodo()
    monkeypatch.setattr(delivery.zenodo, "_request", remote.request)
    monkeypatch.setattr(delivery, "_download_denied", lambda *a, **k: remote.denied)
    kwargs = {
        "packages": packages,
        "execution_id": "execution-123",
        "title": "Study title",
        "credentials": {
            "platform": "zenodo",
            "username": "token",
            "secret": "explicit-token",
        },
        "journal_dir": tmp_path / "private",
    }
    return kwargs, remote


def test_publish_both_restricted_and_replay_without_new_deposit(setup):
    kwargs, remote = setup
    result = delivery.publish_packages(**kwargs)
    assert result["schema_version"] == "research_delivery_dois.v1"
    assert set(result["deposits"]) == {"code", "data"}
    assert all(x["verified"] for x in result["deposits"].values())
    assert all(
        x["metadata"]["access_right"] == "restricted" for x in remote.records.values()
    )
    assert delivery.publish_packages(**kwargs) == result
    assert len(remote.records) == 2
    assert (
        delivery.verify_publication(
            result, execution_id=kwargs["execution_id"], packages=kwargs["packages"]
        )
        == result
    )
    assert not any(
        "explicit-token" in p.read_text() for p in kwargs["journal_dir"].glob("*.json")
    )
    assert all(
        p.stat().st_mode & 0o077 == 0 for p in kwargs["journal_dir"].glob("*.json")
    )


@pytest.mark.parametrize("failure", ["fail_create", "fail_publish"])
def test_lost_response_recovers_same_remote_record(setup, failure):
    kwargs, remote = setup
    setattr(remote, failure, True)
    with pytest.raises(delivery.PublicationError) as err:
        delivery.publish_packages(**kwargs)
    assert "secret" not in str(err.value)
    result = delivery.publish_packages(**kwargs)
    assert len(remote.records) == 2
    assert result["deposits"]["code"]["record_id"] == 11


def test_ambiguous_create_never_creates_again(setup):
    kwargs, remote = setup
    remote.fail_create = True
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(**kwargs)
    remote.records[12] = {**copy.deepcopy(remote.records[11]), "id": 12}
    with pytest.raises(delivery.PublicationError, match="ambiguous"):
        delivery.publish_packages(**kwargs)
    assert len(remote.records) == 2


@pytest.mark.parametrize("change", ["bytes", "title", "account", "sandbox"])
def test_replay_rejects_changed_identity_before_network(setup, change):
    kwargs, remote = setup
    delivery.publish_packages(**kwargs)
    calls = len(remote.calls)
    if change == "bytes":
        Path(kwargs["packages"]["data"]["path"]).write_bytes(b"tampered")
    elif change == "account":
        kwargs["credentials"] = {**kwargs["credentials"], "secret": "another-token"}
    else:
        kwargs[change] = True if change == "sandbox" else "Another study"
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(**kwargs)
    assert len(remote.calls) == calls


@pytest.mark.parametrize("access", [None, "open", "closed", "unknown"])
def test_public_record_must_positively_be_restricted(setup, access):
    kwargs, remote = setup
    remote.access = access
    with pytest.raises(delivery.PublicationError, match="restricted"):
        delivery.publish_packages(**kwargs)


def test_remote_checksum_checked_before_publish(setup):
    kwargs, remote = setup
    remote.bad_checksum = True
    with pytest.raises(delivery.PublicationError, match="checksum"):
        delivery.publish_packages(**kwargs)
    assert not any(url.endswith("/actions/publish") for _, url, _ in remote.calls)


def test_anonymous_download_must_be_denied(setup):
    kwargs, remote = setup
    remote.denied = False
    with pytest.raises(delivery.PublicationError, match="download"):
        delivery.publish_packages(**kwargs)


def test_explicit_account_ignores_environment_token(setup, monkeypatch):
    kwargs, remote = setup
    monkeypatch.setenv("ZENODO_TOKEN", "wrong-account")
    monkeypatch.setattr(
        delivery.zenodo, "create_token_via_login", lambda **kw: "ticket-token"
    )
    kwargs["credentials"] = {
        "platform": "zenodo",
        "username": "owner@example.org",
        "secret": "password",
    }
    delivery.publish_packages(**kwargs)
    assert all(token in (None, "ticket-token") for _, _, token in remote.calls)


def test_offline_verify_detects_receipt_or_archive_tampering(setup):
    kwargs, _ = setup
    receipt = delivery.publish_packages(**kwargs)
    wrong = copy.deepcopy(receipt)
    wrong["deposits"]["code"]["doi"] = "10.5281/zenodo.999"
    with pytest.raises(delivery.PublicationError):
        delivery.verify_publication(wrong, execution_id=kwargs["execution_id"])
    Path(kwargs["packages"]["data"]["path"]).write_bytes(b"changed")
    with pytest.raises(delivery.PublicationError):
        delivery.verify_publication(receipt, execution_id=kwargs["execution_id"])


def test_symlink_journal_and_competing_writer_rejected(setup, tmp_path):
    kwargs, _ = setup
    real = tmp_path / "real"
    real.mkdir()
    kwargs["journal_dir"].symlink_to(real, target_is_directory=True)
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(**kwargs)
    kwargs["journal_dir"].unlink()
    kwargs["journal_dir"].mkdir(mode=0o700)
    with (kwargs["journal_dir"] / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(delivery.PublicationError, match="running"):
            delivery.publish_packages(**kwargs)


def test_missing_journal_and_foreign_execution_rejected(setup):
    kwargs, _ = setup
    receipt = delivery.publish_packages(**kwargs)
    with pytest.raises(delivery.PublicationError):
        delivery.verify_publication(receipt, execution_id="another-execution")
    (kwargs["journal_dir"] / "data.json").unlink()
    with pytest.raises(delivery.PublicationError):
        delivery.verify_publication(receipt, execution_id=kwargs["execution_id"])


def test_missing_kind_journal_does_not_republish(setup):
    kwargs, remote = setup
    delivery.publish_packages(**kwargs)
    (kwargs["journal_dir"] / "code.json").unlink()
    before = len(remote.calls)
    with pytest.raises(delivery.PublicationError, match="journal"):
        delivery.publish_packages(**kwargs)
    assert len(remote.calls) == before


@pytest.mark.parametrize(
    "problem", ["bucket", "owner", "state", "doi", "public_id", "files"]
)
def test_remote_identity_failures_do_not_verify(setup, monkeypatch, problem):
    kwargs, remote = setup
    original = remote.request

    def altered(method, url, **options):
        result = original(method, url, **options)
        if not isinstance(result, dict):
            return result
        if problem == "bucket" and not result.get("submitted") and result.get("links"):
            result["links"]["bucket"] = "https://foreign.example/api/files/1"
        if problem == "owner" and method == "GET" and result.get("owner"):
            result["owner"] = 999
        if problem == "state" and result.get("submitted"):
            result["state"] = "error"
        if problem == "doi" and result.get("submitted"):
            result["doi"] = "10.5281/zenodo.999"
        if "/api/records/" in url:
            if problem == "public_id":
                result["id"] = 999
            if problem == "files":
                result["files"] = [{"filename": "private.zip"}]
        return result

    monkeypatch.setattr(delivery.zenodo, "_request", altered)
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(**kwargs)


def test_upload_changes_source_before_publish_is_rejected(setup, monkeypatch):
    kwargs, remote = setup
    original = remote.request

    def altered(method, url, **options):
        result = original(method, url, **options)
        if method == "PUT" and "/api/files/" in url:
            Path(kwargs["packages"]["code"]["path"]).write_bytes(
                b"changed during upload"
            )
        return result

    monkeypatch.setattr(delivery.zenodo, "_request", altered)
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(**kwargs)
    assert not any(url.endswith("/actions/publish") for _, url, _ in remote.calls)


def test_no_matching_uncertain_creation_does_not_repeat(setup):
    kwargs, remote = setup
    remote.fail_create = True
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(**kwargs)
    remote.records.clear()
    with pytest.raises(delivery.PublicationError, match="ambiguous"):
        delivery.publish_packages(**kwargs)
    assert remote.records == {}


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, False),
        (206, False),
        (302, False),
        (401, True),
        (403, True),
        (404, True),
        (500, False),
    ],
)
def test_anonymous_download_probe_checks_status_without_parsing_bytes(
    monkeypatch, status, expected
):
    class Opener:
        def open(self, request, timeout):
            assert not request.has_header("Authorization")
            if status != 200:
                raise HTTPError(request.full_url, status, "response", {}, None)
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(delivery, "build_opener", lambda *args: Opener())
    assert (
        delivery._download_denied("https://zenodo.org/records/11/files/code.zip")
        is expected
    )


def test_zenodo_api_transport_rejects_foreign_urls_and_redirects(monkeypatch):
    with pytest.raises(RuntimeError, match="Invalid"):
        delivery.zenodo._request(
            "GET", "https://foreign.example/api/records/1", token="private"
        )
    handler = delivery.zenodo._NoRedirect()
    assert (
        handler.redirect_request(None, None, 302, "", {}, "https://foreign.example")
        is None
    )

    class Opener:
        def open(self, request, timeout):
            assert not request.has_header("Authorization")
            return self

        def read(self):
            return b'{"id": 11}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(delivery.zenodo, "build_opener", lambda *args: Opener())
    assert delivery.zenodo._request(
        "GET", "https://zenodo.org/api/records/11", token=None
    ) == {"id": 11}


@pytest.mark.parametrize(
    "files",
    [
        {"enabled": False},
        {"enabled": False, "entries": {}},
        {"enabled": True, "entries": [], "order": []},
    ],
)
def test_modern_restricted_record_empty_files_shape(setup, monkeypatch, files):
    kwargs, remote = setup
    original = remote.request

    def modern(method, url, **options):
        result = original(method, url, **options)
        if "/api/records/" in url:
            result["files"] = files
            result["access"] = {"record": "public", "files": "restricted"}
        return result

    monkeypatch.setattr(delivery.zenodo, "_request", modern)
    assert delivery.publish_packages(**kwargs)["deposits"]["data"]["verified"]


@pytest.mark.parametrize(
    "field", ["marker", "account_hash", "title", "sandbox", "owner_id", "deposition_id"]
)
def test_durable_journal_invariants_checked_offline(setup, field):
    kwargs, _ = setup
    receipt = delivery.publish_packages(**kwargs)
    path = kwargs["journal_dir"] / "code.json"
    journal = json.loads(path.read_text())
    journal[field] = (
        not journal[field]
        if field == "sandbox"
        else 999
        if field.endswith("_id")
        else "changed"
    )
    path.write_text(json.dumps(journal))
    with pytest.raises(delivery.PublicationError):
        delivery.verify_publication(receipt, execution_id=kwargs["execution_id"])


def test_missing_pair_manifest_blocks_replay(setup):
    kwargs, remote = setup
    delivery.publish_packages(**kwargs)
    (kwargs["journal_dir"] / "publication.json").unlink()
    before = len(remote.calls)
    with pytest.raises(delivery.PublicationError, match="manifest"):
        delivery.publish_packages(**kwargs)
    assert len(remote.calls) == before


def test_open_data_publishes_and_verifies_the_code_archive_alone(setup):
    """C-100: open data deposits only the code archive; the pair checks apply only to a pair."""
    kwargs, remote = setup
    kwargs = {**kwargs, "packages": {"code": kwargs["packages"]["code"]}}
    result = delivery.publish_packages(**kwargs)
    assert set(result["deposits"]) == {"code"} and len(remote.records) == 1
    assert (
        delivery.verify_publication(result, execution_id=kwargs["execution_id"])
        == result
    )
    assert (
        delivery.verify_publication(
            result, execution_id=kwargs["execution_id"], packages=kwargs["packages"]
        )
        == result
    )
    with pytest.raises(delivery.PublicationError):
        delivery.publish_packages(
            **{**kwargs, "packages": {"data": setup[0]["packages"]["data"]}}
        )
