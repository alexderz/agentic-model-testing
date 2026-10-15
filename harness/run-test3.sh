#!/usr/bin/env bash
# Test 3 wave (suites/test3/DESIGN.md): MCP use through a delegated probe subagent.
#   RUN_SCRIPT=run-test3.sh python3 -u tools/tune_and_run.py matrix-test3.tsv
# Same replay guards as run-wave-b.sh; every case runs run-case-test3.sh, which finds the MCP source
# from the matrix row's note (mcp=<test-2 case>).
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
export RESULTS="$HERE/results-test3"
export PROMPT_FILE="${PROMPT_FILE:-$HERE/suites/prompt-test3.txt}"
export MATRIX="${MATRIX:-$HERE/matrix-test3.tsv}"
export HA_URL="http://host.containers.internal:8126"
export HA_TOKEN="bakeoff-placeholder-token"
export PROXY_LOG="/srv/bakeoff/replay-logs/ha-replay-access.log"
mkdir -p "$RESULTS"
GUARD_URL="http://127.0.0.1:8126"
code=$(curl -s -m 5 -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $HA_TOKEN" "$GUARD_URL/api/services/light/turn_on")
case "$code" in 403|404|405) ;; *) echo "replay not refusing writes (POST gave $code) -- refusing to run"; exit 1;; esac
ok=$(curl -s -m 5 -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $HA_TOKEN" "$GUARD_URL/api/states")
[ "$ok" = "200" ] || { echo "replay not serving reads ($ok) -- refusing to run"; exit 1; }
cc=$(podman run --rm --userns=keep-id:uid=1000,gid=1000 --add-host=host.containers.internal:host-gateway \
      "${AGENT_IMAGE:-localhost/bakeoff-agent}" curl -s -m 10 -o /dev/null -w "%{http_code}" \
      -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states" 2>/dev/null)
[ "$cc" = "200" ] || { echo "container cannot reach $HA_URL (got '$cc') -- refusing to run"; exit 1; }
echo "replay verified: host reads 200, writes refused ($code), container reads $cc"
export RUNNER="./run-case-test3.sh"
export AGENT=opencode
export CASE_TIMEOUT="${CASE_TIMEOUT:-10800}"
exec ./run-matrix.sh
