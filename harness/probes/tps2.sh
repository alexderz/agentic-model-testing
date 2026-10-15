#!/usr/bin/env bash
# Decode throughput for the max-context variants.
# Two requests per rung: the first pays mmap page-in from the NFS/FS-Cache
# mount, the second is steady state. Reporting only one conflates them.
set -uo pipefail
LOG=/tmp/tps2.log; : > "$LOG"

curl -s --max-time 30 localhost:8081/unload >/dev/null 2>&1
for i in $(seq 1 30); do
  v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  [ "$v" -lt 2000 ] && break; sleep 2
done
echo "VRAM after unload: ${v} MiB" | tee -a "$LOG"
[ "$v" -ge 2000 ] && { echo "ABORT: card not free" | tee -a "$LOG"; echo "=== done ===" >> "$LOG"; exit 1; }

M=/models/llm/swift15-flash-next/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
MM=/models/llm/swift15-flash-next/mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf

ask() {  # $1=nonce  -> curl INSIDE the container; the server is in its netns,
         # not on the host. Curling the host got connection-refused and an
         # empty body, which parsed as a throughput failure.
  podman exec llama-swap curl -s --max-time 1800 \
    http://127.0.0.1:5899/v1/chat/completions \
    -H 'Content-Type: application/json' -d "{
      \"model\":\"swift15\",
      \"messages\":[{\"role\":\"user\",\"content\":\"Session $1. Write a Rust function parsing an ISO-8601 duration into seconds, with two unit tests. No prose.\"}],
      \"max_tokens\":300, \"temperature\":0.7, \"stream\":false}"
}
stats() {
  python3 -c "
import json,sys
raw=sys.stdin.read().strip()
if not raw: print('  EMPTY RESPONSE'); raise SystemExit
try:
    d=json.loads(raw)
except Exception as e:
    print('  NOT JSON:', raw[:160]); raise SystemExit
if 'error' in d: print('  SERVER ERROR:', json.dumps(d['error'])[:200]); raise SystemExit
t=d.get('timings') or {}; u=d.get('usage') or {}
print(f\"  completion_tokens={u.get('completion_tokens','?')}  \"
      f\"decode={t.get('predicted_per_second','?')} tok/s  \"
      f\"prefill={t.get('prompt_per_second','?')} tok/s  \"
      f\"decode_ms={t.get('predicted_ms','?')}\")
"
}

for NC in 48 43; do
  echo "" | tee -a "$LOG"
  echo "=== -ncmoe $NC -c 262144 -ctk q8_0 -ctv q8_0 ===" | tee -a "$LOG"
  podman exec llama-swap /usr/local/bin/llama-server \
    --host 127.0.0.1 --port 5899 -fa on --metrics \
    -ctk q8_0 -ctv q8_0 -m "$M" -mm "$MM" \
    -ngl 999 -ncmoe "$NC" -c 262144 --reasoning-budget 4096 \
    > "/tmp/t2-$NC.log" 2>&1 &
  pid=$!
  ready=no
  for i in $(seq 1 600); do
    grep -q "llama_server: listening on" "/tmp/t2-$NC.log" 2>/dev/null && { ready=yes; break; }
    grep -qiE "failed to allocate|out of memory|model loading error" "/tmp/t2-$NC.log" 2>/dev/null && { ready=oom; break; }
    kill -0 "$pid" 2>/dev/null || { ready=died; break; }
    sleep 2
  done
  echo "ready: $ready" | tee -a "$LOG"
  [ "$ready" != "yes" ] && { kill "$pid" 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null; sleep 8; break; }

  t0=$(date +%s); echo "req 1 (cold, pays mmap page-in):" | tee -a "$LOG"
  ask "cold$RANDOM-$NC" | stats | tee -a "$LOG"
  echo "  wall=$(( $(date +%s) - t0 ))s  VRAM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) MiB" | tee -a "$LOG"

  t0=$(date +%s); echo "req 2 (warm, steady state):" | tee -a "$LOG"
  ask "warm$RANDOM-$NC" | stats | tee -a "$LOG"
  echo "  wall=$(( $(date +%s) - t0 ))s" | tee -a "$LOG"

  kill "$pid" 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null
  for i in $(seq 1 25); do
    v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    [ "$v" -lt 2000 ] && break; sleep 2
  done
done
echo "" | tee -a "$LOG"; echo "=== done ===" | tee -a "$LOG"
