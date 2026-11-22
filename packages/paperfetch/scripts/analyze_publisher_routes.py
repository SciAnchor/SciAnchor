from __future__ import annotations

import argparse
import json
from pathlib import Path

from paperfetch.downloaders.pipeline.analysis import analyze_publisher_routes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate sanitized publisher route metrics from validation run reports."
    )
    parser.add_argument(
        "inputs", nargs="+", help="Validation roots or run_report.json files"
    )
    parser.add_argument(
        "--output", help="Optional output JSON path; stdout is the default"
    )
    args = parser.parse_args()

    result = analyze_publisher_routes(args.inputs)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
