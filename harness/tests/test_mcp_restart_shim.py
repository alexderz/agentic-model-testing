#!/usr/bin/env python3
"""Offline test of mcp-restart-shim.py with a scripted client and two builds of a tiny server.

  python3 tests/test_mcp_restart_shim.py        (prints PASS/FAIL lines, exits non-zero on a failure)
"""
import json, os, select, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(HERE, "mcp-restart-shim.py")
SERVER = '''#!/usr/bin/env python3
import json, sys
TOOLS = %r
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m: continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2026-07-28", "capabilities": {"tools": {}}, "serverInfo": {"name": "v%d"}}
    elif m["method"] == "tools/list":
        r = {"tools": [{"name": t, "inputSchema": {"type": "object"}} for t in TOOLS]}
    elif m["method"] == "tools/call":
        r = {"content": [{"type": "text", "text": "v%d answered " + m["params"]["name"]}]}
    else:
        r = {}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
'''
fails = 0


def check(cond, what):
    global fails
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond: fails += 1


def build(path, version, tools):
    tmp = path + ".new"
    open(tmp, "w").write(SERVER % (tools, version, version))
    os.chmod(tmp, 0o755)
    old = time.time() - 5
    os.utime(tmp, (old, old))                     # older than the shim's 1 s settling window
    os.replace(tmp, path)                         # new inode, like a linker writing a fresh file


class Client:
    def __init__(self, argv, log):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                  bufsize=1, env=dict(os.environ, SHIM_LOG=log))
        self.n = 0; self.notes = []

    def call(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                       "params": params or {}}) + "\n"); self.p.stdin.flush()
        end = time.time() + 15
        while time.time() < end:
            r, _, _ = select.select([self.p.stdout], [], [], end - time.time())
            if not r: break
            m = json.loads(self.p.stdout.readline())
            if m.get("id") == self.n: return m
            self.notes.append(m.get("method"))
        return {}

    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n"); self.p.stdin.flush()


def init(c):
    r = c.call("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t"}})
    c.notify("notifications/initialized")
    return r


with tempfile.TemporaryDirectory() as d:
    rel = os.path.join(d, "target", "release"); os.makedirs(rel)
    log = os.path.join(d, "shim.jsonl")
    c = Client([sys.executable, SHIM, "--find", rel], log)

    r = init(c)
    check(r.get("result", {}).get("capabilities", {}).get("tools", {}).get("listChanged") is True
          and "no server binary" in r["result"]["serverInfo"]["name"],
          "no binary yet: the shim answers initialize itself and advertises listChanged")
    check(c.call("tools/list").get("result", {}).get("tools") == [], "no binary yet: tools/list is empty")
    check("not running" in json.dumps(c.call("tools/call", {"name": "a"}).get("error", {})),
          "no binary yet: tools/call returns an error")

    build(os.path.join(rel, "srv"), 1, ["a"])
    r = c.call("tools/list")
    check([t["name"] for t in r.get("result", {}).get("tools", [])] == ["a"], "build 1 appears: its tools are listed")
    check("notifications/tools/list_changed" in c.notes, "build 1 appears: the client is told the tool list changed")
    check("v1 answered a" in json.dumps(c.call("tools/call", {"name": "a"})), "build 1 answers a tool call")

    c.notes.clear()
    build(os.path.join(rel, "srv"), 2, ["a", "b"])
    r = c.call("tools/list")
    check([t["name"] for t in r.get("result", {}).get("tools", [])] == ["a", "b"], "rebuild: the new tools are listed")
    check("notifications/tools/list_changed" in c.notes, "rebuild: the client is told the tool list changed")
    check("v2 answered b" in json.dumps(c.call("tools/call", {"name": "b"})), "rebuild: the new build answers")
    c.p.stdin.close(); c.p.wait(10)

    L = [json.loads(l) for l in open(log)]
    kinds = [x["kind"] for x in L]
    calls = [x for x in L if x["kind"] == "c2s" and x["msg"].get("method") == "tools/call"]
    check(kinds.count("start") == 2 and kinds.count("replayed_initialize") == 2,
          "log: two starts, each with the handshake replayed")
    check(len(calls) == 3, "log: every tools/call from the client is recorded (3)")

    # binary present from the start: the server answers initialize, version rewritten, listChanged set
    log2 = os.path.join(d, "shim2.jsonl")
    c2 = Client([sys.executable, SHIM, os.path.join(rel, "srv")], log2)
    r = init(c2)
    res = r.get("result", {})
    check(res.get("protocolVersion") == "2025-11-25" and res.get("serverInfo", {}).get("name") == "v2"
          and res.get("capabilities", {}).get("tools", {}).get("listChanged") is True,
          "binary present: the server answers initialize; version rewritten to the client's, listChanged set")
    c2.p.stdin.close(); c2.p.wait(10)
    check(any(x["kind"] == "protocol_version" and x["server"] == "2026-07-28" for x in map(json.loads, open(log2))),
          "log: the server's real protocol version is recorded")

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
