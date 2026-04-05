#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from arelab.config import Settings  # noqa: E402
from arelab.locks import acquire_workflow_lock, clear_workflow_lock, read_active_workflow  # noqa: E402
from arelab.workflows import load_workflow  # noqa: E402


def state_dir() -> Path:
    path = ROOT_DIR / ".state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_path(workflow: str) -> Path:
    return state_dir() / f"{workflow}.router.pid"


def log_path(workflow: str) -> Path:
    return state_dir() / f"{workflow}.router.log"


def _settings(workflow: str) -> tuple[Settings, Any]:
    settings = Settings.load(ROOT_DIR, workflow=workflow)
    spec = load_workflow(ROOT_DIR, workflow)
    return settings, spec


def _llama_server() -> str:
    env = os.environ.get("ARELAB_LLAMA_SERVER")
    if env:
        return env
    candidate = shutil.which("llama-server")
    if candidate:
        return candidate
    raise FileNotFoundError("llama-server binary not found; set ARELAB_LLAMA_SERVER")


def _router_cmd(workflow: str) -> list[str]:
    _, spec = _settings(workflow)
    router = spec.router
    return [
        _llama_server(),
        "--host",
        str(router.get("host", "127.0.0.1")),
        "--port",
        str(router.get("port", 18080)),
        "--models-dir",
        str(router.get("models_dir", str(Path.home() / "Models"))),
        "--models-max",
        str(router.get("models_max", 1)),
        "--ctx-size",
        str(router.get("ctx_size", 4096)),
        "--batch-size",
        str(router.get("batch_size", 64)),
        "--ubatch-size",
        str(router.get("ubatch_size", 64)),
        "--threads",
        str(router.get("threads", 6)),
        "--device",
        str(router.get("device", "none")),
        "--gpu-layers",
        str(router.get("gpu_layers", 0)),
        "--jinja",
        "--slots",
    ]


def _base_url(workflow: str) -> str:
    settings, _ = _settings(workflow)
    return settings.openai_base_url


def _request(url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _wait_ready(workflow: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    url = f"{_base_url(workflow)}/models"
    while time.time() < deadline:
        try:
            payload = _request(url, timeout=5)
            if payload.get("data") is not None:
                return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise TimeoutError(f"router for {workflow} did not become ready at {url}")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_router(workflow: str, foreground: bool) -> int:
    other = "legion" if workflow == "agency" else "agency"
    if pid_path(other).exists():
        stop_router(other)
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "stop", f"{other}.service"], check=False)
    try:
        acquire_workflow_lock(workflow, "router")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "active": read_active_workflow(workflow)}, indent=2), file=sys.stderr)
        return 2
    pid_file = pid_path(workflow)
    if pid_file.exists():
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if _pid_alive(pid):
            print(json.dumps({"workflow": workflow, "pid": pid, "status": "already-running"}, indent=2))
            return 0
        pid_file.unlink(missing_ok=True)
    cmd = _router_cmd(workflow)
    if foreground:
        try:
            return subprocess.run(cmd, check=False).returncode
        finally:
            clear_workflow_lock(workflow)
    log_handle = log_path(workflow).open("a", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
    _wait_ready(workflow)
    print(
        json.dumps(
            {
                "workflow": workflow,
                "pid": proc.pid,
                "base_url": _base_url(workflow),
                "log_path": str(log_path(workflow)),
            },
            indent=2,
        )
    )
    return 0


def stop_router(workflow: str) -> int:
    pid_file = pid_path(workflow)
    if not pid_file.exists():
        print(json.dumps({"workflow": workflow, "status": "not-running"}, indent=2))
        return 0
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    if _pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not _pid_alive(pid):
                break
            time.sleep(1)
        if _pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
    pid_file.unlink(missing_ok=True)
    clear_workflow_lock(workflow)
    print(json.dumps({"workflow": workflow, "pid": pid, "status": "stopped"}, indent=2))
    return 0


def status_router(workflow: str) -> int:
    pid_file = pid_path(workflow)
    payload = {
        "workflow": workflow,
        "base_url": _base_url(workflow),
        "pid_file": str(pid_file),
        "log_path": str(log_path(workflow)),
        "running": False,
    }
    if pid_file.exists():
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        payload["pid"] = pid
        payload["running"] = _pid_alive(pid)
    print(json.dumps(payload, indent=2))
    return 0


def list_models(workflow: str) -> int:
    print(json.dumps(_request(f"{_base_url(workflow)}/models"), indent=2))
    return 0


def model_action(workflow: str, action: str, model: str) -> int:
    payload = _request(f"{_base_url(workflow)}/models/{action}", {"model": model}, timeout=120)
    print(json.dumps(payload, indent=2))
    return 0


def install_services() -> int:
    services_src = ROOT_DIR / "services"
    services_dst = Path.home() / ".config/systemd/user"
    services_dst.mkdir(parents=True, exist_ok=True)
    for name in ("agency.service", "legion.service"):
        src = services_src / name
        dst = services_dst / name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print(json.dumps({"installed": [str(services_dst / "agency.service"), str(services_dst / "legion.service")]}, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("start", "stop", "status", "list-models"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--workflow", choices=["agency", "legion"], required=True)
        if command == "start":
            cmd.add_argument("--foreground", action="store_true")

    for command in ("load-model", "unload-model"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--workflow", choices=["agency", "legion"], required=True)
        cmd.add_argument("--model", required=True)

    sub.add_parser("install-services")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "start":
        return start_router(args.workflow, args.foreground)
    if args.command == "stop":
        return stop_router(args.workflow)
    if args.command == "status":
        return status_router(args.workflow)
    if args.command == "list-models":
        return list_models(args.workflow)
    if args.command == "load-model":
        return model_action(args.workflow, "load", args.model)
    if args.command == "unload-model":
        return model_action(args.workflow, "unload", args.model)
    if args.command == "install-services":
        return install_services()
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
