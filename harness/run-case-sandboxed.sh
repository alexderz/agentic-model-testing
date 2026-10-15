#!/usr/bin/env bash
# Run one case with the AGENT inside a container.
#
# The original run-case.sh ran the agent on the host as the user. A clean work
# tree controlled where it started, not what it could reach. Over 41 cases the
# agents installed 199 crates into ~/.cargo and 45 packages into ~/.local, and
# two of them discovered other models' projects through shared site-packages
# because `pip install -e` writes a .pth every later run can see.
#
# Here the agent gets:
#   * only its own work dir from the host, nothing else
#   * its own throwaway CARGO_HOME / pip target, discarded with the container
#   * a non-root user, no sudo, all capabilities dropped
#   * network to the inference endpoint, the data endpoint, and the package
#     registries -- deliberately NOT a frozen cache, because a frozen cache
#     means every future cohort is tested against staler libraries
#
# Nothing it installs can reach the host, and no two cases can see each other.
#
# run-case-sandboxed.sh <case> <model> <flags>
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# lib.sh sets RESULTS itself, so a plain ${RESULTS:-default} below would never
# fire and a bare invocation would silently write into the test-1 cohort dir.
# Capture the caller's value BEFORE sourcing, then decide.
_results_env="${RESULTS:-}"
source "$HERE/lib.sh"
# lib.sh turns on -e. This runner checks each step itself: with -e, the stop-reason grep below
# (no match for OpenCode, which logs no rawStopReason) ended the script before meta.json and
# ha-requests.jsonl, so every OpenCode case got a reconstructed meta with load time and duration 0.
set +e

CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:-}"
RESULTS="${_results_env:-$HERE/results-r3}"
PROMPT_FILE="${PROMPT_FILE:-$HERE/suites/prompt-rust-mcp.txt}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
AGENT="${AGENT:-pi}"                       # pi | opencode
LAN="${TITAN_LAN:-192.0.2.62}"

OUT="$RESULTS/$CASE"
if [ -f "$OUT/meta.json" ]; then
  arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"
fi
rm -rf "$OUT" 2>/dev/null || eb_rm "$OUT"; mkdir -p "$OUT/work"
[ -s "$PROMPT_FILE" ] || { err "prompt missing: $PROMPT_FILE"; exit 1; }
PROMPT="$(cat "$PROMPT_FILE")"

echo "=== $CASE : $MODEL : $FLAGS  [sandboxed] ==="

# A matrix note may carry `spec={...}` (engines/ENTRY-SPEC.md): set_variant applies it to the entry's spec file.
SPEC_OVR=$( [ -n "${MATRIX:-}" ] && [ -f "$MATRIX" ] && python3 -I "$HERE/tools/entry_spec.py" --note-override \
  "$(awk -F'\t' -v c="$CASE" '$1==c {print $4; exit}' "$MATRIX")" </dev/null || true)
[ -n "$SPEC_OVR" ] && printf '%s\n' "$SPEC_OVR" > "$OUT/spec-override.json"
set_variant "$MODEL" "$FLAGS" "$SPEC_OVR" >/dev/null 2>&1 || {
  err "could not set variant"
  echo "{\"case\":\"$CASE\",\"status\":\"variant_failed\"}" > "$OUT/meta.json"; exit 1; }
load_s=$(warm "$MODEL" || echo "-1")
[ "$load_s" = "-1" ] && {
  err "$CASE: model failed to load with [$FLAGS]"
  echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"load_failed\"}" > "$OUT/meta.json"
  exit 1; }
v=$(vram); ok "loaded in ${load_s}s, VRAM ${v} MiB"

# Inside a container 127.0.0.1 is the CONTAINER, so any host-loopback service is
# unreachable. That is mostly what we want -- the agent cannot touch host-local
# services -- but the data endpoint has to be reachable, so it is addressed via
# host.containers.internal and the replay server binds beyond loopback.
HA_URL="${HA_URL:-http://host.containers.internal:8126}"
HA_TOKEN="${HA_TOKEN:-bakeoff-placeholder-token}"
INFER="http://${LAN}:8080/v1"

