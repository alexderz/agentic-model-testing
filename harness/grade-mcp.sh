#!/usr/bin/env bash
# Grade every generated Rust MCP server by building and speaking to it.
# The agent image's writable root is /work, not /app -- copying into a
# directory that does not exist failed silently and reported "no Cargo.toml".
#
# This script TRUNCATES <dir>/mcp-grades.tsv and grades every case in <dir> (a path inside the
# repo): give it a scratch directory of symlinks, never results-wave-b itself.
# Per case it also keeps grade-mcp.py's full JSON in <dir>/_grader-json/<case>.json
# (which binary and why, every tools/call tried and what came back).
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
GMP=$(eb_input "$HERE/grade-mcp.py") || exit 1
# The recorded Home Assistant: grade-mcp.py checks a tool's reply against its real data.
FXT=$(eb_input "$HERE/fixtures/ha-fixture.json") || exit 1
RES="${1:-results-r3}"
OUT="$HERE/$RES/mcp-grades.tsv"
LIMIT="${GRADE_TIMEOUT:-2400}"   # seconds per case, build and tests included
mkdir -p "$HERE/$RES/_grader-json"
printf 'case\tbuilds\tbinary\tinit\ttools\ttool_call\ttests_pass\ttests_fail\tnote\n' > "$OUT"

