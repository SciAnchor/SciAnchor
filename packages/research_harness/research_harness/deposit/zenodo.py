"""Zenodo code/data deposit: pack → upload → publish → return DOIs.

Auth preference order:
  1. explicit ``token``
  2. env ``ZENODO_TOKEN``
  3. headless login with email/password (requires playwright) → mint PAT

Passwords are never written to disk by this module.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
}
SKIP_SUFFIXES = {".pyc", ".pyo"}

CODE_DIR_NAMES = ("code", "代码", "analysis_code", "src")
DATA_DIR_NAMES = ("data", "数据", "dataset", "datasets")


@dataclass
class DepositResult:
    status: str  # success | error | draft
    topic_id: int | None = None
    topic_name: str | None = None
    code_doi: str | None = None
    data_doi: str | None = None
    code_url: str | None = None
    data_url: str | None = None
    code_deposition_id: int | None = None
    data_deposition_id: int | None = None
    published: bool = False
    sandbox: bool = False
    code_path: str | None = None
    data_path: str | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_DIR_NAMES or path.name == ".DS_Store":
        return True
    return path.suffix in SKIP_SUFFIXES


def pack_zip(src: Path, out_zip: Path, arc_prefix: str) -> list[str]:
    """Zip a file/dir under arc_prefix. Returns archived relative paths."""
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    archived: list[str] = []
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if src.is_file():
            arc = f"{arc_prefix}/{src.name}" if arc_prefix else src.name
            zf.write(src, arcname=arc)
            archived.append(arc)
            return archived
        for root, dirs, files in os.walk(src):
            root_p = Path(root)
            dirs[:] = [d for d in dirs if not _should_skip(root_p / d)]
            for name in files:
                fp = root_p / name
                if _should_skip(fp):
                    continue
                rel = fp.relative_to(src).as_posix()
                arc = f"{arc_prefix}/{rel}" if arc_prefix else rel
                zf.write(fp, arcname=arc)
                archived.append(arc)
    return archived


def _api_base(sandbox: bool) -> str:
    return "https://sandbox.zenodo.org/api" if sandbox else "https://zenodo.org/api"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(
    method: str,
    url: str,
    *,
    token: str | None,
    data: bytes | None = None,
    json_body: dict | None = None,
    content_type: str | None = None,
    timeout: int = 120,
) -> Any:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"zenodo.org", "sandbox.zenodo.org"}
        or not parsed.path.startswith("/api/")
        or parsed.fragment
    ):
        raise RuntimeError("Invalid Zenodo API URL")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = data
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    if hasattr(body, "fileno"):
        headers["Content-Length"] = str(os.fstat(body.fileno()).st_size)
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Zenodo HTTP {e.code} {method} {url}: {err_body[:800]}"
        ) from e
    except URLError as e:
        raise RuntimeError(f"Zenodo network error {method} {url}: {e}") from e


def create_token_via_login(
    *,
    email: str,
    password: str,
    sandbox: bool = False,
    token_name: str | None = None,
    headless: bool = True,
) -> str:
    """Headless browser login → create personal access token. Needs playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "playwright is required for email/password login. "
            "Install: pip install playwright && playwright install chromium. "
            "Or pass a pre-made ZENODO_TOKEN / token=..."
        ) from e

    base = "https://sandbox.zenodo.org" if sandbox else "https://zenodo.org"
    name = token_name or f"rh-deposit-{int(time.time())}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_default_timeout(60_000)
        page.goto(f"{base}/login/", wait_until="networkidle")
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_timeout(2500)
        if "/login" in page.url:
            snippet = page.inner_text("body")[:300]
            browser.close()
            raise RuntimeError(f"Zenodo login failed (url={page.url}): {snippet!r}")

        page.goto(
            f"{base}/account/settings/applications/tokens/new/",
            wait_until="networkidle",
        )
        page.fill('input[name="name"]', name)
        for scope in ("deposit:write", "deposit:actions"):
            box = page.locator(f'input[type="checkbox"][value="{scope}"]')
            if box.count() == 0:
                browser.close()
                raise RuntimeError(f"Scope checkbox missing: {scope}")
            if not box.first.is_checked():
                box.first.check()
        page.locator('button[type="submit"]:has-text("Create")').first.click()
        page.wait_for_timeout(2500)
        text = page.inner_text("body")
        m = re.search(
            r"Access token\s+([A-Za-z0-9]{30,})\s+Please copy",
            text,
            re.I | re.S,
        )
        token = m.group(1) if m else None
        if not token:
            codes = page.eval_on_selector_all(
                "code, pre",
                "els => els.map(e => (e.innerText||'').trim()).filter(Boolean)",
            )
            for c in codes:
                if re.fullmatch(r"[A-Za-z0-9]{30,}", c):
                    token = c
                    break
        browser.close()
        if not token:
            raise RuntimeError("Logged in but could not parse personal access token")
        return token


