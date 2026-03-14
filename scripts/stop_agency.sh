#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
  STATE_DIR="$XDG_RUNTIME_DIR/android-autorelab"
else
  STATE_DIR="/tmp/android-autorelab-$(id -u)"
fi
PID_FILE="$STATE_DIR/agency-router.pid"
PORT=18081

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

port_closed() {
  "$PYTHON_BIN" - <<'PY' "$PORT"
import socket
import sys

sock = socket.socket()
sock.settimeout(0.25)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(0)
finally:
    sock.close()
raise SystemExit(1)
PY
}

router_gone() {
  ! pgrep -f "run_router.py.*workflow agency" >/dev/null 2>&1 &&
    ! pgrep -f "llama-server.*--port ${PORT}" >/dev/null 2>&1 &&
    port_closed
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

pkill -f "llama-server.*--port ${PORT}" >/dev/null 2>&1 || true
pkill -f "run_router.py.*workflow agency" >/dev/null 2>&1 || true
pkill -f "workflow_service.py agency" >/dev/null 2>&1 || true
[ -x "$PYTHON_BIN" ] && "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1 || true
from arelab.locks import clear_workflow_lock
clear_workflow_lock("agency")
PY

if ! wait_for_shutdown 15; then
  pkill -9 -f "run_router.py.*workflow agency" >/dev/null 2>&1 || true
  pkill -9 -f "llama-server.*--port ${PORT}" >/dev/null 2>&1 || true
  wait_for_shutdown 5 || true
fi

if ! router_gone; then
  echo "[FAIL] Agency router cleanup left processes or an open port on ${PORT}" >&2
  exit 1
fi

printf '[PASS] Agency router stopped\n'
