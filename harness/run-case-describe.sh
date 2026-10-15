#!/usr/bin/env bash
# Test 3: describe the installation using an MCP server, in a sandbox.
#
# Rewritten for Open Code rather than Pi. Pi has no native MCP -- the adapter
# never verified (the model hand-wrote a JSON-RPC client instead of using it),
# and we are moving to Open Code regardless. Open Code speaks MCP natively:
# verified by a sentinel a model could not have guessed.
#
# 3A: the model uses the MCP IT built.
# 3B: the model uses an MCP SOMEONE ELSE built (pass --mcp-from).
#
#   run-case-describe.sh <case> <model> <mcp-source-case> [flags]
#
# A model whose assigned MCP does not build has no score. That is recorded as
# build_failed, not treated as a harness error.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"
# lib.sh does `set -euo pipefail`, which clobbers ours. -e plus pipefail is
# lethal here: a grep that finds nothing is a RESULT (zero MCP calls), not an
# error, and -e killed the run just before scoring -- silently, and only on
# the cases worth recording. Failures are handled explicitly via fail().
set +e

CASE="${1:?case}"; MODEL="${2:?model}"; SRC="${3:?mcp source case}"; FLAGS="${4:-}"
RESULTS="${DESCRIBE_RESULTS:-$HERE/results-r4}"   # NOT $RESULTS: lib.sh sets it
SRC_RESULTS="${SRC_RESULTS:-$HERE/results-r3b}"
PROMPT_FILE="${PROMPT_FILE:-$HERE/suites/prompt-describe.txt}"
FIXTURE="${FIXTURE:-$HERE/fixtures/ha-fixture.json}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
LAN="${TITAN_LAN:-192.0.2.62}"
HA_URL="${HA_URL:-http://host.containers.internal:8126}"
HA_TOKEN="${HA_TOKEN:-bakeoff-placeholder-token}"

OUT="$RESULTS/$CASE"
[ -f "$OUT/meta.json" ] && { arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"; }
rm -rf "$OUT"; mkdir -p "$OUT/work"

fail() {  # record why there is no score, then stop
  echo "  $1"
  python3 -c "
import json; json.dump({'case':'$CASE','model':'$MODEL','mcp_from':'$SRC',
 'status':'$2','reason':'''$1''','sandboxed':True}, open('$OUT/meta.json','w'), indent=2)"
  exit 1
}

echo "=== $CASE : $MODEL : MCP from $SRC  [sandboxed, opencode] ==="

SRCWORK="$SRC_RESULTS/$SRC/work"
[ -d "$SRCWORK" ] || fail "no MCP source at $SRCWORK" "no_source"
cp -a "$SRCWORK/." "$OUT/work/" 2>/dev/null || fail "could not seed MCP source" "seed_failed"
rm -rf "$OUT/work/mcp-docs" "$OUT/work/.session"   # not part of the server
touch "$OUT/prompt-marker"

# Saturn: podman runs as evalbox and can relabel (:Z) only files it owns.
eb_take "$OUT/work" || fail "could not hand the work tree to evalbox" "seed_failed"

# 1. build the MCP inside the sandbox; no binary means no score
echo "  building the MCP server..."
# NOTE: bash -c, NOT -lc. A login shell re-reads /etc/profile and replaces the
# image's PATH, dropping /opt/cargo/bin -- cargo vanishes and every MCP looks
# like it does not build. Piping to tail then hid it by returning tail's 0.
podman run --rm --userns=keep-id:uid=1000,gid=1000 --memory=4g --pids-limit=512 \
  --cap-drop=ALL --security-opt=no-new-privileges \
  -v "$OUT/work":/work:Z "$IMAGE" \
  bash -c 'set -o pipefail; cd /work || exit 90
    command -v cargo >/dev/null || { echo "HARNESS: cargo not on PATH ($PATH)"; exit 91; }
    d=$(find . -name Cargo.toml -not -path "*/target/*" -printf "%h\n" | head -1)
    [ -n "$d" ] || { echo "HARNESS: no Cargo.toml in the seeded tree"; exit 92; }
    echo "manifest dir: $d"; cd "$d" || exit 90
    cargo build --release 2>&1 | tail -20' > "$OUT/cargo-build.log" 2>&1
build_rc=$?
# 90-92 are harness faults, not the model's code failing to compile.
case "$build_rc" in
  9[012]) sed 's/^/    /' "$OUT/cargo-build.log"
          fail "build step broken: $(tail -1 "$OUT/cargo-build.log")" "harness_failure" ;;
