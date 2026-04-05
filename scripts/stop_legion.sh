#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/venv_paths.sh"
PYTHON_BIN="$VENV_PYTHON"
[ -n "$PYTHON_BIN" ] || { echo "[FAIL] missing virtualenv python under $ROOT_DIR/.venv" >&2; exit 1; }
STATE_DIR="$(runtime_state_dir)"
PID_FILE="$STATE_DIR/legion-router.pid"
PORT=18082

wait_for_exit() {
  local pid="$1"
  local timeout="${2:-15}"
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

terminate_router_processes() {
  "$PYTHON_BIN" - <<'PY' "$PORT" "$PID_FILE"
import sys
from pathlib import Path

import psutil

port = sys.argv[1]
pid_file = Path(sys.argv[2])


def matches(proc: psutil.Process) -> bool:
    try:
        cmdline = " ".join(proc.cmdline())
    except psutil.Error:
        return False
    return (
        ("run_router.py" in cmdline and "--workflow legion" in cmdline)
        or ("workflow_service.py" in cmdline and "legion" in cmdline)
        or ("llama-server" in cmdline and f"--port {port}" in cmdline)
    )


processes: dict[int, psutil.Process] = {}
if pid_file.exists():
    try:
        processes[int(pid_file.read_text(encoding="utf-8").strip())] = psutil.Process(
            int(pid_file.read_text(encoding="utf-8").strip())
        )
    except (OSError, ValueError, psutil.Error):
        pass

for proc in psutil.process_iter(["pid", "cmdline"]):
    if matches(proc):
        processes[proc.pid] = proc
        try:
            for child in proc.children(recursive=True):
                processes[child.pid] = child
        except psutil.Error:
            pass

targets = list(processes.values())
for proc in sorted(targets, key=lambda item: len(item.children(recursive=True)), reverse=True):
    try:
        proc.terminate()
    except psutil.Error:
        pass

_gone, alive = psutil.wait_procs(targets, timeout=10)
for proc in alive:
    try:
        proc.kill()
    except psutil.Error:
        pass
psutil.wait_procs(alive, timeout=5)
pid_file.unlink(missing_ok=True)
PY
}

router_gone() {
  "$PYTHON_BIN" - <<'PY' "$PORT"
import socket
import sys

import psutil

port = sys.argv[1]
for proc in psutil.process_iter(["cmdline"]):
    try:
        cmdline = " ".join(proc.cmdline())
    except psutil.Error:
        continue
    if ("run_router.py" in cmdline and "--workflow legion" in cmdline) or (
        "workflow_service.py" in cmdline and "legion" in cmdline
    ) or ("llama-server" in cmdline and f"--port {port}" in cmdline):
        raise SystemExit(1)

sock = socket.socket()
sock.settimeout(0.25)
try:
    sock.connect(("127.0.0.1", int(port)))
except OSError:
    raise SystemExit(0)
finally:
    sock.close()
raise SystemExit(1)
PY
}

wait_for_shutdown() {
  local timeout="${1:-15}"
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if router_gone; then
      return 0
    fi
    sleep 1
  done
  return 1
}

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    if ! wait_for_exit "$PID" 10; then
      kill -9 "$PID" 2>/dev/null || true
      wait_for_exit "$PID" 5 || true
    fi
  fi
  rm -f "$PID_FILE"
fi

terminate_router_processes >/dev/null 2>&1 || true
"$PYTHON_BIN" - <<'PY' >/dev/null 2>&1 || true
from arelab.locks import clear_workflow_lock
clear_workflow_lock("legion")
PY

if ! wait_for_shutdown 15; then
  terminate_router_processes >/dev/null 2>&1 || true
  wait_for_shutdown 5 || true
fi

if ! router_gone; then
  echo "[FAIL] Legion router cleanup left processes or an open port on ${PORT}" >&2
  exit 1
fi

printf '[PASS] Legion router stopped\n'
