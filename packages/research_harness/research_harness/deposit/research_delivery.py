"""Frozen-package Zenodo publication with durable, per-execution recovery.

Response shapes: https://developers.zenodo.org/#depositions and #deposition-files.
An uncertain create is reconciled by its atomically created metadata marker;
an absent or ambiguous match never causes a second create.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from . import zenodo

SCHEMA = "research_delivery_dois.v1"
JOURNAL_SCHEMA = "research_delivery_doi_journal.v1"
KINDS = ("code", "data")
TOKEN_USERS = {"token", "api_token", "zenodo_token", "__token__"}
ACCESS_CONDITIONS = (
    "Files are restricted while the associated manuscript is under review. "
    "Access requests from editors, reviewers and researchers with a legitimate "
    "interest are considered by the corresponding author."
)


class PublicationError(RuntimeError):
    """A publication cannot advance without changing or losing its identity."""


def _require(condition, message):
    if not condition:
        raise PublicationError(message)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _safe_path(value):
    path = Path(os.path.abspath(Path(value).expanduser()))
    _require(
        not any(p.is_symlink() for p in (path, *path.parents)),
        "symlink in publication path",
    )
    return path


def _private_dir(value, *, create=False):
    path = _safe_path(value)
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _require(path.is_dir(), "publication journal directory is missing")
    if create:
        os.chmod(path, 0o700)
    return path


def _open_file(path, flags, mode=0o600):
    parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            os.close(parent)
            parent = child
        return os.open(
            path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, mode, dir_fd=parent
        )
    finally:
        os.close(parent)


@contextmanager
def _lock(directory):
    fd = _open_file(directory / ".lock", os.O_RDWR | os.O_CREAT)
    try:
        _require(stat.S_ISREG(os.fstat(fd).st_mode), "invalid publication lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PublicationError("publication already running") from None
        yield
    finally:
        os.close(fd)


def _write(path, value):
    _require(not path.is_symlink(), "invalid publication journal")
    fd, name = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def _read(path):
    try:
        fd = _open_file(path, os.O_RDONLY)
        with os.fdopen(fd, "r") as stream:
            info = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_size <= 65536,
                "invalid publication journal",
            )
            value = json.load(stream)
        _require(isinstance(value, dict), "invalid publication journal")
        return value
    except (OSError, ValueError):
        raise PublicationError("publication journal missing or invalid") from None


@contextmanager
def _package_stream(package):
    path = _safe_path(package["path"])
    fd = _open_file(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_size == package["bytes"],
            "frozen package size changed",
        )
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
        _require(sha == package["sha256"], "frozen package checksum changed")
        stream.seek(0)
        yield stream
        after = os.fstat(stream.fileno())
        _require(
            (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "frozen package changed during upload",
        )


def _kinds(packages):
    """("code", "data"), or ("code",) alone when the data is open: open data is someone else's
    archive, so only the code is deposited and the paper prints the public data URL."""
    _require(
        isinstance(packages, dict) and set(packages) in ({"code"}, set(KINDS)),
        "a code package, or code and data packages, required",
    )
    return tuple(kind for kind in KINDS if kind in packages)


def _packages(packages):
    result = {}
    for kind in _kinds(packages):
        value = packages[kind]
        _require(isinstance(value, dict), "invalid frozen package")
        path = _safe_path(value.get("path", ""))
        _require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.zip", path.name),
            "invalid package filename",
        )
        _require(
            type(value.get("bytes")) is int and value["bytes"] > 0,
            "invalid package size",
        )
        _require(
            isinstance(value.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
            "invalid package checksum",
        )
        package = {
            "path": str(path),
            "sha256": value["sha256"],
            "bytes": value["bytes"],
            "filename": path.name,
        }
        with _package_stream(package) as stream:
            md5 = hashlib.file_digest(stream, "md5").hexdigest()
        result[kind] = {**package, "md5": md5}
    _require(
        "data" not in result or result["code"]["path"] != result["data"]["path"],
        "code and data packages must be distinct",
    )
    return result


def _account(credentials):
    _require(isinstance(credentials, dict), "explicit Zenodo credentials required")
    platform, username, secret = (
        credentials.get(k) for k in ("platform", "username", "secret")
    )
    _require(
        platform == "zenodo"
        and all(isinstance(x, str) and x.strip() for x in (username, secret)),
        "explicit Zenodo credentials required",
    )
    username = username.strip()
    identity = {"platform": platform, "username": username.lower()}
    if username.lower() in TOKEN_USERS:
        identity["token_sha256"] = hashlib.sha256(secret.encode()).hexdigest()
    else:
        _require(
            "@" in username and not any(x in username for x in "\r\n"),
            "invalid Zenodo account",
        )
    return username, secret, _digest(identity)


def _token(username, secret, sandbox):
    if username.lower() in TOKEN_USERS:
        return secret
    try:
        return zenodo.create_token_via_login(
            email=username, password=secret, sandbox=sandbox
        )
    except Exception:
        raise PublicationError("Zenodo authentication failed") from None


def _request(method, url, **kwargs):
    try:
        return zenodo._request(method, url, **kwargs)
    except Exception:
        raise PublicationError(
            "Zenodo request failed; retry resumes the recorded publication"
        ) from None


def _record_id(value):
    _require(type(value) is int and value > 0, "invalid Zenodo record identity")
    return value


def _metadata(title, kind, marker, username):
    return {
        "title": f"{'Code' if kind == 'code' else 'Data'} for: {title}",
        "upload_type": "software" if kind == "code" else "dataset",
        "description": f"Supporting {'software' if kind == 'code' else 'data and results'} for: {html.escape(title)}.",
        "creators": [
            zenodo._creator_from_email(username if "@" in username else None, None)
        ],
        "access_right": "restricted",
        "access_conditions": ACCESS_CONDITIONS,
        "license": "mit" if kind == "code" else "cc-by-4.0",
        "keywords": [marker],
    }


def _check_metadata(record, expected):
    _require(
        isinstance(record, dict) and isinstance(record.get("metadata"), dict),
        "invalid Zenodo record",
    )
    metadata = record["metadata"]
    for key in (
        "title",
        "upload_type",
        "access_right",
        "access_conditions",
        "keywords",
    ):
        _require(
            metadata.get(key) == expected[key],
            f"Zenodo {key} does not match restricted publication",
        )


def _files(files, package):
    _require(
        isinstance(files, list) and len(files) == 1 and isinstance(files[0], dict),
        "Zenodo file inventory changed",
    )
    item = files[0]
    name = item.get("filename", item.get("key"))
    size = item.get("filesize", item.get("size"))
    checksum = str(item.get("checksum", "")).removeprefix("md5:")
    _require(
        name == package["filename"] and str(size) == str(package["bytes"]),
        "Zenodo file identity changed",
    )
    _require(
        checksum == package["md5"],
        "Zenodo uploaded checksum differs from frozen package",
    )


def _bucket(record, base):
    value = (record.get("links") or {}).get("bucket", "")
    parsed = urlsplit(value)
    _require(
        parsed.scheme == "https"
        and parsed.netloc == urlsplit(base).netloc
        and re.fullmatch(r"/api/files/[A-Za-z0-9-]+", parsed.path)
        and not parsed.query
        and not parsed.fragment,
        "invalid Zenodo upload bucket",
    )
    return value


def _recover(base, token, journal):
    # ponytail: one filtered page; ambiguous/saturated results require reconciliation.
    query = urlencode(
        {"q": f'keywords:"{journal["marker"]}"', "size": 100, "all_versions": 1}
    )
    candidates = _request("GET", f"{base}/deposit/depositions?{query}", token=token)
    _require(
        isinstance(candidates, list) and len(candidates) < 100,
        "ambiguous Zenodo creation; reconciliation required",
    )
    matches = [
        x
        for x in candidates
        if isinstance(x, dict)
        and journal["marker"] in (x.get("metadata", {}).get("keywords") or [])
    ]
    _require(len(matches) == 1, "ambiguous Zenodo creation; reconciliation required")
    _check_metadata(matches[0], journal["metadata"])
    return matches[0]


def _download_denied(url):
    try:
        with build_opener(zenodo._NoRedirect()).open(
            Request(url, headers={"Range": "bytes=0-0"}), timeout=30
        ):
            return False
    except HTTPError as exc:
        return exc.code in {401, 403, 404}
    except Exception:
        return False


def _verify_remote(base, token, record, journal):
    _check_metadata(record, journal["metadata"])
    _require(
        record.get("id") == journal["deposition_id"]
        and record.get("owner") == journal["owner_id"],
        "Zenodo deposition owner changed",
    )
    _require(
        record.get("submitted") is True and record.get("state") == "done",
        "Zenodo publication is not yet complete",
    )
    rid = _record_id(record.get("record_id", record.get("id")))
    prefix = "10.5072" if journal["sandbox"] else "10.5281"
    doi = record.get("doi")
    _require(doi == f"{prefix}/zenodo.{rid}", "Zenodo published DOI identity mismatch")
    package = journal["package"]
    files = _request(
        "GET",
        f"{base}/deposit/depositions/{journal['deposition_id']}/files",
        token=token,
    )
    _files(files, package)
    public = _request("GET", f"{base}/records/{rid}", token=None)
    _require(
        isinstance(public, dict)
        and str(public.get("id")) == str(rid)
        and (public.get("doi") or public.get("metadata", {}).get("doi")) == doi,
        "Zenodo public DOI identity mismatch",
    )
    access = public.get("metadata", {}).get("access_right") or public.get(
        "access", {}
    ).get("files")
    _require(
        access == "restricted", "Zenodo public record is not explicitly restricted"
    )
    public_files = public.get("files")
    if isinstance(public_files, dict):
        _require(
            type(public_files.get("enabled")) is bool
            and ("entries" in public_files or public_files["enabled"] is False),
            "unknown Zenodo public file inventory",
        )
        public_files = public_files.get("entries", [])
    _require(
        public_files in (None, [], {}), "Zenodo restricted file inventory is public"
    )
    host = base.removesuffix("/api")
    _require(
        _download_denied(
            f"{host}/records/{rid}/files/{package['filename']}?download=1"
        ),
        "Zenodo anonymous file download not denied",
    )
    return {
        "doi": doi,
        "record_id": rid,
        "url": f"https://doi.org/{doi}",
        **{k: package[k] for k in ("sha256", "bytes", "filename")},
        "verified": True,
    }


def _publish_kind(path, journal, token):
    if journal.get("status") == "verified":
        return journal["receipt"]
    base = zenodo._api_base(journal["sandbox"])
    dep_url = f"{base}/deposit/depositions"
    if not journal.get("deposition_id"):
        if journal["status"] == "creating":
            record = _recover(base, token, journal)
        else:
            journal = {**journal, "status": "creating"}
            _write(path, journal)
            record = _request(
                "POST",
                dep_url,
                token=token,
                json_body={"metadata": journal["metadata"]},
            )
        journal = {
            **journal,
            "deposition_id": _record_id(record.get("id")),
            "owner_id": _record_id(record.get("owner")),
            "status": "created",
        }
        _write(path, journal)
    dep_url += f"/{journal['deposition_id']}"
    record = _request("GET", dep_url, token=token)
    _require(
        record.get("id") == journal["deposition_id"]
        and record.get("owner") == journal["owner_id"],
        "Zenodo deposition identity or owner changed",
    )
    _check_metadata(record, journal["metadata"])
    if record.get("submitted") is not True:
        _require(
            record.get("state") in {"unsubmitted", "inprogress"},
            "Zenodo deposition state blocks publication",
        )
        package = journal["package"]
        files = _request("GET", f"{dep_url}/files", token=token)
        if not files:
            with _package_stream(package) as stream:
                _request(
                    "PUT",
                    f"{_bucket(record, base)}/{package['filename']}",
                    token=token,
                    data=stream,
                    content_type="application/octet-stream",
                    timeout=600,
                )
            files = _request("GET", f"{dep_url}/files", token=token)
        _files(files, package)
        journal = {**journal, "status": "publishing"}
        _write(path, journal)
        _request("POST", f"{dep_url}/actions/publish", token=token)
        record = _request("GET", dep_url, token=token)
    receipt = _verify_remote(base, token, record, journal)
    _write(
        path,
        {
            **journal,
            "status": "verified",
            "receipt": receipt,
            "verified_deposition_id": journal["deposition_id"],
            "verified_owner_id": journal["owner_id"],
        },
    )
    return receipt


def publish_packages(
    *, packages, execution_id, title, credentials, journal_dir, sandbox=False
):
    """Publish exactly the frozen archives (code, and data unless it is open); retry never
    changes identity."""
    _require(
        isinstance(execution_id, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", execution_id),
        "invalid research execution identity",
    )
    _require(
        isinstance(title, str) and bool(title.strip()) and len(title) <= 2000,
        "invalid publication title",
    )
    _require(type(sandbox) is bool, "invalid publication environment")
    try:
        frozen = _packages(packages)
        kinds = tuple(frozen)
        username, secret, account_hash = _account(credentials)
        directory = _private_dir(journal_dir, create=True)
        with _lock(directory):
            manifest_path = directory / "publication.json"
            manifest = {
                "schema_version": JOURNAL_SCHEMA,
                "execution_id": execution_id,
                "account_hash": account_hash,
                "sandbox": sandbox,
                "title": title,
                "packages": frozen,
            }
            if manifest_path.exists() or manifest_path.is_symlink():
                _require(
                    _read(manifest_path) == manifest, "publication identity changed"
                )
                _require(
                    all((directory / f"{kind}.json").is_file() for kind in kinds),
                    "publication kind journal is missing",
                )
            journals = {}
            for kind in kinds:
                identity = {
                    "schema_version": JOURNAL_SCHEMA,
                    "execution_id": execution_id,
                    "kind": kind,
                    "sandbox": sandbox,
                    "account_hash": account_hash,
                    "package": frozen[kind],
                    "title": title,
                }
                marker = "package-" + _digest(identity)
                expected = {
                    **identity,
                    "marker": marker,
                    "metadata": _metadata(title, kind, marker, username),
                }
                path = directory / f"{kind}.json"
                if path.exists() or path.is_symlink():
                    journal = _read(path)
                    _require(
                        all(journal.get(k) == v for k, v in expected.items()),
                        "publication identity changed",
                    )
                    _require(
                        manifest_path.exists() or journal.get("status") == "prepared",
                        "publication journal manifest is missing",
                    )
                else:
                    journal = {**expected, "status": "prepared"}
                    _write(path, journal)
                journals[kind] = journal
            if not manifest_path.exists():
                _write(manifest_path, manifest)
            token = (
                None
                if all(j["status"] == "verified" for j in journals.values())
                else _token(username, secret, sandbox)
            )
            deposits = {
                kind: _publish_kind(directory / f"{kind}.json", journals[kind], token)
                for kind in kinds
            }
            result = {
                "schema_version": SCHEMA,
                "execution_id": execution_id,
                "journal_dir": str(directory),
                "deposits": deposits,
            }
            return verify_publication(
                result, execution_id=execution_id, packages=packages
            )
    except PublicationError:
        raise
    except Exception:
        raise PublicationError(
            "publication failed; retained journals permit recovery"
        ) from None


def verify_publication(receipt, *, execution_id, packages=None):
    """Verify durable local publication evidence and exact frozen bytes, offline."""
    try:
        _require(
            isinstance(receipt, dict)
            and set(receipt)
            == {"schema_version", "execution_id", "journal_dir", "deposits"}
            and receipt["schema_version"] == SCHEMA
            and receipt["execution_id"] == execution_id,
            "invalid publication receipt",
        )
        directory = _private_dir(receipt["journal_dir"])
        _require(
            str(directory) == receipt["journal_dir"],
            "noncanonical publication journal path",
        )
        manifest = _read(directory / "publication.json")
        kinds = _kinds(packages if packages is not None else manifest.get("packages"))
        _require(set(receipt["deposits"]) == set(kinds), "invalid publication receipt")
        journals = {kind: _read(directory / f"{kind}.json") for kind in kinds}
        frozen = _packages(
            packages
            if packages is not None
            else {kind: journal["package"] for kind, journal in journals.items()}
        )
        for kind, journal in journals.items():
            _require(
                journal.get("schema_version") == JOURNAL_SCHEMA
                and journal.get("status") == "verified"
                and journal.get("execution_id") == execution_id
                and journal.get("kind") == kind
                and journal.get("package") == frozen[kind]
                and journal.get("receipt") == receipt["deposits"][kind],
                "publication journal does not match receipt",
            )
            _require(
                manifest
                == {
                    "schema_version": JOURNAL_SCHEMA,
                    "execution_id": execution_id,
                    "account_hash": journal["account_hash"],
                    "sandbox": journal["sandbox"],
                    "title": journal["title"],
                    "packages": frozen,
                },
                "publication journal manifest changed",
            )
            identity = {
                k: journal[k]
                for k in (
                    "schema_version",
                    "execution_id",
                    "kind",
                    "sandbox",
                    "account_hash",
                    "package",
                    "title",
                )
            }
            _require(
                journal["marker"] == "package-" + _digest(identity)
                and journal["metadata"]["keywords"] == [journal["marker"]]
                and journal["metadata"]["access_right"] == "restricted"
                and journal["metadata"]["access_conditions"] == ACCESS_CONDITIONS,
                "publication marker or restricted metadata changed",
            )
            _require(
                _record_id(journal["owner_id"]) == journal["verified_owner_id"]
                and _record_id(journal["deposition_id"])
                == journal["verified_deposition_id"],
                "verified Zenodo identity changed",
            )
            expected = journal["receipt"]
            rid = _record_id(expected.get("record_id"))
            doi = f"{'10.5072' if journal['sandbox'] else '10.5281'}/zenodo.{rid}"
            _require(
                expected
                == {
                    "doi": doi,
                    "record_id": rid,
                    "url": f"https://doi.org/{doi}",
                    **{k: frozen[kind][k] for k in ("sha256", "bytes", "filename")},
                    "verified": True,
                },
                "publication receipt fields changed",
            )
        _require(
            "data" not in journals
            or (
                journals["code"]["owner_id"] == journals["data"]["owner_id"]
                and journals["code"]["deposition_id"]
                != journals["data"]["deposition_id"]
                and receipt["deposits"]["code"]["record_id"]
                != receipt["deposits"]["data"]["record_id"]
            ),
            "code and data DOI ownership or identity mismatch",
        )
        return receipt
    except PublicationError:
        raise
    except Exception:
        raise PublicationError("publication verification failed") from None
