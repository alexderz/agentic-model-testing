#!/usr/bin/env bash
# Test 8 wave (suites/test8/README.md): the pagoda and the orrery as agent tasks with sub-agents and a sealed browser
# (Model Master 2).
#   MATRIX=$PWD/matrix-test8.tsv RUN_SCRIPT=run-test8.sh python3 -u tools/tune_and_run.py matrix-test8.tsv
# Every case runs run-case-test8.sh. The 2-hour cap on the agent is applied inside the container (T8_CAP_S);
# CASE_TIMEOUT here is only the outer guard of run-matrix.sh and also covers loading the model and rendering.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
export RESULTS="$HERE/results-test8"
export MATRIX="${MATRIX:-$HERE/matrix-test8.tsv}"
export T8_CAP_S="${T8_CAP_S:-7200}"
mkdir -p "$RESULTS"
export RUNNER="./run-case-test8.sh"
export AGENT=opencode
export CASE_TIMEOUT="${CASE_TIMEOUT:-$(( T8_CAP_S + 3600 ))}"
exec ./run-matrix.sh
