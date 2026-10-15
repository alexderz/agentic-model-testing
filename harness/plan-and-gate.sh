#!/usr/bin/env bash
# Plan a config per model, verify it by loading, and gate it with a tool call.
#
# For each model: pick the largest context >= MIN_CTX that the card can hold with
# an f16 cache, estimate -ncmoe from the model size, then LOAD it. On OOM, raise
# -ncmoe (fewer experts on GPU) and retry. Records what actually worked.
#
# Predicting alone is not enough -- the KV estimate was wrong by 3.4x once
# because it assumed every block caches. Every row here is a real load.
#
#   ./plan-and-gate.sh <model-id> [model-id ...]
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"
set +e

MIN_CTX="${MIN_CTX:-131072}"      # >= 100k, per the operator. 131072 is the natural rung.
CEIL="${CEIL:-22600}"             # MiB; leave headroom for compute buffers
GATE_TIMEOUT="${GATE_TIMEOUT:-300}"  # inference only; warm() covers loading
OUT="${GATE_OUT:-$HERE/gates}"; mkdir -p "$OUT"
REPORT="$OUT/config-$(date +%Y%m%d-%H%M%S).tsv"
printf 'model\tctx\tkv\tncmoe\tvram_mib\tload_s\tfinish\tverdict\tnote\n' > "$REPORT"

TOOLS='[{"type":"function","function":{"name":"get_entity_state",
  "description":"Read the current state of one Home Assistant entity.",
  "parameters":{"type":"object","properties":{"entity_id":{"type":"string"}},
  "required":["entity_id"]}}}]'

for id in "$@"; do
  echo "=== plan+gate: $id ==="
  # Ask the config what this entry is; container-engine entries are not tunable.
  isctr=$(tssh "grep -A6 '^  $id:' ~/ai/config/llama-swap.yaml | grep -c 'podman run'")
  if [ "${isctr:-0}" -gt 0 ]; then
    echo "  container-engine entry (sglang/exl3) -- not flag-tunable, gating as configured"
    load_s=$(warm "$id"); v=$(vram)
    printf '%s\t%s\tn/a\tn/a\t%s\t%s\t-\t%s\tcontainer entry, used as configured\n' \
      "$id" "n/a" "${v:--1}" "${load_s:--1}" \
      "$([ -n "$load_s" ] && echo GATED || echo LOAD_FAILED)" >> "$REPORT"
    continue
  fi

  ok_cfg=""
  # Ladder of (cache type, context) fallbacks. A model that cannot hold the
  # target context at f16 should drop cache precision before it is dropped from
  # the cohort -- excluding it for a CONFIG reason would be recorded as if it
  # were a capability finding. 102400 is the floor the operator set (>= 100k).
  for combo in "f16 $MIN_CTX" "q8_0 $MIN_CTX" "q8_0 102400"; do
    set -- $combo; kvt="$1"; ctx="$2"
    [ -n "$ok_cfg" ] && break
    for attempt in $(seq 1 4); do
      cur_nc=$(tssh "grep -A8 '^  $id:' ~/ai/config/llama-swap.yaml | grep -oP '(?<=-ncmoe )\d+' | head -1")
      base_nc=${cur_nc:-0}
      try_nc=$(( base_nc + (attempt - 1) * 4 ))
      # A DENSE model has no expert-offload knob, so retrying the same flags
      # three more times just burns three more cold loads. Its only levers are
      # cache type and context, which the outer combo loop already walks.
      if [ "${base_nc:-0}" -eq 0 ]; then
        try_nc=0
        [ "$attempt" -gt 1 ] && break
      fi
      [ "$try_nc" -gt 60 ] && break
      flags="-ngl 999"
      [ "$try_nc" -gt 0 ] && flags="$flags -ncmoe $try_nc"
      flags="$flags -c $ctx -ctk $kvt -ctv $kvt"
      echo "  try: $flags"
      set_variant "$id" "$flags" >/dev/null 2>&1
      load_s=$(warm "$id")
      if [ -z "$load_s" ] || [ "$load_s" = "-1" ]; then
        echo "    load failed (likely OOM); backing off"; continue
      fi
      v=$(vram)
      if [ "${v:-99999}" -gt "$CEIL" ]; then
        echo "    ${v} MiB over ceiling ${CEIL}; backing off"; continue
      fi
      ok_cfg="$flags"; ok_v="$v"; ok_load="$load_s"; ok_nc="$try_nc"
      ok_kv="$kvt"; ok_ctx="$ctx"
      echo "    OK ${v} MiB in ${load_s}s (kv=$kvt ctx=$ctx)"
      break
    done
  done

  if [ -z "$ok_cfg" ]; then
    printf '%s\t-\t-\t-\t-\t-\t-\tNO_CONFIG\tnothing held at f16/q8_0 x %s or q8_0 x 102400 under %s MiB\n' \
      "$id" "$MIN_CTX" "$CEIL" >> "$REPORT"
    err "$id: no working config at ctx=$MIN_CTX"
    continue
  fi

  # Tool-call gate: the runtime must TERMINATE on a tool call, not just emit one.
  resp=$(curl -s -m "${GATE_TIMEOUT:-300}" "$TITAN_URL/chat/completions" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$id\",\"messages\":[
        {\"role\":\"user\",\"content\":\"What is the state of light.kitchen? Use the tool; do not guess.\"}],
        \"tools\":$TOOLS,\"tool_choice\":\"auto\",\"max_tokens\":512,\"temperature\":0.3}")
  read -r finish tname note < <(printf '%s' "$resp" | python3 -c "
import json,sys
raw=sys.stdin.read().strip()
if not raw: print('- - empty'); raise SystemExit
try: d=json.loads(raw)
except Exception: print('- - not_json'); raise SystemExit
if 'error' in d: print('- -', str(d['error'])[:50].replace(' ','_')); raise SystemExit
c=(d.get('choices') or [{}])[0]
fr=c.get('finish_reason') or '-'
tc=(c.get('message') or {}).get('tool_calls') or []
nm=(tc[0].get('function',{}).get('name') if tc else '-') or '-'
content=((c.get('message') or {}).get('content') or '')
print(fr, nm, 'xml_in_content' if (not tc and 'tool_call' in content) else '-')
")
  if [ "$finish" = "tool_calls" ] && [ "$tname" = "get_entity_state" ]; then
    verdict=PASS
  elif [ "$note" = "xml_in_content" ]; then verdict=FAIL_UNPARSED
  else verdict=FAIL_NO_TOOLCALL; fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$id" "${ok_ctx:-?}" "${ok_kv:-?}" "${ok_nc:-0}" "$ok_v" "$ok_load" "$finish" "$verdict" "$note" >> "$REPORT"
  case "$verdict" in PASS) ok "$id: $verdict ($ok_v MiB)";; *) err "$id: $verdict";; esac
done

echo; echo "=== $REPORT ==="; column -t -s$'\t' "$REPORT"
