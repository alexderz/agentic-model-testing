#!/usr/bin/env bash
# Probe: max KV context with expert layers pushed to CPU, Swift 1.5 Flash-Next.
# Runs llama-server directly on a spare port; llama-swap's config is untouched.
set -uo pipefail
LOG=/tmp/maxctx-probe.log
: > "$LOG"

# GET, not POST. llama-swap answers POST /unload with 405, and the first run of
# this probe discarded that error, left the model resident, and reported the
# resulting OOM as though 262k context did not fit.
curl -s --max-time 30 localhost:8081/unload >/dev/null 2>&1
for i in $(seq 1 30); do
  v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  [ "$v" -lt 2000 ] && break
  sleep 2
done
echo "VRAM after unload: ${v} MiB" | tee -a "$LOG"
# Abort rather than measure against an occupied card: an OOM here would look
# exactly like "the context is too large".
if [ "$v" -ge 2000 ]; then
  echo "ABORT: card not free, refusing to probe (would produce a false OOM)" | tee -a "$LOG"
  echo "=== done ===" | tee -a "$LOG"; exit 1
fi

M=/models/llm/swift15-flash-next/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
MM=/models/llm/swift15-flash-next/mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf

for NC in 48 43; do
  echo "" | tee -a "$LOG"
  echo "=== -ncmoe $NC -c 262144 -ctk q8_0 -ctv q8_0 ===" | tee -a "$LOG"
  podman exec llama-swap /usr/local/bin/llama-server \
    --host 127.0.0.1 --port 5899 -fa on \
    -ctk q8_0 -ctv q8_0 -m "$M" -mm "$MM" \
    -ngl 999 -ncmoe "$NC" -c 262144 --reasoning-budget 4096 \
    > "/tmp/maxctx-$NC.log" 2>&1 &
  probe_pid=$!

  ready=no; t0=$(date +%s)
  for i in $(seq 1 400); do
    if grep -qE "server is listening|starting the main loop" "/tmp/maxctx-$NC.log" 2>/dev/null; then
      ready=yes; break; fi
    if grep -qiE "failed to allocate|out of memory|cudaMalloc failed|model loading error" "/tmp/maxctx-$NC.log" 2>/dev/null; then
      ready=oom; break; fi
    kill -0 "$probe_pid" 2>/dev/null || { ready=died; break; }
    sleep 3
  done
  load_s=$(( $(date +%s) - t0 ))

  peak=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  echo "outcome: $ready   load: ${load_s}s   VRAM: ${peak} MiB / 24576" | tee -a "$LOG"
  grep -iE "KV self size|kv_size|CUDA0 (model|compute) buffer|CPU model buffer|n_ctx +=|offloaded|graph splits" \
    "/tmp/maxctx-$NC.log" 2>/dev/null | tail -18 | sed 's/^/    /' | tee -a "$LOG"
  [ "$ready" = "oom" ] && grep -iE "failed to allocate|out of memory|cudaMalloc" "/tmp/maxctx-$NC.log" | head -4 | sed 's/^/    !! /' | tee -a "$LOG"

  # Explicit PID. `pkill -f llama-server` has matched my own shell before.
  kill "$probe_pid" 2>/dev/null
  podman exec llama-swap pkill -x llama-server 2>/dev/null
  for i in $(seq 1 20); do
    v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    [ "$v" -lt 2000 ] && break; sleep 2
  done
  [ "$ready" != "yes" ] && { echo "ladder stops: -ncmoe $NC did not come up" | tee -a "$LOG"; break; }
done

echo "" | tee -a "$LOG"
echo "=== done, VRAM now $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) MiB ===" | tee -a "$LOG"
