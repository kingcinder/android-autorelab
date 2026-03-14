#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
  STATE_DIR="$XDG_RUNTIME_DIR/android-autorelab"
else
  STATE_DIR="/tmp/android-autorelab-$(id -u)"
fi
ACTIVE_LOCK="$STATE_DIR/active-workflow.json"

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

wait_for_reset() {
  local deadline=$((SECONDS + 30))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ ! -f "$ACTIVE_LOCK" ] &&
      ! pgrep -f "$ROOT_DIR/.venv/bin/arelab" >/dev/null 2>&1 &&
      ! pgrep -f "$ROOT_DIR/.venv/bin/agencyctl" >/dev/null 2>&1 &&
      ! pgrep -f "$ROOT_DIR/.venv/bin/legionctl" >/dev/null 2>&1 &&
      ! pgrep -f "$ROOT_DIR/scripts/run_router.py --repo-root $ROOT_DIR --workflow agency" >/dev/null 2>&1 &&
      ! pgrep -f "$ROOT_DIR/scripts/run_router.py --repo-root $ROOT_DIR --workflow legion" >/dev/null 2>&1 &&
      ! pgrep -f "llama-server.*--port 18081" >/dev/null 2>&1 &&
      ! pgrep -f "llama-server.*--port 18082" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "[FAIL] verifier reset did not quiesce prior workflow state" >&2
  return 1
}

reset_workflows() {
  systemctl --user stop agency.service legion.service >/dev/null 2>&1 || true
  "$ROOT_DIR/scripts/stop_agency.sh" >/dev/null 2>&1 || true
  "$ROOT_DIR/scripts/stop_legion.sh" >/dev/null 2>&1 || true
  systemctl --user stop agency.service legion.service >/dev/null 2>&1 || true
  systemctl --user reset-failed agency.service legion.service >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv/bin/arelab" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv/bin/agencyctl" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv/bin/legionctl" >/dev/null 2>&1 || true
  "$PYTHON_BIN" -c "from arelab.locks import clear_workflow_lock; clear_workflow_lock()" >/dev/null 2>&1 || true
  wait_for_reset
}

reset_workflows
unset ARELAB_OPENAI_BASE_URL
"$ROOT_DIR/scripts/start_agency.sh" >/dev/null
wait_for_router "http://127.0.0.1:18081/v1/models" 90
ARELAB_OPENAI_BASE_URL="http://127.0.0.1:18081/v1" ARELAB_VERIFY_WORKFLOW="agency" "$ROOT_DIR/scripts/verify_shared.sh"
reset_workflows
"$ROOT_DIR/scripts/verify_agency.sh"
reset_workflows
"$ROOT_DIR/scripts/verify_legion.sh"
