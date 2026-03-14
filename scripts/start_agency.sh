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
LOG_FILE="$STATE_DIR/agency-router.log"
LOCK_FILE="$STATE_DIR/active-workflow.json"
PORT=18081
mkdir -p "$STATE_DIR"
umask 077

[ -x "$PYTHON_BIN" ] || { echo "[FAIL] missing virtualenv python at $PYTHON_BIN" >&2; exit 1; }

MODE="${1:-background}"
if [ -f "$LOCK_FILE" ]; then
  python3 - <<'PY' "$LOCK_FILE"
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    path.unlink(missing_ok=True)
    raise SystemExit(0)

pid = int(payload.get("pid", 0) or 0)
alive = pid > 0
if alive:
    try:
        os.kill(pid, 0)
    except OSError:
        alive = False
if not alive:
    path.unlink(missing_ok=True)
PY
fi
if [ "$MODE" != "--foreground" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user stop legion.service >/dev/null 2>&1 || true
fi
"$ROOT_DIR/scripts/stop_legion.sh" >/dev/null 2>&1 || true
if [ "$MODE" != "--foreground" ]; then
  "$ROOT_DIR/scripts/stop_legion.sh" >/dev/null 2>&1 || true
fi

router_ready() {
  "$PYTHON_BIN" - <<'PY' "$ROOT_DIR" "agency" "5"
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
workflow = sys.argv[2]
timeout = int(sys.argv[3])
sys.path.insert(0, str(repo_root / "src"))
from arelab.config import Settings  # noqa: E402
from arelab.router import RouterClient  # noqa: E402

settings = Settings.load(repo_root, workflow=workflow)
client = RouterClient(settings)
try:
    client.wait_until_ready(timeout=timeout)
except Exception:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

workflow_lock_ready() {
  "$PYTHON_BIN" - <<'PY' "$LOCK_FILE" "agency"
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
workflow = sys.argv[2]
if not path.exists():
    raise SystemExit(1)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if payload.get("workflow") != workflow:
    raise SystemExit(1)
pid = int(payload.get("pid", 0) or 0)
if pid <= 0:
    raise SystemExit(1)
try:
    os.kill(pid, 0)
except OSError:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

if [ -f "$PID_FILE" ]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${EXISTING_PID:-}" ] && kill -0 "$EXISTING_PID" 2>/dev/null && router_ready && workflow_lock_ready; then
    printf '[PASS] Agency router already running (pid=%s, port=%s, log=%s)\n' "$EXISTING_PID" "$PORT" "$LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if router_ready && workflow_lock_ready; then
  printf '[PASS] Agency router already running (port=%s, log=%s)\n' "$PORT" "$LOG_FILE"
  exit 0
fi

"$ROOT_DIR/scripts/stop_agency.sh" >/dev/null 2>&1 || true

CMD=("$PYTHON_BIN" "$ROOT_DIR/scripts/run_router.py" --repo-root "$ROOT_DIR" --workflow agency)

if [ "$MODE" = "--foreground" ]; then
  exec "${CMD[@]}"
fi

nohup "${CMD[@]}" >>"$LOG_FILE" 2>&1 </dev/null &
ROUTER_PID=$!
disown "$ROUTER_PID" 2>/dev/null || true
echo "$ROUTER_PID" >"$PID_FILE"
READY=0
for _ in $(seq 1 45); do
  if ! kill -0 "$ROUTER_PID" 2>/dev/null; then
    break
  fi
  if router_ready && workflow_lock_ready; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  "$ROOT_DIR/scripts/stop_agency.sh" >/dev/null 2>&1 || true
  if kill -0 "$ROUTER_PID" 2>/dev/null; then
    echo "[FAIL] Agency router did not become ready; inspect $LOG_FILE" >&2
  else
    echo "[FAIL] Agency router exited early; inspect $LOG_FILE" >&2
  fi
  rm -f "$PID_FILE"
  exit 1
fi
printf '[PASS] Agency router started (pid=%s, port=%s, log=%s)\n' "$ROUTER_PID" "$PORT" "$LOG_FILE"
