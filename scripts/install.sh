#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PIP_BIN="$VENV_DIR/bin/pip"
TOOLS_FILE="$ROOT_DIR/config/tools.yaml"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '[FAIL] missing command: %s\n' "$1" >&2
    exit 1
  }
}

info() { printf '[INFO] %s\n' "$*"; }
pass() { printf '[PASS] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }

need_cmd "$PYTHON_BIN"

if command -v apt-get >/dev/null 2>&1; then
  info "apt-family system detected"
  if sudo -n true >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y \
      build-essential \
      python3 \
      python3-venv \
      python3-pip \
      openjdk-21-jdk \
      git \
      unzip \
      wget \
      curl \
      binutils \
      file \
      p7zip-full \
      cmake \
      ninja-build \
      binwalk \
      android-sdk-libsparse-utils
  else
    warn "sudo without prompt is unavailable; skipping system package installation"
  fi
elif command -v dnf >/dev/null 2>&1; then
  warn "dnf detected; install system prerequisites manually or extend this script"
elif command -v pacman >/dev/null 2>&1; then
  warn "pacman detected; install system prerequisites manually or extend this script"
else
  warn "No supported package manager detected; continuing with Python-only setup"
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$PIP_BIN" install --upgrade pip wheel setuptools
"$PIP_BIN" install -e "$ROOT_DIR[analysis,dev]"
"$PIP_BIN" freeze --local | sort > "$ROOT_DIR/requirements.lock"
pass "Python environment installed"

chmod +x "$ROOT_DIR"/scripts/*.sh "$ROOT_DIR"/scripts/*.py

if [ -x "$HOME/.local/opt/ghidra-current/support/analyzeHeadless" ]; then
  pass "Ghidra headless detected"
else
  warn "Ghidra headless not found at ~/.local/opt/ghidra-current/support/analyzeHeadless"
fi

ROOT_DIR_ENV="$ROOT_DIR" python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["ROOT_DIR_ENV"])
for path in [root / "config" / "models.yaml", root / "config" / "tools.yaml", root / "config" / "policies.yaml"]:
    assert path.exists(), path
PY

pass "Config templates present"
info "Smoke tests"
"$VENV_DIR/bin/python" -c "import fastapi, pydantic, yaml; print('python stack ok')"
"$VENV_DIR/bin/python" -c "import angr; print('angr ok')"
need_cmd binwalk
need_cmd file
need_cmd strings
need_cmd gcc
[ -x "${HOME}/.local/opt/ghidra-current/support/analyzeHeadless" ] || {
  printf '[FAIL] missing Ghidra analyzeHeadless under %s\n' "$HOME/.local/opt/ghidra-current/support/analyzeHeadless" >&2
  exit 1
}
pass "Base smoke tests passed"

if systemctl --user show-environment >/dev/null 2>&1; then
  "$ROOT_DIR/scripts/install_services.sh" >/dev/null
  pass "Agency/Legion user services installed"
else
  warn "user systemd unavailable; workflow services were not installed"
fi

info "Install complete. Activate with: source $VENV_DIR/bin/activate"
