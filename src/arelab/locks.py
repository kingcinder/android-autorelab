from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import psutil

from arelab.util import utc_now


def _runtime_dir() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "android-autorelab"
    uid = getattr(os, "getuid", None)
    owner = uid() if callable(uid) else os.environ.get("USERNAME", "default")
    return Path(tempfile.gettempdir()) / f"android-autorelab-{owner}"


def _workflow_state_path(workflow: str) -> Path:
    path = _runtime_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / f"active-workflow-{workflow}.json"


def _legacy_state_path() -> Path:
    path = _runtime_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "active-workflow.json"


def state_path(workflow: str | None = None) -> Path:
    if workflow:
        return _workflow_state_path(workflow)
    return _legacy_state_path()


def _read_payload(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _lock_paths() -> list[Path]:
    runtime = _runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    paths = sorted(runtime.glob("active-workflow-*.json"))
    legacy = _legacy_state_path()
    if legacy.exists():
        paths.append(legacy)
    return paths


def read_active_workflow(workflow: str | None = None) -> dict[str, object] | None:
    if workflow:
        return _read_payload(_workflow_state_path(workflow))
    for path in _lock_paths():
        payload = _read_payload(path)
        if payload:
            return payload
    return None


def clear_workflow_lock(expected_workflow: str | None = None) -> None:
    if expected_workflow:
        current = read_active_workflow(expected_workflow) or {}
        if not current or current.get("workflow") in {expected_workflow, None}:
            _workflow_state_path(expected_workflow).unlink(missing_ok=True)
        legacy = _read_payload(_legacy_state_path()) or {}
        if legacy.get("workflow") in {expected_workflow, None}:
            _legacy_state_path().unlink(missing_ok=True)
        return
    for path in _lock_paths():
        path.unlink(missing_ok=True)


def acquire_workflow_lock(workflow: str, owner: str) -> bool:
    path = _workflow_state_path(workflow)
    active = read_active_workflow(workflow)
    if active and active.get("workflow") == workflow and pid_alive(int(active.get("pid", 0))):
        return False
    payload = {
        "workflow": workflow,
        "pid": os.getpid(),
        "owner": owner,
        "created_at": utc_now(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True


@contextmanager
def workflow_lock(workflow: str, owner: str):
    created = acquire_workflow_lock(workflow, owner)
    try:
        yield
    finally:
        current = read_active_workflow(workflow) or {}
        if created and current.get("pid") == os.getpid():
            clear_workflow_lock(workflow)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False