PROXY_LOG="${PROXY_LOG:-/srv/bakeoff/replay-logs/ha-replay-access.log}"
proxy_start=$(wc -l < "$PROXY_LOG" 2>/dev/null || echo 0)

# ---- opencode config -------------------------------------------------------
# Written only when AGENT=opencode. Every choice below is deliberate:
#
#  share: disabled      a shared session uploads the transcript. Never, for an
#                       eval that reads a real home.
#  autoupdate: false    a version bump mid-cohort makes the halves incomparable.
#  instructions/skills/plugin empty + --pure
#                       the Pi equivalents of -nc -ns -np -ne. No ambient
#                       AGENTS.md, no skills, no external plugins.
#  enabled_providers    ONLY titan. Even with stray credentials it cannot reach
#                       a hosted model and silently stop testing the local one.
#  small_model          the same model. Left unset it picks another provider for
#                       title generation, which either fails or forces a swap.
#  snapshot: false      snapshot tracking writes files into the work tree, which
#                       the metrics then count as model output.
#  subagent_depth: 1    subagents ALLOWED. Note this makes opencode strictly
#                       more capable than Pi, which has no subagent tool at
#                       all -- so a difference in outcome is a difference
#                       between AGENTS as shipped, not between models.
#  question: false      there is no human to answer; the tool can only stall.
#  everything else true MAX TOOLING, including websearch and webfetch.
mkdir -p "$OUT/oc"
# Context window, so OpenCode can compact before it hits the wall. Without a
# limit it never compacts and asks for 32k output tokens on top of a full
# prompt: vLLM rejects prompt+max_tokens > max_model_len with a 400
# (ContextOverflowError) and the session ends -- wb-qwen3.8-27b-vllm-240k died
# mid-fix that way at 214k. From -c in FLAGS, or the container entry's known
# max_model_len.
# Limits come from the entry's bakeoff.spec (engines/ENTRY-SPEC.md; MODEL-CHECKLIST.md "served context"), read by
# tools/entry_spec.py, the only reader. The case keeps the spec it ran with. FALLBACK ONLY, until every entry carries
# a spec: the old hand-kept map below, with a loud warning. Delete it once `entry_spec.py --titan --check` is clean.
if LIM=$(python3 -I "$HERE/tools/entry_spec.py" --titan --limits "$MODEL" 2>>"$OUT/spec-warnings.log" </dev/null); then
  read -r CTX_RAW OUT_LIMIT CTX_LIMIT _ <<<"$LIM"
  python3 -I "$HERE/tools/entry_spec.py" --titan --entry "$MODEL" > "$OUT/entry-spec.json" 2>>"$OUT/spec-warnings.log" </dev/null || true
  log "limits from bakeoff.spec: served $CTX_RAW, OpenCode context $CTX_LIMIT, reply $OUT_LIMIT"
else
echo "!! WARNING: $MODEL has no usable bakeoff.spec; using the old hand-kept limits ($OUT/spec-warnings.log)" >&2
CTX_LIMIT=$(printf '%s' "$FLAGS" | sed -En 's/.*-c ([0-9]+).*/\1/p')
case "$MODEL" in
  qwen3.8-27b-vllm)      CTX_LIMIT=150000 ;;
  qwen3.8-27b-vllm-240k) CTX_LIMIT=245760 ;;
  qwen3.8-27b-uncensored-vllm) CTX_LIMIT=150000 ;;
  gemma-4-26b-a4b-vllm)  CTX_LIMIT=73728 ;;   # the entry serves --max-model-len 73728 (262144 overflowed: 41.7k prompt + 32k reply, 2026-10-09)
  flashnext)             CTX_LIMIT=204800 ;;
  qwen3.8-27b-vllm-64k)  CTX_LIMIT=65536 ;;
  qwen3.8-27b-vllm-quote) CTX_LIMIT=57344 ;;
  strata-*)              CTX_LIMIT=262144 ;;
