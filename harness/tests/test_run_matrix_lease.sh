#!/usr/bin/env bash
# Offline check of run-matrix.sh's handling of titan's GPU lease (Model Master 2, 2026-10-15): a lease the calling
# queue holds is kept between cases (no release, the queue's reason stays in front), a lease the script takes itself
# is released after each case, a leftover "eval case" lease and a stale one count as the script's own, another
# holder is still waited for (and one that slips in between the status read and the acquire too), and
# BAKEOFF_LEASE_HELD=1/0 overrides the status. ssh runs the commands here against tests/fixtures/gpu-lease (a copy
# of titan's ~/bin/gpu-lease) with fake curl, nvidia-smi, podman and sleep. No titan, no GPU. Every line must be PASS.
#   tests/test_run_matrix_lease.sh                 (KEEP=1 keeps the temp dir)
#   RUN_MATRIX=./run-matrix.sh.new tests/test_run_matrix_lease.sh   (check a replacement before renaming it in)
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
RM="${RUN_MATRIX:-./run-matrix.sh}"
T=$(mktemp -d); if [ -n "${KEEP:-}" ]; then echo "kept: $T"; else trap 'rm -rf "$T"' EXIT; fi
FAILS=0
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILS=$((FAILS + 1)); }
ok() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

# --- fakes -------------------------------------------------------------------------------------------------------
B="$T/bin"; mkdir -p "$B" "$T/home/bin"
cp tests/fixtures/gpu-lease "$T/home/bin/gpu-lease"; chmod +x "$T/home/bin/gpu-lease"
cat > "$B/ssh" <<'EOF'
#!/bin/bash
# "ssh [opts] host cmd": run cmd here with HOME=$FAKE_HOME (so ~/bin/gpu-lease is the fixture)
while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac; done
shift; cmd="$*"
printf '%s\n' "$cmd" >> "$F/ssh.log"
lease() { HOME="$FAKE_HOME" bash -c "~/bin/gpu-lease $1" >/dev/null 2>&1; }
case "$cmd" in
  *"gpu-lease status"*)
    n=$(( $(cat "$F/status-calls" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$F/status-calls"
    case " ${FAIL_STATUS_CALLS:-} " in *" $n "*) exit 255 ;; esac ;;
  *"gpu-lease acquire bakeoff"*)
    [ -f "$F/rival-before-acquire" ] && { rm -f "$F/rival-before-acquire"; lease "acquire rival 'slipped in'"; } ;;
esac
HOME="$FAKE_HOME" bash -c "$cmd"; rc=$?
# the race the fix closes: whenever the bakeoff lease is released, a rival takes the GPU at once
case "$cmd" in *"gpu-lease release bakeoff"*) [ -f "$F/rival-on-release" ] && lease "acquire rival 'took the gap'" ;; esac
exit $rc
EOF
cat > "$B/sleep" <<'EOF'
#!/bin/bash
# no real waiting; after RIVAL_LEAVES_AFTER sleeps the other holder ("operator" or "rival") gives the lease back
n=$(( $(cat "$F/sleeps" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$F/sleeps"
if [ -n "${RIVAL_LEAVES_AFTER:-}" ] && [ "$n" -ge "$RIVAL_LEAVES_AFTER" ]; then
  h=$(sed -n 1p "$GPU_LEASE_FILE" 2>/dev/null)
  if [ "$h" = operator ] || [ "$h" = rival ]; then
    # RIVAL_THEN_QUEUE: a queue's acquire (GPU_LEASE_WAIT) wins the card the moment the other holder leaves
    if [ -n "${RIVAL_THEN_QUEUE:-}" ]; then printf '%s\n%s\n%s\n' bakeoff "$(date +%s)" "$RIVAL_THEN_QUEUE" > "$GPU_LEASE_FILE"
    else rm -f "$GPU_LEASE_FILE"; fi
  fi
fi
exit 0
EOF
cat > "$B/curl" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$F/curl.log"
case "$*" in *running*) echo '{"running":[]}' ;; esac
exit 0
EOF
cat > "$B/nvidia-smi" <<'EOF'
#!/bin/bash
case "$*" in *memory.total*) echo "100 MiB, 24576 MiB" ;; *) echo 100 ;; esac
EOF
printf '#!/bin/bash\nexit 0\n' > "$B/podman"
printf '#!/bin/bash\nexit 1\n' > "$B/pgrep"
printf '#!/bin/bash\nprintf "%%s\\n" "$*" >> "$F/poke.log"\n' > "$B/claude-poke"
cat > "$T/runner.sh" <<'EOF'
#!/bin/bash
# fake run-case.sh: note who holds the lease while the case runs, write a result
printf '%s\t%s\t%s\n' "$1" "$(sed -n 1p "$GPU_LEASE_FILE" 2>/dev/null)" "$(sed -n 3p "$GPU_LEASE_FILE" 2>/dev/null)" >> "$F/cases.log"
# a queue's hourly refresher firing during the case (blind rewrite, as run-next-new.sh does)
[ -f "$F/refresh-during-case" ] && printf '%s\n%s\n%s\n' bakeoff "$(date +%s)" 'new-work slot' > "$GPU_LEASE_FILE"
mkdir -p "$RESULTS/$1"; echo '{"status": "ok"}' > "$RESULTS/$1/meta.json"
EOF
chmod +x "$B"/* "$T/runner.sh"
printf 'c1\tm1\t-\tx\nc2\tm2\t-\tx\n' > "$T/two.tsv"
printf 'c1\tm1\t-\tx\n' > "$T/one.tsv"
for i in 1 2 3; do printf 'r%s\tm%s\t-\tx\n' $i $i > "$T/row$i.tsv"; done

# run <name> <matrix> <lease: none|keep|holder:age_s:reason> [VAR=value ...]: one matrix run in directory <name>
# (keep: a further run in the same directory, lease and counters as the last run left them)
run() {
  local name=$1 m=$2 l=$3; shift 3
  F="$T/$name"; mkdir -p "$F/results"
  if [ "$l" != none ] && [ "$l" != keep ]; then
    IFS=: read -r lh la lr <<<"$l"; printf '%s\n%s\n%s\n' "$lh" "$(( $(date +%s) - la ))" "$lr" > "$F/lease"
  fi
  env PATH="$B:$PATH" F="$F" FAKE_HOME="$T/home" GPU_LEASE_FILE="$F/lease" RESULTS="$F/results" MATRIX="$T/$m" RUNNER="$T/runner.sh" \
    TITAN=titan "$@" timeout 120 "$RM" >> "$F/out.log" 2>&1
  echo $? > "$F/rc"
}
holder() { sed -n 1p "$T/$1/lease" 2>/dev/null; }
reason() { sed -n 3p "$T/$1/lease" 2>/dev/null; }
releases() { grep -c 'gpu-lease release bakeoff' "$T/$1/ssh.log" 2>/dev/null; }
cases() { cut -f1,2 "$T/$1/cases.log" 2>/dev/null | tr '\t\n' ': '; }

# 1. a queue holds the lease: kept across both cases, nobody slips in, the queue's reason stays in front
run queue two.tsv "bakeoff:120:new-work slot"
ok "queue lease: matrix exit 0, both cases ran" "[ \$(cat $T/queue/rc) = 0 ] && [ \$(wc -l < $T/queue/cases.log) = 2 ]"
ok "queue lease: no release issued" "[ \$(releases queue) = 0 ]"
ok "queue lease: bakeoff held during both cases" "[ \"\$(cases queue)\" = 'c1:bakeoff c2:bakeoff ' ]"
ok "queue lease: still held by bakeoff after the matrix" "[ \"\$(holder queue)\" = bakeoff ]"
ok "queue lease: the queue's reason kept in front of the case" "[ \"\$(reason queue)\" = 'new-work slot [eval case c2]' ]"
ok "queue lease: GPU_LEASE_KEEP_MODEL passed for each case" "grep -q \"GPU_LEASE_KEEP_MODEL='m1' \" $T/queue/ssh.log && grep -q \"GPU_LEASE_KEEP_MODEL='m2' \" $T/queue/ssh.log"
ok "queue lease: logged as kept" "grep -q 'bakeoff lease held by the caller (new-work slot): kept after the case' $T/queue/out.log"

# 1b. the same with a rival that grabs the GPU the moment the bakeoff lease is released (the bug before the fix)
F="$T/queue-rival"; mkdir -p "$F"; touch "$F/rival-on-release"
run queue-rival two.tsv "bakeoff:120:test 8 agent pagoda and orrery" GPU_WAIT_MAX=120
ok "queue lease + rival: both cases ran under bakeoff, no wait" "[ \"\$(cases queue-rival)\" = 'c1:bakeoff c2:bakeoff ' ] && ! grep -q 'waiting for GPU' $T/queue-rival/out.log"
ok "queue lease + rival: lease never handed to the rival" "[ \"\$(holder queue-rival)\" = bakeoff ]"

# 1c. one process per row, as tools/tune_and_run.py runs it; the second process cannot read the status (3 tries)
run rows row1.tsv "bakeoff:120:redo at full context"
run rows row2.tsv keep FAIL_STATUS_CALLS="2 3 4"
run rows row3.tsv keep
ok "queue lease, one process per row: all three rows ran under bakeoff" "[ \"\$(cases rows)\" = 'r1:bakeoff r2:bakeoff r3:bakeoff ' ]"
ok "queue lease, status unreadable in row 2: lease left alone (no acquire, no release)" "grep -q 'status unreadable: left as it is' $T/rows/out.log && ! grep -q \"KEEP_MODEL='m2'\" $T/rows/ssh.log"
ok "queue lease, one process per row: never released, queue reason still in front" "[ \$(releases rows) = 0 ] && [ \"\$(holder rows)\" = bakeoff ] && [ \"\$(reason rows)\" = 'redo at full context [eval case r3]' ]"

# 1d. a queue's lease with no reason line: kept, and marked so the next process still sees a queue's lease
run noreason row1.tsv "bakeoff:120:"
run noreason row2.tsv keep
ok "queue lease without a reason: kept across two processes" "[ \$(releases noreason) = 0 ] && [ \"\$(holder noreason)\" = bakeoff ] && [ \"\$(reason noreason)\" = 'queue lease [eval case r2]' ]"

# 2. nobody holds it: taken for each case and released after it
run self two.tsv none
ok "self-taken: both cases ran" "[ \$(cat $T/self/rc) = 0 ] && [ \"\$(cases self)\" = 'c1:bakeoff c2:bakeoff ' ]"
ok "self-taken: reason is the case" "[ \"\$(cut -f3 $T/self/cases.log | tr '\n' '|')\" = 'eval case c1|eval case c2|' ]"
ok "self-taken: released after each case" "[ \$(releases self) = 2 ] && [ ! -e $T/self/lease ]"
ok "self-taken: logged as taken per case" "grep -q 'bakeoff lease taken for the case and released after it' $T/self/out.log"

# 2b. lease taken by this script, but the queue's refresher rewrites it during the case: the queue's lease wins
F="$T/refreshed"; mkdir -p "$F"; touch "$F/refresh-during-case"
run refreshed one.tsv none
ok "self-taken, refresher rewrote it mid-case: not released" "[ \$(releases refreshed) = 0 ] && [ \"\$(reason refreshed)\" = 'new-work slot' ] && grep -q 'bakeoff lease not released: it is now HELD by bakeoff' $T/refreshed/out.log"

# 2c. self-taken, status unreadable at release time: not released (fail closed); the next run clears the leftover
run relblip one.tsv none FAIL_STATUS_CALLS="2 3 4"
ok "self-taken, status unreadable at release: not released" "[ \$(releases relblip) = 0 ] && [ \"\$(reason relblip)\" = 'eval case c1' ] && grep -q 'not released: it is now unreadable' $T/relblip/out.log"
run relblip row1.tsv keep
ok "the next run treats that leftover as its own and releases it" "[ \$(releases relblip) = 1 ] && [ ! -e $T/relblip/lease ]"

# 3. a leftover lease of this script ("eval case ...") and a stale queue lease count as its own: released
run leftover one.tsv "bakeoff:600:eval case dead-run-r1"
ok "leftover eval-case lease: case ran, then released" "[ \"\$(cases leftover)\" = 'c1:bakeoff ' ] && [ \$(releases leftover) = 1 ] && [ ! -e $T/leftover/lease ]"
run stale one.tsv "bakeoff:30000:new-work slot"
ok "stale queue lease: treated as free, taken and released" "[ \"\$(cases stale)\" = 'c1:bakeoff ' ] && [ \$(releases stale) = 1 ] && [ ! -e $T/stale/lease ]"

# 4. someone else holds it: waited for, then taken and released; never released for them
run other one.tsv "operator:60:real work" RIVAL_LEAVES_AFTER=2
ok "other holder: waited for" "grep -q '^   waiting for GPU: HELD by operator since' $T/other/out.log && [ \$(cat $T/other/sleeps) -ge 2 ]"
ok "other holder: case ran only after, under bakeoff" "[ \"\$(cases other)\" = 'c1:bakeoff ' ] && grep -q 'GPU free after 120s' $T/other/out.log"
ok "other holder: no release of theirs, ours released" "! grep -q 'release operator' $T/other/ssh.log && [ \$(releases other) = 1 ] && [ ! -e $T/other/lease ]"
run other-stays one.tsv "operator:60:real work" GPU_WAIT_MAX=180
ok "other holder who stays: matrix stops at GPU_WAIT_MAX, no case, their lease intact" "grep -q 'GPU held for 180s -- stopping' $T/other-stays/out.log && [ ! -e $T/other-stays/cases.log ] && [ \"\$(holder other-stays)\" = operator ] && ! grep -q 'gpu-lease acquire' $T/other-stays/ssh.log"

# 5. a holder slips in between the status read and the acquire: waited for like any other
F="$T/race"; mkdir -p "$F"; touch "$F/rival-before-acquire"
run race one.tsv none RIVAL_LEAVES_AFTER=1
ok "race before acquire: noticed" "grep -q '^   lease taken before our acquire: HELD by rival' $T/race/out.log"
ok "race before acquire: case ran under bakeoff after the rival left" "[ \"\$(cases race)\" = 'c1:bakeoff ' ] && [ \$(grep -c 'gpu-lease acquire bakeoff' $T/race/ssh.log) = 2 ] && [ ! -e $T/race/lease ]"

# 5b. the same, but a queue takes the lease while we wait: the retry must treat it as the queue's (Grok review 2)
F="$T/race-queue"; mkdir -p "$F"; touch "$F/rival-before-acquire"
run race-queue one.tsv none RIVAL_LEAVES_AFTER=1 RIVAL_THEN_QUEUE="new-work slot"
ok "race, then a queue's lease: case ran under the queue's lease" "[ \"\$(cut -f1-3 $T/race-queue/cases.log)\" = \"\$(printf 'c1\tbakeoff\tnew-work slot [eval case c1]')\" ]"
ok "race, then a queue's lease: not released, queue reason kept" "[ \$(releases race-queue) = 0 ] && [ \"\$(holder race-queue)\" = bakeoff ] && [ \"\$(reason race-queue)\" = 'new-work slot [eval case c1]' ]"

# 6. BAKEOFF_LEASE_HELD overrides the status
run env1 two.tsv none BAKEOFF_LEASE_HELD=1
ok "BAKEOFF_LEASE_HELD=1: taken, kept, never released" "[ \"\$(cases env1)\" = 'c1:bakeoff c2:bakeoff ' ] && [ \$(releases env1) = 0 ] && [ \"\$(holder env1)\" = bakeoff ]"
run env0 two.tsv "bakeoff:120:new-work slot" BAKEOFF_LEASE_HELD=0
ok "BAKEOFF_LEASE_HELD=0: released after each case even with a queue's lease" "[ \$(releases env0) = 2 ] && [ ! -e $T/env0/lease ]"

bash -n "$RM"; ok "bash -n $RM" "[ $? = 0 ]"
echo "test_run_matrix_lease ($RM): $([ $FAILS = 0 ] && echo 'ALL PASS' || echo "$FAILS FAIL")"
[ $FAILS = 0 ]
