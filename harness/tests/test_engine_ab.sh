#!/usr/bin/env bash
# Offline check of the engine A/B steps (Model Master 2, 2026-10-15: queue-new.d/40-strata44-ab, 45-exl3-162-ab,
# 50-maya1111-ab): tools/engine_ab.py and tools/maya_digits_probe.py against a mock llama-swap (tests/fake_engine_ab.py,
# with tests/fake_ssh_ab.sh for ssh titan), the exllamav3 step's probe() (sourced) on the same mock,
# tools/add_clone_entry.py --sim on four entries of titan's yaml
# (tests/fixtures/clone-entry) with the three real plans, and the steps' syntax. No titan, no GPU. Every line must
# be PASS.   tests/test_engine_ab.sh          (KEEP=1 keeps the temp dir)
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
T=$(mktemp -d); [ -n "${KEEP:-}" ] || trap 'kill $FAKE 2>/dev/null; rm -rf "$T"' EXIT
FAILS=0
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILS=$((FAILS + 1)); }
ok() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

# 1. engine_ab.py against the mock
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
mkdir -p "$T/logs"
python3 -I tests/fake_engine_ab.py "$PORT" "$T/logs" & FAKE=$!
for i in $(seq 1 50); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.1; done
export AB_BASE="http://127.0.0.1:$PORT" AB_SSH="$HERE/tests/fake_ssh_ab.sh"
timeout 300 python3 -I tools/engine_ab.py --out "$T/ab" --workload agentic --order A,B,B,A --load-s 30 \
  --entry A=old --log "A=$T/logs/old.log" --entry B=new --log "B=$T/logs/new.log" > "$T/ab.txt" 2>&1
ok "engine_ab agentic: exit 0" "[ $? = 0 ]"
ok "engine_ab agentic: four ok rounds in summary.tsv" "[ \$(awk -F'\t' 'NR>1 && \$4==\"ok\"' $T/ab/summary.tsv | wc -l) = 4 ]"
ok "engine_ab agentic: eight requests a round" "[ \$(awk -F'\t' 'NR>1 && \$7==8' $T/ab/summary.tsv | wc -l) = 4 ]"
ok "engine_ab agentic: log decode rate read (25.0)" "[ \$(awk -F'\t' 'NR>1 && \$13==\"25.0\"' $T/ab/summary.tsv | wc -l) = 4 ]"
ok "engine_ab agentic: means per label" "grep -q '^mean A (old, 2 rounds)' $T/ab.txt && grep -q '^mean B (new, 2 rounds)' $T/ab.txt"
ok "engine_ab agentic: a round's log is only its own" "[ \$(grep -c 'strata serve' $T/ab/round1-A.log) -lt \$(grep -c 'strata serve' $T/logs/old.log) ]"
timeout 300 python3 -I tools/engine_ab.py --out "$T/bench" --workload bench --order A,B --load-s 30 \
  --entry A=old --entry B=new > "$T/bench.txt" 2>&1
ok "engine_ab bench: exit 0, 15 requests a round" "[ $? = 0 ] && [ \$(awk -F'\t' 'NR>1 && \$7==15' $T/bench/summary.tsv | wc -l) = 2 ]"
timeout 300 python3 -I tools/engine_ab.py --out "$T/broken" --workload bench --order A,B --load-s 5 \
  --entry A=old --entry B=broken > "$T/broken.txt" 2>&1
ok "engine_ab: a failing entry gives exit 1 and a FAILED row, the other round still runs" \
  "[ $? = 1 ] && grep -q $'\tbroken\tFAILED\t' $T/broken/summary.tsv && grep -q $'\told\tok\t' $T/broken/summary.tsv"

for m in cut errsse; do
  timeout 120 python3 -I tools/engine_ab.py --out "$T/$m" --workload bench --order A --load-s 30 --entry A=$m \
    > "$T/$m.txt" 2>&1
  ok "engine_ab: a stream that ends wrong ($m) is a FAILED round, exit 1" \
    "[ $? = 1 ] && grep -q $'\t$m\tFAILED\t' $T/$m/summary.tsv"
done
grep -q 'without a finish_reason' "$T/cut/summary.tsv" && grep -q 'engine error' "$T/errsse/summary.tsv" \
  && pass "engine_ab: the FAILED rows say why (cut off / engine error)" || fail "engine_ab: the FAILED rows say why"
s0=$SECONDS
timeout 120 python3 -I tools/engine_ab.py --out "$T/slow" --workload bench --order A --load-s 4 --entry A=slow \
  > "$T/slow.txt" 2>&1