for d in "$RES"/*/; do
  c=$(basename "$d")
  case "$c" in *superseded*|host-run-*|dead-endpoint-*|_grader-json) continue;; esac
  [ -d "$d/work" ] || continue
  find "$d/work/" -name Cargo.toml -not -path "*/target/*" -print -quit 2>/dev/null | grep -q . || {
    printf '%s\t-\t-\t-\t-\t-\t-\t-\tno cargo project\n' "$c" >> "$OUT"
    printf '%-14s no cargo project\n' "$c"; continue; }
  printf '%-14s ' "$c"
  # Grade a private copy: case trees can hold root-owned files written after
  # the run (a .git/config), and the :Z relabel of the original then fails,
  # which the old code recorded as an all-dash "did not build" row.
  # The snapshot is handed to evalbox so podman can relabel it (plain mkdir, not mktemp -d: mktemp's
  # mode 700 masks the group ACL evalbox reads through).
  snap="$HERE/tmp/gsnap.$$.$RANDOM"; mkdir -p "$snap"; cp -r "$d/work/." "$snap/" 2>/dev/null
  find "$snap" -name .git -type d -prune -exec rm -rf {} + 2>/dev/null
  # evalbox reads the snapshot through group evals: a file the case left at mode 600 (cargo's
  # incremental .lock files, once the case is archived under our own account) makes eb_take's
  # copy fail, and podman then cannot relabel the tree. Five archived cases failed that way.
  chmod -R g+rX "$snap" 2>/dev/null
  if ! eb_take "$snap" 2>/dev/null; then
    rm -rf "$snap" 2>/dev/null; eb_rm "$snap" "$snap.eb"
    printf '%s\t?\t?\t?\t?\t?\t?\t?\tgrader error: could not hand the work snapshot to evalbox (unreadable files?)\n' "$c" >> "$OUT"
    echo "grader error: snapshot"; continue
  fi
  name="bakeoff-grade-b-$$-$RANDOM"; rcf="$HERE/tmp/.grc.$$"; : > "$rcf"
  # grade-mcp.py keeps its own deadline (GRADE_DEADLINE) below the container's, prints a JSON
  # line per finished phase, and `timeout` inside the container ends it a little before the
  # outer limit. So a slow build or test run yields a row that says "grader timeout" and keeps
  # the facts already established, instead of a row of dashes that reads like a dead server.
  # Network: inside the container host.containers.internal is 127.0.0.1, where grade-mcp.py
  # relays ports 8126 AND 8127 to the grading replay (GRADE_REPLAY). A server or test with the
  # prompt's :8126 address hard-coded therefore reaches the grading replay too, never the live one.
  j=$( { timeout $((LIMIT + 60)) "$PODMAN" run --rm --name "$name" --userns=keep-id:uid=1000,gid=1000 \
        --add-host=host.containers.internal:127.0.0.1 --add-host=host.docker.internal:127.0.0.1 \
        --add-host=grade-replay.internal:host-gateway -e GRADE_REPLAY=grade-replay.internal:8127 \
        --memory=4g --pids-limit=512 --cap-drop=ALL --security-opt=no-new-privileges \
        -v "$snap":/src:ro,Z -v "$GMP":/grade-mcp.py:ro,z -v "$FXT":/fixture.json:ro,z \
        -e GRADE_ROOT=/home/agent/grading \
        -e GRADE_DEADLINE=$((LIMIT - 100)) \
        -e HA_FIXTURE=/fixture.json \
        -e HA_URL="http://host.containers.internal:8127" \
        -e HA_BASE_URL="http://host.containers.internal:8127" \
        -e HA_TOKEN="bakeoff-placeholder-token" \
        localhost/bakeoff-agent \
        sh -c "mkdir -p /home/agent/grading && cp -r /src/. /home/agent/grading/ && cd /home/agent/grading && timeout -k 5 $LIMIT python3 /grade-mcp.py" \
        2>/dev/null; echo $? > "$rcf"; } | tail -1)
  rc=$(cat "$rcf" 2>/dev/null); rm -f "$rcf"
  # a container that outlived the outer limit must not keep building under the next case
  [ "$rc" = 124 ] || [ "$rc" = 137 ] && "$PODMAN" rm -f -t 0 "$name" >/dev/null 2>&1
  rm -rf "$snap" 2>/dev/null || eb_rm "$snap"
  printf '%s\n' "${j:-{\}}" > "$HERE/$RES/_grader-json/$c.json"
  python3 - "$c" "$j" "$rc" "$LIMIT" >> "$OUT" <<'PY'
import json,sys
c,raw,rc,limit=sys.argv[1:5]
try: r=json.loads(raw)
except Exception: r={}
gerr = r.get("grader_error") if isinstance(r, dict) else None
if gerr: r = {}
t=r.get("cargo_test") or {}
killed = rc in ("124","137")
phase = r.get("phase") or "start"
# which columns the phase that was running would have filled; "?" = never evaluated
PENDING = {"start": ("builds","binary","initialize","tools_list","tools_call","tests"),
           "manifest": ("builds","binary","initialize","tools_list","tools_call","tests"),
           "build": ("builds","binary","initialize","tools_list","tools_call","tests"),
           "speak": ("initialize","tools_list","tools_call","tests"), "test": ("tests",)}
pend = PENDING.get(phase, ()) if (killed or not r) else ()
def b(k):
    if k in pend: return "?"
    return "yes" if r.get(k) is True else ("-" if not r.get(k) else str(r[k]))
note=[]
if killed: note.append(f"grader timeout: container stopped after {limit}s during {phase}; ? = not evaluated")
elif not r: note.append(f"grader error: {gerr or 'no output from grade-mcp.py'} (container rc={rc})")
if r.get("grader_timeout") and not str(r.get("build_error") or "").startswith("grader timeout"):
    note.append("grader timeout: " + r["grader_timeout"])
for k in ("build_error","note","init_error","rpc_error","call_note"):
    if r.get(k): note.append(str(r[k]))
print("\t".join([c, b("builds"), "?" if "binary" in pend else str(r.get("binary") or "-"), b("initialize"),
                 "?" if "tools_list" in pend else str(r.get("tools_list") or 0), b("tools_call"),
                 "?" if "tests" in pend else str(t.get("passed","-")),
                 "?" if "tests" in pend else str(t.get("failed","-")),
                 " ".join("; ".join(note).split())[:300]]))
PY
  tail -1 "$OUT" | cut -f2-6 | tr '\t' ' '
done
echo; column -t -s$'\t' "$OUT"
