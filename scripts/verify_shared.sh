#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
ARELAB_BIN="$VENV_DIR/bin/arelab"
VERIFY_WORKFLOW="${ARELAB_VERIFY_WORKFLOW:-default}"

pass() { printf '[PASS] %s\n' "$*"; }
info() { printf '[INFO] %s\n' "$*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || { printf '[FAIL] missing command: %s\n' "$1" >&2; exit 1; }; }
have_user_systemd() { command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; }
managed_backend() { [ -n "${ARELAB_OPENAI_BASE_URL:-}" ]; }

wait_for_unit_stopped() {
  local unit="$1"
  local timeout="${2:-30}"
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local state
    state="$(systemctl --user is-active "$unit" 2>/dev/null || true)"
    if [ "$state" != "active" ] && [ -n "$state" ]; then
      return 0
    fi
    sleep 1
  done
  printf '[FAIL] expected %s to be stopped\n' "$unit" >&2
  exit 1
}

[ -x "$PYTHON_BIN" ] || { echo "[FAIL] missing virtualenv; run scripts/install.sh first" >&2; exit 1; }
[ -x "$ARELAB_BIN" ] || { echo "[FAIL] missing arelab entrypoint; reinstall required" >&2; exit 1; }

if ! managed_backend; then
  have_user_systemd && systemctl --user stop agency.service legion.service >/dev/null 2>&1 || true
  "$ROOT_DIR/scripts/stop_agency.sh" >/dev/null 2>&1 || true
  "$ROOT_DIR/scripts/stop_legion.sh" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv/bin/arelab" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv/bin/agencyctl" >/dev/null 2>&1 || true
  pkill -f "$ROOT_DIR/.venv/bin/legionctl" >/dev/null 2>&1 || true
  if have_user_systemd; then
    systemctl --user stop agency.service legion.service >/dev/null 2>&1 || true
    systemctl --user reset-failed agency.service legion.service >/dev/null 2>&1 || true
    wait_for_unit_stopped agency.service 30
    wait_for_unit_stopped legion.service 30
  fi
  "$PYTHON_BIN" -c "from arelab.locks import clear_workflow_lock; clear_workflow_lock()"
fi

info "Tool verification"
need_cmd binwalk
binwalk --help >/dev/null
pass "binwalk --help"

"$PYTHON_BIN" -c "import angr; print('angr ok')" >/dev/null
pass "python import angr"

GHIDRA_PATH="$(ROOT_DIR_ENV="$ROOT_DIR" VERIFY_WORKFLOW_ENV="$VERIFY_WORKFLOW" "$PYTHON_BIN" -c 'import os; from pathlib import Path; from arelab.config import Settings; from arelab.tooling import detect_tools; root = Path(os.environ["ROOT_DIR_ENV"]); workflow = os.environ["VERIFY_WORKFLOW_ENV"]; print(detect_tools(Settings.load(root, workflow=workflow)).get("analyzeHeadless") or "")')"
[ -n "$GHIDRA_PATH" ] || { echo "[FAIL] ghidra analyzeHeadless missing" >&2; exit 1; }
GHIDRA_HELP="$("$GHIDRA_PATH" -help 2>&1 || true)"
echo "$GHIDRA_HELP" | grep -q "Headless Analyzer Usage"
pass "ghidra analyzeHeadless -help"

"$ROOT_DIR/scripts/lpunpack.py" --help >/dev/null
pass "lpunpack adapter"
"$ROOT_DIR/scripts/unpack_bootimg.py" --help >/dev/null
pass "unpack_bootimg adapter"
"$ROOT_DIR/scripts/avbtool.py" --help >/dev/null
pass "avbtool adapter"

info "Model gateway verification"
ROOT_DIR_ENV="$ROOT_DIR" VERIFY_WORKFLOW_ENV="$VERIFY_WORKFLOW" "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path

from arelab.config import Settings
from arelab.model_gateway import ModelGateway
from arelab.router import RouterClient

root = Path(os.environ["ROOT_DIR_ENV"])
settings = Settings.load(root, workflow=os.environ["VERIFY_WORKFLOW_ENV"])
gateway = ModelGateway(settings, root / "tmp-prompts")
client = RouterClient(settings)
client.wait_until_ready(timeout=60)
models = gateway.available_models()
assert models, "no models discovered"
print("\n".join(models))
model = gateway.resolve_role("triage")
if not model:
    verify_models = settings.workflow_config.get("verify_models") or []
    model = verify_models[0] if verify_models else None
assert model, "no verification model resolved"
client.load_model(model, timeout=240)
client.wait_for_model_state(model, expected={"loading", "loaded"}, timeout=240, settle_seconds=1.0)
try:
    client.warm_model(model, timeout=180)
    payload = gateway.chat_json(
        role="triage",
        system_prompt="Return JSON only. Do not include reasoning in the final answer.",
        user_prompt='Return exactly this JSON object and nothing else: {"swap_candidates": []}',
        schema_name="verify-triage",
        max_tokens=128,
        timeout=180,
    )
    assert payload == {"swap_candidates": []}
finally:
    client.unload_model(model, timeout=240)
    client.wait_for_model_state(model, expected={"unloaded"}, timeout=240, settle_seconds=1.0)
PY
pass "model list + chat completion"

RUN_JSON="$("$ARELAB_BIN" --repo-root "$ROOT_DIR" --workflow "$VERIFY_WORKFLOW" demo --profile fast)"
RUN_ID="$(RUN_JSON_ENV="$RUN_JSON" "$PYTHON_BIN" -c 'import json, os; print(json.loads(os.environ["RUN_JSON_ENV"])["run_id"])')"
REPORT_PATH="$ROOT_DIR/runs/$VERIFY_WORKFLOW/$RUN_ID/reports/report.md"
[ -f "$REPORT_PATH" ] || { echo "[FAIL] report missing: $REPORT_PATH" >&2; exit 1; }
grep -q "SWAP-" "$REPORT_PATH"
pass "shared proof run generated SWAP report"

info "Running unit tests"
"$VENV_DIR/bin/pytest" -q
pass "unit tests"
