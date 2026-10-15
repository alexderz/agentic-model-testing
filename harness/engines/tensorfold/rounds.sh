#!/bin/bash
# Engine comparison on titan, 2026-10-13: TensorFold 0.6.6 + DFlash2 against our llama.cpp entries on
# the same prompts. A fresh server start for every engine and round, engines interleaved. Needs the GPU lease.
set -u
cd ~/tf-bench
B="python3 bench_tasks.py"
free_gpu() { for i in $(seq 1 60); do [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 600 ] && return 0; sleep 2; done; echo "GPU not free"; return 1; }
wait_tf() { for i in $(seq 1 200); do podman logs tensorfold 2>&1 | grep -q "serving bench" && return 0; podman ps -q --filter name=tensorfold | grep -q . || return 1; sleep 3; done; return 1; }
tf() { label=$1; shift; echo "== $(date +%T) $label"; podman rm -f -t 10 tensorfold >/dev/null 2>&1; free_gpu || return
  ./run.sh --context 16384 --no-thinking "$@" >/dev/null && wait_tf && $B http://127.0.0.1:18080 bench --tokens 400 --label "$label" --output "$label.json" | tail -1
  echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"; podman logs tensorfold 2>&1 | grep -o "loaded in [0-9.]*s"; podman rm -f -t 10 tensorfold >/dev/null; }
lc() { label=$1; model=$2; echo "== $(date +%T) $label ($model)"; free_gpu || return
  $B http://127.0.0.1:8081 "$model" --tokens 400 --label "$label" --output "$label.json" | tail -1
  echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"; curl -s -m 60 http://127.0.0.1:8081/unload >/dev/null; }
tf tf-nodraft --no-drafts
for r in 1 2 3; do
  tf "tf-dflash2-r$r"
  lc "lcpp-mtp-r$r" lcpp6-q38-27b-cyber-mtp
  lc "lcpp-plain-r$r" qwen3.8-27b
done
free_gpu; echo "== ALL DONE $(date +%T)"
