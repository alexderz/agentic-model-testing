#!/usr/bin/env bash
# Test 7 wave (suites/test7/README.md): the labyrinth, an agent task with a verifier (Model Master 2).
#   MATRIX=$PWD/matrix-test7.tsv RUN_SCRIPT=run-test7.sh python3 -u tools/tune_and_run.py matrix-test7.tsv
# Every case runs run-case-test7.sh. The 3-hour cap on the agent is applied inside the container (T7_CAP_S);
# CASE_TIMEOUT here is only the outer guard of run-matrix.sh and also covers loading the model.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
export RESULTS="$HERE/results-test7"
export MATRIX="${MATRIX:-$HERE/matrix-test7.tsv}"
export T7_CAP_S="${T7_CAP_S:-10800}"
mkdir -p "$RESULTS"
export RUNNER="./run-case-test7.sh"
export AGENT=opencode
export CASE_TIMEOUT="${CASE_TIMEOUT:-$(( T7_CAP_S + 3600 ))}"
exec ./run-matrix.sh
