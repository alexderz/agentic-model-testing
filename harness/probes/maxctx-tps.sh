#!/usr/bin/env bash
# Max-context ladder for Swift 1.5 Flash-Next: VRAM *and* decode throughput.
# Each rung gets a unique prompt so no rung is served from a warm prefix cache.
set -uo pipefail
LOG=/tmp/maxctx-tps.log; : > "$LOG"

curl -s --max-time 30 localhost:8081/unload >/dev/null 2>&1
for i in $(seq 1 30); do
  v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  [ "$v" -lt 2000 ] && break; sleep 2
done
echo "VRAM after unload: ${v} MiB" | tee -a "$LOG"
[ "$v" -ge 2000 ] && { echo "ABORT: card not free" | tee -a "$LOG"; echo "=== done ===" >> "$LOG"; exit 1; }

M=/models/llm/swift15-flash-next/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
MM=/models/llm/swift15-flash-next/mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf

for NC in 48 43 36; do
  echo "" | tee -a "$LOG"
  echo "=== -ncmoe $NC -c 262144 -ctk q8_0 -ctv q8_0 ===" | tee -a "$LOG"
  podman exec llama-swap /usr/local/bin/llama-server \
    --host 0.0.0.0 --port 5899 -fa on --metrics \
    -ctk q8_0 -ctv q8_0 -m "$M" -mm "$MM" \
    -ngl 999 -ncmoe "$NC" -c 262144 --reasoning-budget 4096 \
    > "/tmp/tps-$NC.log" 2>&1 &
  pid=$!

  # llama.cpp prints "llama_server: listening on http://..." -- NOT
  # "server is listening". Matching the wrong string made a working config
  # look like a load failure and stopped the previous ladder early.
  ready=no; t0=$(date +%s)
  for i in $(seq 1 600); do
    grep -q "llama_server: listening on" "/tmp/tps-$NC.log" 2>/dev/null && { ready=yes; break; }
    grep -qiE "failed to allocate|out of memory|cudaMalloc failed|model loading error" "/tmp/tps-$NC.log" 2>/dev/null && { ready=oom; break; }
    kill -0 "$pid" 2>/dev/null || { ready=died; break; }
    sleep 2
  done
  load_s=$(( $(date +%s) - t0 ))
  echo "load: ${load_s}s  ready: $ready" | tee -a "$LOG"
  if [ "$ready" != "yes" ]; then
    grep -iE "error|failed|out of memory" "/tmp/tps-$NC.log" | head -4 | sed 's/^/    !! /' | tee -a "$LOG"
    kill "$pid" 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null; sleep 8
    echo "ladder stops at $NC" | tee -a "$LOG"; break
  fi

  # Unique prompt: a random nonce means this cannot hit a cached prefix,
  # and it forces real decode rather than prompt echo.
  NONCE="$RANDOM$RANDOM-$NC-$(date +%s)"
  RESP=$(curl -s --max-time 900 http://127.0.0.1:5899/v1/chat/completions \
    -H 'Content-Type: application/json' -d "{
      \"model\":\"swift15\",
      \"messages\":[{\"role\":\"user\",\"content\":\"Session $NONCE. Write a Rust function that parses an ISO-8601 duration string into seconds. Include two unit tests. No explanation.\"}],
      \"max_tokens\":400, \"temperature\":0.7, \"stream\":false}")
  tps=$(printf '%s' "$RESP" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin); t=d.get('timings') or {}
    u=d.get('usage') or {}
    print(f\"predicted={u.get('completion_tokens','?')} \"
          f\"decode_tps={t.get('predicted_per_second','?')} \"
          f\"prefill_tps={t.get('prompt_per_second','?')}\")
except Exception as e:
    print('PARSE FAIL:', str(e)[:120])
")
  vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  echo "VRAM: ${vram} MiB / 24576   $tps" | tee -a "$LOG"
  grep -iE "n_ctx_slot|kv_unified|KV self|buffer size" "/tmp/tps-$NC.log" | tail -6 | sed 's/^/    /' | tee -a "$LOG"

  kill "$pid" 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null
  for i in $(seq 1 25); do
    v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    [ "$v" -lt 2000 ] && break; sleep 2
  done
done
echo "" | tee -a "$LOG"
echo "=== done, VRAM $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) MiB ===" | tee -a "$LOG"
