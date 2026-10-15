#!/usr/bin/env bash
# Find the lowest -ncmoe that still loads, i.e. the most weight we can keep
# resident on the card, for each MoE model that is currently leaving VRAM idle.
#
# The round 1/2 "max" variants were tuned for CONTEXT and never checked whether
# they filled the GPU. They did not: every case but one left 5-15 GB unused, and
# qwen3-235b was running on 9 GB of a 24 GB card. -ncmoe N keeps N layers' worth
# of experts on the CPU, so LOWER means more on the GPU and faster.
#
# Steps down until the load fails, then reports the last value that worked with
# one step of safety margin. Writes results/fill-probe.tsv.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"; source lib.sh

OUT="${OUT:-$HERE/results/fill-probe.tsv}"
mkdir -p "$(dirname "$OUT")"
printf 'model\tctx\tstart_ncmoe\tbest_ncmoe\tvram_mib\tload_s\theadroom_mib\n' > "$OUT"

# model : context : starting ncmoe (the value the current case uses)
CANDIDATES="${CANDIDATES:-
qwen3-235b-a22b:40960:94
glm-4.7-flash:202752:30
glm-4.7-flash:65536:12
nemotron3-super-120b:1048576:88
glm-4.5-air:131072:47
nemotron3-nano-30b:262144:24
nemotron3-nano-30b:1048576:30
qwen3-coder-30b-a3b:65536:8
}"

try() {  # try <model> <flags> -> echoes "vram load_s" or nothing
  local m="$1" f="$2" ls v
  set_variant "$m" "$f" >/dev/null 2>&1 || return 1
  ls=$(warm "$m" 2>/dev/null || echo -1)
  [ "$ls" = "-1" ] && return 1
  v=$(vram)
  echo "$v $ls"
}

for entry in $CANDIDATES; do
  [ -z "$entry" ] && continue
  model="${entry%%:*}"; rest="${entry#*:}"
  ctx="${rest%%:*}"; start="${rest##*:}"

  echo "=== $model  ctx=$ctx  from ncmoe=$start ==="
  step=$(( start / 8 )); [ "$step" -lt 2 ] && step=2
  best=""; best_v=""; best_l=""
  n="$start"

  while [ "$n" -ge 0 ]; do
    flags="-ngl 999 -ncmoe $n -c $ctx"
    printf '  ncmoe %-3s ' "$n"
    if res=$(try "$model" "$flags"); then
      v="${res%% *}"; l="${res##* }"
      printf 'OK  %s MiB (%ss free)\n' "$v" "$((24576 - v))"
      best="$n"; best_v="$v"; best_l="$l"
      # stop once we are within ~1.5 GB of the card: further steps will OOM
      [ "$((24576 - v))" -lt 1500 ] && { echo "  -> near capacity, stopping"; break; }
      n=$((n - step))
    else
      printf 'FAIL (oom)\n'
      break
    fi
  done

  if [ -n "$best" ]; then
    # one step of margin back toward safety, since VRAM use drifts with load
    safe=$best
    [ "$((24576 - best_v))" -lt 800 ] && safe=$((best + 2))
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$model" "$ctx" "$start" "$safe" "$best_v" "$best_l" "$((24576 - best_v))" >> "$OUT"
    echo "  best: ncmoe $safe (was $start)"
  else
    printf '%s\t%s\t%s\tNONE\t\t\t\n' "$model" "$ctx" "$start" >> "$OUT"
    echo "  nothing loaded"
  fi
done

echo
column -t -s$'\t' "$OUT"
