#!/usr/bin/env bash
# Test 3: use an MCP server through a delegated subagent (suites/test3/DESIGN.md).
#
#   run-case-test3.sh <case> <model> <flags> [<mcp-source-case-dir>]
#
# <mcp-source-case-dir> is a graded test-2 case folder (live area or NAS archive). When it is not given
# (run-matrix.sh passes only case, model and flags), the case's row in $MATRIX (default
# matrix-test3.tsv) names it in its note as `mcp=<test-2 case>`, looked up in results-wave-b in the live
# area first, then the archive (evals.env). Its crate (the first
# Cargo.toml with a [package] section, outside target/) is copied without target/ and .git into the
# agent's /work/mcp-src. 3G passes the known-good server's case (suites/test3/KNOWN-GOOD.md), 3O the
# model's own test-2 case. Same sandbox, model loading, context margins and network policy as
# run-case-sandboxed.sh; OpenCode only (Pi has no subagents). Before the agent starts, the server is
# built once (log: t3/prebuild.log), so a server that builds is connected from the first call; one
# that does not build is handled by the shim (no tools until the agent builds it).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_results_env="${RESULTS:-}"
source "$HERE/lib.sh"
set +e                                   # lib.sh turns on -e; this runner checks each step itself
CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:--}"; SRC_CASE="${4:-}"
if [ -z "$SRC_CASE" ]; then
  source "$HERE/evals.env"
  M="${MATRIX:-$HERE/matrix-test3.tsv}"
  SRC=$(awk -F'\t' -v c="$CASE" '$1==c {print $4}' "$M" | grep -oP 'mcp=\K\S+' | head -1)
  [ -n "$SRC" ] || { err "no mcp=<case> for $CASE in $M"; exit 1; }
  for root in "$EVALS_REPO/results-wave-b" "$EVALS_ARCHIVE_RESULTS/results-wave-b"; do
    [ -d "$root/$SRC" ] && { SRC_CASE="$root/$SRC"; break; }
  done
  [ -n "$SRC_CASE" ] || { err "test-2 case $SRC not found in the live area or the archive"; exit 1; }
fi
[ "$FLAGS" = "-" ] && FLAGS=""
RESULTS="${_results_env:-$HERE/results-test3}"
PROMPT_FILE="${PROMPT_FILE:-$HERE/suites/prompt-test3.txt}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
LAN="${TITAN_LAN:-192.0.2.62}"

OUT="$RESULTS/$CASE"
if [ -f "$OUT/meta.json" ]; then
  arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"
fi
rm -rf "$OUT" 2>/dev/null || eb_rm "$OUT"; mkdir -p "$OUT/work" "$OUT/t3"
[ -s "$PROMPT_FILE" ] || { err "prompt missing: $PROMPT_FILE"; exit 1; }

# the server's source: the first real crate under the source case's work/
CRATE=$(python3 - "$SRC_CASE/work" <<'PY'
import os, sys
for root, dirs, files in os.walk(sys.argv[1]):
    dirs[:] = sorted(d for d in dirs if d not in ("target", ".git", "node_modules"))
    if "Cargo.toml" in files and "[package]" in open(os.path.join(root, "Cargo.toml"), errors="replace").read():
        print(root); break
PY
)
[ -n "$CRATE" ] || { err "no Rust crate in $SRC_CASE/work"; echo "{\"case\":\"$CASE\",\"status\":\"no_source\"}" > "$OUT/meta.json"; exit 1; }
mkdir -p "$OUT/work/mcp-src"
tar -C "$CRATE" --exclude=./target --exclude=./.git -cf - . | tar -C "$OUT/work/mcp-src" -xf -
printf '%s\n' "$SRC_CASE" "$CRATE" > "$OUT/t3/source.txt"

echo "=== $CASE : $MODEL : $FLAGS : mcp from $(basename "$SRC_CASE")  [test 3, sandboxed] ==="
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
  gemma-4-26b-a4b-vllm)  CTX_LIMIT=73728 ;;   # the entry serves --max-model-len 73728 (262144 overflowed: 41.7k prompt + 32k reply, 2026-10-09)
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
OPTS="{}"
case "$MODEL" in *-vllm|*-vllm-*) OPTS="{\"thinking_token_budget\": $TB}" ;; esac
case "$CASE" in *-pp) OPTS=$(python3 -c "import json,sys;d=json.loads(sys.argv[1]);d['presence_penalty']=1.5;print(json.dumps(d))" "$OPTS") ;; esac

