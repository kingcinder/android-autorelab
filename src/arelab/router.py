from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arelab.config import Settings
from arelab.locks import read_active_workflow, workflow_lock


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


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


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
    active = read_active_workflow() or {}
    active_pid = int(active.get("pid", 0) or 0)
    if (
        active.get("workflow") == workflow
        and active.get("owner") == "router"
        and active_pid != os.getpid()
        and _pid_alive(active_pid)
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
