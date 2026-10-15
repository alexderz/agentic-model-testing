#!/bin/bash
# Stage 2 of the new-model pipeline (operator 2026-10-15 12:25, CLAW-CHECKS.md): the pagoda (test 6, page.html) and
# orrery (test 5, orrery.svg) one-shots for each model KEY of newmodels.tsv whose test 1 is recorded, then the offline
# renders. Run by a queue-new.d step inside run-next-new.sh's lease (SSH exported, nothing loaded at the start).
#   tools/newmodel_oneshots.sh KEY ...        env: TRIES (thinking-on samples, default 3), NT_TRIES (thinking-off
#                                             samples after those, default 0), ONESHOT_TIMEOUT (wall per case, 14400)
# Each entry is first set to test 1's tuned flags (lib.sh set_variant; tools/newmodels.py flags), so the one-shot runs
# at the context test 1 ran at; the reply cap is that context less 4096 tokens of room for the ~200-token prompt (the
# redo-big rule: earlier misses ran out of a 32,000 cap). As run-next-redo-big.sh: up to TRIES thinking-on samples
# until one yields the artifact, then up to NT_TRIES thinking-off samples (cases ...nmnt..., meta.json says thinking
# off; only for a template that honours enable_thinking false: LFM2.5's opens every turn with <think>, so 0 there).
# Cases t6nm<n>-<entry> and t5nm<n>-<entry>; a recorded case is skipped (tools/run_oneshot.py), so a rerun resumes.
# A missing artifact after every try is a result (logged), not a failure. Exit 1 when a KEY's test 1 is not recorded
# or its flags could not be set (that model gets no one-shots).
# REPEATS="2 3 4 5" (stage 7, run-next-five.sh): one thinking-on sample per run, cases t6r<n>-<entry> and
# t5r<n>-<entry> (the get-to-5 names), same flags and cap; TRIES and NT_TRIES are not used.
# Before each set_variant the model the previous KEY's one-shots left loaded is unloaded through titan's loopback
# llama-swap port (as run_oneshot.py and run-next-new.sh do, never :8080), and the KEY is skipped unless /running is
# empty, so the yaml is never rewritten under a loaded model.
set -u
cd "$(dirname "$0")/.." || exit 1
: "${SSH:?run from a queue-new.d step (run-next-new.sh exports SSH)}"
TRIES=${TRIES:-3} NT_TRIES=${NT_TRIES:-0}
mkdir -p results-test5 results-test6 tmp/newmodel-oneshots
one() {   # one <results> <prompt> <artifact> <case> <entry> <cap> [VAR=value ...]
  local res=$1 prompt=$2 art=$3 case=$4 entry=$5 cap=$6; shift 6
  printf '%s\t%s\n' "$case" "$entry" > "tmp/newmodel-oneshots/$case.tsv"
  env ONESHOT_ARTIFACT="$art" ONESHOT_MAX_TOKENS="$cap" ONESHOT_TIMEOUT="${ONESHOT_TIMEOUT:-14400}" "$@" \
    python3 -u tools/run_oneshot.py "$res" "$prompt" "tmp/newmodel-oneshots/$case.tsv" < /dev/null
}
free() {   # unload what the one-shots loaded; 0 when /running is empty
  local i R
  for i in $(seq 1 6); do
    R=$(timeout 40 $SSH "curl -s --max-time 10 http://127.0.0.1:8081/unload >/dev/null; sleep 5; curl -s --max-time 10 http://127.0.0.1:8081/running")
    echo "$R" | grep -q '"running":\[\]' && return 0
    sleep 10
  done
  echo "!! a model is still loaded: $R"; return 1
}
rc=0 missing= ran=
for key in "$@"; do
  out=$(python3 -I tools/newmodels.py flags "$key") || { echo "!! $key: no one-shots: $out"; rc=1; continue; }
  entry=${out%%$'\t'*} flags=${out#*$'\t'}
  ctx=$(printf '%s\n' "$flags" | grep -oP '(^| )-c \K[0-9]+' | head -n 1)
  [ -n "$ctx" ] && [ "$ctx" -ge 32768 ] || { echo "!! $key: no context in test 1's flags [$flags]"; rc=1; continue; }
  cap=$((ctx - 4096))
  echo "### $key: $entry at test 1's flags [$flags], reply cap $cap"
  free || { echo "!! $key: GPU not free; no one-shots"; rc=1; continue; }
  ( source ./lib.sh; set_variant "$entry" "$flags" ) < /dev/null || { echo "!! $key: could not set $entry to [$flags]"; rc=1; continue; }
  ran="$ran $entry"
  if [ -n "${REPEATS:-}" ]; then
    for n in $REPEATS; do
      one results-test6 suites/prompt-test6-pagoda.txt html "t6r$n-$entry" "$entry" "$cap"
      [ -f "results-test6/t6r$n-$entry/page.html" ] || missing="$missing t6r$n:$entry"
      one results-test5 suites/prompt-test5-orrery.txt svg "t5r$n-$entry" "$entry" "$cap"
      [ -f "results-test5/t5r$n-$entry/orrery.svg" ] || missing="$missing t5r$n:$entry"
    done
    continue
  fi
  for t in 6 5; do
    if [ "$t" = 6 ]; then res=results-test6 prompt=suites/prompt-test6-pagoda.txt art=html file=page.html
    else res=results-test5 prompt=suites/prompt-test5-orrery.txt art=svg file=orrery.svg; fi
    got=
    for a in $(seq 1 "$TRIES"); do
      case=t${t}nm$a-$entry
      one "$res" "$prompt" "$art" "$case" "$entry" "$cap"
      [ -f "$res/$case/$file" ] && { got=$case; break; }
    done
    if [ -z "$got" ] && [ "$NT_TRIES" -gt 0 ]; then
      for a in $(seq 1 "$NT_TRIES"); do
        case=t${t}nmnt$a-$entry
        one "$res" "$prompt" "$art" "$case" "$entry" "$cap" ONESHOT_NO_THINK=1
        [ -f "$res/$case/$file" ] && { got=$case; break; }
      done
    fi
    if [ -n "$got" ]; then echo "### test $t $entry: $file in $got"
    else echo "!! test $t $entry: no $file after every try"; missing="$missing t$t:$entry"; fi
  done
done
echo "### one-shots ended $(date -Is)${missing:+; no artifact:$missing}"
for e in $ran; do
  for d in results-test6/t6nm*-"$e"/ results-test6/t6r[0-9]-"$e"/; do
    [ -f "$d/page.html" ] && [ ! -d "$d/frames" ] && { echo "--- render $d"; tools/render_html.sh "$d/page.html" "$d/frames" 1500 5000 10000; }
  done
  for d in results-test5/t5nm*-"$e"/ results-test5/t5r[0-9]-"$e"/; do
    [ -f "$d/orrery.svg" ] && [ ! -d "$d/frames" ] && { echo "--- render $d"; tools/render_svg.sh "$d/orrery.svg" "$d/frames"; }
  done
done
exit $rc
