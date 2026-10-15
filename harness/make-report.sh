#!/usr/bin/env bash
# Rebuild the report (report/data.json, index.html, artifact.html) from the grade TSVs, reading
# case folders from the live area first and the NAS archive second. Paths: evals.env.
set -euo pipefail
source "$(dirname "$(realpath "$0")")/evals.env"
R=$EVALS_REPO; X=$EVALS_ARCHIVE_RESULTS
exec python3 "$R/tools/build_report.py" \
  --grades-a "$R/results-wave-a/grades.tsv" \
  --grades-b "$R/results-wave-b/mcp-grades-all.tsv" \
  --trust "$R/results-wave-b/trust-grades.tsv" \
  --ab "$R/results-wave-b/results-llamacpp060.json" --ab "$R/results-wave-b/results-llamacpp060-redo.json" \
  --cases-a "$R/results-wave-a" --cases-a "$X/results-wave-a" \
  --cases-b "$R/results-wave-b" --cases-b "$X/results-wave-b" \
  --grades-c "$R/results-test3/grades.tsv" --rubric-c "$R/results-test3/rubric.tsv" \
  --cases-c "$R/results-test3" --cases-c "$X/results-test3" \
  --out "$R/report"
