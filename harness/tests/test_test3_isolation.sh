#!/usr/bin/env bash
# End-to-end check of test 3's isolation, offline: a real OpenCode 1.18.32 session in the agent image,
# with the config from tools/test3_config.py, mcp-restart-shim.py and a fake MCP server, driven by a
# scripted fake model (tests/fake_llm.py). Runs as evalbox. Every line must be PASS.
#   tests/test_test3_isolation.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
source ./evalbox-lib.sh
T="$HERE/tmp/t3iso"; rm -rf "$T" 2>/dev/null || eb_rm "$T"; mkdir -p "$T/src/target/release" "$T/t3" "$T/opt"
cat > "$T/src/target/release/fakesrv" <<'PY'
#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m: continue
    if m["method"] == "initialize": r = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}
    elif m["method"] == "tools/list": r = {"tools": [{"name": "get_config", "description": "Home Assistant config", "inputSchema": {"type": "object", "properties": {}}}]}
    elif m["method"] == "tools/call": r = {"content": [{"type": "text", "text": "FAKE-CONFIG-ANSWER"}]}
    else: r = {}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
PY
chmod +x "$T/src/target/release/fakesrv"; touch -d '2020-01-01' "$T/src/target/release/fakesrv"
cp mcp-restart-shim.py "$T/opt/shim.py"; cp tests/fake_llm.py "$T/opt/fake_llm.py"
python3 tools/test3_config.py --model m --base-url http://127.0.0.1:9999/v1 --context 100000 --output 8000 \
  --out "$T/opencode.json"
eb_take "$T"
timeout 300 "$PODMAN" run --rm --network none --user root \
  -v "$T/opencode.json":/root/.config/opencode/opencode.json:ro,Z -v "$T/opt":/opt/t3:ro,Z \
  -v "$T/src":/work/mcp-src:Z -v "$T/t3":/t3:Z --entrypoint sh localhost/bakeoff-agent -c '
  python3 /opt/t3/fake_llm.py 9999 /t3/llm.jsonl & sleep 1
  cd /work && HOME=/root timeout 200 opencode run --pure --format json --model titan/m "go" > /t3/events.jsonl 2> /t3/stderr.log
  echo "opencode rc=$?" > /t3/rc' >/dev/null 2>&1
podman unshare cat "$T/t3/rc" 2>/dev/null
python3 - "$T" <<'EOF'
import json, subprocess, sys
T = sys.argv[1]
def rd(name):
    r = subprocess.run([sys.argv[0] if False else "bash", "-c", f'source ./evalbox-lib.sh; podman unshare cat "{T}/t3/{name}"'],
                       capture_output=True, text=True)
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
llm, shim = rd("llm.jsonl"), rd("shim.jsonl")
fails = 0
def check(ok, what):
    global fails
    print(("PASS  " if ok else "FAIL  ") + what); fails += (not ok)
main = [x for x in llm if x["agent"] == "main" and x["tools_offered"]]   # skips the title request
probe = [x for x in llm if x["agent"] == "probe"]
mt = set(main[0]["tools_offered"]) if main else set(); pt = set(probe[0]["tools_offered"]) if probe else set()
check(bool(main) and not any(t.startswith("ha_") for t in mt), f"main agent is not offered any ha_ tool (offered: {sorted(mt)})")
check("task" in mt, "main agent can delegate (task offered)")
r1 = main[1]["tool_results"][0] if len(main) > 1 and main[1]["tool_results"] else ""
check("FAKE-CONFIG-ANSWER" not in r1, f"main agent's direct ha_get_config call gets no MCP data ({r1[:120]!r})")
check(bool(probe), "the task tool started mcp-probe")
check(pt == {"ha_get_config"}, f"mcp-probe is offered only the MCP tools (offered: {sorted(pt)})")
r2 = probe[1]["tool_results"][0] if len(probe) > 1 and probe[1]["tool_results"] else ""
check("uid=" not in r2, f"mcp-probe's bash call does not run ({r2[:120]!r})")
r3 = probe[2]["tool_results"][-1] if len(probe) > 2 and probe[2]["tool_results"] else ""
check("FAKE-CONFIG-ANSWER" in r3, "mcp-probe's ha_get_config call returns the server's answer")
calls = [x for x in shim if x["kind"] == "c2s" and x["msg"].get("method") == "tools/call"]
check(len(calls) == 1, f"the shim log has exactly one tools/call, the probe's ({len(calls)})")
back = [x for x in main[-1]["tool_results"]] if main else []
check(any("probe done" in str(b) for b in back), "the probe's answer comes back to the main agent")
print("ALL PASS" if not fails else f"{fails} FAILED"); sys.exit(1 if fails else 0)
EOF
rc=$?
eb_rm "$T"
exit $rc
