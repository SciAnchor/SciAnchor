#!/usr/bin/env python3
"""Pack code+data and mint a Zenodo DOI via REST API.

Auth is TOKEN only (not username/password):
  export ZENODO_TOKEN=...   # https://zenodo.org/account/settings/applications/
  # sandbox token from https://sandbox.zenodo.org/account/settings/applications/

Usage:
  python scripts/zenodo_deposit.py \\
    --title "Supporting data and code" \\
    --code /path/to/code --data /path/to/data \\
    --creator "Last, First" \\
    --sandbox --dry-run          # pack+upload draft, no publish

  python scripts/zenodo_deposit.py ... --sandbox   # publish on sandbox (test DOI)
  python scripts/zenodo_deposit.py ...             # publish on production
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

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


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_DIR_NAMES or path.name == ".DS_Store":
        return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    return False


def pack_zip(paths: list[tuple[str, Path]], out_zip: Path) -> list[str]:
    """Zip (arc_prefix, src_path) pairs. Returns list of archived relative paths."""
    archived: list[str] = []
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for prefix, src in paths:
            src = src.resolve()
            if not src.exists():
                raise FileNotFoundError(src)
            if src.is_file():
                arc = f"{prefix}/{src.name}" if prefix else src.name
                zf.write(src, arcname=arc)
                archived.append(arc)
                continue
            for root, dirs, files in os.walk(src):
                root_p = Path(root)
                dirs[:] = [d for d in dirs if not _should_skip(root_p / d)]
                for name in files:
                    fp = root_p / name
                    if _should_skip(fp):
                        continue
                    rel = fp.relative_to(src)
                    arc = f"{prefix}/{rel.as_posix()}" if prefix else rel.as_posix()
                    zf.write(fp, arcname=arc)
                    archived.append(arc)
    return archived


def deposit(
    *,
    token: str,
    title: str,
    description: str,
    creators: list[dict],
    upload_type: str,
    zip_path: Path,
    sandbox: bool,
    publish: bool,
    license_id: str,
    access_right: str,
    access_conditions: str = "",
    embargo_date: str = "",
) -> dict:
    base = "https://sandbox.zenodo.org/api" if sandbox else "https://zenodo.org/api"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    auth_only = {"Authorization": f"Bearer {token}"}

    r = requests.post(f"{base}/deposit/depositions", json={}, headers=headers, timeout=60)
    r.raise_for_status()
    dep = r.json()
    dep_id = dep["id"]
    bucket = dep["links"]["bucket"]
    reserved = (dep.get("metadata") or {}).get("prereserve_doi") or {}
    reserved_doi = reserved.get("doi")

    with zip_path.open("rb") as fp:
        up = requests.put(
            f"{bucket}/{zip_path.name}",
            data=fp,
            headers=auth_only,
            timeout=600,
        )
    up.raise_for_status()

    metadata = {
        "title": title,
        "upload_type": upload_type,
        "description": description,
        "creators": creators,
        "access_right": access_right,
    }
    # A restricted record needs access_conditions -- that text is what someone
    # requesting access is shown. The licence is only strictly required for
    # open/embargoed records, but setting it now means the record is already
    # correct if the deposit is later opened.
    metadata["license"] = license_id
    if access_right == "restricted":
        metadata["access_conditions"] = access_conditions
    elif access_right == "embargoed":
        metadata["embargo_date"] = embargo_date

    meta = {"metadata": metadata}
    m = requests.put(
        f"{base}/deposit/depositions/{dep_id}",
        data=json.dumps(meta),
        headers=headers,
        timeout=60,
    )
    m.raise_for_status()
    draft = m.json()

    result = {
        "deposition_id": dep_id,
        "sandbox": sandbox,
        "reserved_doi": reserved_doi,
        "published": False,
        "doi": reserved_doi,
        "html_url": draft.get("links", {}).get("html"),
        "record_url": None,
    }

    if not publish:
        result["status"] = "draft"
        return result

    p = requests.post(
        f"{base}/deposit/depositions/{dep_id}/actions/publish",
        headers=auth_only,
        timeout=120,
    )
    p.raise_for_status()
    pub = p.json()
    result.update(
        {
            "status": "published",
            "published": True,
            "doi": pub.get("doi") or reserved_doi,
            "doi_url": pub.get("doi_url") or (
                f"https://doi.org/{pub.get('doi')}" if pub.get("doi") else None
            ),
            "record_url": pub.get("links", {}).get("record_html")
            or pub.get("links", {}).get("html"),
            "html_url": pub.get("links", {}).get("html"),
        }
    )
    return result


def parse_creators(raw: list[str]) -> list[dict]:
    out = []
    for item in raw:
        # "Last, First" or "Last, First|ORCID"
        name, _, orcid = item.partition("|")
        entry: dict = {"name": name.strip()}
        if orcid.strip():
            entry["orcid"] = orcid.strip()
        out.append(entry)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="Supporting data and code for the associated manuscript.")
    ap.add_argument("--creator", action="append", required=True, help='Repeatable. "Last, First" or "Last, First|0000-0000-..."')
    ap.add_argument("--code", action="append", type=Path, default=[], help="Code dir/file (repeatable)")
    ap.add_argument("--data", action="append", type=Path, default=[], help="Data dir/file (repeatable)")
    ap.add_argument("--extra", action="append", type=Path, default=[], help="Extra path packed under extra/ (repeatable)")
    ap.add_argument("--zip-name", default="data-and-code.zip")
    ap.add_argument("--keep-zip", type=Path, default=None, help="Keep the built zip at this path")
    ap.add_argument("--upload-type", default="software", choices=["software", "dataset", "other"])
    ap.add_argument("--license", dest="license_id", default="cc-by-4.0")
    # Deposits accompanying a manuscript under review default to restricted:
    # the DOI is minted and citable, but holding the link does not grant access
    # to the files. Opening a record later is a deliberate act; a record
    # published open cannot be closed again.
    ap.add_argument("--access-right", default="restricted",
                    choices=["open", "embargoed", "restricted", "closed"])
    ap.add_argument("--access-conditions",
                    default="Files are restricted while the associated manuscript "
                            "is under review. Access requests from editors and "
                            "reviewers are granted on request.",
                    help="Shown to anyone requesting access to a restricted record")
    ap.add_argument("--embargo-date", default="",
                    help="YYYY-MM-DD; required when --access-right=embargoed")
    ap.add_argument("--sandbox", action="store_true", help="Use sandbox.zenodo.org (test DOI)")
    ap.add_argument("--dry-run", action="store_true", help="Upload draft only; do not publish / mint live DOI")
    ap.add_argument("--token-env", default="ZENODO_TOKEN", help="Env var holding the access token")
    ap.add_argument("--token", default=None, help="Token override (prefer env var)")
    args = ap.parse_args(argv)

    if not args.code and not args.data and not args.extra:
        ap.error("Provide at least one of --code / --data / --extra")

    token = args.token or os.environ.get(args.token_env)
    if not token:
        print(
            f"Missing token. Create one at zenodo Applications, then:\n"
            f"  export {args.token_env}=...\\n"
            f"Sandbox needs a separate sandbox token.",
            file=sys.stderr,
        )
        return 2

    pairs: list[tuple[str, Path]] = []
    for p in args.code:
        pairs.append(("code", p))
    for p in args.data:
        pairs.append(("data", p))
    for p in args.extra:
        pairs.append(("extra", p))

    tmp_dir = None
    if args.keep_zip:
        zip_path = args.keep_zip.resolve()
        zip_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir = tempfile.mkdtemp(prefix="zenodo_deposit_")
        zip_path = Path(tmp_dir) / args.zip_name

    print(f"packing → {zip_path}")
    archived = pack_zip(pairs, zip_path)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"packed {len(archived)} files, {size_mb:.2f} MB")

    if args.access_right == "embargoed" and not args.embargo_date:
        print("--access-right=embargoed requires --embargo-date YYYY-MM-DD",
              file=sys.stderr)
        return 2
    if args.access_right == "restricted" and not args.access_conditions.strip():
        print("--access-right=restricted requires non-empty --access-conditions",
              file=sys.stderr)
        return 2

    print(
        f"depositing to {'sandbox' if args.sandbox else 'PRODUCTION'}"
        f"{' (draft only)' if args.dry_run else ' (WILL PUBLISH)'}"
        f" · access={args.access_right}"
    )
    if not args.sandbox and not args.dry_run:
        print("WARNING: production publish is permanent for this version.", file=sys.stderr)
        if args.access_right == "open":
            print("WARNING: access_right=open makes the files publicly downloadable "
                  "immediately, and an open record cannot later be closed.",
                  file=sys.stderr)

    try:
        result = deposit(
            token=token,
            title=args.title,
            description=args.description,
            creators=parse_creators(args.creator),
            upload_type=args.upload_type,
            zip_path=zip_path,
            sandbox=args.sandbox,
            publish=not args.dry_run,
            license_id=args.license_id,
            access_right=args.access_right,
            access_conditions=args.access_conditions,
            embargo_date=args.embargo_date,
        )
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        print(f"HTTP error: {e}\n{body}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("doi"):
        print(f"\nDOI: https://doi.org/{result['doi']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
