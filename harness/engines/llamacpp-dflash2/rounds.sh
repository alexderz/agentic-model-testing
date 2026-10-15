#!/bin/bash
# llama.cpp + DFlash2 arm of the engine comparison on titan, 2026-10-13: our llama.cpp 0.6.0 image with the
# DFlash2 drafter (GGUF), with the MTP head of our entry and without drafting, on the prompts of
# engines/tensorfold/rounds.sh. A TensorFold round is interleaved in every round as the anchor to the other
# sittings. A fresh server start for every engine and round. Needs the GPU lease and nothing loaded in llama-swap.
# Runs in ~/tf-bench on titan, with this directory's files in ~/tf-bench/lcpp-dflash2.
# A round counts only if its JSON exists afterwards: the old file is removed first, and a server that did not
# start, runs another drafting mode than asked, or a failed benchmark leaves none ("FAILED").
set -uo pipefail
cd ~/tf-bench
B="python3 bench_tasks.py"
failed=0
fail() { echo "   FAILED: $*"; failed=$((failed + 1)); }
free_gpu() { for i in $(seq 1 60); do [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 600 ] && return 0; sleep 2; done; echo "GPU not free"; return 1; }
wait_tf() { for i in $(seq 1 200); do podman logs tensorfold 2>&1 | grep -q "serving bench" && return 0; podman ps -q --filter name=tensorfold | grep -q . || return 1; sleep 3; done; return 1; }
wait_lc() { for i in $(seq 1 100); do curl -sf -m 3 http://127.0.0.1:18082/health >/dev/null && return 0; podman ps -q --filter name=lcpp-dflash2 | grep -q . || return 1; sleep 3; done; return 1; }
# the server's own log must show the drafting mode that was asked for
check_lc() { mode=$1; log=$2
  case $mode in
    dflash2) grep -q "adding speculative implementation 'draft-dflash'" "$log" && grep -q "DFlash2-BF16.gguf" "$log" || { echo "BF16 DFlash drafter not in use"; return 1; };;
    dflash2-q4) grep -q "adding speculative implementation 'draft-dflash'" "$log" && grep -q "DFlash2-Q4_K_M.gguf" "$log" || { echo "Q4_K_M DFlash drafter not in use"; return 1; };;
    mtp) grep -q "creating MTP draft context" "$log" || { echo "MTP head not used"; return 1; };;
    nodraft) ! grep -qE "adding speculative implementation|creating MTP draft context" "$log" || { echo "a drafter is loaded"; return 1; };;
  esac; }
tf() { label=$1; shift; echo "== $(date +%T) $label"; rm -f "$label.json"
  podman rm -f -t 10 tensorfold >/dev/null 2>&1; free_gpu || { fail "GPU busy"; return 1; }
  if ./run.sh --context 16384 --no-thinking "$@" >/dev/null && wait_tf; then
    if out=$($B http://127.0.0.1:18080 bench --tokens 400 --label "$label" --output "$label.json"); then echo "$out" | tail -1
    else rm -f "$label.json"; fail "benchmark"; fi
    echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"; podman logs tensorfold 2>&1 | grep -o "loaded in [0-9.]*s"
  else fail "server did not start"; fi
  podman rm -f -t 10 tensorfold >/dev/null 2>&1; }
# lc LABEL MODE [extra llama-server flags]
lc() { label=$1; mode=$2; shift 2; echo "== $(date +%T) $label ($mode $*)"; rm -f "$label.json"; ok=1
  podman rm -f -t 10 lcpp-dflash2 >/dev/null 2>&1; free_gpu || { fail "GPU busy"; return 1; }
  t0=$(date +%s)
  if EXTRA="$*" lcpp-dflash2/run.sh "$mode" >/dev/null && wait_lc; then
    echo "   ready after $(( $(date +%s) - t0 )) s, vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
    podman logs lcpp-dflash2 > "$label.server.log" 2>&1
    if why=$(check_lc "$mode" "$label.server.log"); then
      if out=$($B http://127.0.0.1:18082 bench --tokens 400 --label "$label" --output "$label.json"); then echo "$out" | tail -1; ok=0
      else rm -f "$label.json"; fail "benchmark"; fi
      echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
    else fail "$why"; fi
  else fail "server did not start"; podman logs lcpp-dflash2 2>&1 | grep -iE "out of memory|failed to" | head -3; fi
  podman logs lcpp-dflash2 > "$label.server.log" 2>&1
  awk '/draft acceptance/ { for (i = 1; i <= NF; i++) if ($i == "accepted") { a += $(i-1); g += $(i+2) } } END { if (g) printf "   drafts: %d of %d accepted (%.0f %%)\n", a, g, 100*a/g }' "$label.server.log"
  podman rm -f -t 10 lcpp-dflash2 >/dev/null 2>&1; return $ok; }
# one arm by hand:  lcpp-dflash2/rounds.sh lc LABEL MODE [flags]   or   lcpp-dflash2/rounds.sh tf LABEL
if [ $# -gt 0 ]; then "$@"; echo "== DONE $(date +%T), $failed failed"; exit "$failed"; fi
# The BF16 drafter does not fit beside four server slots (the default); try it with one slot, else use Q4_K_M.
D=dflash2; DF="-np 1"
# Only an out-of-memory start switches the drafter; any other failure ends the run.
if ! lc lcpp-dflash2-bf16-np1 dflash2 -np 1; then
  grep -qiE "out of memory|failed to allocate" lcpp-dflash2-bf16-np1.server.log || { echo "== STOPPED $(date +%T): the BF16 probe failed for another reason"; exit 1; }
  failed=$((failed - 1)); echo "   BF16 drafter does not fit; rounds use the Q4_K_M drafter"; D=dflash2-q4; DF=""; fi
lc lcpp-nodraft nodraft
for r in 1 2 3; do
  lc "lcpp-dflash2-r$r" "$D" $DF
  tf "tf-dflash2-s3-r$r"
  lc "lcpp-mtp-r$r" mtp
done
lc lcpp-dflash2-q4-np1 dflash2-q4 -np 1
lc lcpp-dflash2-q4-np4 dflash2-q4
free_gpu; echo "== ALL DONE $(date +%T), $failed failed"; exit "$failed"