ok "engine_ab: --load-s is a hard deadline for a stream that never ends (failed within 15 s)" \
  "[ $? = 1 ] && [ $((SECONDS - s0)) -lt 15 ] && grep -q 'no answer within 4 s' $T/slow/summary.tsv"
timeout 300 python3 -I tools/engine_ab.py --out "$T/rot" --workload agentic --order A,A --load-s 30 \
  --entry A=rotate --log "A=$T/logs/rotate.log" > "$T/rot.txt" 2>&1
ok "engine_ab: a log replaced by a new file of the same size is read from its start (all of round 2's lines)" \
  "[ $? = 0 ] && [ \$(grep -c 'strata serve' $T/rot/round2-A.log) = \$(grep -c 'strata serve' $T/logs/rotate.log) ] \
   && [ \$(grep -c 'strata serve' $T/rot/round2-A.log) -ge 9 ]"
timeout 300 python3 -I tools/engine_ab.py --out "$T/regrow" --workload agentic --order A,A --load-s 30 \
  --entry A=regrow --log "A=$T/logs/regrow.log" > "$T/regrow.txt" 2>&1
ok "engine_ab: a log truncated in place and grown past its old size is read from its start (all of round 2's lines)" \
  "[ $? = 0 ] && [ \$(grep -c 'strata serve' $T/regrow/round2-A.log) = \$(grep -c 'strata serve' $T/logs/regrow.log) ] \
   && [ \$(grep -c 'strata serve' $T/regrow/round2-A.log) -ge 9 ] && grep -q 'truncated in place' $T/logs/regrow.log"

# 2. maya_digits_probe.py against the mock
timeout 120 python3 -I tools/maya_digits_probe.py --base "$AB_BASE" --entry new --out "$T/probe" --sizes 20,40 \
  --needle 30 > "$T/probe.txt" 2>&1
ok "digits probe: exit 0, 8 digit rows and a needle row" "[ $? = 0 ] && [ \$(tail -n +2 $T/probe/probe.tsv | wc -l) = 9 ]"
ok "digits probe: needle found, summary line" "grep -q 'needle 1/1; failed requests 0' $T/probe.txt"
timeout 120 python3 -I tools/maya_digits_probe.py --base "$AB_BASE" --entry broken --out "$T/probe2" --sizes 20 \
  > "$T/probe2.txt" 2>&1
ok "digits probe: failed requests give exit 1" "[ $? = 1 ] && grep -q 'failed requests 4' $T/probe2.txt"

# 2b. the exllamav3 step's probe() (sourced, AB_FUNCS_ONLY=1) against the mock: load and prompt outcomes in context.tsv.
# The container log holds an old out-of-memory error and a setting that says OOM; neither may make a failure a result.
export AB_PODMAN_LOG="$T/logs/podman.log"
printf '1000\ttorch.OutOfMemoryError: CUDA out of memory (a load before this probe)\n%s\tsettings: oom_score_adj=-500, OOM guard on\n' \
  "$(( $(date +%s) + 100000 ))" > "$AB_PODMAN_LOG"
probe45() {  # probe45 ENTRY LOAD_S: probe() with two prompts; its output in $T/p45-ENTRY.txt, rows in $T/p45-ENTRY.tsv
  ( export SSH="$HERE/tests/fake_ssh_ab.sh" AB_LOAD_S=$2 CTX="$T/p45-$1.tsv" AB_FUNCS_ONLY=1
    # shellcheck disable=SC1091
    source queue-new.d/45-exl3-162-ab.sh.new; probe "$1" "30 75" "40 76"; echo "probe rc=$?" ) > "$T/p45-$1.txt" 2>&1
}
outc() { cut -f3 "$T/p45-$1.tsv" | tr '\n' ' '; }
probe45 new 30
ok "probe: a load and two answered prompts are ok rows, rc 0" "[ \"\$(outc new)\" = 'ok ok ok ' ] && grep -q 'probe rc=0' $T/p45-new.txt"
probe45 broken 4
ok "probe: a failed load with only an old and a settings OOM line is FAILED, rc 1" \
  "[ \"\$(outc broken)\" = 'FAILED ' ] && grep -q 'probe rc=1' $T/p45-broken.txt"
probe45 oomload 4
ok "probe: a load that logs a new out-of-memory error is oom (a result), rc 0" \
  "[ \"\$(outc oomload)\" = 'oom ' ] && grep -q 'probe rc=0' $T/p45-oomload.txt"
