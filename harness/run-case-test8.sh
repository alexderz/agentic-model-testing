#!/usr/bin/env bash
# Test 8: the pagoda (test 6) and the orrery (test 5) as agent tasks (suites/test8/README.md). One OpenCode run with
# sub-agents on and a locked-down browser; the file it leaves is rendered and graded like the one-shot.
#
#   run-case-test8.sh <case> <model> <flags> [<run>]        case t8-pagoda-* or t8-orrery-*
#
# Two containers per case:
#  * the agent: localhost/bakeoff-agent as in test 7, but with no public Internet (net-policy.sh, NET_PUBLIC=0: only
#    llama-swap on Titan) and with webfetch and websearch off. /work starts empty.
#  * the browser: localhost/bakeoff-browser (Playwright MCP on the grader's Chromium) with --network=none, a read-only
#    root, no capabilities, its settings mounted read-only, and the agent's /work mounted read-only for the preview
#    server on 127.0.0.1:8000 (sandbox/t8/preview.py). The agent reaches it only through the MCP socket in /sock.
#    Playwright's browser_run_code_unsafe (Node code in the browser container) and browser_file_upload are off.
# Screenshots come back as images only when the served model takes images: checked at the start of every case
# (t8_tools.py vision, rule vision_verdict; T8_VISION=0|1 overrides) and stated in the prompt. An unclear probe is
# tried once more; unclear twice stops the case as a harness failure before the agent starts.
# The agent is stopped after $T8_CAP_S seconds (default 7200). Then the file is rendered with tools/render_html.sh or
# tools/render_svg.sh into frames/, and t8-stats.json counts the tool, browser and sub-agent calls.
# T8_OFFLINE_TEST=1 (tests/test_test8.sh only): no Titan; a scripted fake model ($T8_FAKE_DIR/fake_llm.py) runs
# inside the agent container and the limits are fixed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_results_env="${RESULTS:-}"
source "$HERE/lib.sh"
set +e                                   # lib.sh turns on -e; this runner checks each step itself
CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:--}"; RUN="${4:-}"
[ -n "$RUN" ] || RUN=$(printf '%s' "$CASE" | grep -oP -- '-r\K[0-9]+$')
RUN="${RUN:-0}"
[ "$FLAGS" = "-" ] && FLAGS=""
case "$CASE" in
  t8-pagoda-*) TASK=pagoda; ART=page.html ;;
  t8-orrery-*) TASK=orrery; ART=orrery.svg ;;
  *) err "$CASE: a test 8 case name starts t8-pagoda- or t8-orrery-"; exit 1 ;;
esac
RESULTS="${_results_env:-$HERE/results-test8}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
BIMAGE="${BROWSER_IMAGE:-localhost/bakeoff-browser}"
LAN="${TITAN_LAN:-192.0.2.62}"
CAP="${T8_CAP_S:-7200}"
OFFLINE="${T8_OFFLINE_TEST:-0}"
THREE_DIR=${THREE_DIR:-/srv/bakeoff/vendor/three-0.186.1/package}

OUT="$RESULTS/$CASE"
if [ -f "$OUT/meta.json" ]; then
  arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"
fi
rm -rf "$OUT" 2>/dev/null || eb_rm "$OUT"; mkdir -p "$OUT/work" "$OUT/t8" "$OUT/sock"
printf '%s\n' "$RUN" "$CAP" "$TASK" > "$OUT/t8/case.txt"

echo "=== $CASE : $MODEL : $FLAGS : $TASK, run $RUN, cap ${CAP}s  [test 8, sandboxed, browser] ==="
if [ "$OFFLINE" = 1 ]; then
  OUT_LIMIT=8000; CTX_LIMIT=100000; load_s=0; v=0; BASE="http://127.0.0.1:9999/v1"
  PROBE_BASE="${T8_PROBE_BASE:-$BASE}"   # tests/test_test8.sh: a mock on the host answers the image probe
