#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from arelab.config import Settings
from arelab.router import run_router_foreground


def resolve_llama_bin(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or "/" in value:
        return candidate.resolve()
    resolved = shutil.which(value)
    if resolved:
        return Path(resolved).resolve()
    return candidate


def default_llama_bin(repo_root: Path, workflow: str) -> str:
    env = os.environ.get("ARELAB_LLAMA_SERVER")
    if env:
        return env
    settings = Settings.load(repo_root, workflow=workflow)
    configured = settings.tool_overrides.get("llama_server")
    if configured:
        return configured
    resolved = shutil.which("llama-server")
    if resolved:
        return resolved
    return "llama-server"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a workflow-specific llama.cpp router in the foreground.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--workflow", required=True, choices=["agency", "legion"])
    parser.add_argument("--llama-bin", default=None)
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    llama_bin = args.llama_bin or default_llama_bin(repo_root, args.workflow)
    return run_router_foreground(repo_root, args.workflow, resolve_llama_bin(llama_bin))


if __name__ == "__main__":
    raise SystemExit(main())
