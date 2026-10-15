#!/usr/bin/env bash
# Test 7: the labyrinth (suites/test7/README.md). One agent run: write a seeded generator for a three-floor maze that
# meets every rule of TASK.md, a showcase labyrinth.json and NOTES.md, with verify.py to check against.
#
#   run-case-test7.sh <case> <model> <flags> [<run>]
#
# The agent gets a fresh copy of suites/test7/project (TASK.md, verify.py) as /work, and as its prompt
# suites/test7/prompt-preamble.txt followed by TASK.md. TASK.md stays in /work so a compaction cannot lose it. The
# agent is stopped after $T7_CAP_S seconds (default 10800 = 3 hours) by `timeout` inside the container. Same
# sandbox, model loading, context margins and network policy as run-case-test4.sh, without the Home Assistant
# replay; OpenCode only. Grade with grade-test7.py (untouched verify.py, unseen seeds, in a container with no network).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_results_env="${RESULTS:-}"
source "$HERE/lib.sh"
set +e                                   # lib.sh turns on -e; this runner checks each step itself
CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:--}"; RUN="${4:-}"
SUITE="$HERE/suites/test7"
[ -n "$RUN" ] || RUN=$(printf '%s' "$CASE" | grep -oP -- '-r\K[0-9]+$')
RUN="${RUN:-0}"
[ "$FLAGS" = "-" ] && FLAGS=""
RESULTS="${_results_env:-$HERE/results-test7}"
PREAMBLE="${PROMPT_PREAMBLE:-$SUITE/prompt-preamble.txt}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
LAN="${TITAN_LAN:-192.0.2.62}"
CAP="${T7_CAP_S:-10800}"

OUT="$RESULTS/$CASE"
if [ -f "$OUT/meta.json" ]; then
  arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"
fi
rm -rf "$OUT" 2>/dev/null || eb_rm "$OUT"; mkdir -p "$OUT/work" "$OUT/t7"
[ -s "$PREAMBLE" ] || { err "prompt preamble missing: $PREAMBLE"; exit 1; }
[ -s "$SUITE/project/TASK.md" ] && [ -s "$SUITE/project/verify.py" ] || { err "starting files missing: $SUITE/project"; exit 1; }

# a fresh work folder for every run
cp "$SUITE/project/TASK.md" "$SUITE/project/verify.py" "$OUT/work/"
cat "$PREAMBLE" "$SUITE/project/TASK.md" > "$OUT/prompt.txt"
printf '%s\n' "$RUN" "$CAP" > "$OUT/t7/case.txt"

echo "=== $CASE : $MODEL : $FLAGS : run $RUN, cap ${CAP}s  [test 7, sandboxed] ==="
# A matrix note may carry `spec={...}` (engines/ENTRY-SPEC.md): set_variant applies it to the entry's spec file.
SPEC_OVR=$( [ -n "${MATRIX:-}" ] && [ -f "$MATRIX" ] && python3 -I "$HERE/tools/entry_spec.py" --note-override \
  "$(awk -F'\t' -v c="$CASE" '$1==c {print $4; exit}' "$MATRIX")" </dev/null || true)
[ -n "$SPEC_OVR" ] && printf '%s\n' "$SPEC_OVR" > "$OUT/spec-override.json"
set_variant "$MODEL" "$FLAGS" "$SPEC_OVR" >/dev/null 2>&1 || {
  err "could not set variant"; echo "{\"case\":\"$CASE\",\"status\":\"variant_failed\"}" > "$OUT/meta.json"; exit 1; }
# context and reply limits from the entry's bakeoff.spec (engines/ENTRY-SPEC.md), checked before the model loads.
# There is no fallback map: an entry without a usable spec is a setup error, not a guess at its context.
LIM=$(python3 -I "$HERE/tools/entry_spec.py" --titan --limits "$MODEL" 2>>"$OUT/spec-warnings.log" </dev/null) || LIM=""
read -r _ OUT_LIMIT CTX_LIMIT _ <<<"$LIM"
if ! [[ "${OUT_LIMIT:-}" =~ ^[0-9]+$ && "${CTX_LIMIT:-}" =~ ^[0-9]+$ ]]; then
  err "$CASE: $MODEL has no usable bakeoff.spec (see $OUT/spec-warnings.log)"
  echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"spec_missing\"}" > "$OUT/meta.json"; exit 1
fi
python3 -I "$HERE/tools/entry_spec.py" --titan --entry "$MODEL" > "$OUT/entry-spec.json" 2>>"$OUT/spec-warnings.log" </dev/null || true
log "limits from bakeoff.spec: OpenCode context $CTX_LIMIT, reply $OUT_LIMIT"
load_s=$(warm "$MODEL" || echo "-1")
[ "$load_s" = "-1" ] && {
  err "$CASE: model failed to load with [$FLAGS]"
  echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"load_failed\"}" > "$OUT/meta.json"; exit 1; }
