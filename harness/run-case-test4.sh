#!/usr/bin/env bash
# Test 4: one repeated run of one ticket against the known-good project (suites/test4/DESIGN.md).
#
#   run-case-test4.sh <case> <model> <flags> [<ticket> [<run>]]
#
# One case = one model entry, one ticket, one run number. Case names are t4-<ticket>-<model short
# name>-r<n>. When <ticket> is not given (run-matrix.sh passes only case, model and flags), the case's
# row in $MATRIX (default matrix-test4.tsv) names it in its note as `ticket=<id>`; failing that it is
# read from the case name. The run number comes from the case name's -r<n>.
#
# The agent gets a fresh copy of suites/test4/project as /work and the ticket's TICKET.md, wrapped in
# suites/test4/prompt-preamble.txt, as its prompt. Before the clock starts the project is built once
# (log: t4/prebuild.log), so the cap measures the agent's work, not the first compile. The agent is
# stopped after $T4_CAP_S seconds (default 2700 = 45 minutes) by `timeout` inside the container.
# Same sandbox, model loading, context margins and network policy as run-case-sandboxed.sh; OpenCode
# only. Grade with grade-test4.py.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_results_env="${RESULTS:-}"
source "$HERE/lib.sh"
set +e                                   # lib.sh turns on -e; this runner checks each step itself
CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:--}"; TICKET="${4:-}"; RUN="${5:-}"
SUITE="$HERE/suites/test4"
M="${MATRIX:-$HERE/matrix-test4.tsv}"
if [ -z "$TICKET" ] && [ -f "$M" ]; then
  TICKET=$(awk -F'\t' -v c="$CASE" '$1==c {print $4}' "$M" | grep -oP 'ticket=\K[A-Za-z0-9_-]+' | head -1)
fi
if [ -z "$TICKET" ]; then                # from the case name: the longest ticket id it starts with
  for t in $(ls "$SUITE/tickets" | awk '{print length($0), $0}' | sort -rn | cut -d' ' -f2); do
    case "$CASE" in "t4-$t-"*) TICKET="$t"; break ;; esac
  done
fi
[ -n "$TICKET" ] || { err "no ticket=<id> for $CASE in $M and none in the case name"; exit 1; }
[ -s "$SUITE/tickets/$TICKET/TICKET.md" ] || { err "unknown ticket: $TICKET"; exit 1; }
[ -n "$RUN" ] || RUN=$(printf '%s' "$CASE" | grep -oP -- '-r\K[0-9]+$')
RUN="${RUN:-0}"
[ "$FLAGS" = "-" ] && FLAGS=""
RESULTS="${_results_env:-$HERE/results-test4}"
PREAMBLE="${PROMPT_PREAMBLE:-$SUITE/prompt-preamble.txt}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
LAN="${TITAN_LAN:-192.0.2.62}"
CAP="${T4_CAP_S:-2700}"

OUT="$RESULTS/$CASE"
if [ -f "$OUT/meta.json" ]; then
  arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"
fi
rm -rf "$OUT" 2>/dev/null || eb_rm "$OUT"; mkdir -p "$OUT/work" "$OUT/t4"
[ -s "$PREAMBLE" ] || { err "prompt preamble missing: $PREAMBLE"; exit 1; }
[ -f "$SUITE/project/Cargo.toml" ] || { err "starting tree missing: $SUITE/project"; exit 1; }

# a fresh work tree for every run
tar -C "$SUITE/project" --exclude=./target --exclude=./.git -cf - . | tar -C "$OUT/work" -xf -
cat "$PREAMBLE" "$SUITE/tickets/$TICKET/TICKET.md" > "$OUT/prompt.txt"
printf '%s\n' "$TICKET" "$RUN" "$CAP" > "$OUT/t4/case.txt"

echo "=== $CASE : $MODEL : $FLAGS : ticket $TICKET, run $RUN, cap ${CAP}s  [test 4, sandboxed] ==="
# A matrix note may carry `spec={...}` (engines/ENTRY-SPEC.md): set_variant applies it to the entry's spec file.
SPEC_OVR=$( [ -n "${MATRIX:-}" ] && [ -f "$MATRIX" ] && python3 -I "$HERE/tools/entry_spec.py" --note-override \
  "$(awk -F'\t' -v c="$CASE" '$1==c {print $4; exit}' "$MATRIX")" </dev/null || true)
[ -n "$SPEC_OVR" ] && printf '%s\n' "$SPEC_OVR" > "$OUT/spec-override.json"
set_variant "$MODEL" "$FLAGS" "$SPEC_OVR" >/dev/null 2>&1 || {
  err "could not set variant"; echo "{\"case\":\"$CASE\",\"status\":\"variant_failed\"}" > "$OUT/meta.json"; exit 1; }
load_s=$(warm "$MODEL" || echo "-1")
[ "$load_s" = "-1" ] && {
  err "$CASE: model failed to load with [$FLAGS]"
  echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"load_failed\"}" > "$OUT/meta.json"; exit 1; }
