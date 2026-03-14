#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR"
for unit in "$ROOT_DIR"/services/*.service; do
  target="$UNIT_DIR/$(basename "$unit")"
  sed "s#__ARELAB_ROOT__#$ROOT_DIR#g" "$unit" > "$target"
  chmod 0644 "$target"
done
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload
else
  printf '[WARN] user systemd unavailable; unit files were written but not reloaded\n' >&2
fi
printf '[PASS] Installed workflow services into %s\n' "$UNIT_DIR"
