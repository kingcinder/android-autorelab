#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repo-local lpunpack adapter. Uses system lpunpack when available."
    )
    parser.add_argument("super_image", nargs="?")
    parser.add_argument("output_dir", nargs="?")
    args = parser.parse_args()
    system = shutil.which("lpunpack")
    if system:
        if args.super_image and args.output_dir:
            return subprocess.call([system, args.super_image, args.output_dir])
        parser.print_help()
        return 0
    if args.super_image and args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        sys.stderr.write("system lpunpack is not installed; adapter created the output directory only\n")
        return 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
