"""Minimal MCP stdio client over a unix socket, for checking the test 8 browser container by hand.
  python3 mcp_client.py /sock/mcp.sock '<json list of [tool, args]>'
Prints the tool names, then one line per call: tool, isError, text (cut), and the image parts' mime types.
"""
import json
import socket
import sys

s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
f = s.makefile("rwb")
n = 0


def rpc(method, params=None, notify=False):
    global n
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not notify:
        n += 1
        msg["id"] = n
    f.write((json.dumps(msg) + "\n").encode()); f.flush()
    if notify:
        return None
    while True:
        r = json.loads(f.readline())
        if r.get("id") == n:
            return r


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t8check", "version": "1"}})
rpc("notifications/initialized", notify=True)
tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
print("TOOLS", " ".join(sorted(tools)))
for name, args in json.loads(sys.argv[2]):
    r = rpc("tools/call", {"name": name, "arguments": args})
    res = r.get("result") or {}
    text = " | ".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text").replace("\n", " ")
    imgs = [c.get("mimeType") for c in res.get("content", []) if c.get("type") == "image"]
    print("CALL", name, "error" if (res.get("isError") or "error" in r) else "ok", imgs, (text or json.dumps(r.get("error")))[:700])
