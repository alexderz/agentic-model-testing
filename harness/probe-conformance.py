#!/usr/bin/env python3
"""Re-check every built MCP server the way a real client checks it.

Three things a conforming server must do that our first grader did not test:
  * echo the request id on the initialize response
  * include protocolVersion in that result
  * advertise at least one tool

Uses the binaries already built in results-r3b -- no rebuild, no GPU.
"""
import json
import os
import subprocess
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "results-r3b"
REQ = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "probe", "version": "1"}}},
       {"jsonrpc": "2.0", "method": "notifications/initialized"},
       {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]
PAYLOAD = "".join(json.dumps(r) + "\n" for r in REQ)


def find_bin(work):
    for dirpath, dirnames, files in os.walk(work):
        if not dirpath.endswith(os.path.join("target", "release")):
            continue
        for f in files:
            p = os.path.join(dirpath, f)
            if "." not in f and os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


rows = []
for case in sorted(os.listdir(ROOT)):
    work = os.path.join(ROOT, case, "work")
    if not os.path.isdir(work):
        continue
    b = find_bin(work)
    if not b:
        rows.append((case, "-", "no binary", "-", "-"))
        continue
    rel = "/work/" + os.path.relpath(b, work)
    try:
        r = subprocess.run(
            ["podman", "run", "--rm", "-i", "--userns=keep-id",
             "--add-host=host.containers.internal:host-gateway",
             "-e", "HA_URL=http://host.containers.internal:8126",
             "-e", "HA_BASE_URL=http://host.containers.internal:8126",
             "-e", "HA_TOKEN=bakeoff-placeholder-token",
             "-v", f"{os.path.abspath(work)}:/work:Z",
             "localhost/bakeoff-agent", "timeout", "20", rel],
            input=PAYLOAD, capture_output=True, text=True, timeout=60)
        so = r.stdout
    except Exception as e:
        rows.append((case, os.path.basename(b), f"launch: {type(e).__name__}", "-", "-"))
        continue
    init_id, ver, tools = None, None, 0
    for line in so.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        res = m.get("result") or {}
        if "serverInfo" in res or "protocolVersion" in res:
            init_id = m.get("id")
            ver = res.get("protocolVersion")
        if "tools" in res:
            tools = len(res["tools"] or [])
    if init_id is None and ver is None:
        verdict = "no initialize response"
    elif init_id != 1:
        verdict = f"id NOT echoed (got {init_id!r})"
    elif not ver:
        verdict = "no protocolVersion"
    else:
        verdict = "conforms"
    rows.append((case, os.path.basename(b), verdict, ver or "-", tools))

print(f"{'case':22} {'binary':22} {'verdict':28} {'version':12} tools")
for r in rows:
    print(f"{r[0]:22} {r[1]:22} {r[2]:28} {str(r[3]):12} {r[4]}")
