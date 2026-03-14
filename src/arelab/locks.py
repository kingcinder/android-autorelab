from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from arelab.util import utc_now


def _runtime_dir() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "android-autorelab"
    return Path("/tmp") / f"android-autorelab-{os.getuid()}"


def state_path() -> Path:
    path = _runtime_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "active-workflow.json"


def read_active_workflow() -> dict[str, object] | None:
    path = state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def clear_workflow_lock(expected_workflow: str | None = None) -> None:
    path = state_path()
    if not path.exists():
        return
    current = read_active_workflow() or {}
    if expected_workflow and current.get("workflow") not in {expected_workflow, None}:
        return
    path.unlink(missing_ok=True)


def acquire_workflow_lock(workflow: str, owner: str) -> bool:
    path = state_path()
    active = read_active_workflow()
    if active and active.get("workflow") not in {None, workflow} and _pid_alive(int(active.get("pid", 0))):
        raise RuntimeError(
            f"Workflow lock is held by {active.get('workflow')} (pid={active.get('pid')})"
        )
    if active and active.get("workflow") == workflow and _pid_alive(int(active.get("pid", 0))):
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
        current = read_active_workflow() or {}
        if created and current.get("pid") == os.getpid():
            clear_workflow_lock(workflow)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
