#!/usr/bin/env bash
# Run each generated CLI inside a container and record what actually works.
# The code is model-written and unreviewed, so it never executes on pluto:
#   * no host network -- it reaches only the dedicated test proxy
#   * work dir copied in, mounted read-only, runs as an unprivileged user
#   * no capabilities, memory and pid capped
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
RES="${1:-results-r2}"
TOK="${HA_TOKEN:?set HA_TOKEN to the replay token}"
OUT="$HERE/$RES/grades.tsv"
printf 'case\tentry\thelp\treads\tbad_input\tbad_auth\tno_crash\ttests_pass\ttests_fail\tsubcmds\n' > "$OUT"

for d in "$RES"/*/; do
  c=$(basename "$d"); [ -d "$d/work" ] || continue
  printf '%-22s ' "$c"
  j=$(podman run --rm \
        --add-host=host.containers.internal:host-gateway \
        --memory=2g --pids-limit=256 --cap-drop=ALL \
        --security-opt=no-new-privileges \
        -v "$HERE/$d/work":/src:ro,Z \
        -v "$HERE/rubric.py":/rubric.py:ro,Z \
        -e HA_URL="http://host.containers.internal:8125" \
        -e HA_TOKEN="$TOK" \
        localhost/bakeoff-grader \
        sh -c 'cp -r /src/. /app/ 2>/dev/null; python3 /rubric.py' 2>/dev/null | tail -1)
  [ -z "$j" ] && j='{}'
  python3 - "$c" "$j" >> "$OUT" <<'PY'
import json,sys
c,raw=sys.argv[1],sys.argv[2]
try: r=json.loads(raw)
except Exception: r={}
t=r.get("tests") or {}
def b(k): return "yes" if r.get(k) else "-"
print("\t".join([c, str(r.get("entrypoint") or "-"), b("help"), b("reads"),
                 b("bad_input"), b("bad_auth"), b("no_crash"),
                 str(t.get("passed","-")), str(t.get("failed","-")),
                 str(len(r.get("subcommands") or []))]))
PY
  tail -1 "$OUT" | cut -f3-9 | tr '\t' ' '
done
echo; column -t -s$'\t' "$OUT"