else
  BASE="http://$LAN:8080/v1"; PROBE_BASE=$BASE
  # A matrix note may carry `spec={...}` (engines/ENTRY-SPEC.md): set_variant applies it to the entry's spec file.
  SPEC_OVR=$( [ -n "${MATRIX:-}" ] && [ -f "$MATRIX" ] && python3 -I "$HERE/tools/entry_spec.py" --note-override \
    "$(awk -F'\t' -v c="$CASE" '$1==c {print $4; exit}' "$MATRIX")" </dev/null || true)
  [ -n "$SPEC_OVR" ] && printf '%s\n' "$SPEC_OVR" > "$OUT/spec-override.json"
  set_variant "$MODEL" "$FLAGS" "$SPEC_OVR" >/dev/null 2>&1 || {
    err "could not set variant"; echo "{\"case\":\"$CASE\",\"status\":\"variant_failed\"}" > "$OUT/meta.json"; exit 1; }
  # context and reply limits from the entry's bakeoff.spec (engines/ENTRY-SPEC.md); no fallback map
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
fi

# Does the served model take images? Decides whether screenshots come back as images, and what the prompt says.
if [ -n "${T8_VISION:-}" ]; then
  VISION=$T8_VISION; printf '{"vision": %s, "override": true}\n' "$VISION" > "$OUT/t8-vision.json"
else
  # t8_tools.py vision_verdict (swap probe, 2026-10-15): prints 1 or 0, or exits 3 when unclear (no HTTP answer, a
  # 408/429/5xx not about images, no colour, ...). A hung probe is not unloaded before the retry: the retry then also
  # times out and the case stops as a harness failure, which is safe (Grok vis review 4, should-fix 4, accepted). Unclear is never coerced to 0: one retry, then the case stops
  # before the agent starts, as a harness failure, which tools/tune_and_run.py leaves runnable.
  VISION=
  for try in 1 2; do
    VISION=$(python3 -I "$HERE/tools/t8_tools.py" vision "$PROBE_BASE" "$MODEL" "$OUT/t8-vision.json" </dev/null); vrc=$?
    [ "$vrc" = 0 ] && [[ "$VISION" =~ ^[01]$ ]] && break
    cp -f "$OUT/t8-vision.json" "$OUT/t8-vision-try$try.json" 2>/dev/null
    err "$CASE: the image probe was unclear (try $try, exit $vrc; see t8-vision-try$try.json)"
    VISION=
    [ "$try" = 1 ] && [ "$OFFLINE" != 1 ] && sleep 10
  done
  if [ -z "$VISION" ]; then
    err "$CASE: the image probe was unclear twice -- HARNESS failure, not a model result; the agent did not start"
    python3 -I -c 'import json, sys; json.dump(dict(case=sys.argv[1], model=sys.argv[2], flags=sys.argv[3], status="harness_failure", reason="vision probe unclear twice (no HTTP answer, a non-image server error, or no clear left-half colour; see t8-vision-try1.json and t8-vision-try2.json)", test=8, run=int(sys.argv[4]), sandboxed=True), open(sys.argv[5], "w"), indent=2)' \
      "$CASE" "$MODEL" "$FLAGS" "$RUN" "$OUT/meta.json"
    exit 1
  fi
fi
[ "$VISION" = 1 ] && IMGRESP=allow || IMGRESP=omit
log "vision: $VISION (browser image responses: $IMGRESP)"
python3 -I "$HERE/tools/t8_tools.py" prompt "$TASK" "$CAP" "$VISION" "$OUT/prompt.txt" </dev/null \
  || { err "prompt assembly failed"; exit 1; }

TB=$(( OUT_LIMIT - 6000 < 24000 ? OUT_LIMIT - 6000 : 24000 ))
OPTS=""
case "$MODEL" in *-vllm|*-vllm-*) OPTS="\"thinking_token_budget\": $TB" ;; esac
case "$CASE" in *-pp|*-pp-r[0-9]*) OPTS="${OPTS:+$OPTS, }\"presence_penalty\": 1.5" ;; esac
MODEL_OPTS=""; [ -n "$OPTS" ] && MODEL_OPTS=", \"options\": {$OPTS}"
[ "$VISION" = 1 ] && MODEL_OPTS="$MODEL_OPTS, \"attachment\": true, \"modalities\": {\"input\": [\"text\", \"image\"], \"output\": [\"text\"]}"

