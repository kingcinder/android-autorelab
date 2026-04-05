#!/usr/bin/env bash

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

resolve_venv_executable() {
  local name="$1"
  local candidates=(
    "$VENV_DIR/bin/$name"
    "$VENV_DIR/bin/$name.exe"
    "$VENV_DIR/Scripts/$name"
    "$VENV_DIR/Scripts/$name.exe"
    "$VENV_DIR/Scripts/$name.cmd"
    "$VENV_DIR/Scripts/$name.bat"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [ -e "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

VENV_PYTHON="${VENV_PYTHON:-$(resolve_venv_executable python || resolve_venv_executable python3 || true)}"
VENV_PIP="${VENV_PIP:-$(resolve_venv_executable pip || resolve_venv_executable pip3 || true)}"
VENV_PYTEST="${VENV_PYTEST:-$(resolve_venv_executable pytest || true)}"
VENV_ARELAB="${VENV_ARELAB:-$(resolve_venv_executable arelab || true)}"
VENV_AGENCYCTL="${VENV_AGENCYCTL:-$(resolve_venv_executable agencyctl || true)}"
VENV_LEGIONCTL="${VENV_LEGIONCTL:-$(resolve_venv_executable legionctl || true)}"
VENV_BIN_DIR="${VENV_BIN_DIR:-$(dirname "${VENV_PYTHON:-$VENV_DIR}")}"

runtime_state_dir() {
  [ -n "${VENV_PYTHON:-}" ] || return 1
  "$VENV_PYTHON" - <<'PY'
from arelab.locks import state_path

print(state_path().parent)
PY
}

workflow_lock_path() {
  local workflow="$1"
  [ -n "${VENV_PYTHON:-}" ] || return 1
  "$VENV_PYTHON" - <<'PY' "$workflow"
import sys

from arelab.locks import state_path

print(state_path(sys.argv[1]))
PY
}

launch_detached() {
  local log_file="$1"
  shift
  [ -n "${VENV_PYTHON:-}" ] || { echo "missing VENV_PYTHON" >&2; return 1; }
  "$VENV_PYTHON" - <<'PY' "$log_file" "$@"
import subprocess
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
command = sys.argv[2:]
log_path.parent.mkdir(parents=True, exist_ok=True)
with log_path.open("a", encoding="utf-8") as handle:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
print(proc.pid)
PY
}
