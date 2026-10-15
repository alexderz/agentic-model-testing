#!/bin/bash
# exllamav3 arm of the engine comparison on titan, 2026-10-13: exllamav3 1.6.1 with the DFlash2 drafter,
# with its own MTP head and without drafting, on the prompts of engines/tensorfold/rounds.sh. A TensorFold round is
# interleaved in every round, so the two DFlash2 engines are measured in one sitting. A fresh server start for
# every engine and round. Needs the GPU lease and nothing loaded in llama-swap. Runs in ~/tf-bench on titan, with
# this directory's files in ~/tf-bench/exllamav3 and TensorFold's run.sh next to bench_tasks.py.
# A round counts only if its JSON exists afterwards: the old file is removed first, and a server that did not
# start, did not warm up, runs another drafting mode than asked, or a failed benchmark leaves none ("FAILED").
set -uo pipefail
cd ~/tf-bench
B="python3 bench_tasks.py"
failed=0
fail() { echo "   FAILED: $*"; failed=$((failed + 1)); }
free_gpu() { for i in $(seq 1 60); do [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 600 ] && return 0; sleep 2; done; echo "GPU not free"; return 1; }
wait_tf() { for i in $(seq 1 200); do podman logs tensorfold 2>&1 | grep -q "serving bench" && return 0; podman ps -q --filter name=tensorfold | grep -q . || return 1; sleep 3; done; return 1; }
# TabbyAPI loads the model (and warms it up) before it opens the port, so an answer from /v1/models means ready
wait_ex() { for i in $(seq 1 300); do curl -sf -m 3 http://127.0.0.1:18081/v1/models >/dev/null && return 0; podman ps -q --filter name=exllamav3 | grep -q . || return 1; sleep 3; done; return 1; }
# the server's own log must show the warmup and the drafting mode that was asked for
check_ex() { mode=$1; log=$2
  grep -q "Warmup finished" "$log" || { echo "no warmup"; return 1; }
  case $mode in
    dflash2) grep -q "Using draft model" "$log" || { echo "drafter not loaded"; return 1; };;
    mtp) grep -q "Using main model MTP component" "$log" || { echo "MTP head not used"; return 1; };;
    nodraft) ! grep -qE "Using draft model|Using main model MTP component" "$log" || { echo "a drafter is loaded"; return 1; };;
  esac; }
tf() { label=$1; shift; echo "== $(date +%T) $label"; rm -f "$label.json"
  podman rm -f -t 10 tensorfold >/dev/null 2>&1; free_gpu || { fail "GPU busy"; return; }
  if ./run.sh --context 16384 --no-thinking "$@" >/dev/null && wait_tf; then
    if out=$($B http://127.0.0.1:18080 bench --tokens 400 --label "$label" --output "$label.json"); then echo "$out" | tail -1
    else rm -f "$label.json"; fail "benchmark"; fi
    echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"; podman logs tensorfold 2>&1 | grep -o "loaded in [0-9.]*s"
  else fail "server did not start"; fi
  podman rm -f -t 10 tensorfold >/dev/null 2>&1; }
ex() { label=$1; shift; mode=${1:-dflash2}; echo "== $(date +%T) $label"; rm -f "$label.json"
  podman rm -f -t 10 exllamav3 >/dev/null 2>&1; free_gpu || { fail "GPU busy"; return; }
  t0=$(date +%s)
  if exllamav3/run.sh "$@" >/dev/null && wait_ex; then
    echo "   ready after $(( $(date +%s) - t0 )) s"; podman logs exllamav3 > "$label.server.log" 2>&1
    if why=$(check_ex "$mode" "$label.server.log"); then
      model=$(curl -s -m 5 http://127.0.0.1:18081/v1/model | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
      if out=$($B http://127.0.0.1:18081 "$model" --tokens 400 --label "$label" --output "$label.json"); then echo "$out" | tail -1
      else rm -f "$label.json"; fail "benchmark"; fi
      echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
    else fail "$why"; fi
  else fail "server did not start"; fi
  podman logs exllamav3 > "$label.server.log" 2>&1; podman rm -f -t 10 exllamav3 >/dev/null 2>&1; }
# one arm by hand:  exllamav3/rounds.sh ex LABEL [dflash2|mtp|nodraft] [3bpw]   or   exllamav3/rounds.sh tf LABEL
if [ $# -gt 0 ]; then "$@"; echo "== DONE $(date +%T), $failed failed"; exit "$failed"; fi
ex ex-nodraft nodraft
for r in 1 2 3; do
  ex "ex-dflash2-r$r" dflash2
  tf "tf-dflash2-s2-r$r"
  ex "ex-mtp-r$r" mtp
done
ex ex-dflash2-3bpw dflash2 3bpw
free_gpu; echo "== ALL DONE $(date +%T), $failed failed"
