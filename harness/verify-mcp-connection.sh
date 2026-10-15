#!/usr/bin/env bash
# Did the CLIENT accept this case's MCP server? Ground truth, not inference.
#
# The shim log only proves the server emitted something. Open Code can still
# refuse it -- an initialize result with an uncorrelatable id closes the
# connection -- and "had a working MCP and ignored it" is a very different
# claim about a model than "had no MCP and made numbers up".
#
# HA_URL deliberately points at the discard port: initialize and tools/list
# do not need the data endpoint, and pointing at the live replay would append
# to the shared access log and inflate the request count of whichever case is
# running right now.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
for d in "$@"; do
  [ -d "$d/work" ] || continue
  [ -f "$d/oc/opencode.json" ] || continue
  out=$(podman run --rm --userns=keep-id \
        -e HA_URL=http://127.0.0.1:9 -e HA_BASE_URL=http://127.0.0.1:9 \
        -v "$PWD/$d/work":/work:Z \
        -v "$PWD/mcp-version-shim.py":/mcp-version-shim.py:ro,Z \
        -v "$PWD/$d/oc/opencode.json":/home/agent/.config/opencode/opencode.json:ro,Z \
        localhost/bakeoff-agent bash -c 'cd /work && timeout 60 opencode mcp list 2>&1' \
        | sed 's/\x1b\[[0-9;]*m//g')
  if echo "$out" | grep -q 'connected'; then v=connected
  else v=$(echo "$out" | grep -A2 'failed' | tail -n +2 | head -1 | sed 's/^[ │]*//;s/[[:space:]]*$//')
       v="refused: ${v:-unknown}"; fi
  python3 - "$d" "$v" <<'PY'
import json, sys
p = sys.argv[1] + "/meta.json"
m = json.load(open(p))
m["client_accepted_mcp"] = sys.argv[2]
json.dump(m, open(p, "w"), indent=2)
print(f"{m.get('case',''):18} {sys.argv[2]}")
PY
done
