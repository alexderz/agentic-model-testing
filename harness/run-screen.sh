#!/usr/bin/env bash
# Wave 1: screening. One simple functional-code task across every candidate.
#
# Purpose is exclusion, not ranking: find models that cannot write working code
# so wave 2 (context and quality at context) is not wasted on them. Short by
# design -- 40 min per case, not the 2h+ of the MCP build test.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
export RESULTS="$HERE/results-screen"
export PROMPT_FILE="$HERE/suites/prompt-screen-functional.txt"
export MATRIX="$HERE/matrix-screen.tsv"
export AGENT=opencode
export CASE_TIMEOUT="${CASE_TIMEOUT:-2400}"
export SCORER=skip                # graded below, in a container
export RUNNER="$HERE/runner-screen.sh"
mkdir -p "$RESULTS"
exec ./run-matrix.sh
