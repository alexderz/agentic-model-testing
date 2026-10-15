#!/usr/bin/env bash
# Test 4 wave (suites/test4/DESIGN.md): the same ticket, model and settings, run N times.
#   RUN_SCRIPT=run-test4.sh python3 -u tools/tune_and_run.py matrix-test4-<model>.tsv
# Make the matrix with suites/test4/make-matrix.py. Same replay guards as run-test3.sh; every case runs
# run-case-test4.sh, which finds its ticket from the matrix row's note (ticket=<id>).
#
# The 45-minute cap on the agent is applied inside the container by run-case-test4.sh (T4_CAP_S).
# CASE_TIMEOUT here is only the outer guard of run-matrix.sh; it also covers loading the model (up to
# 40 minutes cold) and the prebuild, so it must stay well above T4_CAP_S.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
export RESULTS="$HERE/results-test4"
export MATRIX="${MATRIX:-$HERE/matrix-test4.tsv}"
export T4_CAP_S="${T4_CAP_S:-2700}"
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
export RUNNER="./run-case-test4.sh"
export AGENT=opencode
export CASE_TIMEOUT="${CASE_TIMEOUT:-$(( T4_CAP_S + 3600 ))}"
exec ./run-matrix.sh
