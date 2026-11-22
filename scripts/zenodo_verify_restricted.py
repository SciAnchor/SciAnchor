#!/usr/bin/env python3
"""Prove that a deposit is citable but not readable.

Depositing a client's data and code under a DOI that turns out to be publicly
downloadable is not a recoverable mistake: a published Zenodo record cannot be
un-published, and an open record cannot later be closed. So the restricted
state is verified from the outside -- an unauthenticated fetch, the way a
stranger holding the DOI would see it -- rather than trusted from the upload
response.

The check is deliberately paranoid about the direction of failure. Anything it
cannot confirm is reported as a failure, never as a pass.

Usage:
    # rehearse the whole flow on sandbox, then verify what a stranger sees
    python3 scripts/zenodo_verify_restricted.py --self-test --sandbox

    # verify a record that already exists
    python3 scripts/zenodo_verify_restricted.py --record 4562981
    python3 scripts/zenodo_verify_restricted.py --doi 10.5281/zenodo.4562981

Exit code 0 only when the record is citable and its files are not public.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent


def fetch(url: str, timeout: int = 20) -> tuple[int, dict | None]:
    """Unauthenticated GET -- deliberately no token, this is the stranger's view."""
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}),
                     timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except HTTPError as e:
        return e.code, None
    except (URLError, TimeoutError, json.JSONDecodeError):
        return 0, None


def verify(record_id: str, sandbox: bool) -> tuple[bool, list[str]]:
    host = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    status, rec = fetch(f"https://{host}/api/records/{record_id}")
    lines = []

    if status != 200 or rec is None:
        return False, [f"record {record_id} is not publicly resolvable (HTTP {status}); "
                       f"a citable DOI must return its metadata to anyone"]

    md = rec.get("metadata") or {}
    access = md.get("access_right") or rec.get("access", {}).get("files")
    doi = rec.get("doi") or md.get("doi")
    files = rec.get("files") or []

    lines.append(f"record     : {record_id} on {host}")
    lines.append(f"title      : {(md.get('title') or '')[:70]}")
    lines.append(f"doi        : {doi}")
    lines.append(f"access     : {access}")
    lines.append(f"files listed to an anonymous caller: {len(files)}")

    ok = True
    if not doi:
        lines.append("FAIL: no DOI on the record -- it is not citable")
        ok = False
    if access in ("open", "public"):
        lines.append(f"FAIL: access_right is {access!r}; the files are public")
        ok = False
    if files:
        names = [f.get("key") or f.get("filename") for f in files][:5]
        lines.append(f"FAIL: files are exposed to an anonymous caller: {names}")
        ok = False

    # A download link that serves bytes without a token is the failure that
    # matters most, so probe it directly rather than inferring from metadata.
    for f in files:
        link = (f.get("links") or {}).get("self") or (f.get("links") or {}).get("download")
        if not link:
            continue
        code, _ = fetch(link, timeout=15)
        if code == 200:
            lines.append(f"FAIL: {f.get('key')} downloads without authentication")
            ok = False

    if ok:
        lines.append("PASS: the DOI resolves and the metadata is public, "
                     "but the files are not retrievable without access")
    return ok, lines


def self_test(sandbox: bool) -> int:
    """Deposit a throwaway package, then verify it from the outside."""
    token = os.environ.get("ZENODO_TOKEN", "").strip()
    if not token:
        print("self-test needs ZENODO_TOKEN (a sandbox token for --sandbox)",
              file=sys.stderr)
        return 2
    if not sandbox:
        print("refusing to run the self-test against production; pass --sandbox",
              file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        payload = Path(tmp) / "data"
        payload.mkdir()
        (payload / "README.txt").write_text(
            "Throwaway payload for verifying restricted-access deposits.\n")

        cmd = [
            sys.executable, str(ROOT / "zenodo_deposit.py"),
            "--title", "Restricted-access verification (throwaway)",
            "--description", "Created by zenodo_verify_restricted.py to confirm "
                             "that a minted DOI does not expose its files.",
            "--creator", "Test, Harness",
            "--data", str(payload),
            "--upload-type", "dataset",
            "--access-right", "restricted",
            "--sandbox",
        ]
        print("depositing a throwaway restricted record on sandbox ...")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            return 1

        m = re.search(r"(?:sandbox\.)?zenodo\.\d+|10\.5072/zenodo\.(\d+)", proc.stdout)
        rec = None
        try:
            payload_json = json.loads(proc.stdout[proc.stdout.index("{"):])
            rec = str(payload_json.get("deposition_id") or "")
            doi = payload_json.get("doi") or ""
            if not rec and doi:
                rec = doi.rsplit(".", 1)[-1]
        except (ValueError, json.JSONDecodeError):
            if m:
                rec = m.group(1)
        if not rec:
            print("could not determine the record id from the deposit output",
                  file=sys.stderr)
            return 1

    print()
    ok, lines = verify(rec, sandbox=True)
    print("\n".join(lines))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", help="Zenodo record id")
    ap.add_argument("--doi", help="full DOI, e.g. 10.5281/zenodo.4562981")
    ap.add_argument("--sandbox", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="deposit a throwaway record on sandbox, then verify it")
    args = ap.parse_args()

    if args.self_test:
        return self_test(args.sandbox)

    rec = args.record
    if not rec and args.doi:
        rec = args.doi.rsplit(".", 1)[-1]
    if not rec:
        print("pass --record, --doi, or --self-test", file=sys.stderr)
        return 2

    ok, lines = verify(rec, args.sandbox)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