def resolve_token(
    *,
    token: str | None = None,
    email: str | None = None,
    password: str | None = None,
    sandbox: bool = False,
) -> str:
    tok = token or os.environ.get("ZENODO_TOKEN")
    if tok:
        return tok
    email = email or os.environ.get("ZENODO_EMAIL")
    password = password or os.environ.get("ZENODO_PASSWORD")
    if email and password:
        return create_token_via_login(email=email, password=password, sandbox=sandbox)
    raise RuntimeError(
        "No Zenodo credentials. Provide token / ZENODO_TOKEN, "
        "or email+password / ZENODO_EMAIL+ZENODO_PASSWORD."
    )


def _child_named(root: Path, names: tuple[str, ...]) -> Path | None:
    if not root.is_dir():
        return None
    lower_map = {p.name.lower(): p for p in root.iterdir()}
    for name in names:
        hit = lower_map.get(name.lower())
        if hit is not None and hit.exists():
            return hit
    return None


def _looks_like_deposit_root(path: Path) -> bool:
    return (
        _child_named(path, CODE_DIR_NAMES) is not None
        and _child_named(path, DATA_DIR_NAMES) is not None
    )


def _slug_tokens(text: str) -> set[str]:
    parts = re.split(r"[^a-zA-Z0-9一-鿿]+", text.lower())
    return {p for p in parts if len(p) >= 2}


