#!/usr/bin/env bash
# Find the lowest -ncmoe (most experts on GPU) that holds at FULL context.
#
# Filling the card is the biggest single lever measured in this project: test 1
# saw 2.15x on one model from refilling idle VRAM, more than any model swap.
# The gates left 14-15 GiB of 24 idle.
#
# Runs llama-server directly on port 5899 inside the llama-swap container, so
# llama-swap.yaml is untouched until a winner is chosen.
#
#   ./tune-ncmoe.sh <model-dir> <shard-glob> [mmproj] 
set -uo pipefail
TITAN="${TITAN:-192.0.2.62}"
DIR="${1:?model dir}"; GLOB="${2:?glob}"; MMPROJ="${3:-}"
CTX="${CTX:-262144}"
KVT="${KVT:-q8_0}"     # -ctk/-ctv type: f16 | q8_0 | q4_0
LADDER="${LADDER:-46 43 40 38 36 34}"
CEIL="${CEIL:-22800}"   # MiB. Leave ~1.7 GiB: compute buffers grow under load,
                        # and a config that loads but OOMs mid-case is worse
                        # than one that never loaded.
LOG="/tmp/tune-$DIR.log"

run_remote() { ssh -n -o BatchMode=yes "$TITAN" "$@" 2>&1 | grep -v -iE "xauth|X11"; }

echo "=== tune $DIR at ctx=$CTX kv=$KVT (ceiling ${CEIL} MiB) ==="
run_remote "curl -s --max-time 30 localhost:8081/unload >/dev/null 2>&1; \
  for i in \$(seq 1 30); do v=\$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); \
  [ \"\$v\" -lt 2000 ] && break; sleep 2; done; echo \"card free at \${v} MiB\""

best=""; bestv=""; besttps=""
for NC in $LADDER; do
  printf '  -ncmoe %-3s ' "$NC"
  mm=""; [ -n "$MMPROJ" ] && mm="-mm /models/llm/$DIR/$MMPROJ"
  # Prove the positive: require a real completion, not just a log line. A
  # readiness grep for the wrong string once made a working server look dead.
  out=$(run_remote "
    podman exec llama-swap sh -c 'ls /models/llm/$DIR/$GLOB 2>/dev/null | head -1' > /tmp/tune-first 2>/dev/null
    first=\$(cat /tmp/tune-first)
    [ -n \"\$first\" ] || { echo 'NOFILE'; exit 0; }
    podman exec llama-swap /usr/local/bin/llama-server --host 127.0.0.1 --port 5899 \
      -fa on --metrics -ctk $KVT -ctv $KVT -m \"\$first\" $mm \
      -ngl 999 -ncmoe $NC -c $CTX --reasoning-budget 4096 > /tmp/tune-$DIR-$NC.log 2>&1 &
    pid=\$!
    ready=no
    for i in \$(seq 1 400); do
      grep -q 'llama_server: listening on' /tmp/tune-$DIR-$NC.log 2>/dev/null && { ready=yes; break; }
      grep -qiE 'failed to allocate|out of memory|cudaMalloc failed|model loading error' /tmp/tune-$DIR-$NC.log 2>/dev/null && { ready=oom; break; }
      kill -0 \$pid 2>/dev/null || { ready=died; break; }
      sleep 3
    done
    if [ \"\$ready\" != yes ]; then
      echo \"OOM \$(grep -oiE 'allocating [0-9.]+ MiB|out of memory' /tmp/tune-$DIR-$NC.log | head -1)\"
      kill \$pid 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null; sleep 6; exit 0
    fi
    r=\$(podman exec llama-swap curl -s --max-time 600 http://127.0.0.1:5899/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d '{\"model\":\"t\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ready\"}],\"max_tokens\":24,\"temperature\":0}')
    v=\$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    tps=\$(printf '%s' \"\$r\" | python3 -c 'import json,sys
raw=sys.stdin.read().strip()
try:
    d=json.loads(raw); t=d.get(\"timings\") or {}
    print(\"%.2f\" % (t.get(\"predicted_per_second\") or 0)) if \"choices\" in d else print(\"NOANSWER\")
except Exception: print(\"NOANSWER\")')
    echo \"OK \$v \$tps\"
    kill \$pid 2>/dev/null; podman exec llama-swap pkill -x llama-server 2>/dev/null
    for i in \$(seq 1 25); do v2=\$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); [ \"\$v2\" -lt 2000 ] && break; sleep 2; done
  ")
  set -- $out
  case "${1:-}" in
    OK)
      v="${2:-0}"; tps="${3:-?}"
      if [ "$tps" = "NOANSWER" ]; then
        echo "loaded ${v} MiB but did NOT answer -- rejecting"
      elif [ "$v" -gt "$CEIL" ]; then
        echo "${v} MiB > ceiling ${CEIL} -- too tight, stopping"
        break
      else
        echo "OK  ${v} MiB  ${tps} tok/s"
        best="$NC"; bestv="$v"; besttps="$tps"
      fi ;;
    OOM)   shift; echo "OOM ${*:-}"; break ;;
    NOFILE) echo "no file matching $GLOB"; break ;;
    *)     echo "unclear: ${out:0:80}"; break ;;
  esac
done

echo
if [ -n "$best" ]; then
  echo "  WINNER $DIR: -ncmoe $best -c $CTX kv=$KVT  ->  ${bestv} MiB, ${besttps} tok/s"
else
  echo "  no setting held at ctx=$CTX kv=$KVT"
fi
