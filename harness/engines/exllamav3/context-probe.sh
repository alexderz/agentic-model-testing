#!/bin/bash
# How much context exllamav3 holds on titan's 24 GiB, and how fast it reads a long prompt.
#   [MODE=dflash2|mtp|nodraft] exllamav3/context-probe.sh CACHE_TOKENS CACHE_MODE "LINES SEED" ["LINES SEED" ...]
# CACHE_MODE is TabbyAPI's cache_mode: FP16, or k_bits,v_bits such as 8,8. Each "LINES SEED" is one prompt of
# engines/tensorfold/long_prompt.py (about 22 tokens a line; a new seed gives a prompt nothing has cached).
# Needs the GPU lease and nothing loaded in llama-swap. Runs in ~/tf-bench on titan.
set -uo pipefail
cd ~/tf-bench
size=$1; cmode=$2; shift 2; mode=${MODE:-dflash2}
echo "== exllamav3 1.6.1, $mode, 4.00bpw, cache_size $size, cache_mode $cmode, $(date '+%F %T')"
podman rm -f -t 10 exllamav3 >/dev/null 2>&1
for i in $(seq 1 60); do [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 600 ] && break; sleep 2; done
EXTRA_ENV="-e TABBY_MODEL_CACHE_SIZE=$size -e TABBY_MODEL_MAX_SEQ_LEN=$size -e TABBY_MODEL_CACHE_MODE=$cmode" exllamav3/run.sh "$mode" >/dev/null
ok=0; for i in $(seq 1 300); do curl -sf -m 3 http://127.0.0.1:18081/v1/models >/dev/null && { ok=1; break; }
  podman ps -q --filter name=exllamav3 | grep -q . || break; sleep 3; done
if [ $ok = 1 ]; then
  echo "   loaded, vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
  model=$(curl -s -m 5 http://127.0.0.1:18081/v1/model | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
  for p in "$@"; do
    echo "-- $p (lines seed)"
    # shellcheck disable=SC2086
    python3 long_prompt.py http://127.0.0.1:18081 "$model" $p 2>&1 | tail -3
    podman logs exllamav3 2>&1 | tr -s ' \n' ' ' | grep -oE "#[0-9]+ chat/completions: [0-9,]+ tokens generated[^#]*" | tail -1
    echo "   vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
  done
else
  echo "   DID NOT LOAD"; podman logs exllamav3 2>&1 | grep -v '^ *$' | tail -12
fi
podman logs exllamav3 2>&1 | grep -ciE "out of memory|OOM" | sed 's/^/   out-of-memory lines in the server log: /'
podman rm -f -t 10 exllamav3 >/dev/null 2>&1