def resolve_deposit_paths(
    *,
    topic_id: int | None = None,
    topic_name: str | None = None,
    code_path: str | Path | None = None,
    data_path: str | Path | None = None,
    deposit_root: str | Path | None = None,
    search_roots: list[str | Path] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Resolve code/data directories. Raises FileNotFoundError with hints on failure."""
    meta: dict[str, Any] = {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "resolved_from": None,
    }

    if code_path and data_path:
        code = Path(code_path).expanduser().resolve()
        data = Path(data_path).expanduser().resolve()
        if not code.exists() or not data.exists():
            raise FileNotFoundError(f"code/data path missing: {code} / {data}")
        meta["resolved_from"] = "explicit_paths"
        return code, data, meta

    if deposit_root:
        root = Path(deposit_root).expanduser().resolve()
        code = _child_named(root, CODE_DIR_NAMES)
        data = _child_named(root, DATA_DIR_NAMES)
        if code and data:
            meta["resolved_from"] = f"deposit_root:{root}"
            return code.resolve(), data.resolve(), meta
        raise FileNotFoundError(
            f"deposit_root {root} lacks code/data (or 代码/数据) children"
        )

    # Auto-discover from search roots using topic_name tokens
    if not topic_name and topic_id is None:
        raise FileNotFoundError(
            "Need code_path+data_path, deposit_root, or topic_id/topic_name"
        )

    tokens = _slug_tokens(topic_name or "")
    # always keep a few strong anchors from the name
    roots: list[Path] = []
    for r in search_roots or _default_search_roots():
        rp = Path(r).expanduser()
        if rp.exists():
            roots.append(rp)

    candidates: list[Path] = []
    for root in roots:
        # shallow walk
        try:
            for dirpath, dirnames, _files in os.walk(root):
                depth = Path(dirpath).relative_to(root).parts
                if len(depth) > 4:
                    dirnames[:] = []
                    continue
                # prune heavy trees
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in SKIP_DIR_NAMES and d not in {".git", "node_modules"}
                ]
                p = Path(dirpath)
                if _looks_like_deposit_root(p):
                    candidates.append(p)
                # also accept .../deposit with code+data
                if p.name.lower() == "deposit" and _looks_like_deposit_root(p):
                    candidates.append(p)
        except OSError:
            continue

    if not candidates:
        raise FileNotFoundError(
            f"No deposit roots with code+data under {roots}. "
            "Pass deposit_root or code_path/data_path."
        )

    def score(path: Path) -> int:
        blob = str(path).lower()
        s = 0
        for t in tokens:
            if t in blob:
                s += 3 if len(t) >= 4 else 1
        if path.name.lower() == "deposit":
            s += 1
        return s

    ranked = sorted(candidates, key=score, reverse=True)
    if tokens:
        best = ranked[0]
        if score(best) <= 0:
            raise FileNotFoundError(
                f"Found {len(candidates)} deposit-like dirs but none match "
                f"topic_name={topic_name!r}. Top: {[str(p) for p in ranked[:5]]}. "
                "Pass deposit_root explicitly."
            )
    else:
        best = ranked[0]

    code = _child_named(best, CODE_DIR_NAMES)
    data = _child_named(best, DATA_DIR_NAMES)
    assert code and data
    meta["resolved_from"] = f"search:{best}"
    meta["candidates_considered"] = len(candidates)
    return code.resolve(), data.resolve(), meta


def _default_search_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("RH_DEPOSIT_SEARCH_ROOTS", "")
    if env:
        roots.extend(Path(p) for p in env.split(os.pathsep) if p.strip())
    cwd = Path.cwd()
    roots.extend(
        [
            cwd / "tmp",
            cwd / "deliverables",
            cwd,
        ]
    )
    # unique preserve order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def deposit_one(
    *,
    token: str,
    title: str,
    description: str,
    creators: list[dict[str, str]],
    src: Path,
    upload_type: str,
    zip_name: str,
    sandbox: bool = False,
    publish: bool = True,
    license_id: str = "cc-by-4.0",
    access_right: str = "open",
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Pack src, upload to Zenodo, optionally publish. Returns deposition dict."""
    base = _api_base(sandbox)
    tmp = work_dir or Path(tempfile.mkdtemp(prefix="rh_zenodo_"))
    tmp.mkdir(parents=True, exist_ok=True)
    zip_path = tmp / zip_name
    prefix = "code" if upload_type == "software" else "data"
    archived = pack_zip(src, zip_path, prefix)

    dep = _request("POST", f"{base}/deposit/depositions", token=token, json_body={})
    dep_id = dep["id"]
    bucket = dep["links"]["bucket"]
    reserved = (dep.get("metadata") or {}).get("prereserve_doi") or {}

    with zip_path.open("rb") as fp:
        raw = fp.read()
    _request(
        "PUT",
        f"{bucket}/{zip_path.name}",
        token=token,
        data=raw,
        content_type="application/octet-stream",
        timeout=600,
    )

    meta = {
        "metadata": {
            "title": title,
            "upload_type": upload_type,
            "description": description,
            "creators": creators,
            "access_right": access_right,
            "license": license_id,
        }
    }
    draft = _request(
        "PUT",
        f"{base}/deposit/depositions/{dep_id}",
        token=token,
        json_body=meta,
    )

    result = {
        "deposition_id": dep_id,
        "reserved_doi": reserved.get("doi"),
        "doi": reserved.get("doi"),
        "published": False,
        "files_archived": len(archived),
        "zip_bytes": zip_path.stat().st_size,
        "html_url": (draft.get("links") or {}).get("html"),
    }
    if not publish:
        result["status"] = "draft"
        return result

    pub = _request(
        "POST",
        f"{base}/deposit/depositions/{dep_id}/actions/publish",
        token=token,
        timeout=180,
    )
    doi = pub.get("doi") or reserved.get("doi")
    result.update(
        {
            "status": "published",
            "published": True,
            "doi": doi,
            "doi_url": pub.get("doi_url")
            or (f"https://doi.org/{doi}" if doi else None),
            "html_url": (pub.get("links") or {}).get("html")
            or (pub.get("links") or {}).get("record_html"),
            "record_url": (pub.get("links") or {}).get("record_html"),
        }
    )
    return result


def _creator_from_email(email: str | None, creator: str | None) -> dict[str, str]:
    if creator:
        # "Last, First" or "First Last"
        name = creator.strip()
        if "," not in name and " " in name:
            parts = name.split()
            name = f"{parts[-1]}, {' '.join(parts[:-1])}"
        return {"name": name}
    if email and "@" in email:
        local = email.split("@", 1)[0]
        # hair_du -> Du, Hair ; liub_dl -> Liub, Dl (best-effort)
        bits = re.split(r"[._\-+]", local)
        bits = [b for b in bits if b]
        if len(bits) >= 2:
            # last token as surname if short pattern like hair_du
            return {"name": f"{bits[-1].capitalize()}, {bits[0].capitalize()}"}
        return {"name": local}
    return {"name": "Author, Unknown"}


def deposit_code_and_data(
    *,
    topic_id: int | None = None,
    topic_name: str | None = None,
    title: str | None = None,
    creator: str | None = None,
    email: str | None = None,
    password: str | None = None,
    token: str | None = None,
    code_path: str | Path | None = None,
    data_path: str | Path | None = None,
    deposit_root: str | Path | None = None,
    search_roots: list[str | Path] | None = None,
    sandbox: bool = False,
    publish: bool = True,
    code_license: str = "mit",
    data_license: str = "cc-by-4.0",
) -> DepositResult:
    """End-to-end: resolve paths → auth → deposit code + data → DOIs."""
    try:
        code, data, path_meta = resolve_deposit_paths(
            topic_id=topic_id,
            topic_name=topic_name,
            code_path=code_path,
            data_path=data_path,
            deposit_root=deposit_root,
            search_roots=search_roots,
        )
    except Exception as e:
        return DepositResult(
            status="error",
            topic_id=topic_id,
            topic_name=topic_name,
            error=f"path_resolve: {e}",
        )

    try:
        tok = resolve_token(
            token=token, email=email, password=password, sandbox=sandbox
        )
    except Exception as e:
        return DepositResult(
            status="error",
            topic_id=topic_id,
            topic_name=topic_name,
            code_path=str(code),
            data_path=str(data),
            error=f"auth: {e}",
        )

    display = title or topic_name or f"topic-{topic_id}" or "Research deposit"
    creators = [_creator_from_email(email, creator)]
    work = Path(tempfile.mkdtemp(prefix="rh_zenodo_pair_"))

    try:
        code_res = deposit_one(
            token=tok,
            title=f"Analysis code for: {display}",
            description=(
                f"Replication / analysis code package for «{display}». "
                "Packed automatically by Research Harness deposit.zenodo."
            ),
            creators=creators,
            src=code,
            upload_type="software",
            zip_name="code.zip",
            sandbox=sandbox,
            publish=publish,
            license_id=code_license,
            work_dir=work / "code",
        )
        data_res = deposit_one(
            token=tok,
            title=f"Supporting data for: {display}",
            description=(
                f"Supporting data package for «{display}». "
                "Packed automatically by Research Harness deposit.zenodo."
            ),
            creators=creators,
            src=data,
            upload_type="dataset",
            zip_name="data.zip",
            sandbox=sandbox,
            publish=publish,
            license_id=data_license,
            work_dir=work / "data",
        )
    except Exception as e:
        return DepositResult(
            status="error",
            topic_id=topic_id,
            topic_name=topic_name,
            code_path=str(code),
            data_path=str(data),
            sandbox=sandbox,
            error=str(e),
            details={"path_meta": path_meta},
        )

    published = bool(code_res.get("published") and data_res.get("published"))
    status = "success" if published else "draft"
    return DepositResult(
        status=status,
        topic_id=topic_id,
        topic_name=topic_name,
        code_doi=code_res.get("doi"),
        data_doi=data_res.get("doi"),
        code_url=code_res.get("doi_url")
        or (f"https://doi.org/{code_res['doi']}" if code_res.get("doi") else None),
        data_url=data_res.get("doi_url")
        or (f"https://doi.org/{data_res['doi']}" if data_res.get("doi") else None),
        code_deposition_id=code_res.get("deposition_id"),
        data_deposition_id=data_res.get("deposition_id"),
        published=published,
        sandbox=sandbox,
        code_path=str(code),
        data_path=str(data),
        details={
            "path_meta": path_meta,
            "code": code_res,
            "data": data_res,
        },
    )


def lookup_topic(
    db_path: str | Path,
    topic_id: int | None = None,
    topic_name: str | None = None,
) -> tuple[int | None, str | None]:
    """Return (id, name) from RH pool.db."""
    import sqlite3

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        if topic_id is not None:
            row = conn.execute(
                "SELECT id, name FROM topics WHERE id = ?", (int(topic_id),)
            ).fetchone()
        elif topic_name:
            row = conn.execute(
                "SELECT id, name FROM topics WHERE name = ?", (topic_name,)
            ).fetchone()
        else:
            return None, None
        if row is None:
            return None, None
        return int(row["id"]), str(row["name"])
    finally:
        conn.close()
