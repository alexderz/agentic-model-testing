#!/usr/bin/env python3
"""Drive an MCP server over stdio and call every tool it advertises once.

  mcp_exercise.py BINARY [ARGS...]      (environment passed through: HA_URL, HA_TOKEN, ...)

Prints one JSON object: the server's initialize answer, its tool list, and for every tool the
arguments used, whether the call errored, and the first 4000 characters of the result text.
Arguments are built from each tool's inputSchema: required properties get a plausible value for
this fixture (entity_id, domain, service, ...), optional ones are left out. Used to check a server
before test 3 hands it to an agent (suites/test3/KNOWN-GOOD.md); it does not grade.
"""
import json, os, select, subprocess, sys, time

PROTO = os.environ.get("MCP_PROTOCOL", "2026-07-28")
GUESS = {"entity_id": "climate.trane_ac_upstairs", "entity": "climate.trane_ac_upstairs",
         "entity_ids": ["light.studio_studio_1", "person.avery"], "domain": "light",
         "service": "turn_on", "event_type": "state_changed", "integration": "hue",
         "query": "light", "pattern": "light.*", "limit": 5}


def value(name, schema):
    if name in GUESS: return GUESS[name]
    t = schema.get("type")
    if isinstance(t, list): t = next((x for x in t if x != "null"), "string")
    if "enum" in schema: return schema["enum"][0]
    if t == "integer" or t == "number": return 5
    if t == "boolean": return False
    if t == "array": return []
    if t == "object": return {}
    if "time" in name or "start" in name or "end" in name: return "2026-09-30T00:00:00Z"
    return "light"


class Server:
    def __init__(self, argv):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.n = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None: msg["params"] = params
        if not notify:
            self.n += 1; msg["id"] = self.n
        self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        if notify: return None
        end = time.time() + 30
        while time.time() < end:
            r, _, _ = select.select([self.p.stdout], [], [], end - time.time())
            if not r: break
            line = self.p.stdout.readline()
            if not line: break
            try: m = json.loads(line)
            except ValueError: continue
            if m.get("id") == self.n: return m
        return {"error": "no answer within 30 s"}


def main():
    s = Server(sys.argv[1:])
    out = {"initialize": s.send("initialize", {"protocolVersion": PROTO, "capabilities": {},
                                               "clientInfo": {"name": "mcp_exercise", "version": "1"}})}
    s.send("notifications/initialized", notify=True)
    tools, cursor = [], None
    for _ in range(20):
        r = s.send("tools/list", {"cursor": cursor} if cursor else {})
        res = r.get("result") or {}
        tools += res.get("tools") or []
        cursor = res.get("nextCursor")
        if not cursor: break
    out["tools"] = [t.get("name") for t in tools]
    out["calls"] = []
    for t in tools:
        sch = t.get("inputSchema") or {}
        props = sch.get("properties") or {}
        args = {k: value(k, props.get(k) or {}) for k in sch.get("required") or []}
        r = s.send("tools/call", {"name": t["name"], "arguments": args})
        res = r.get("result") or {}
        text = "".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))
        if not text and "structuredContent" in res: text = json.dumps(res["structuredContent"])
        out["calls"].append({"tool": t["name"], "args": args, "rpc_error": r.get("error"),
                             "is_error": bool(res.get("isError")), "text": text[:4000]})
    s.p.terminate()
    print(json.dumps(out))


main()
