#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from arelab.config import Settings
from arelab.locks import clear_workflow_lock, workflow_lock
from arelab.model_gateway import ModelGateway
from arelab.router import RouterClient


def wait_for_router(base_url: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    url = f"{base_url.rstrip('/')}/models"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for router at {url}")


def router_command(settings: Settings) -> list[str]:
    router = settings.workflow_config.get("router", {})
    binary = os.environ.get("ARELAB_LLAMA_SERVER") or shutil.which("llama-server")
    if not binary:
        raise FileNotFoundError("llama-server not found; set ARELAB_LLAMA_SERVER")
    return [
        str(binary),
        "--models-dir",
        str(router.get("models_dir", settings.repo_root / "models")),
        "--models-max",
        str(router.get("models_max", 1)),
        "--host",
        str(router.get("host", "127.0.0.1")),
        "--port",
        str(router.get("port", 18081)),
        "--ctx-size",
        str(router.get("ctx_size", 4096)),
        "--batch-size",
        str(router.get("batch_size", 64)),
        "--ubatch-size",
        str(router.get("ubatch_size", 64)),
        "--threads",
        str(router.get("threads", 6)),
        "--jinja",
        "--device",
        str(router.get("device", "none")),
        "--gpu-layers",
        str(router.get("gpu_layers", 0)),
        "--slots",
        "--api-key",
        os.environ.get("ARELAB_OPENAI_API_KEY", "none"),
    ]


def run_service(repo_root: Path, workflow: str) -> int:
    settings = Settings.load(repo_root, workflow=workflow)
    planner = settings.model_pins.get("planner")
    preload = workflow == "legion" and planner

    with workflow_lock(workflow, "service"):
        proc = subprocess.Popen(router_command(settings))
        try:
            wait_for_router(settings.openai_base_url)
            if preload:
                gateway = ModelGateway(settings, repo_root / "runs" / workflow / "_service-prompts")
                client = RouterClient(settings)
                client.load_model(planner)
                gateway.available_models()
            return proc.wait()
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
            clear_workflow_lock(workflow)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", nargs="?")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--clear-lock", dest="clear_lock", default=None)
    args = parser.parse_args()
    if args.clear_lock:
        clear_workflow_lock(args.clear_lock)
        return 0
    if not args.workflow:
        raise SystemExit("workflow is required")
    return run_service(Path(args.repo_root).resolve(), args.workflow)


if __name__ == "__main__":
    raise SystemExit(main())