mkdir -p "$OUT/oc" "$OUT/oc-data"
python3 "$HERE/tools/test3_config.py" --model "$MODEL" --base-url "http://$LAN:8080/v1" --context "$CTX_LIMIT" \
  --output "$OUT_LIMIT" --options "$OPTS" --ha-url "$HA_URL" --ha-token "$HA_TOKEN" --shim-log /t3/shim.jsonl \
  --out "$OUT/oc/opencode.json" || { err "config generation failed"; exit 1; }
cp "$PROMPT_FILE" "$OUT/prompt.txt"
# The task also lies in the work folder (operator 2026-10-10/11): a compaction drops the first message, and with it
# the asked shape of facts.json (Gemma and Coder390 lost credit that way). The prompt's last line points at this file.
cp "$PROMPT_FILE" "$OUT/work/TASK.md"
cat > "$OUT/agent-cmd.sh" <<AGENTEOF
set -e
export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=1800000
# CARGO_HOME under /root: the agent runs as container root without capabilities, which cannot write
# /home/agent (owned by uid 1000). Rustup's toolchain stays in /opt (RUSTUP_HOME, /opt/cargo/bin).
export CARGO_HOME=/root/.cargo PATH="/root/.cargo/bin:/opt/cargo/bin:\$PATH"
export HA_URL='$HA_URL' HA_BASE_URL='$HA_URL' HA_TOKEN='$HA_TOKEN'
export HOME=/root
( cd /work/mcp-src && cargo build --release ) > /t3/prebuild.log 2>&1 && echo "prebuild: ok" >> /t3/prebuild.log \
  || echo "prebuild: FAILED" >> /t3/prebuild.log
cd /work
exec opencode run --auto --pure --format json --log-level INFO --model "titan/$MODEL" --dir /work "\$(cat /prompt.txt)"
AGENTEOF

# podman runs as evalbox (tools/podman-eb): hand it every mounted path; shared inputs as mirrors
eb_take "$OUT/work" "$OUT/agent-cmd.sh" "$OUT/prompt.txt" "$OUT/oc" "$OUT/oc-data" "$OUT/t3" \
  || { err "could not hand the case files to evalbox"; exit 1; }
NETPOL=$(eb_input "$HERE/net-policy.sh") || exit 1
SHIMF=$(eb_input "$HERE/mcp-restart-shim.py") || exit 1

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
  -v "$SHIMF":/opt/t3/shim.py:ro,z \
  -v "$OUT/work":/work:Z \
  -v "$OUT/t3":/t3:Z \
  -v "$OUT/agent-cmd.sh":/agent-cmd.sh:ro,Z \
  -v "$OUT/prompt.txt":/prompt.txt:ro,Z \
  -v "$OUT/oc/opencode.json":/root/.config/opencode/opencode.json:ro,Z \
  -v "$OUT/oc-data":/root/.local/share/opencode:Z \
  "$IMAGE" /net-policy.sh bash /agent-cmd.sh \
  > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
t1=$(date +%s.%N)
dur=$(python3 -c "print(f'{float('$t1')-float('$t0'):.1f}')")
[ "$rc" -ne 0 ] && err "agent exited $rc (see stderr.log)"

ev_bytes=$(wc -c < "$OUT/events.jsonl" 2>/dev/null || echo 0)
if [ "$ev_bytes" -lt 5000 ]; then
  err "agent produced only ${ev_bytes} bytes of events -- treating as HARNESS failure, not a model result"
  python3 -c "
import json; json.dump({'case':'$CASE','model':'$MODEL','flags':'$FLAGS','status':'harness_failure',
 'reason':'events.jsonl only ${ev_bytes} bytes','test':3,'sandboxed':True}, open('$OUT/meta.json','w'), indent=2)"
  exit 1
fi
tail -n +$((proxy_start + 1)) "$PROXY_LOG" 2>/dev/null > "$OUT/ha-requests.jsonl" || true
python3 "$HERE/distil-meta.py" "$OUT" "$CASE" "$MODEL" "$FLAGS" "$load_s" "$v" "$dur" "" 2>/dev/null \
  || echo "{\"case\":\"$CASE\",\"model\":\"$MODEL\",\"flags\":\"$FLAGS\",\"status\":\"ok\",\"duration_s\":$dur,\"sandboxed\":true}" > "$OUT/meta.json"
python3 - "$OUT/meta.json" "$SRC_CASE" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); m.update(test=3, mcp_source_case=sys.argv[2]); json.dump(m, open(sys.argv[1], "w"), indent=2)
PY
echo "  test 3 case done in ${dur}s; grade with: python3 grade-test3.py $OUT"
