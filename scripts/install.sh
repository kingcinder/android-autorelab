#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
source "$ROOT_DIR/scripts/venv_paths.sh"
PIP_BIN="$VENV_PIP"
PYTHON_VENV_BIN="$VENV_PYTHON"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '[FAIL] missing command: %s\n' "$1" >&2
    exit 1
  }
}

info() { printf '[INFO] %s\n' "$*"; }
pass() { printf '[PASS] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }

is_windows_shell() {
  case "${OSTYPE:-}:$(uname -s 2>/dev/null || echo unknown)" in
    msys*:*) return 0 ;;
    cygwin*:*) return 0 ;;
    *:MINGW*|*:MSYS*|*:CYGWIN*|*Windows_NT*) return 0 ;;
    *) return 1 ;;
  esac
}

cleanup_partial_install_state() {
  "$PYTHON_VENV_BIN" - <<'PY' "$VENV_DIR"
import shutil
import sys
from pathlib import Path

venv_dir = Path(sys.argv[1])
roots = [venv_dir / "Lib" / "site-packages"]
versioned = venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
roots.append(versioned)

removed = []
for root in roots:
    if not root.exists():
        continue
    for path in root.iterdir():
        name = path.name.lower()
        if not name.startswith("~") or "autorelab" not in name:
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        removed.append(str(path))
if removed:
    print("[INFO] removed partial install state:")
    for item in removed:
        print(item)
PY
}

windows_entrypoints_busy() {
  local image
  for image in arelab.exe agencyctl.exe legionctl.exe; do
    if tasklist.exe //FI "IMAGENAME eq $image" 2>/dev/null | grep -Fqi "$image"; then
      warn "refusing to reinstall while $image is running"
      return 0
    fi
  done
  return 1
}

editable_install_healthy() {
  [ -n "$VENV_ARELAB" ] || return 1
  [ -n "$VENV_AGENCYCTL" ] || return 1
  [ -n "$VENV_LEGIONCTL" ] || return 1
  "$PYTHON_VENV_BIN" - <<'PY' "$ROOT_DIR" || return 1
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
src_root = (repo_root / "src").resolve()
import arelab

module_path = Path(arelab.__file__).resolve()
if src_root not in module_path.parents:
    raise SystemExit(1)
if str(src_root) not in sys.path:
    raise SystemExit(1)
PY
  "$VENV_ARELAB" --help >/dev/null 2>&1 || return 1
  "$VENV_AGENCYCTL" --help >/dev/null 2>&1 || return 1
  "$VENV_LEGIONCTL" --help >/dev/null 2>&1 || return 1
}

install_project_dependencies() {
  local deps=()
  mapfile -t deps < <("$PYTHON_VENV_BIN" - <<'PY' "$ROOT_DIR"
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
with (root / "pyproject.toml").open("rb") as handle:
    project = tomllib.load(handle)["project"]
deps = list(project.get("dependencies", []))
optional = project.get("optional-dependencies", {})
for group in ("analysis", "dev"):
    deps.extend(optional.get(group, []))
for dep in deps:
    print(dep)
PY
  )
  [ "${#deps[@]}" -gt 0 ] || return 0
  "$PYTHON_VENV_BIN" -m pip install "${deps[@]}"
}

install_editable_package() {
  cleanup_partial_install_state
  if editable_install_healthy; then
    pass "Editable install already healthy"
    return 0
  fi
  if is_windows_shell && windows_entrypoints_busy; then
    printf '[FAIL] stop arelab.exe, agencyctl.exe, and legionctl.exe before reinstalling the editable package on Windows\n' >&2
    exit 1
  fi
  if ! (
    cd "$ROOT_DIR"
    "$PYTHON_VENV_BIN" -m pip install -e "." --no-deps
  ); then
    if is_windows_shell; then
      printf '[FAIL] editable reinstall failed on Windows; ensure no arelab/agencyctl/legionctl process is running and retry\n' >&2
    fi
    exit 1
  fi
  source "$ROOT_DIR/scripts/venv_paths.sh"
  editable_install_healthy || {
    printf '[FAIL] editable package install completed but the local entrypoints are still unhealthy\n' >&2
    exit 1
  }
  pass "Editable package installed"
}

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

source "$ROOT_DIR/scripts/venv_paths.sh"
PYTHON_VENV_BIN="$VENV_PYTHON"
[ -n "$PIP_BIN" ] || { printf '[FAIL] missing pip inside %s\n' "$VENV_DIR" >&2; exit 1; }
[ -n "$PYTHON_VENV_BIN" ] || { printf '[FAIL] missing python inside %s\n' "$VENV_DIR" >&2; exit 1; }
"$PIP_BIN" --version >/dev/null
"$PYTHON_VENV_BIN" -m pip install --upgrade pip wheel setuptools
install_project_dependencies
install_editable_package
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
[ -n "$VENV_PYTHON" ] || { printf '[FAIL] missing python inside %s\n' "$VENV_DIR" >&2; exit 1; }
"$VENV_PYTHON" -c "import fastapi, pydantic, yaml; print('python stack ok')"
"$VENV_PYTHON" -c "import angr; print('angr ok')"
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
