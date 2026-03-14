#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"
sed "s#__ARELAB_ROOT__#$ROOT_DIR#g" "$ROOT_DIR/services/agency.service" > "$SYSTEMD_DIR/agency.service"
sed "s#__ARELAB_ROOT__#$ROOT_DIR#g" "$ROOT_DIR/services/legion.service" > "$SYSTEMD_DIR/legion.service"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload
else
  printf '[WARN] user systemd unavailable; unit files were written but not reloaded\n' >&2
fi
printf '[PASS] Installed agency.service and legion.service into %s\n' "$SYSTEMD_DIR"