probe45 oomprompt 30
ok "probe: a prompt that logs a new out-of-memory error is oom, the rest skipped, rc 0" \
  "[ \"\$(outc oomprompt)\" = 'ok oom ' ] && grep -q 'probe rc=0' $T/p45-oomprompt.txt"
s0=$SECONDS; probe45 stall 4
ok "probe: a 200 that stalls (curl times out) is not a load: FAILED within the deadline, rc 1" \
  "[ \"\$(outc stall)\" = 'FAILED ' ] && grep -q 'curl 28' $T/p45-stall.tsv && grep -q 'probe rc=1' $T/p45-stall.txt \
   && [ $((SECONDS - s0)) -lt 15 ]"
rm -f "$T/p45-oomload.tsv"; AB_PODMAN_LOG="$T/logs/gone.log" probe45 oomload 4
ok "probe: an out-of-memory error in a log that cannot be read (container gone) is FAILED, rc 1" \
  "[ \"\$(outc oomload)\" = 'FAILED ' ] && grep -q 'probe rc=1' $T/p45-oomload.txt && grep -q 'lines ?' $T/p45-oomload.tsv"
unset AB_PODMAN_LOG
kill $FAKE 2>/dev/null; wait $FAKE 2>/dev/null

# 3. add_clone_entry.py --sim with the three plans on a copy of the fixture
cp -a tests/fixtures/clone-entry "$T/sim"
Y="$T/sim/home/operator/ai/config/llama-swap.yaml"
cp "$Y" "$T/yaml.before"
for p in engines/strata/strata44-entry.json engines/exllamav3/exl3-162-entries.json engines/maya/maya1111-entry.json; do
  python3 -I tools/add_clone_entry.py --sim "$T/sim" "$p" > "$T/sim-$(basename "$p").txt" 2>&1
  ok "add_clone_entry --sim $(basename "$p"): exit 0, entries added" "[ $? = 0 ] && grep -q '^added ' $T/sim-$(basename "$p").txt"
done
ok "add_clone_entry: the fixture's own entries are unchanged" "python3 -I -c '
import sys, yaml
a = yaml.safe_load(open(sys.argv[1]))[\"models\"]; b = yaml.safe_load(open(sys.argv[2]))[\"models\"]
sys.exit(0 if all(b[k] == v for k, v in a.items()) and len(b) == len(a) + 5 else 1)' $T/yaml.before $Y"
ok "add_clone_entry: a backup of the yaml before each write" "[ \$(ls $T/sim/home/operator/ai/config/ | grep -c bak-clone) = 3 ]"
python3 -I tools/add_clone_entry.py --sim "$T/sim" engines/exllamav3/exl3-162-entries.json > "$T/sim-rerun.txt" 2>&1
ok "add_clone_entry: a rerun skips every entry and writes nothing" \
  "[ $? = 0 ] && [ \$(grep -c '^skip ' $T/sim-rerun.txt) = 3 ] && grep -q 'no new entries' $T/sim-rerun.txt"
S="$T/sim/home/operator/ai/config/specs/strata44-flash-next-pcie.json"
python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1])); s["served_context"]=1; json.dump(s,open(sys.argv[1],"w"))' "$S"
cp "$Y" "$T/yaml.mid"
python3 -I tools/add_clone_entry.py --sim "$T/sim" engines/strata/strata44-entry.json > "$T/sim-tamper.txt" 2>&1
ok "add_clone_entry: an entry whose spec differs from the plan aborts, yaml untouched" \
  "[ $? = 1 ] && grep -q 'PROBLEMS' $T/sim-tamper.txt && cmp -s $Y $T/yaml.mid"
python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1])); s["served_context"]=262144; json.dump(s,open(sys.argv[1],"w"))' "$S"
python3 -I tests/test_engine_ab.py "$T/sim"; [ $? = 0 ] || FAILS=$((FAILS + 1))

# 4. the steps
for s in queue-new.d/40-strata44-ab.sh.new queue-new.d/45-exl3-162-ab.sh.new queue-new.d/50-maya1111-ab.sh.new; do
  ok "bash -n $s" "bash -n $s"
done
SSH= bash queue-new.d/45-exl3-162-ab.sh.new > "$T/nossh.txt" 2>&1
ok "a step refuses to run without run-next-new.sh's SSH" "[ $? != 0 ] && grep -q 'run from run-next-new.sh' $T/nossh.txt"
echo "test_engine_ab: $([ $FAILS = 0 ] && echo 'all PASS' || echo "$FAILS FAIL")"
exit $((FAILS > 0))
