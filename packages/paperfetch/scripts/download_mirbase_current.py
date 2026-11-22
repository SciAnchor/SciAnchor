from __future__ import annotations

import argparse
import json
import os

from paperfetch.datasets.mirbase import download_mirbase_current


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载并校验 miRBase CURRENT 的 mature.fa 与 hairpin.fa"
    )
    parser.add_argument("--output-dir", required=True, help="验证后的 FASTA 输出目录")
    parser.add_argument(
        "--proxy",
        default=os.getenv("SPC_MIRBASE_PROXY") or os.getenv("DOWNLOAD_PROXY"),
        help="显式 HTTP/SOCKS 代理；默认读取 SPC_MIRBASE_PROXY 或 DOWNLOAD_PROXY",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="强制直连并忽略代理环境变量",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args()
    report = download_mirbase_current(
        args.output_dir,
        proxy=None if args.direct else args.proxy,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
