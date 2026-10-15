#!/usr/bin/env bash
# Grade wave A (test 1) CLIs by RUNNING them in a container.
#
# Model-written, unreviewed code never executes on pluto: no host network, work
# dir mounted read-only, unprivileged user, capabilities dropped, memory capped.
#
# Endpoint is a SECOND replay on 8127, not the 8126 instance the live case uses:
# run-case-sandboxed captures 8126's access log for the duration of a running
# case, so grading against it would attribute the grader's HTTP requests to the
# model under test. Same fixture, separate process and log.
# (Historical note: not the live proxy on 8124 either: wave A agents run
# in containers, where 127.0.0.1 is the container itself.
#
# This script TRUNCATES <dir>/grades.tsv and grades every case in <dir>: give it a
# scratch directory of symlinks, never results-wave-a itself.
# Per case it also keeps the rubric's full JSON in <dir>/_grader-json/<case>.json
# (which command read, what the bad-input and bad-auth commands printed, test errors).
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
RUB=$(eb_input "$HERE/rubric.py") || exit 1
# The recorded Home Assistant: rubric.py checks the CLI's output against its real entities.
FXT=$(eb_input "$HERE/fixtures/ha-fixture.json") || exit 1
# Accept a relative OR absolute results dir. Joining $HERE with an absolute
# path silently produces a path that matches nothing, and every model then
# grades as all-dashes -- indistinguishable from "every model failed".
RES="$(cd "${1:-results-wave-a}" 2>/dev/null && pwd)" || RES="$HERE/${1:-results-wave-a}"
OUT="$RES/grades.tsv"
LIMIT="${GRADE_TIMEOUT:-1500}"   # seconds per case; rubric.py's own budgets add up to less
mkdir -p "$RES" "$RES/_grader-json"
# tests_error is the LAST column and new (2026-10-10): readers that take columns by header name
# (tools/build_report.py) or the first ten by position are unaffected.
printf 'case\tentry\thelp\treads\tbad_input\tbad_auth\tno_crash\ttests_pass\ttests_fail\tsubcmds\ttests_error\n' > "$OUT"

for d in "$RES"/*/; do
  c=$(basename "$d"); case "$c" in superseded*|_grader-json|'*') continue;; esac
  [ -d "$d/work" ] || continue
  # Only grade FINISHED cases. Without this, grading a still-running case
  # measures a partial work tree: q38-27b-cyber was graded 5/5 with 31 tests
  # while it was mid-run with 2 of its eventual files written.
  [ -f "$d/meta.json" ] || { echo "skip (still running)"; continue; }
  printf '%-30s ' "$c"
  # grade an evalbox-owned snapshot: podman (as evalbox) cannot relabel the case tree for :Z
  snap="$HERE/tmp/wsnap.$$.$RANDOM"; mkdir -p "$snap"; cp -r "$d/work/." "$snap/" 2>/dev/null
  # evalbox reads the snapshot through group evals; a file left at mode 600 would make the copy fail
  chmod -R g+rX "$snap" 2>/dev/null
  if ! eb_take "$snap" 2>/dev/null; then
    rm -rf "$snap" 2>/dev/null; eb_rm "$snap" "$snap.eb"
    printf '%s\tGRADER-ERROR\t?\t?\t?\t?\t?\t-\t-\t0\tGRADER ERROR: could not hand the work snapshot to evalbox (unreadable files?)\n' "$c" >> "$OUT"
    echo "grader error: snapshot"; continue
  fi
  name="bakeoff-grade-a-$$-$RANDOM"; rcf="$HERE/tmp/.wrc.$$"; : > "$rcf"
  # Two time limits: `timeout` inside the container ends the rubric cleanly a little early;
  # the outer one is the backstop. Either way the exit status is kept, so a timeout is
  # reported as a timeout, not as a row of dashes that reads like a failed CLI.
  # The snapshot is mounted read-only at /work, the path the agent's sandbox used, and graded from
  # a writable copy in /app: tests that name /work/... (four archived cases do) find the files.
  # Network: inside the container host.containers.internal is 127.0.0.1, where rubric.py relays
  # ports 8126 AND 8127 to the grading replay (GRADE_REPLAY). A CLI or test with the prompt's
  # :8126 address hard-coded therefore reaches the grading replay too, never the live one.
  j=$( { timeout $((LIMIT + 30)) "$PODMAN" run --rm --name "$name" \
        --add-host=host.containers.internal:127.0.0.1 --add-host=host.docker.internal:127.0.0.1 \
        --add-host=grade-replay.internal:host-gateway -e GRADE_REPLAY=grade-replay.internal:${GRADE_PORT:-8127} \
        --memory=2g --pids-limit=256 --cap-drop=ALL \
        --security-opt=no-new-privileges \
        -v "$snap":/work:ro,Z \
        -v "$RUB":/rubric.py:ro,z \
        -v "$FXT":/fixture.json:ro,z \
        -e HA_FIXTURE=/fixture.json \
        -e HA_URL="http://host.containers.internal:${GRADE_PORT:-8127}" \
        -e HA_TOKEN="bakeoff-placeholder-token" \
        localhost/bakeoff-grader \
        sh -c "cp -r /work/. /app/ 2>/dev/null; timeout -k 5 $LIMIT python3 /rubric.py" 2>/dev/null; echo $? > "$rcf"; } | tail -1)
  rc=$(cat "$rcf" 2>/dev/null); rm -f "$rcf"
  # a container that outlived the outer limit must not keep running under the next case
  [ "$rc" = 124 ] || [ "$rc" = 137 ] && "$PODMAN" rm -f -t 0 "$name" >/dev/null 2>&1
  rm -rf "$snap" 2>/dev/null || eb_rm "$snap"
  [ -z "$j" ] && j='{}'
  printf '%s\n' "$j" > "$RES/_grader-json/$c.json"
  # Field names must match rubric.py's OUTPUT, not the column headers. rubric
  # emits entrypoint / subcommands / tests{passed,failed}; reading "entry",
  # "subcmds" and "tests_pass" silently yields blanks and zeros for every model.
  python3 - "$c" "$j" "$rc" "$LIMIT" >> "$OUT" <<'PY'
import json,sys
c,raw,rc,limit=sys.argv[1:5]
try: r=json.loads(raw)
except Exception: r={}
gerr = r.pop("grader_error", None) if isinstance(r, dict) else None
if gerr: r = {}
timed_out = rc in ("124","137")
pending = set(r.get("pending") or []) if r else {"help","reads","bad_input","bad_auth","no_crash","tests"}
t=r.get("tests") or {}
# "?" = never evaluated (grader stopped first); "-" = evaluated and failed
def b(k):
    if k in pending and (timed_out or not r): return "?"
    return "yes" if r.get(k) else "-"
note=[]
if timed_out: note.append(f"GRADER TIMEOUT after {limit}s: checks marked ? were not evaluated")
elif not r: note.append(f"GRADER ERROR: {gerr or 'no rubric output'} (container rc={rc})")
if t.get("error"): note.append(str(t["error"]))
entry = str(r.get("entrypoint") or "-")
if (timed_out or not r) and entry == "-": entry = "GRADER-TIMEOUT" if timed_out else "GRADER-ERROR"
print("\t".join([c, entry, b("help"), b("reads"),
                 b("bad_input"), b("bad_auth"), b("no_crash"),
                 str(t.get("passed","-")), str(t.get("failed","-")),
                 str(len(r.get("subcommands") or [])),
                 " ".join("; ".join(note).split())[:400]]))
PY
  tail -1 "$OUT" | cut -f2-7 | tr '\t' ' '
done
echo; column -t -s$'\t' "$OUT"