esac
CTX_LIMIT=${CTX_LIMIT:-131072}
# Margin: OpenCode decides to compact from the PREVIOUS turn's usage, so one
# large tool result can carry the next prompt past the limit. The vLLM 240k
# case died twice at exactly 213,761 + 32,000 > 245,760. Tell OpenCode 10% less.
# 10% was not enough on small windows: wb-qwen3.8-27b-vllm-64k overflowed at
# 50,792 + 14,745 > 65,536 after one large tool result (spec docs). Keep at least
# 16k of slack whatever the window.
CTX_RAW=$CTX_LIMIT
M10=$(( CTX_LIMIT / 10 )); MARGIN=$(( M10 > 16384 ? M10 : 16384 ))
CTX_LIMIT=$(( CTX_LIMIT - MARGIN ))
OUT_LIMIT=$(( CTX_LIMIT / 4 < 32000 ? CTX_LIMIT / 4 : 32000 ))
fi   # end of the fallback
# Per-case request options, passed by OpenCode in every request body (verified
# with a capture stub). A case id ending in -pp gets Qwen's anti-repetition
# remedy: two runs ended in a 32k-token thinking loop on 2026-10-03.
# Thinking budget (operator, 2026-10-04): 24k of thinking inside the 32k reply
# cap, so a long or stuck think is closed with room left to answer instead of
# burning the whole cap. vLLM takes it per request (needs --reasoning-config
# on the server); llama.cpp gets --reasoning-budget in the case flags instead
# (tools/tune_and_run.py), so only vLLM models carry it in the body.
OPTS=""
TB=$(( OUT_LIMIT - 6000 < 24000 ? OUT_LIMIT - 6000 : 24000 ))   # budget inside the reply cap
PI_THINK=""
case "$MODEL" in *-vllm|*-vllm-*) OPTS="\"thinking_token_budget\": $TB"; PI_THINK=" --thinking high" ;; esac
case "$CASE" in *-pp) OPTS="${OPTS:+$OPTS, }\"presence_penalty\": 1.5" ;; esac
MODEL_OPTS=""; [ -n "$OPTS" ] && MODEL_OPTS=", \"options\": {$OPTS}"  # one step has used 24k reasoning tokens
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

cat > "$OUT/agent-cmd.sh" <<AGENTEOF
set -e
# 30 min per bash call: cargo builds on a box whose CPU is also running 42
# layers of MoE experts are slow, and a killed build is indistinguishable from
# code that does not compile.
export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=1800000
# CARGO_HOME under /root (2026-10-07): the agent runs as container root without capabilities, which
# cannot write /home/agent (uid 1000); agents had to find their own (e.g. /opt/cargo, /tmp).
export CARGO_HOME=/root/.cargo
export PYTHONUSERBASE=/root/.pylocal
export PATH="\$CARGO_HOME/bin:/root/.pylocal/bin:\$PATH"
export HA_URL='$HA_URL' HA_BASE_URL='$HA_URL' HA_TOKEN='$HA_TOKEN'
cd /work
if [ "$AGENT" = "opencode" ]; then
  export HOME=/root
  # --pure: no external plugins. --auto: headless, nothing can approve a prompt.
  # NOT --share. --dir pins the working directory.
  exec opencode run --auto --pure --format json --log-level INFO \
    --model "titan/$MODEL" --dir /work "\$(cat /prompt.txt)"
else
  exec pi --model "titan/$MODEL"$PI_THINK --mode json -nc -ns -np -ne \
    --session-dir /home/agent/session -p "\$(cat /prompt.txt)"
fi
AGENTEOF

