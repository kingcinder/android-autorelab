#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError

from arelab.config import Settings
from arelab.locks import read_active_workflow
from arelab.router import RouterClient


def _latest_run_id(runs_root: Path) -> str:
    run_dirs = sorted(
        [
            path
            for path in runs_root.iterdir()
            if path.is_dir() and not path.name.startswith("_") and (path / "run.json").exists()
        ],
        reverse=True,
    )
    if not run_dirs:
        raise RuntimeError("no run directories found")
    return run_dirs[0].name


def _assert_loaded_cap(client: RouterClient, cap: int) -> list[str]:
    deadline = time.time() + 30
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            active = client.active_models()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
            continue
        if len(active) > cap:
            raise RuntimeError(f"active models exceed cap {cap}: {active}")
        return active
    if last_error:
        raise last_error
    raise RuntimeError("timed out waiting for active model list")


def _status_of(client: RouterClient, model: str) -> str:
    try:
        return client.status_map().get(model, "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _wait_for_status(client: RouterClient, model: str, expected: set[str], timeout: int) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _status_of(client, model)
        if status in expected:
            return status
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for {model} status in {sorted(expected)}; last={_status_of(client, model)}")


def _assert_model_loaded(client: RouterClient, model: str, cap: int) -> list[str]:
    active = _assert_loaded_cap(client, cap)
    loaded = client.loaded_models()
    if model not in loaded:
        raise RuntimeError(f"{model} is not loaded; active={active} loaded={loaded}")
    return loaded


def _runtime_dir() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "android-autorelab"
    return Path("/tmp") / f"android-autorelab-{os.getuid()}"


def _launcher_pid(workflow: str) -> int | None:
    pid_file = _runtime_dir() / f"{workflow}-router.pid"
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        active = read_active_workflow() or {}
        if active.get("workflow") == workflow:
            try:
                return int(active.get("pid", 0) or 0) or None
            except Exception:  # noqa: BLE001
                return None
        return None


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock_state(workflow: str) -> dict[str, object]:
    active = read_active_workflow() or {}
    if active.get("workflow") != workflow:
        raise RuntimeError(f"active workflow lock mismatch: expected {workflow}, got {active or None}")
    active_pid = int(active.get("pid", 0) or 0)
    if not _pid_alive(active_pid):
        raise RuntimeError(f"workflow lock for {workflow} points at a dead pid: {active_pid}")
    return active


def _assert_router_listening(settings: Settings) -> None:
    router = settings.workflow_config.get("router", {})
    host = str(router.get("host", "127.0.0.1"))
    port = int(router.get("port", 0) or 0)
    if port <= 0:
        raise RuntimeError(f"invalid router port configured for {settings.workflow}: {port}")
    sock = socket.socket()
    sock.settimeout(1.0)
    try:
        sock.connect((host, port))
    except OSError as exc:
        raise RuntimeError(f"router socket is not reachable at {host}:{port}") from exc
    finally:
        sock.close()


def _assert_router_process(workflow: str) -> tuple[int, str]:
    pid = _launcher_pid(workflow)
    if not _pid_alive(pid):
        raise RuntimeError(f"missing live launcher pid for {workflow}")
    cmdline = Path(f"/proc/{pid}/cmdline").read_text(encoding="utf-8").replace("\x00", " ").strip()
    if "run_router.py" not in cmdline or workflow not in cmdline:
        raise RuntimeError(f"launcher pid {pid} is not the expected {workflow} router wrapper: {cmdline}")
    return pid, cmdline


def _process_rows() -> dict[int, tuple[int, int]]:
    rows = subprocess.check_output(["ps", "-eo", "pid=,ppid=,rss="], text=True).splitlines()
    result: dict[int, tuple[int, int]] = {}
    for row in rows:
        parts = row.split()
        if len(parts) != 3:
            continue
        pid, ppid, rss = (int(parts[0]), int(parts[1]), int(parts[2]))
        result[pid] = (ppid, rss)
    return result


def _descendant_rss_kb(root_pid: int | None) -> int | None:
    if not root_pid:
        return None
    table = _process_rows()
    if root_pid not in table:
        return None
    children: dict[int, list[int]] = {}
    for pid, (ppid, _rss) in table.items():
        children.setdefault(ppid, []).append(pid)
    rss_total = 0
    stack = [root_pid]
    seen: set[int] = set()
    while stack:
        pid = stack.pop()
        if pid in seen or pid not in table:
            continue
        seen.add(pid)
        _ppid, rss = table[pid]
        rss_total += rss
        stack.extend(children.get(pid, []))
    return rss_total


def verify_workflow(repo_root: Path, workflow: str) -> dict[str, object]:
    settings = Settings.load(repo_root, workflow=workflow)
    client = RouterClient(settings)
    launcher_pid, launcher_cmd = _assert_router_process(workflow)
    lock_state = _lock_state(workflow)
    _assert_router_listening(settings)
    client.wait_until_ready(timeout=60)
    workflow_cfg = settings.workflow_config
    verify_models = workflow_cfg.get("verify_models") or list(workflow_cfg.get("roles", {}).values())[:3]
    max_loaded = int(workflow_cfg.get("router", {}).get("models_max", 1))
    verify_cfg = workflow_cfg.get("verify", {})
    status_timeout = int(verify_cfg.get("status_timeout_sec", 180))
    settle_seconds = int(verify_cfg.get("settle_seconds", 1))
    rss_growth_limit_mb = int(verify_cfg.get("rss_growth_limit_mb", 768))
    loaded_history: list[list[str]] = []
    rss_history_kb: list[dict[str, object]] = []
    available_models = [item.get("id", "") for item in client.list_models()]
    missing_verify_models = [model for model in verify_models if model not in available_models]
    if missing_verify_models:
        raise RuntimeError(f"router missing expected verify models: {missing_verify_models}; available={available_models}")
    baseline_rss_kb = _descendant_rss_kb(launcher_pid)
    for model in verify_models:
        try:
            client.load_model(model, timeout=status_timeout)
        except HTTPError:
            pass
        _wait_for_status(client, model, {"loaded"}, timeout=status_timeout)
        warm_error: str | None = None
        try:
            client.warm_model(model, timeout=status_timeout)
        except Exception as exc:  # noqa: BLE001
            warm_error = str(exc)
        if warm_error:
            raise RuntimeError(f"warm request failed for {model}: {warm_error}")
        time.sleep(settle_seconds)
        loaded_history.append(_assert_model_loaded(client, model, max_loaded))
        rss_history_kb.append(
            {
                "phase": "loaded",
                "model": model,
                "rss_kb": _descendant_rss_kb(launcher_pid),
                "status": _status_of(client, model),
                "warm_error": warm_error,
            }
        )
    for model in reversed(verify_models):
        try:
            client.unload_model(model, timeout=status_timeout)
        except HTTPError:
            pass
        _wait_for_status(client, model, {"unloaded"}, timeout=status_timeout)
        time.sleep(settle_seconds)
        rss_history_kb.append(
            {
                "phase": "unloaded",
                "model": model,
                "rss_kb": _descendant_rss_kb(launcher_pid),
            }
        )

    final_rss_kb = _descendant_rss_kb(launcher_pid)
    if baseline_rss_kb is not None and final_rss_kb is not None:
        allowed_growth_kb = rss_growth_limit_mb * 1024
        if final_rss_kb > baseline_rss_kb + allowed_growth_kb:
            raise RuntimeError(
                f"router RSS grew too much after load/unload cycle: baseline={baseline_rss_kb}KB "
                f"final={final_rss_kb}KB limit={allowed_growth_kb}KB"
            )

    ctl = repo_root / ".venv" / "bin" / f"{workflow}ctl"
    profile = "fast"
    subprocess.run(
        [str(ctl), "--repo-root", str(repo_root), "demo", "--profile", profile],
        check=True,
        text=True,
    )
    run_id = _latest_run_id(repo_root / "runs" / workflow)
    report_path = repo_root / "runs" / workflow / run_id / "reports" / "report.md"
    if not report_path.exists():
        raise RuntimeError(f"missing report at {report_path}")
    report_text = report_path.read_text(encoding="utf-8")
    for needle in ("SWAP-", "check_admin_token", "vulnerable_copy", "multiply_count"):
        if needle not in report_text:
            raise RuntimeError(f"report missing expected marker: {needle}")
    try:
        loaded_final = client.loaded_models()
    except Exception:  # noqa: BLE001
        loaded_final = []
    active_final = client.active_models()
    if active_final:
        raise RuntimeError(f"workflow router still reports active models after unload: {active_final}")
    return {
        "workflow": workflow,
        "launcher_pid": launcher_pid,
        "launcher_cmd": launcher_cmd,
        "lock_state": lock_state,
        "router_base_url": client.base_url,
        "available_models": available_models,
        "verify_models": verify_models,
        "loaded_history": loaded_history,
        "loaded_final": loaded_final,
        "active_final": active_final,
        "rss_baseline_kb": baseline_rss_kb,
        "rss_final_kb": final_rss_kb,
        "rss_history_kb": rss_history_kb,
        "run_id": run_id,
        "report_path": str(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Agency or Legion router + proof run.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--workflow", required=True, choices=["agency", "legion"])
    args = parser.parse_args()
    result = verify_workflow(Path(args.repo_root).resolve(), args.workflow)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
