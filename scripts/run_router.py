#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from arelab.router import run_router_foreground


def default_llama_bin() -> str:
    env = os.environ.get("ARELAB_LLAMA_SERVER")
    if env:
        return env
    resolved = shutil.which("llama-server")
    if resolved:
        return resolved
    return "llama-server"


def resolve_llama_bin(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or "/" in value:
        return candidate.resolve()
    resolved = shutil.which(value)
    if resolved:
        return Path(resolved).resolve()
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a workflow-specific llama.cpp router in the foreground.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--workflow", required=True, choices=["agency", "legion"])
    parser.add_argument(
        "--llama-bin",
        default=default_llama_bin(),
    )
    args = parser.parse_args()
    return run_router_foreground(Path(args.repo_root).resolve(), args.workflow, resolve_llama_bin(args.llama_bin))


if __name__ == "__main__":
    raise SystemExit(main())
