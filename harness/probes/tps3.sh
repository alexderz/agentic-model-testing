#!/usr/bin/env bash
# What does max context COST? Production setting at its current context vs full
# context, plus the -ncmoe 43 candidate. 3 warm reps each: a single sample
# swung 3.75 -> 6.30 tok/s on the same config, so one number cannot rank these.
set -uo pipefail
LOG=/tmp/tps3.log; : > "$LOG"
curl -s --max-time 30 localhost:8081/unload >/dev/null 2>&1
for i in $(seq 1 30); do v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); [ "$v" -lt 2000 ] && break; sleep 2; done
[ "$v" -ge 2000 ] && { echo "ABORT: card not free" | tee -a "$LOG"; echo "=== done ===" >> "$LOG"; exit 1; }

M=/models/llm/swift15-flash-next/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
MM=/models/llm/swift15-flash-next/mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf

ask() { podman exec llama-swap curl -s --max-time 1800 \
  http://127.0.0.1:5899/v1/chat/completions -H 'Content-Type: application/json' \
  -d "{\"model\":\"s\",\"messages\":[{\"role\":\"user\",\"content\":\"Run $1. Write a Rust function parsing an ISO-8601 duration into seconds, with two unit tests. No prose.\"}],\"max_tokens\":300,\"temperature\":0.7,\"stream\":false}"; }
tps() { python3 -c "
import json,sys
r=sys.stdin.read().strip()
if not r: print('EMPTY'); raise SystemExit
d=json.loads(r)
if 'error' in d: print('ERR', json.dumps(d['error'])[:120]); raise SystemExit
t=d.get('timings') or {}
print(f\"{t.get('predicted_per_second',0):.2f}\")"; }

run() {  # $1=ncmoe  $2=ctx  $3=label
  echo "" | tee -a "$LOG"; echo "=== $3 : -ncmoe $1 -c $2 ===" | tee -a "$LOG"
  podman exec llama-swap /usr/local/bin/llama-server --host 127.0.0.1 --port 5899 \
    -fa on --metrics -ctk q8_0 -ctv q8_0 -m "$M" -mm "$MM" \
    -ngl 999 -ncmoe "$1" -c "$2" --reasoning-budget 4096 > "/tmp/t3-$1-$2.log" 2>&1 &
  pid=$!; ready=no
  for i in $(seq 1 600); do
    grep -q "llama_server: listening on" "/tmp/t3-$1-$2.log" 2>/dev/null && { ready=yes; break; }
    grep -qiE "failed to allocate|out of memory|model loading error" "/tmp/t3-$1-$2.log" 2>/dev/null && { ready=oom; break; }
    kill -0 "$pid" 2>/dev/null || { ready=died; break; }; sleep 2
  done
  if [ "$ready" != "yes" ]; then
    echo "  DID NOT START ($ready)" | tee -a "$LOG"
    grep -iE "error|out of memory" "/tmp/t3-$1-$2.log" | head -3 | sed 's/^/    !! /' | tee -a "$LOG"
    kill "$pid" 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null; sleep 8; return
  fi
  ask "warmup$RANDOM" >/dev/null 2>&1          # absorb mmap page-in
  vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  out=""
  for rep in 1 2 3; do out="$out $(ask "r$rep-$RANDOM" | tps)"; done
  echo "  VRAM ${vram} MiB / 24576   decode tok/s:$out" | tee -a "$LOG"
  kill "$pid" 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null
  for i in $(seq 1 25); do v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); [ "$v" -lt 2000 ] && break; sleep 2; done
}

run 36  98304 "PRODUCTION today"
run 36 262144 "production offload, full context"
run 43 262144 "candidate"
echo "" | tee -a "$LOG"; echo "=== done ===" | tee -a "$LOG"
