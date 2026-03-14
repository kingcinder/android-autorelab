from __future__ import annotations

import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

from arelab.config import Settings
from arelab.locks import workflow_lock


def _router_command(settings: Settings) -> list[str]:
    router = settings.workflow_config.get("router", {})
    server = router.get("llama_server") or shutil.which("llama-server") or "llama-server"
    command = [
        server,
        "--host",
        str(router.get("host", "127.0.0.1")),
        "--port",
        str(router.get("port", 10081)),
        "--models-dir",
        str(router.get("models_dir", settings.repo_root / "models")),
        "--models-max",
        str(router.get("models_max", 1)),
        "--ctx-size",
        str(router.get("ctx_size", 4096)),
        "--jinja",
    ]
    if not router.get("autoload", False):
        command.append("--no-models-autoload")
    for arg in router.get("extra_args", []):
        command.append(str(arg))
    return command


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m arelab.workflow_service <repo_root> <workflow>")

    repo_root = Path(sys.argv[1]).resolve()
    workflow = sys.argv[2]
    settings = Settings.load(repo_root, workflow=workflow)
    process: subprocess.Popen[str] | None = None
    stopping = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        if process and process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    with workflow_lock(workflow, "service"):
        process = subprocess.Popen(  # noqa: S603
            _router_command(settings),
            cwd=str(repo_root),
        )
        try:
            while not stopping and process.poll() is None:
                time.sleep(1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