# The OpenCode config of run-case-test7.sh, plus the browser MCP server; web tools off (no Internet here); the two
# Playwright tools that reach past the page off.
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
    "options": {"baseURL": "$BASE",
                "requestTimeout": 5400000, "timeout": 5400000},
    "models": {"$MODEL": {"name": "$MODEL",
      "limit": {"context": $CTX_LIMIT, "output": $OUT_LIMIT}$MODEL_OPTS}}}},
  "mcp": {"browser": {"type": "local", "enabled": true, "timeout": 60000,
    "command": ["python3", "-I", "/opt/t8/mcp-bridge.py", "/sock/mcp.sock"]}},
  "tools": {
    "bash": true, "edit": true, "write": true, "read": true,
    "grep": true, "glob": true, "lsp": true, "apply_patch": true,
    "skill": true, "todowrite": true, "task": true,
    "webfetch": false, "websearch": false,
    "browser_browser_run_code_unsafe": false, "browser_browser_file_upload": false,
    "question": false
  },
  "permission": {"bash": "allow", "edit": "allow", "webfetch": "deny", "doom_loop": "deny"}
}
OCEOF
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$OUT/oc/opencode.json" \
  || { err "config generation failed"; exit 1; }

FAKE_LINE=""
[ "$OFFLINE" = 1 ] && FAKE_LINE="python3 /opt/t8fake/fake_llm.py 9999 /t8/llm.jsonl & sleep 1"
cat > "$OUT/agent-cmd.sh" <<AGENTEOF
# 5 min: OpenCode gives up on a tool call only at this timeout, and a call whose shell died (tiel pilot
# 2026-10-15: pkill -f matched the tool's own shell) stalls until then; hang_watchdog.py stops a case after
# 600 s with no events and no processes, so this stays below that. The agent can ask for a longer timeout.
export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=300000
export CARGO_HOME=/root/.cargo PATH="/root/.cargo/bin:/opt/cargo/bin:\$PATH"
export HOME=/root
cd /work
$FAKE_LINE
# the preview on the agent's own 127.0.0.1:8000 (tiel pilot 2026-10-15: an agent that cannot curl it starts a server
# of its own, and a pkill -f for that server killed OpenCode's tool shell, which hung the session)
python3 -I /opt/t8/preview-bridge.py /sock/preview.sock 8000 &
for i in \$(seq 1 50); do curl -s -o /dev/null -m 2 http://127.0.0.1:8000/ && break; sleep 0.2; done
# no preview means a blind agent: stop before OpenCode, so the case is a harness failure (events under 5000 bytes)
curl -s -o /dev/null -m 2 http://127.0.0.1:8000/ || { echo 'agent-cmd: the preview is not on 127.0.0.1:8000' >&2; exit 3; }
date +%s.%N > /t8/agent-start
timeout -k 30 $CAP opencode run --auto --pure --format json --log-level INFO --model "titan/$MODEL" --dir /work "\$(cat /prompt.txt)"
rc=\$?
date +%s.%N > /t8/agent-end
echo \$rc > /t8/agent-rc
exit \$rc
AGENTEOF

