#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repo-local avbtool adapter for read-only inspection workflows."
    )
    parser.add_argument("command", nargs="?")
    parser.add_argument("image", nargs="?")
    parser.add_argument("--json", dest="json_out", action="store_true")
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    payload = {
        "command": args.command,
        "image": args.image,
        "note": "System avbtool not installed; this adapter only records requested read-only actions.",
    }
    if args.json_out:
        print(json.dumps(payload, indent=2))
    else:
        print(payload["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
