#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repo-local unpack_bootimg adapter. Produces metadata stub when AOSP tooling is absent."
    )
    parser.add_argument("--input", required=False)
    parser.add_argument("--out", required=False)
    args = parser.parse_args()
    if not args.input or not args.out:
        parser.print_help()
        return 0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "input": args.input,
        "note": "AOSP unpack_bootimg.py not installed; no binary extraction performed.",
    }
    (out_dir / "bootimg-stub.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