esac
# Only target/release/<name>, never deps/ or build/ -- those hold hash-suffixed
# test and build-script binaries. Running one of those as the MCP server looks
# like a server that answers nothing.
BIN=$(find "$OUT/work" -regex '.*/target/release/[^/]*' -type f -perm -111 \
        ! -name "*.*" ! -name "*-[0-9a-f][0-9a-f]*" 2>/dev/null | head -1)
[ "$build_rc" -eq 0 ] && [ -n "$BIN" ] || \
  fail "MCP from $SRC did not build, cargo rc=$build_rc (see cargo-build.log)" "build_failed"
REL_BIN="/work/${BIN#"$OUT/work/"}"
echo "  binary: $(basename "$BIN")"

# 2. Open Code config: titan provider + the MCP server under test.
#    Open Code launches the binary directly, so config comes from env.
mkdir -p "$OUT/oc"
cat > "$OUT/oc/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {"titan": {"npm": "@ai-sdk/openai-compatible",
    "options": {"baseURL": "http://${LAN}:8080/v1"},
    "models": {"$MODEL": {"name": "$MODEL"}}}},
  "mcp": {"ha": {"type": "local",
    "command": ["python3", "/mcp-version-shim.py", "$REL_BIN"], "enabled": true,
    "environment": {"HA_URL": "$HA_URL", "HA_BASE_URL": "$HA_URL",
                    "HA_TOKEN": "$HA_TOKEN", "SHIM_LOG": "/work/.shim.json"}}}
}
JSON

cp "$PROMPT_FILE" "$OUT/prompt.txt"
PROXY_LOG="${PROXY_LOG:-/srv/bakeoff/replay-logs/ha-replay-access.log}"
proxy_start=$(wc -l < "$PROXY_LOG" 2>/dev/null || echo 0)

set_variant "$MODEL" "$FLAGS" >/dev/null 2>&1 || true
load_s=$(warm "$MODEL" || echo "-1")
[ "$load_s" = "-1" ] && fail "model failed to load" "load_failed"
v=$(vram); ok "loaded in ${load_s}s, VRAM ${v} MiB"

# 3. run. Extensions stay ENABLED -- the MCP server is the point of the test.
#    --auto: headless Open Code auto-REJECTS every permission request, so a
#    model that reached for /tmp was blocked and stalled while one that happened
#    to pick /work sailed through. The container is the isolation boundary; the
#    permission layer on top of it only measured which scratch path a model
#    guessed. Removing it measures MCP use instead.
eb_take "$OUT/oc" "$OUT/prompt.txt" || fail "could not hand the agent config to evalbox" "seed_failed"
SHIM=$(eb_input "$HERE/mcp-version-shim.py") || fail "could not stage the shim" "seed_failed"
t0=$(date +%s.%N)
podman run --rm --name "describe-$CASE" --userns=keep-id:uid=1000,gid=1000 \
  --add-host=host.containers.internal:host-gateway \
  --memory=8g --pids-limit=1024 --cap-drop=ALL --security-opt=no-new-privileges \
  -v "$OUT/work":/work:Z \
  -v "$OUT/oc/opencode.json":/home/agent/.config/opencode/opencode.json:ro,Z \
  -v "$OUT/prompt.txt":/prompt.txt:ro,Z \
  -v "$SHIM":/mcp-version-shim.py:ro,z \
  "$IMAGE" bash -c "cd /work && opencode run --auto --model titan/$MODEL --format json \
     \"\$(cat /prompt.txt)\"" \
  > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
t1=$(date +%s.%N)
dur=$(python3 -c "print(f'{float('$t1')-float('$t0'):.1f}')")
[ "$rc" -ne 0 ] && err "opencode exited $rc (see stderr.log)"

ev=$(wc -c < "$OUT/events.jsonl" 2>/dev/null || echo 0)
[ "$ev" -lt 2000 ] && { head -3 "$OUT/stderr.log" 2>/dev/null | sed 's/^/    /'
  fail "only ${ev} bytes of events -- harness failure, not a model result" "harness_failure"; }

cp -a "$OUT/work/REPORT.md" "$OUT/" 2>/dev/null || true
cp -a "$OUT/work/.shim.json" "$OUT/mcp-version.json" 2>/dev/null || true
tail -n +$((proxy_start + 1)) "$PROXY_LOG" 2>/dev/null > "$OUT/ha-requests.jsonl" || true

# 4. did it actually call the MCP, or just talk? executed tools only.
mcp_calls=$(grep -ocE '"(tool|toolName|name)":"[^"]*ha[_-][a-z_]*"' "$OUT/events.jsonl" 2>/dev/null || true)
mcp_calls=${mcp_calls:-0}
echo "  mcp tool invocations: $mcp_calls"

python3 "$HERE/score-describe.py" "$OUT" "$CASE" "$MODEL" "$SRC" \
        "$load_s" "$v" "$dur" "$FIXTURE"
