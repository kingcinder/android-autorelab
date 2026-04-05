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
