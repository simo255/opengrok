#!/usr/bin/env bash
# Switch Grok Bot inference: native (xAI/Grok) vs glm-hop (local OpenAI hop).
set -euo pipefail

SAND_DATA="${SAND_DATA:-/home/box/sand-data}"
MODE_FILE="${SAND_INFERENCE_MODE_FILE:-$SAND_DATA/inference-mode.json}"
SUPERVISOR_CMD="/tmp/sand-supervisor/command.json"

usage() {
  cat <<'EOF'
Usage: set-inference-mode.sh <native|glm-hop|status>

  native   — stock Grok Bot model via xAI / Grok subscription (no GLM hop)
  glm-hop  — OpenAI-compatible hop + model-bindings.json (default)
  status   — show active mode

Env: SAND_DATA, SAND_INFERENCE_MODE (temporary override), SAND_INFERENCE_MODE_FILE

Requests sand-host restart via sand-supervisor when /tmp/sand-supervisor exists.
EOF
}

if [[ "${1:-}" == "" ]] || [[ "${1}" == "-h" ]] || [[ "${1}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1}" == "status" ]]; then
  echo "file: $(cat "$MODE_FILE" 2>/dev/null || echo '(missing)')"
  if [[ -n "${SAND_INFERENCE_MODE:-}" ]]; then
    echo "env:  SAND_INFERENCE_MODE=${SAND_INFERENCE_MODE} (overrides file)"
  fi
  tail -3 "${OPENGROK_LOG:-/tmp/opengrok-session.log}" 2>/dev/null | sed 's/^/log:  /' || true
  exit 0
fi

MODE="${1}"
if [[ "$MODE" != "native" && "$MODE" != "glm-hop" ]]; then
  echo "error: mode must be native or glm-hop" >&2
  usage >&2
  exit 1
fi

NOW="$(date -Iseconds)"
python3 - <<PY
import json
from pathlib import Path
p = Path("$MODE_FILE")
out = {
    "_comment": "native = Grok/xAI stock inference. glm-hop = hop lane. See docs/STOCK-HOST.md",
    "mode": "$MODE",
    "updatedAt": "$NOW",
}
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, indent=2) + "\n")
print("wrote", p, "mode=", out["mode"])
PY

if [[ -d /tmp/sand-supervisor ]]; then
  RESTART_ID="restart-$(date +%s)"
  NOW_MS=$(($(date +%s) * 1000))
  printf '%s\n' "{\"id\":\"$RESTART_ID\",\"kind\":\"restart\",\"issuedAtMs\":$NOW_MS}" > /tmp/sand-supervisor/command.json.part
  mv /tmp/sand-supervisor/command.json.part "$SUPERVISOR_CMD"
  echo "sand-supervisor restart issued: $RESTART_ID"
else
  echo "note: restart sand-host manually to apply"
fi
