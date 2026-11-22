#!/usr/bin/env python3
"""Standalone disclosure checker for a blind_submission package.

Run this DELIBERATELY before blind review. It is wired into no execution path
and gates nothing automatically — that is intentional. The three-paper plan
defers code adaptation "until three-paper evidence shows a repeated,
generalizable gap", so this stays a script until the manifest shape is proven.

    ./scripts/check_disclosure_package.py \
        --manifest <episode>/disclosure_manifest.json \
        --package  <episode>/blind_submission \
        [--json]

Exit codes: 0 clean, 1 findings, 2 usage/IO error.

What it checks:  every present asset was declared; every declared asset is
present; roles are known; internal-data and open-data assets carry a
scenario-appropriate justification; open data is cited rather than shipped;
every asset records why a reviewer would ask for it.

What it does NOT check:  whether the disclosed *amount* is right. That is a
scenario judgement. A clean run means "nothing undeclared or unjustified was
found", not "this is the correct disclosure".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "research_harness"))

from research_harness.reports.disclosure_check import (  # noqa: E402
    check_disclosure_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--manifest", required=True, help="disclosure manifest JSON")
    parser.add_argument("--package", required=True, help="blind_submission directory")
    parser.add_argument("--json", action="store_true", help="emit the raw report")
    args = parser.parse_args()

    try:
        report = check_disclosure_package(args.manifest, args.package)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: manifest is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    print(f"Disclosure check: {report['package_dir']}")
    print(
        f"  declared {report['assets_declared']}  present {report['assets_present']}"
    )
    if report["passed"]:
        print("  PASS — nothing undeclared or unjustified")
    else:
        print(f"  FAIL — {len(report['findings'])} finding(s)")
        for finding in report["findings"]:
            print(f"    [{finding['code']}] {finding['path']}")
            print(f"        {finding['detail']}")

    print("  not checked by this tool:")
    for item in report["not_checked"]:
        print(f"    - {item}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