# the browser's files: sandbox/t8 and the shared three.js rewrite, staged in one folder and mirrored for evalbox
OPTSRC="$HERE/tmp/t8-opt"; rm -rf "$OPTSRC"; mkdir -p "$OPTSRC"
cp "$HERE"/sandbox/t8/*.py "$HERE"/sandbox/t8/*.sh "$HERE"/sandbox/t8/*.json "$HERE/tools/three_rewrite.py" "$HERE/tools/svg_fit.py" "$OPTSRC/" && chmod -R a+rX "$OPTSRC" || { err "staging sandbox/t8 failed"; exit 1; }
OPT=$(eb_input "$OPTSRC") || exit 1
THREE=$(eb_input "$THREE_DIR") || exit 1
NETPOL=$(eb_input "$HERE/net-policy.sh") || exit 1
FAKE_MOUNT=()
if [ "$OFFLINE" = 1 ]; then
  FAKE=$(eb_input "${T8_FAKE_DIR:?T8_FAKE_DIR}") || exit 1
  FAKE_MOUNT=(-v "$FAKE":/opt/t8fake:ro,z)
fi
# the prompt stays in /work as TASK.md: a compaction drops the first message (as in test 7)
cp "$OUT/prompt.txt" "$OUT/work/TASK.md"
# podman runs as evalbox: hand it every per-case path. /work and /sock are shared by the two containers (:z).
eb_take "$OUT/work" "$OUT/sock" "$OUT/agent-cmd.sh" "$OUT/prompt.txt" "$OUT/oc" "$OUT/oc-data" "$OUT/t8" \
  || { err "could not hand the case files to evalbox"; exit 1; }

BNAME="bakeoff-browser-$CASE"; ANAME="bakeoff-$CASE"
stop_all() {
  podman logs "$BNAME" > "$OUT/browser.log" 2>&1
  # space and memory at the end, so a browser-side failure leaves its cause (the pilot orrery's /fit did not)
  podman exec "$BNAME" timeout 15 sh -c 'echo "--- end of case: df /tmp /root; memory.events"; df -k /tmp /root;
    cat /sys/fs/cgroup/memory.events || echo "memory.events unreadable"' >> "$OUT/browser.log" 2>&1
  podman rm -f "$ANAME" "$BNAME" >/dev/null 2>&1 || true
}
trap stop_all EXIT
trap 'exit 143' INT TERM
# a browser that fails before the agent starts is the harness's fault, not the model's: say so in meta.json
hfail() {
  err "$1 -- HARNESS failure, not a model result"
  python3 -I -c 'import json, sys; json.dump(dict(case=sys.argv[1], model=sys.argv[2], flags=sys.argv[3], status="harness_failure", reason=sys.argv[4], test=8, run=int(sys.argv[5]), sandboxed=True), open(sys.argv[6], "w"), indent=2)' \
    "$CASE" "$MODEL" "$FLAGS" "$1" "$RUN" "$OUT/meta.json"
  exit 1
}
podman rm -f "$BNAME" >/dev/null 2>&1
podman run -d --name "$BNAME" \
  --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges \
  --tmpfs /tmp:rw,size=1g --tmpfs /root:rw,size=64m --memory=3g --pids-limit=512 \
  -e PLAYWRIGHT_MCP_IMAGE_RESPONSES="$IMGRESP" \
  -v "$OUT/work":/site:ro,z \
  -v "$THREE":/three:ro,z \
  -v "$OPT":/opt/t8:ro,z \
  -v "$OUT/sock":/sock:z \
  "$BIMAGE" bash /opt/t8/browser-entry.sh >/dev/null || hfail "the browser container did not start"
for i in $(seq 1 60); do podman unshare test -S "$OUT/sock/mcp.sock" && break; sleep 1; done
podman unshare test -S "$OUT/sock/mcp.sock" || hfail "the browser socket did not appear in 60 s (see browser.log)"
podman unshare test -S "$OUT/sock/preview.sock" || hfail "the preview socket did not appear (see browser.log)"

t0=$(date +%s.%N)
podman run --rm --name "$ANAME" \
  --user root \
  --add-host=host.containers.internal:host-gateway \
  --memory=8g --pids-limit=1024 \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=SETPCAP \
  --security-opt=no-new-privileges \
  -e TITAN_IP="$LAN" -e NET_PUBLIC=0 \
  -v "$NETPOL":/net-policy.sh:ro,z \
  -v "$OUT/work":/work:z \
  -v "$OUT/sock":/sock:z \
  -v "$OUT/t8":/t8:Z \
  -v "$OPT":/opt/t8:ro,z \
  "${FAKE_MOUNT[@]}" \
  -v "$OUT/agent-cmd.sh":/agent-cmd.sh:ro,Z \
  -v "$OUT/prompt.txt":/prompt.txt:ro,Z \
  -v "$OUT/oc/opencode.json":/root/.config/opencode/opencode.json:ro,Z \
  -v "$OUT/oc-data":/root/.local/share/opencode:Z \
  "$IMAGE" /net-policy.sh bash /agent-cmd.sh \
  > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
t1=$(date +%s.%N)
stop_all; trap - EXIT

# agent-start, agent-end and agent-rc are in /t8, which the agent can write: untrusted numbers, checked against the
# host's own clock and the container's exit code (as in run-case-test7.sh)
dur=$(python3 -I - "$OUT" "$RUN" "$CAP" "$rc" "$t0" "$t1" "$TASK" "$VISION" <<'PY'
import json, os, re, sys
out, run, cap, crc, t0, t1, task, vision = sys.argv[1:9]
wall = float(t1) - float(t0)


def small(name, pat):
    try:
        fd = os.open(os.path.join(out, "t8", name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            s = fh.read(64).decode("ascii", "replace").strip()
    except OSError:
        return None
    return s if re.fullmatch(pat, s) else None


num = r"[0-9]{1,12}(\.[0-9]{1,12})?"
a, b = small("agent-start", num), small("agent-end", num)
dur = float(b) - float(a) if a and b else None
if dur is None or not wall - 300 <= dur <= wall + 5:
    dur = wall
r = small("agent-rc", r"[0-9]{1,3}")
crc = int(crc)
h = dict(test=8, task=task, run=int(run), cap_s=int(cap), vision=int(vision), agent_rc=crc,
         agent_rc_file=int(r) if r is not None else None, container_wall_s=round(wall, 1),
         timed_out=crc in (124, 137) or dur >= int(cap))
with open(os.path.join(out, "t8-host.json"), "w") as fh:
    json.dump(h, fh)
print(f"{dur:.1f}")
PY
) || dur=0
[ "$rc" -ne 0 ] && err "agent exited $rc (see stderr.log)"

ev_bytes=$(wc -c < "$OUT/events.jsonl" 2>/dev/null || echo 0)
if [ "$ev_bytes" -lt 5000 ] && [ "$OFFLINE" != 1 ]; then
  err "agent produced only ${ev_bytes} bytes of events -- treating as HARNESS failure, not a model result"
  python3 -c "
import json; json.dump({'case':'$CASE','model':'$MODEL','flags':'$FLAGS','status':'harness_failure',
 'reason':'events.jsonl only ${ev_bytes} bytes','test':8,'run':int('$RUN'),'sandboxed':True},
 open('$OUT/meta.json','w'), indent=2)"
  exit 1
fi
python3 "$HERE/distil-meta.py" "$OUT" "$CASE" "$MODEL" "$FLAGS" "$load_s" "$v" "$dur" "" 2>/dev/null \
  || echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"ok\",\"duration_s\":$dur,\"sandboxed\":true}" > "$OUT/meta.json"
python3 -I "$HERE/tools/t8_tools.py" stats "$OUT" </dev/null || err "stats failed"

# the graded file, rendered like the one-shot (tests 5 and 6)
# /work is the agent's: copy the file without following a link (a symlink is not an answer), up to 32 MB
if python3 -I - "$OUT/work/$ART" "$OUT/$ART" <<'PY'
import os, stat, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
except OSError:
    sys.exit(1)
with os.fdopen(fd, "rb") as fh:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_size > 32 << 20:   # a bigger file is no answer, not a cut one
        sys.exit(1)
    data = fh.read(32 << 20)
with open(sys.argv[2], "wb") as fh:
    fh.write(data)
PY
then
  if [ "$TASK" = pagoda ]; then "$HERE/tools/render_html.sh" "$OUT/$ART" "$OUT/frames"
  else "$HERE/tools/render_svg.sh" "$OUT/$ART" "$OUT/frames"; fi
else
  err "$CASE: no /work/$ART at the end"
fi
python3 -I - "$OUT" "$ART" <<'PY'
import json, os, sys
out, art = sys.argv[1:3]
p = os.path.join(out, "meta.json")
m = json.load(open(p))
m.update(json.load(open(os.path.join(out, "t8-host.json"))))
m["artifact"] = art if os.path.isfile(os.path.join(out, art)) else None
m["artifact_bytes"] = os.path.getsize(os.path.join(out, art)) if m["artifact"] else 0
for f in ("t8-stats.json", "t8-vision.json"):
    try:
        m[f[:-5].replace("-", "_")] = json.load(open(os.path.join(out, f)))
    except (OSError, ValueError):
        pass
with open(p + ".tmp", "w") as fh:
    json.dump(m, fh, indent=2)
os.replace(p + ".tmp", p)
PY
echo "  test 8 case done in ${dur}s (agent exit $rc); frames in $OUT/frames; grade by hand (suites/test8/README.md)"