v=$(vram); ok "loaded in ${load_s}s, VRAM ${v} MiB"


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
# 9 min: OpenCode gives up on a tool call only at this timeout, and a call whose shell died (tiel pilot
# 2026-10-15) stalls until then; hang_watchdog.py stops a case after 600 s with no events and no processes,
# so this stays below that. A build or search that runs longer can ask for a longer timeout.
export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=540000
# CARGO_HOME under /root: the agent runs as container root without capabilities, which cannot write
# /home/agent (owned by uid 1000). Rustup's toolchain stays in /opt (RUSTUP_HOME, /opt/cargo/bin).
export CARGO_HOME=/root/.cargo PATH="/root/.cargo/bin:/opt/cargo/bin:\$PATH"
export HOME=/root
cd /work
date +%s.%N > /t7/agent-start
timeout -k 30 $CAP opencode run --auto --pure --format json --log-level INFO --model "titan/$MODEL" --dir /work "\$(cat /prompt.txt)"
rc=\$?
date +%s.%N > /t7/agent-end
echo \$rc > /t7/agent-rc
exit \$rc
AGENTEOF

# podman runs as evalbox (tools/podman-eb): hand it every mounted path; shared inputs as mirrors
eb_take "$OUT/work" "$OUT/agent-cmd.sh" "$OUT/prompt.txt" "$OUT/oc" "$OUT/oc-data" "$OUT/t7" \
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
  -v "$OUT/t7":/t7:Z \
  -v "$OUT/agent-cmd.sh":/agent-cmd.sh:ro,Z \
  -v "$OUT/prompt.txt":/prompt.txt:ro,Z \
  -v "$OUT/oc/opencode.json":/root/.config/opencode/opencode.json:ro,Z \
  -v "$OUT/oc-data":/root/.local/share/opencode:Z \
  "$IMAGE" /net-policy.sh bash /agent-cmd.sh \
  > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
t1=$(date +%s.%N)
# agent-start, agent-end and agent-rc are in /t7, which the agent can write: read them as untrusted numbers and fall
# back to the host's own measures (container wall time, container exit code) when missing or out of range
dur=$(python3 -I - "$OUT" "$RUN" "$CAP" "$rc" "$t0" "$t1" <<'PY'
import json, os, re, sys
out, run, cap, crc, t0, t1 = sys.argv[1:7]
wall = float(t1) - float(t0)


def small(name, pat):
    try:
        fd = os.open(os.path.join(out, "t7", name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            s = fh.read(64).decode("ascii", "replace").strip()
    except OSError:
        return None
    return s if re.fullmatch(pat, s) else None


num = r"[0-9]{1,12}(\.[0-9]{1,12})?"
a, b = small("agent-start", num), small("agent-end", num)
dur = float(b) - float(a) if a and b else None
if dur is None or not wall - 300 <= dur <= wall + 5:   # the stamps must agree with the host's own clock
    dur = wall
r = small("agent-rc", r"[0-9]{1,3}")
crc = int(crc)   # agent-cmd.sh exits with the agent's code, so the container's code is the one to trust
h = dict(test=7, run=int(run), cap_s=int(cap), agent_rc=crc, agent_rc_file=int(r) if r is not None else None,
         container_wall_s=round(wall, 1), timed_out=crc in (124, 137) or dur >= int(cap))
with open(os.path.join(out, "t7-host.json"), "w") as fh:
    json.dump(h, fh)
print(f"{dur:.1f}")
PY
) || dur=0
agent_rc=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["agent_rc"])' "$OUT/t7-host.json" 2>/dev/null || echo "$rc")
[ "$rc" -ne 0 ] && err "agent exited $rc (see stderr.log)"

ev_bytes=$(wc -c < "$OUT/events.jsonl" 2>/dev/null || echo 0)
if [ "$ev_bytes" -lt 5000 ]; then
  err "agent produced only ${ev_bytes} bytes of events -- treating as HARNESS failure, not a model result"
  python3 -c "
import json; json.dump({'case':'$CASE','model':'$MODEL','flags':'$FLAGS','status':'harness_failure',
 'reason':'events.jsonl only ${ev_bytes} bytes','test':7,'run':int('$RUN'),'sandboxed':True},
 open('$OUT/meta.json','w'), indent=2)"
  exit 1
fi
python3 "$HERE/distil-meta.py" "$OUT" "$CASE" "$MODEL" "$FLAGS" "$load_s" "$v" "$dur" "" 2>/dev/null \
  || echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"ok\",\"duration_s\":$dur,\"sandboxed\":true}" > "$OUT/meta.json"
python3 -I - "$OUT" <<'PY'
import json, os, sys
p = os.path.join(sys.argv[1], "meta.json")
m = json.load(open(p))
m.update(json.load(open(os.path.join(sys.argv[1], "t7-host.json"))))
with open(p + ".tmp", "w") as fh:
    json.dump(m, fh, indent=2)
os.replace(p + ".tmp", p)
PY
echo "  test 7 case done in ${dur}s (agent exit $agent_rc); grade with: python3 grade-test7.py $OUT"