printf '%s' "$PROMPT" > "$OUT/prompt.txt"
# The agent session log lives OUTSIDE /work. It used to sit at /work/.session,
# inside the very directory the prompt tells the agent to organise -- and an
# agent duly ran
#     mkdir -p /work/src/... && rm -rf /work/.session
# while tidying its workspace, deleting the harness state out from under Pi,
# which died with ENOENT mid-run. That reads as a model failure and is not one.
# Nothing the agent is invited to reorganise may hold harness state.
#
# Mount the whole agent dir, not just models.json. Bind-mounting a single file
# makes podman create its parent dirs root-owned, and the agent then cannot
# write its credential store next to it (EACCES on auth.json).
mkdir -p "$OUT/pi-agent" "$OUT/session" "$OUT/oc-data"
# Pi sends no thinking budget unless told to. Both Pi runs on 2026-10-05 spent
# the whole reply cap on one think and Pi ended the run on "length". For vLLM
# models: mark the model as reasoning, let Pi send thinking_token_budget, run
# at --thinking high (agent-cmd.sh), and set "high" to the same budget
# OpenCode gets. Pi itself keeps 1024 tokens of the cap for the answer.
PI_REASON=""
case "$MODEL" in *-vllm|*-vllm-*)
  PI_REASON=',"reasoning":true,"compat":{"supportsThinkingTokenBudget":true}'
  printf '{"thinkingBudgets":{"high":%s}}\n' "$TB" > "$OUT/pi-agent/settings.json" ;;
esac
# Pi gets the same margined window as OpenCode (CTX_LIMIT, not CTX_RAW): Pi estimates its own
# prompt size, and on 2026-10-06 the estimate was low by enough that 53,249 + 12,288 > 65,536
# and vLLM refused the request (wa-qwen3.8-27b-vllm-64k-pi-tb).
# Since 2026-10-14 CTX_LIMIT no longer holds a reply for OpenCode, which reserves it itself (engines/ENTRY-SPEC.md).
# Pi reserves only 16,384 before it compacts, so its window gives the reply back: Pi then compacts where OpenCode does.
PI_WINDOW=$(( CTX_LIMIT - OUT_LIMIT + 16384 ))
cat > "$OUT/pi-agent/models.json" <<JSON
{"providers":{"titan":{"api":"openai-completions","baseUrl":"$INFER","apiKey":"not-needed",
 "sendSessionAffinityHeaders":true,"sessionAffinityFormat":"openrouter",
 "models":[{"id":"$MODEL","contextWindow":$PI_WINDOW,"maxTokens":$OUT_LIMIT$PI_REASON}]}}}
JSON

# Saturn: podman runs as evalbox, which can relabel (:Z) only files it owns. Hand every mounted
# per-case path to evalbox; shared read-only inputs come from evalbox-owned mirrors (:ro,z).
eb_take "$OUT/work" "$OUT/agent-cmd.sh" "$OUT/prompt.txt" "$OUT/pi-agent" "$OUT/session" "$OUT/oc" "$OUT/oc-data" \
  || { err "could not hand the case files to evalbox"; exit 1; }
NETPOL=$(eb_input "$HERE/net-policy.sh") || { err "could not stage net-policy.sh"; exit 1; }
MCPD=""; [ -n "${MCP_DOCS:-}" ] && { MCPD=$(eb_input "$MCP_DOCS") || exit 1; }
OFFD=""; [ -n "${OFFLINE_DOCS:-}" ] && { OFFD=$(eb_input "$OFFLINE_DOCS") || exit 1; }

t0=$(date +%s.%N)
# --userns=keep-id maps the host uid to the same uid inside the container, so
# the agent user can write to the mounted work dir and the files it produces
# are owned by the invoking user, not an unreadable subuid. Without it the
# agent gets EACCES on its own working directory.
# If this script is killed (case timeout), the container must die with it;
# otherwise it keeps a model resident and the next case contends for VRAM.
trap 'podman rm -f "bakeoff-$CASE" >/dev/null 2>&1 || true' EXIT INT TERM