v=$(vram); ok "loaded in ${load_s}s, VRAM ${v} MiB"

HA_URL="${HA_URL:-http://host.containers.internal:8126}"
HA_TOKEN="${HA_TOKEN:-bakeoff-placeholder-token}"
PROXY_LOG="${PROXY_LOG:-/srv/bakeoff/replay-logs/ha-replay-access.log}"
proxy_start=$(wc -l < "$PROXY_LOG" 2>/dev/null || echo 0)

# context and reply limits: from the entry's bakeoff.spec, as in run-case-sandboxed.sh (fallback: the old map, loudly)
if LIM=$(python3 -I "$HERE/tools/entry_spec.py" --titan --limits "$MODEL" 2>>"$OUT/spec-warnings.log" </dev/null); then
  read -r _ OUT_LIMIT CTX_LIMIT _ <<<"$LIM"
  python3 -I "$HERE/tools/entry_spec.py" --titan --entry "$MODEL" > "$OUT/entry-spec.json" 2>>"$OUT/spec-warnings.log" </dev/null || true
  log "limits from bakeoff.spec: OpenCode context $CTX_LIMIT, reply $OUT_LIMIT"
else
echo "!! WARNING: $MODEL has no usable bakeoff.spec; using the old hand-kept limits ($OUT/spec-warnings.log)" >&2
CTX_LIMIT=$(printf '%s' "$FLAGS" | sed -En 's/.*-c ([0-9]+).*/\1/p')
case "$MODEL" in
  qwen3.8-27b-vllm)      CTX_LIMIT=150000 ;;
  qwen3.8-27b-vllm-240k) CTX_LIMIT=245760 ;;
  qwen3.8-27b-uncensored-vllm) CTX_LIMIT=150000 ;;
  gemma-4-26b-a4b-vllm)  CTX_LIMIT=73728 ;;
  flashnext)             CTX_LIMIT=204800 ;;
  qwen3.8-27b-vllm-64k)  CTX_LIMIT=65536 ;;
  qwen3.8-27b-vllm-quote) CTX_LIMIT=57344 ;;
  strata-*)              CTX_LIMIT=262144 ;;
esac
CTX_LIMIT=${CTX_LIMIT:-131072}
M10=$(( CTX_LIMIT / 10 )); MARGIN=$(( M10 > 16384 ? M10 : 16384 ))
CTX_LIMIT=$(( CTX_LIMIT - MARGIN ))
OUT_LIMIT=$(( CTX_LIMIT / 4 < 32000 ? CTX_LIMIT / 4 : 32000 ))
fi   # end of the fallback
TB=$(( OUT_LIMIT - 6000 < 24000 ? OUT_LIMIT - 6000 : 24000 ))
OPTS=""
case "$MODEL" in *-vllm|*-vllm-*) OPTS="\"thinking_token_budget\": $TB" ;; esac
case "$CASE" in *-pp|*-pp-r[0-9]*) OPTS="${OPTS:+$OPTS, }\"presence_penalty\": 1.5" ;; esac
MODEL_OPTS=""; [ -n "$OPTS" ] && MODEL_OPTS=", \"options\": {$OPTS}"

# The OpenCode config of run-case-sandboxed.sh, unchanged: see the notes there for each setting.
mkdir -p "$OUT/oc" "$OUT/oc-data"
cat > "$OUT/oc/opencode.json" <<OCEOF
{
  "\$schema": "https://opencode.ai/config.json",
  "share": "disabled",
  "autoupdate": false,
  "instructions": [],
  "skills": [],
  "plugin": [],
  "snapshot": false,
  "subagent_depth": 1,
  "logLevel": "INFO",
  "enabled_providers": ["titan"],
  "model": "titan/$MODEL",
  "small_model": "titan/$MODEL",
  "provider": {"titan": {"npm": "@ai-sdk/openai-compatible",
    "options": {"baseURL": "http://$LAN:8080/v1",
                "requestTimeout": 5400000, "timeout": 5400000},
    "models": {"$MODEL": {"name": "$MODEL",
      "limit": {"context": $CTX_LIMIT, "output": $OUT_LIMIT}$MODEL_OPTS}}}},
  "tools": {
    "bash": true, "edit": true, "write": true, "read": true,
    "grep": true, "glob": true, "lsp": true, "apply_patch": true,
    "skill": true, "todowrite": true, "task": true,
    "webfetch": true, "websearch": true,
    "question": false
  },
  "permission": {"bash": "allow", "edit": "allow", "webfetch": "allow", "doom_loop": "deny"}
}
OCEOF
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$OUT/oc/opencode.json" \
  || { err "config generation failed"; exit 1; }

