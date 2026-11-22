#!/usr/bin/env python3
"""One-shot: login Zenodo → mint API token → pack code/data → deposit (+optional publish).

Env:
  ZENODO_EMAIL / ZENODO_PASSWORD   required unless --token given
  ZENODO_TOKEN                     optional skip-login path

Examples:
  # draft only (safe)
  python scripts/zenodo_auto_deposit.py \\
    --title "Supporting data and code" \\
    --creator "Last, First" \\
    --code ./code --data ./data \\
    --dry-run

  # publish production DOI
  python scripts/zenodo_auto_deposit.py \\
    --title "..." --creator "Last, First" \\
    --code ./code --data ./data
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="Supporting data and code for the associated manuscript.")
    ap.add_argument("--creator", action="append", required=True)
    ap.add_argument("--code", action="append", type=Path, default=[])
    ap.add_argument("--data", action="append", type=Path, default=[])
    ap.add_argument("--extra", action="append", type=Path, default=[])
    ap.add_argument("--upload-type", default="software", choices=["software", "dataset", "other"])
    ap.add_argument("--license", dest="license_id", default="cc-by-4.0")
    # Deposits accompanying a manuscript under review are restricted by default:
    # the DOI is minted and citable, but the link alone does not open the files.
    ap.add_argument("--access-right", default="restricted",
                    choices=["open", "embargoed", "restricted", "closed"])
    ap.add_argument("--access-conditions",
                    default="Files are restricted while the associated manuscript "
                            "is under review. Access requests from editors and "
                            "reviewers are granted on request.")
    ap.add_argument("--embargo-date", default="",
                    help="YYYY-MM-DD; required when --access-right=embargoed")
    ap.add_argument("--sandbox", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Upload draft only; do not publish")
    ap.add_argument("--token", default=None, help="Reuse existing token; skip browser login")
    ap.add_argument("--email", default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--keep-zip", type=Path, default=None)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)

    if not args.code and not args.data and not args.extra:
        ap.error("Provide at least one of --code / --data / --extra")

    token = args.token or os.environ.get("ZENODO_TOKEN")
    if not token:
        email = args.email or os.environ.get("ZENODO_EMAIL")
        password = args.password or os.environ.get("ZENODO_PASSWORD")
        if not email or not password:
            print("Need --token / ZENODO_TOKEN, or ZENODO_EMAIL+ZENODO_PASSWORD", file=sys.stderr)
            return 2
        auto = _load("zenodo_auto_token", ROOT / "zenodo_auto_token.py")
        print("logging in headless → creating personal access token...", flush=True)
        token = auto.login_and_create_token(
            email=email,
            password=password,
            sandbox=args.sandbox,
            token_name=f"rh-deposit-{int(time.time())}",
            headless=not args.headed,
        )
        print("token acquired (not printed)", flush=True)

    deposit = _load("zenodo_deposit", ROOT / "zenodo_deposit.py")
    cmd = [
        sys.executable,
        str(ROOT / "zenodo_deposit.py"),
        "--title",
        args.title,
        "--description",
        args.description,
        "--upload-type",
        args.upload_type,
        "--license",
        args.license_id,
        "--access-right",
        args.access_right,
        "--access-conditions",
        args.access_conditions,
        "--token",
        token,
    ]
    if args.embargo_date:
        cmd += ["--embargo-date", args.embargo_date]
    for c in args.creator:
        cmd += ["--creator", c]
    for p in args.code:
        cmd += ["--code", str(p)]
    for p in args.data:
        cmd += ["--data", str(p)]
    for p in args.extra:
        cmd += ["--extra", str(p)]
    if args.sandbox:
        cmd.append("--sandbox")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.keep_zip:
        cmd += ["--keep-zip", str(args.keep_zip)]

    # avoid leaking token via shell history: pass as argv only in this process tree
    print(
        f"depositing ({'sandbox' if args.sandbox else 'PRODUCTION'}"
        f"{', draft' if args.dry_run else ', PUBLISH'}"
        f", access={args.access_right})...",
        flush=True,
    )
    env = os.environ.copy()
    env["ZENODO_TOKEN"] = token
    # strip password from child env
    env.pop("ZENODO_PASSWORD", None)
    # re-exec deposit module in-process to keep token out of `ps` a bit cleaner
    return deposit.main(
        [
            "--title",
            args.title,
            "--description",
            args.description,
            "--upload-type",
            args.upload_type,
            "--license",
            args.license_id,
            "--token",
            token,
            *sum([["--creator", c] for c in args.creator], []),
            *sum([["--code", str(p)] for p in args.code], []),
            *sum([["--data", str(p)] for p in args.data], []),
            *sum([["--extra", str(p)] for p in args.extra], []),
            *(["--sandbox"] if args.sandbox else []),
            *(["--dry-run"] if args.dry_run else []),
            *(["--keep-zip", str(args.keep_zip)] if args.keep_zip else []),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