# --user root + NET_ADMIN, NOT --userns=keep-id. Rootless podman maps
# container-root to the invoking host user, so files still land owned by that
# user and no host privilege is gained -- but it is the only way to hold
# CAP_NET_ADMIN over the container's OWN netns, which net-policy.sh needs to
# install the egress firewall. net-policy.sh drops the capability with setpriv
# before the agent starts, so the model runs with CapEff 0 and cannot edit the
# policy (verified: `nft flush ruleset` returns Operation not permitted).
# NOTE: no comments inside the podman invocation below. A '#' line in a
# backslash-continued command comments out everything after it, so the
# image argument vanished and podman failed with "requires at least 1
# arg(s)" -- which reads like an opencode error and is not one.
# --user root + NET_ADMIN + SETPCAP: net-policy.sh installs the egress
# firewall, then setpriv clears every capability before the agent starts.
podman run --rm --name "bakeoff-$CASE" \
  --user root \
  --add-host=host.containers.internal:host-gateway \
  --memory=8g --pids-limit=1024 \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=SETPCAP \
  --security-opt=no-new-privileges \
  -e TITAN_IP="$LAN" \
  -v "$NETPOL":/net-policy.sh:ro,z \
  -v "$OUT/work":/work:Z \
  -v "$OUT/agent-cmd.sh":/agent-cmd.sh:ro,Z \
  -v "$OUT/prompt.txt":/prompt.txt:ro,Z \
  -v "$OUT/pi-agent":/home/agent/.pi/agent:Z \
  -v "$OUT/session":/home/agent/session:Z \
  -v "$OUT/oc/opencode.json":/root/.config/opencode/opencode.json:ro,Z \
  -v "$OUT/oc-data":/root/.local/share/opencode:Z \
  ${MCPD:+-v "$MCPD":/work/mcp-docs:ro,z} \
  ${OFFD:+-v "$OFFD":/work/docs:ro,z} \
  "$IMAGE" /net-policy.sh bash /agent-cmd.sh \
  > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
t1=$(date +%s.%N)
dur=$(python3 -c "print(f'{float('$t1')-float('$t0'):.1f}')")
[ "$rc" -ne 0 ] && err "agent exited $rc (see stderr.log)"

# A run that produced almost no events did not happen -- the agent died early.
# Recording that as a model result is how a harness bug becomes a capability
# claim, so make it an explicit harness failure.
ev_bytes=$(wc -c < "$OUT/events.jsonl" 2>/dev/null || echo 0)
if [ "$ev_bytes" -lt 5000 ]; then
  err "agent produced only ${ev_bytes} bytes of events -- treating as HARNESS failure, not a model result"
  head -3 "$OUT/stderr.log" 2>/dev/null | sed 's/^/    /'
  python3 -c "
import json; json.dump({'case':'$CASE','model':'$MODEL','flags':'$FLAGS',
 'status':'harness_failure','reason':'events.jsonl only ${ev_bytes} bytes',
 'sandboxed':True}, open('$OUT/meta.json','w'), indent=2)"
  exit 1
fi

# Surface why generation stopped. "length" means the model was cut off by the
# output cap -- a SETTING problem, not a capability one, and invisible in
# meta.json until now.
stop=$(grep -o '"rawStopReason":"[^"]*"' "$OUT/events.jsonl" 2>/dev/null | tail -1 | cut -d'"' -f4)
[ -n "$stop" ] && echo "  last stop reason: $stop"

tail -n +$((proxy_start + 1)) "$PROXY_LOG" 2>/dev/null > "$OUT/ha-requests.jsonl" || true

# SCORER=skip leaves meta.json to the caller (the screening wave grades by
# executing the model's code in a container, which distil-meta does not do).
if [ "${SCORER:-}" = "skip" ]; then
  echo "  scoring deferred to caller (SCORER=skip)"
  exit 0
fi
python3 "$HERE/distil-meta.py" "$OUT" "$CASE" "$MODEL" "$FLAGS" "$load_s" "$v" "$dur" "${stop:-}" 2>/dev/null \
  || echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"ok\",\"duration_s\":$dur,\"sandboxed\":true}" > "$OUT/meta.json"
