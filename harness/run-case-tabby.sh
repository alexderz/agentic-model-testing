#!/usr/bin/env bash
# Run one bake-off case against a model served by TabbyAPI instead of llama.cpp.
#
# OrcaSAQ-2 is EXL3, which llama.cpp cannot read, and llama-swap cannot spawn
# TabbyAPI because llama-swap's `cmd` executes inside llama-swap's own
# container. So TabbyAPI runs as a sibling container and this script owns the
# VRAM handoff explicitly:
#
#   stop llama-swap  ->  start TabbyAPI  ->  gate  ->  run case  ->  restore
#
# TabbyAPI's memory is invisible to llama-swap, so the two must never be up at
# once. This script fails closed rather than leaving both running.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source lib.sh

CASE="${1:?case name}"; MODEL_DIR="${2:?model dir under ~/ai/models/llm}"; CTX="${3:-32768}"
PORT="${TABBY_PORT:-5001}"
LANIP="${TITAN_LAN:-192.0.2.62}"
API="http://${LANIP}:${PORT}/v1"

cleanup() {
  echo "-- restoring llama-swap --"
  tssh "podman rm -f -i tabbyapi >/dev/null 2>&1; systemctl --user start llama-swap.service" || true
}
trap cleanup EXIT

echo "=== $CASE : TabbyAPI : $MODEL_DIR (ctx $CTX) ==="

# 1. free the GPU entirely -- llama-swap cannot see TabbyAPI's allocation
tssh "systemctl --user stop llama-swap.service; podman rm -f -i tabbyapi >/dev/null 2>&1" || true
sleep 5
used=$(vram); echo "   VRAM after stopping llama-swap: ${used} MiB"
if [ "${used:-0}" -gt 2000 ]; then
  err "GPU still holding ${used} MiB; refusing to start TabbyAPI"
  exit 1
fi

# 2. bring TabbyAPI up on the same podman network llama-swap uses
tssh "podman run -d --name tabbyapi --replace --rm \
  --network llama --security-opt label=disable --device nvidia.com/gpu=all \
  -v \$HOME/ai/models:/models:ro \
  --publish ${LANIP}:${PORT}:5000 \
  ghcr.io/theroyallab/tabbyapi:cu13 \
  python3 main.py --host 0.0.0.0 --port 5000 \
    --model-dir /models/llm --model-name ${MODEL_DIR} \
    --max-seq-len ${CTX} --cache-mode Q8" >/dev/null || { err "tabbyapi start failed"; exit 1; }

# 3. wait for it to serve
echo -n "   waiting for TabbyAPI "
for i in $(seq 1 90); do
  code=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "${API}/models" 2>/dev/null)
  [ "$code" = "200" ] && { echo "up after ${i}0s"; break; }
  printf '.'; sleep 10
done
[ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "${API}/models" 2>/dev/null)" = "200" ] || {
  err "TabbyAPI never became ready"
  tssh "podman logs --tail 20 tabbyapi" 2>&1 | tail -20
  exit 1
}
echo "   VRAM with model loaded: $(vram) MiB"

# 4. same tool-call gate every other model had to pass
API="${API}/chat/completions" OUT="$HERE/results-r2/preflight-tabby.tsv" \
  ./preflight.sh "$MODEL_DIR" 2>&1 | tail -3
grep -q "PASS" "$HERE/results-r2/preflight-tabby.tsv" 2>/dev/null || {
  err "$MODEL_DIR failed the tool-call gate; not scoring it"
  exit 1
}

# 5. point Pi at TabbyAPI, run the case, put the config back
PI_CFG="$HOME/.pi/agent/models.json"
cp "$PI_CFG" "$PI_CFG.bak-tabby-$(date +%Y%m%d-%H%M%S)"
python3 - "$PI_CFG" "$API" "$MODEL_DIR" <<'PY'
import json, sys
cfg, api, mid = sys.argv[1], sys.argv[2].replace("/chat/completions", ""), sys.argv[3]
d = json.load(open(cfg))
d["providers"]["tabby"] = {"api": "openai-completions", "baseUrl": api,
                           "apiKey": "not-needed", "models": [{"id": mid}]}
json.dump(d, open(cfg, "w"), indent=2)
print("pi provider 'tabby' ->", api)
PY

RESULTS="$HERE/results-r2" PROMPT_FILE="$HERE/prompt-r2.txt" \
HA_URL="http://127.0.0.1:8124" HA_TOKEN="bakeoff-placeholder-token" \
PI_PROVIDER=tabby SKIP_VARIANT=1 \
  ./run-case.sh "$CASE" "$MODEL_DIR" "tabbyapi ctx=$CTX" </dev/null
