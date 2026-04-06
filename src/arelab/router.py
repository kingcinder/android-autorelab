from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arelab.config import Settings
from arelab.locks import pid_alive, read_active_workflow, state_path, workflow_lock


_ROUTER_START_LOCKS: dict[str, threading.Lock] = {}


def _router_start_lock(workflow: str) -> threading.Lock:
    lock = _ROUTER_START_LOCKS.get(workflow)
    if lock is None:
        lock = threading.Lock()
        _ROUTER_START_LOCKS[workflow] = lock
    return lock


def router_pid_path(workflow: str) -> Path:
    runtime = state_path(workflow).parent
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / f"{workflow}-router.pid"


def router_log_path(workflow: str) -> Path:
    runtime = state_path(workflow).parent
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / f"{workflow}-router.log"


def _read_router_pid(workflow: str) -> int | None:
    path = router_pid_path(workflow)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return None


def _router_log_excerpt(workflow: str, lines: int = 20) -> str:
    path = router_log_path(workflow)
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _router_launch_command(settings: Settings) -> list[str]:
    script = settings.repo_root / "scripts" / "run_router.py"
    return [
        sys.executable,
        str(script),
        "--repo-root",
        str(settings.repo_root),
        "--workflow",
        settings.workflow,
    ]


class RouterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.workflow_config.get("router", {}).get("base_url", settings.openai_base_url).rstrip("/")
        self.manage_base_url = self.base_url.removesuffix("/v1")

    def _request(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        data = None
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method="POST" if data else "GET",
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (http.client.RemoteDisconnected, ConnectionResetError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1)
        if last_error:
            raise last_error
        raise RuntimeError(f"request failed for {path}")

    def _manage_request(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        data = None
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.manage_base_url}{path}",
            data=data,
            headers=headers,
            method="POST" if data else "GET",
        )
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (http.client.RemoteDisconnected, ConnectionResetError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt == 4:
                    raise
                time.sleep(1)
        if last_error:
            raise last_error
        raise RuntimeError(f"management request failed for {path}")

    def wait_until_ready(self, timeout: int = 60) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.list_models()
                return
            except Exception:  # noqa: BLE001
                time.sleep(1)
        raise TimeoutError(f"router at {self.base_url} did not become ready")

    def list_models(self) -> list[dict[str, Any]]:
        try:
            payload = self._manage_request("/models", timeout=20)
        except Exception:  # noqa: BLE001
            payload = self._request("/models", timeout=20)
        return payload.get("data", [])

    def status_map(self) -> dict[str, str]:
        return {
            item.get("id", ""): item.get("status", {}).get("value", "unknown")
            for item in self.list_models()
        }

    def loaded_models(self) -> list[str]:
        return [name for name, status in self.status_map().items() if status == "loaded"]

    def active_models(self) -> list[str]:
        return [
            name
            for name, status in self.status_map().items()
            if status in {"loading", "loaded"}
        ]

    def load_model(self, model: str, timeout: int = 240) -> dict[str, Any]:
        return self._manage_request("/models/load", payload={"model": model}, timeout=timeout)

    def unload_model(self, model: str, timeout: int = 240) -> dict[str, Any]:
        try:
            return self._manage_request("/models/unload", payload={"model": model}, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                return {"success": False, "ignored": True, "model": model}
            raise

    def warm_model(self, model: str, timeout: int = 180) -> None:
        chat_payload = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 128,
            "messages": [
                {
                    "role": "system",
                    "content": "Return compact JSON only. No reasoning in the final answer.",
                },
                {
                    "role": "user",
                    "content": 'Return exactly this JSON object and nothing else: {"ok": true}',
                },
            ],
        }
        try:
            self._request("/chat/completions", payload=chat_payload, timeout=timeout)
            return
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
        completion_payload = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 32,
            "prompt": 'Return exactly this JSON object and nothing else: {"ok": true}',
        }
        try:
            self._request("/completions", payload=completion_payload, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise

    def wait_for_model_state(
        self,
        model: str,
        *,
        expected: set[str],
        timeout: int = 180,
        settle_seconds: float = 1.0,
    ) -> str:
        deadline = time.time() + timeout
        last_state = "unknown"
        while time.time() < deadline:
            last_state = self.status_map().get(model, "unknown")
            if last_state in expected:
                if settle_seconds:
                    time.sleep(settle_seconds)
                return last_state
            time.sleep(1)
        raise TimeoutError(
            f"model {model} did not reach any of {sorted(expected)} within {timeout}s; last_state={last_state}"
        )


def ensure_router_ready(settings: Settings, *, timeout: int = 30) -> None:
    workflow = settings.workflow
    if workflow not in {"agency", "legion"}:
        return
    client = RouterClient(settings)
    try:
        client.wait_until_ready(timeout=2)
        return
    except Exception:  # noqa: BLE001
        pass
    with _router_start_lock(workflow):
        try:
            client.wait_until_ready(timeout=2)
            return
        except Exception:  # noqa: BLE001
            pass
        pid = _read_router_pid(workflow)
        if pid and pid_alive(pid):
            try:
                client.wait_until_ready(timeout=timeout)
                return
            except Exception as exc:  # noqa: BLE001
                excerpt = _router_log_excerpt(workflow)
                raise RuntimeError(
                    f"{workflow} router process {pid} is running but {client.base_url} never became ready."
                    + (f"\nRecent router log output:\n{excerpt}" if excerpt else "")
                ) from exc
        router_pid_path(workflow).unlink(missing_ok=True)
        log_path = router_log_path(workflow)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting {workflow} router\n")
            handle.flush()
            process = subprocess.Popen(
                _router_launch_command(settings),
                cwd=str(settings.repo_root),
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        router_pid_path(workflow).write_text(f"{process.pid}\n", encoding="utf-8")
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                client.wait_until_ready(timeout=2)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if process.poll() is not None:
                    router_pid_path(workflow).unlink(missing_ok=True)
                    excerpt = _router_log_excerpt(workflow)
                    raise RuntimeError(
                        f"{workflow} router exited before {client.base_url} became ready (pid={process.pid}, exit_code={process.returncode})."
                        + (f"\nRecent router log output:\n{excerpt}" if excerpt else "")
                    ) from exc
        excerpt = _router_log_excerpt(workflow)
        raise RuntimeError(
            f"{workflow} router could not be started for {client.base_url} (pid={process.pid})."
            + (f"\nRecent router log output:\n{excerpt}" if excerpt else "")
        ) from last_error


def build_router_command(settings: Settings, llama_bin: Path) -> list[str]:
    router = settings.workflow_config.get("router", {})
    models_dir = router.get("models_dir") or str(settings.repo_root / "models")
    command = [
        str(llama_bin),
        "--models-dir",
        str(models_dir),
        "--models-max",
        str(router.get("models_max", 1)),
        "--host",
        str(router.get("host", "127.0.0.1")),
        "--port",
        str(router.get("port", 18080)),
        "--ctx-size",
        str(router.get("ctx_size", 4096)),
        "--threads",
        str(router.get("threads", 6)),
        "--batch-size",
        str(router.get("batch_size", 64)),
        "--ubatch-size",
        str(router.get("ubatch_size", 64)),
        "--jinja",
        "--device",
        str(router.get("device", "none")),
        "--gpu-layers",
        str(router.get("gpu_layers", 0)),
        "--no-kv-offload",
        "--no-op-offload",
    ]
    if not router.get("autoload", False):
        command.append("--no-models-autoload")
    for arg in router.get("extra_args", []):
        if arg not in command:
            command.append(str(arg))
    return command


def run_router_foreground(repo_root: Path, workflow: str, llama_bin: Path) -> int:
    settings = Settings.load(repo_root, workflow=workflow)
    exclusive_with = settings.workflow_config.get("exclusive_with")
    if exclusive_with:
        active_other = read_active_workflow(str(exclusive_with)) or {}
        other_pid = int(active_other.get("pid", 0) or 0)
        if (
            active_other.get("workflow") == exclusive_with
            and other_pid != os.getpid()
            and pid_alive(other_pid)
        ):
            raise RuntimeError(f"{workflow} router cannot start while {exclusive_with} is active (pid={other_pid})")
    active = read_active_workflow(workflow) or {}
    active_pid = int(active.get("pid", 0) or 0)
    if (
        active.get("workflow") == workflow
        and active.get("owner") == "router"
        and active_pid != os.getpid()
        and pid_alive(active_pid)
    ):
        raise RuntimeError(f"{workflow} router already active (pid={active_pid})")
    command = build_router_command(settings, llama_bin)
    with workflow_lock(workflow, "router"):
        process = subprocess.Popen(command, stdin=subprocess.PIPE)

        def _forward(sig: int, _frame: object) -> None:
            if process.poll() is None:
                process.send_signal(sig)

        signal.signal(signal.SIGTERM, _forward)
        signal.signal(signal.SIGINT, _forward)
        return process.wait()
