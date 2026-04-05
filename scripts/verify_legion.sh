#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/venv_paths.sh"
PYTHON_BIN="$VENV_PYTHON"
[ -n "$PYTHON_BIN" ] || { echo "[FAIL] missing virtualenv python under $ROOT_DIR/.venv" >&2; exit 1; }
STATE_DIR="$(runtime_state_dir)"
ACTIVE_LOCK="$(workflow_lock_path legion)"
PORT=18082

lock_path_for() {
  workflow_lock_path "$1"
}

wait_for_router() {
  local url="$1"
  local timeout="${2:-60}"
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "[FAIL] timed out waiting for router endpoint: $url" >&2
  return 1
}

assert_pid_matches() {
  local workflow="$1"
  local pid_file="$STATE_DIR/${workflow}-router.pid"
  [ -f "$pid_file" ] || { echo "[FAIL] missing pid file: $pid_file" >&2; exit 1; }
  local pid
  pid="$(cat "$pid_file")"
  "$PYTHON_BIN" - <<'PY' "$pid" "$workflow"
import sys

import psutil

pid = int(sys.argv[1])
workflow = sys.argv[2]
try:
    cmdline = " ".join(psutil.Process(pid).cmdline())
except psutil.Error as exc:
    raise SystemExit(f"[FAIL] router pid not alive for {workflow}: {pid}") from exc
if "run_router.py" not in cmdline or workflow not in cmdline:
    raise SystemExit(f"[FAIL] pid {pid} is not the expected {workflow} router wrapper: {cmdline}")
PY
}

assert_lock_workflow() {
  local workflow="$1"
  local lock_path
  lock_path="$(lock_path_for "$workflow")"
  "$PYTHON_BIN" - <<'PY' "$lock_path" "$workflow"
import json
import sys
from pathlib import Path

from arelab.locks import pid_alive

path = Path(sys.argv[1])
workflow = sys.argv[2]
if not path.exists():
    raise SystemExit("[FAIL] active workflow lock is missing")
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("workflow") != workflow:
    raise SystemExit(f"[FAIL] active workflow lock mismatch: {payload}")
pid = int(payload.get("pid", 0) or 0)
if pid <= 0:
    raise SystemExit(f"[FAIL] active workflow lock has invalid pid: {payload}")
if not pid_alive(pid):
    raise SystemExit(f"[FAIL] active workflow lock pid is dead: {payload}")
PY
}

assert_port_listening() {
  local port="$1"
  "$PYTHON_BIN" - <<'PY' "$port"
import socket
import sys

sock = socket.socket()
sock.settimeout(1.0)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError as exc:
    raise SystemExit(f"[FAIL] router port is not listening on 127.0.0.1:{sys.argv[1]}") from exc
finally:
    sock.close()
PY
}

wait_for_lock() {
  local workflow="$1"
  local timeout="${2:-10}"
  local deadline=$((SECONDS + timeout))
  local lock_path
  lock_path="$(lock_path_for "$workflow")"
  while [ "$SECONDS" -lt "$deadline" ]; do
    if "$PYTHON_BIN" - <<'PY' "$lock_path" "$workflow"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
workflow = sys.argv[2]
if not path.exists():
    raise SystemExit(1)
payload = json.loads(path.read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("workflow") == workflow else 1)
PY
    then
      return 0
    fi
    sleep 1
  done
  echo "[FAIL] timed out waiting for active lock: $workflow" >&2
  exit 1
}

reset_state() {
  pkill -f "$ROOT_DIR/.venv.*/arelab" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv.*/agencyctl" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv.*/legionctl" >/dev/null 2>&1 || true
  cleanup
}

cleanup() {
  "$ROOT_DIR/scripts/stop_agency.sh" >/dev/null 2>&1 || true
  "$ROOT_DIR/scripts/stop_legion.sh" >/dev/null 2>&1 || true
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop agency.service >/dev/null 2>&1 || true
    systemctl --user stop legion.service >/dev/null 2>&1 || true
  fi
  rm -f "$ACTIVE_LOCK"
}
trap cleanup EXIT

reset_state
"$ROOT_DIR/scripts/install_workflow_services.sh" >/dev/null 2>&1 || true
grep -q '^Conflicts=legion.service' "$ROOT_DIR/services/agency.service"
grep -q '^Conflicts=agency.service' "$ROOT_DIR/services/legion.service"
grep -q '^ExecStartPre=.*scripts/stop_agency.sh' "$ROOT_DIR/services/legion.service"

"$PYTHON_BIN" - "$ROOT_DIR" <<'PY' &
import sys
import time
from pathlib import Path

repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root / "src"))
from arelab.locks import workflow_lock  # noqa: E402

with workflow_lock("agency", "verify-lock"):
    time.sleep(30)
PY
AGENCY_LOCK_PID=$!
wait_for_lock agency 10

if "$PYTHON_BIN" "$ROOT_DIR/scripts/run_router.py" --repo-root "$ROOT_DIR" --workflow legion >/dev/null 2>&1; then
  echo "[FAIL] Legion router started while Agency workflow lock was active" >&2
  kill "$AGENCY_LOCK_PID" >/dev/null 2>&1 || true
  exit 1
fi
kill "$AGENCY_LOCK_PID" >/dev/null 2>&1 || true
wait "$AGENCY_LOCK_PID" >/dev/null 2>&1 || true

"$ROOT_DIR/scripts/start_legion.sh" >/dev/null
wait_for_router "http://127.0.0.1:18082/models" 90
curl -fsS "http://127.0.0.1:18082/models" >/dev/null
assert_pid_matches legion
assert_lock_workflow legion
assert_port_listening "$PORT"
"$PYTHON_BIN" "$ROOT_DIR/scripts/workflow_verify.py" --repo-root "$ROOT_DIR" --workflow legion
printf '[PASS] Legion verification complete\n'
