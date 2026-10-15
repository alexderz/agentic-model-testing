#!/usr/bin/env bash
# Gate models before spending a night on them.
#
# Two checks per model, both non-negotiable:
#   load        the entry starts and answers a trivial completion
#   tool_calls  it emits a parseable tool call and the runtime TERMINATES on it
#
# The second one is the expensive catch. A model whose chat template llama.cpp
# cannot terminate on generates to the token limit on every turn and scores
# zero for reasons that have nothing to do with capability. MiMo-V2.6-9B was
# excluded from test 1 for exactly this.
#
#   ./gate-models.sh model-a model-b ...
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"
set +e     # a failed gate is a RESULT; -e would abort the remaining models

OUT="${GATE_OUT:-$HERE/gates}"; mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
REPORT="$OUT/gate-$STAMP.tsv"
printf 'model\tload_s\tvram_mib\tfinish_reason\ttool_name\tverdict\tnote\n' > "$REPORT"

TOOLS='[{"type":"function","function":{"name":"get_entity_state",
  "description":"Read the current state of one Home Assistant entity.",
  "parameters":{"type":"object","properties":{"entity_id":{"type":"string",
  "description":"e.g. light.kitchen"}},"required":["entity_id"]}}}]'

for id in "$@"; do
  echo "=== gate: $id ==="
  load_s=$(warm "$id"); rc=$?
  if [ $rc -ne 0 ] || [ -z "$load_s" ]; then
    printf '%s\t-\t-\t-\t-\tLOAD_FAILED\tdid not answer a trivial completion\n' "$id" >> "$REPORT"
    err "$id: load failed"; continue
  fi
  v=$(vram); ok "$id loaded in ${load_s}s, VRAM ${v} MiB"

  # Ask for something only the tool can answer, so a refusal to call it is a
  # real signal rather than the model reasonably answering from knowledge.
  # The model is already loaded here, so this is pure inference and does not
  # need the load-sized budget warm() uses. Sized from the arithmetic instead:
  # at the ~15 tok/s these models decode, a --reasoning-budget 4096 model can
  # legitimately spend ~275s thinking before its first tool call. 300s covers
  # that; 90s would fail reasoning models for reasoning.
  resp=$(curl -s -m "${GATE_TIMEOUT:-900}" "$TITAN_URL/chat/completions" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$id\",\"messages\":[
        {\"role\":\"user\",\"content\":\"What is the current state of light.kitchen? Use the tool; do not guess.\"}],
        \"tools\":$TOOLS,\"tool_choice\":\"auto\",\"max_tokens\":512,\"temperature\":0.3}")
  read -r finish tname note < <(printf '%s' "$resp" | python3 -c "
import json,sys
raw=sys.stdin.read().strip()
if not raw: print('- - empty_response'); raise SystemExit
try: d=json.loads(raw)
except Exception: print('- - not_json'); raise SystemExit
if 'error' in d:
    print('- -', str(d['error'])[:60].replace(' ','_')); raise SystemExit
c=(d.get('choices') or [{}])[0]
fr=c.get('finish_reason') or '-'
tc=(c.get('message') or {}).get('tool_calls') or []
name=(tc[0].get('function',{}).get('name') if tc else '-') or '-'
# A model that emits tool-call XML as plain content is the failure this gate
# exists to catch: well-formed intent the runtime never parsed.
content=((c.get('message') or {}).get('content') or '')
hint='xml_in_content' if (not tc and 'tool_call' in content) else '-'
print(fr, name, hint)
")
  if [ "$finish" = "tool_calls" ] && [ "$tname" = "get_entity_state" ]; then
    verdict=PASS
  elif [ "$note" = "xml_in_content" ]; then
    verdict=FAIL_UNPARSED
  else
    verdict=FAIL
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$load_s" "$v" "$finish" "$tname" "$verdict" "$note" >> "$REPORT"
  case "$verdict" in
    PASS) ok "$id: tool call OK (finish=$finish)";;
    *)    err "$id: $verdict (finish=$finish tool=$tname note=$note)";;
  esac
done

echo; echo "=== gate report: $REPORT ==="
column -t -s$'\t' "$REPORT"
