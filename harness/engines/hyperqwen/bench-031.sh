#!/bin/bash
# HyperQwen vLLM 0.31 speed trial on titan (2026-10-14, Model Master 2): profile D on the newer image
# (qwen3.8-27b-vllm-031) against the same profile on 0.30 (qwen3.8-27b-vllm), the night search's method
# (results-night-search/: bench_tasks.py, 5 prompts x code/prose/structured, 400 tokens, thinking off, temperature 0;
# then deep.py, 6,400 records, about 141k tokens, a needle and the code decode rate with the window that full).
# Rounds alternate 0.31, 0.30, 0.31, 0.30, each a fresh load through llama-swap (port 8081, loopback). Peak card memory
# sampled every 2 s. An untimed 0.31 warm-up round comes first (v031-warm, left out of the summary): 0.31's compile,
# Triton and FlashInfer caches start empty, and the first timed 0.31 round must not pay for filling them (0.30's
# caches are warm from daily use). The caller holds the GPU lease and has checked that nothing is loaded.
#   ~/hq031-bench/bench-031.sh            (writes ~/hq031-bench/out/<label>.json, .deep.json, .vram, .log)
set -uo pipefail
cd ~/hq031-bench || exit 1; mkdir -p out; O=out
base=http://127.0.0.1:8081
idle() { curl -s -m 60 $base/unload >/dev/null
  for i in $(seq 1 60); do [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 600 ] && return 0; sleep 2; done
  echo "!! card not empty"; return 1; }
peak_start() { : > "$O/$1.vram"; ( while :; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits >> "$O/$1.vram"; sleep 2; done ) & PK=$!; }
peak_stop() { kill "$PK" 2>/dev/null; wait "$PK" 2>/dev/null; echo "   peak $(sort -n "$O/$1.vram" | tail -1) MiB"; }
failed=0
round() { e=$1 label=$2
  idle || { failed=$((failed + 1)); return; }
  echo "== $(date '+%F %T') $label ($e)"; rm -f "$O/$label.json" "$O/$label.deep.json"
  peak_start "$label"; t0=$(date +%s)
  # load first; the first token of the first prompt would otherwise include the load
  if ! curl -s -m 2400 $base/v1/chat/completions -H 'Content-Type: application/json' \
      -d "{\"model\":\"$e\",\"max_tokens\":4,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"chat_template_kwargs\":{\"enable_thinking\":false}}" \
      | grep -q '"choices"'; then
    echo "!! $e did not answer"; peak_stop "$label"; podman logs hyperqwen > "$O/$label.server.log" 2>&1; failed=$((failed + 1)); idle; return
  fi
  echo "   loaded in $(( $(date +%s) - t0 )) s, vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
  python3 bench_tasks.py $base "$e" --tokens 400 --label "$label" --output "$O/$label.json" 2>&1 | tail -4
  [ "${PIPESTATUS[0]}" = 0 ] || { echo "!! bench_tasks failed"; failed=$((failed + 1)); }
  python3 deep.py $base "$e" 6400 41 "$O/$label.deep.json" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 0 ] || { echo "!! deep.py failed"; failed=$((failed + 1)); }
  peak_stop "$label"
  podman logs hyperqwen > "$O/$label.server.log" 2>&1
}
round qwen3.8-27b-vllm-031 v031-warm
round qwen3.8-27b-vllm-031 v031-r1
round qwen3.8-27b-vllm v030-r1
round qwen3.8-27b-vllm-031 v031-r2
round qwen3.8-27b-vllm v030-r2
idle
echo "== ALL DONE $(date '+%F %T'), $failed failed"
exit $failed