cat > "$OUT/agent-cmd.sh" <<AGENTEOF
export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=1800000
# CARGO_HOME under /root: the agent runs as container root without capabilities, which cannot write
# /home/agent (owned by uid 1000). Rustup's toolchain stays in /opt (RUSTUP_HOME, /opt/cargo/bin).
export CARGO_HOME=/root/.cargo PATH="/root/.cargo/bin:/opt/cargo/bin:\$PATH"
export HA_URL='$HA_URL' HA_BASE_URL='$HA_URL' HA_TOKEN='$HA_TOKEN'
export HOME=/root
# Before the clock starts: fetch the crates and compile the project as it is, release and test profile.
( cd /work && cargo build --release && cargo test --no-run ) > /t4/prebuild.log 2>&1 \
  && echo "prebuild: ok" >> /t4/prebuild.log || echo "prebuild: FAILED" >> /t4/prebuild.log
cd /work
date +%s.%N > /t4/agent-start
timeout -k 30 $CAP opencode run --auto --pure --format json --log-level INFO --model "titan/$MODEL" --dir /work "\$(cat /prompt.txt)"
rc=\$?
date +%s.%N > /t4/agent-end
echo \$rc > /t4/agent-rc
exit \$rc
AGENTEOF

# podman runs as evalbox (tools/podman-eb): hand it every mounted path; shared inputs as mirrors
eb_take "$OUT/work" "$OUT/agent-cmd.sh" "$OUT/prompt.txt" "$OUT/oc" "$OUT/oc-data" "$OUT/t4" \
  || { err "could not hand the case files to evalbox"; exit 1; }
NETPOL=$(eb_input "$HERE/net-policy.sh") || exit 1

t0=$(date +%s.%N)
trap 'podman rm -f "bakeoff-$CASE" >/dev/null 2>&1 || true' EXIT INT TERM
podman run --rm --name "bakeoff-$CASE" \
  --user root \
  --add-host=host.containers.internal:host-gateway \
  --memory=8g --pids-limit=1024 \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=SETPCAP \
  --security-opt=no-new-privileges \
  -e TITAN_IP="$LAN" \
  -v "$NETPOL":/net-policy.sh:ro,z \
  -v "$OUT/work":/work:Z \
  -v "$OUT/t4":/t4:Z \
  -v "$OUT/agent-cmd.sh":/agent-cmd.sh:ro,Z \
  -v "$OUT/prompt.txt":/prompt.txt:ro,Z \
  -v "$OUT/oc/opencode.json":/root/.config/opencode/opencode.json:ro,Z \
  -v "$OUT/oc-data":/root/.local/share/opencode:Z \
  "$IMAGE" /net-policy.sh bash /agent-cmd.sh \
  > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
t1=$(date +%s.%N)
wall=$(python3 -c "print(f'{float('$t1')-float('$t0'):.1f}')")
# the agent's own time: between the two stamps agent-cmd.sh writes; the whole container when one is missing
dur=$(python3 - "$OUT/t4" "$wall" <<'PY'
import sys
try:
    a = float(open(sys.argv[1] + "/agent-start").read()); b = float(open(sys.argv[1] + "/agent-end").read())
    print(f"{b - a:.1f}")
except (OSError, ValueError):
    print(sys.argv[2])
PY
)
agent_rc=$(cat "$OUT/t4/agent-rc" 2>/dev/null || echo "$rc")
[ "$rc" -ne 0 ] && err "agent exited $rc (see stderr.log)"

ev_bytes=$(wc -c < "$OUT/events.jsonl" 2>/dev/null || echo 0)
if [ "$ev_bytes" -lt 5000 ]; then
  err "agent produced only ${ev_bytes} bytes of events -- treating as HARNESS failure, not a model result"
  python3 -c "
import json; json.dump({'case':'$CASE','model':'$MODEL','flags':'$FLAGS','status':'harness_failure',
 'reason':'events.jsonl only ${ev_bytes} bytes','test':4,'ticket':'$TICKET','run':int('$RUN'),'sandboxed':True},
 open('$OUT/meta.json','w'), indent=2)"
  exit 1
fi
tail -n +$((proxy_start + 1)) "$PROXY_LOG" 2>/dev/null > "$OUT/ha-requests.jsonl" || true
python3 "$HERE/distil-meta.py" "$OUT" "$CASE" "$MODEL" "$FLAGS" "$load_s" "$v" "$dur" "" 2>/dev/null \
  || echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"ok\",\"duration_s\":$dur,\"sandboxed\":true}" > "$OUT/meta.json"
python3 - "$OUT" "$TICKET" "$RUN" "$CAP" "$agent_rc" "$wall" <<'PY'
import json, os, sys
out, ticket, run, cap, rc, wall = sys.argv[1:7]
p = os.path.join(out, "meta.json")
m = json.load(open(p))
pre = os.path.join(out, "t4", "prebuild.log")
m.update(test=4, ticket=ticket, run=int(run), cap_s=int(cap), agent_rc=int(rc), timed_out=int(rc) in (124, 137),
         container_wall_s=float(wall),
         prebuild=("ok" if os.path.exists(pre) and "prebuild: ok" in open(pre, errors="replace").read() else "failed"))
json.dump(m, open(p, "w"), indent=2)
PY
echo "  test 4 case done in ${dur}s (agent exit $agent_rc); grade with: python3 grade-test4.py $OUT"
