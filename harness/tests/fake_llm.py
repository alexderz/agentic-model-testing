#!/usr/bin/env python3
"""A scripted, streaming OpenAI-compatible chat endpoint for testing OpenCode configs offline.

  fake_llm.py PORT LOG        (LOG gets one JSON line per request: agent, offered tools, tool results)

It plays a fixed test-3 script, deciding by the system prompt whether it is serving the main agent or
the `mcp-probe` subagent (whose prompt starts "You are mcp-probe"), and by how many tool results the
conversation already holds:
  main:  1) call ha_get_config directly (must be refused)  2) call task -> mcp-probe  3) answer "done"
  probe: 1) call bash (must not exist / be refused)  2) call ha_get_config  3) answer "probe done"
"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, LOG = int(sys.argv[1]), sys.argv[2]


def plan(req):
    msgs = req.get("messages") or []
    system = " ".join(m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
                      for m in msgs if m.get("role") == "system")
    probe = "You are mcp-probe" in system
    done = sum(1 for m in msgs if m.get("role") == "tool")
    if probe:
        steps = [("bash", {"command": "id", "description": "who am I"}), ("ha_get_config", {}), None]
    else:
        steps = [("ha_get_config", {}),
                 ("task", {"description": "read config", "prompt": "Use your tools to get the Home Assistant config.",
                           "subagent_type": "mcp-probe"}),
                 None]
    return ("probe" if probe else "main"), (steps[done] if done < len(steps) else None)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "m", "object": "model"}]}).encode())

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        who, step = plan(req)
        tools = [t.get("function", {}).get("name") for t in req.get("tools") or []]
        results = [m.get("content") for m in req.get("messages") or [] if m.get("role") == "tool"]
        with open(LOG, "a") as f:
            f.write(json.dumps({"agent": who, "tools_offered": sorted(tools), "step": step and step[0],
                                "tool_results": [str(r)[:300] for r in results]}) + "\n")
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()

        def chunk(delta, finish=None):
            c = {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": "m",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n"); self.wfile.flush()
        if step is None:
            chunk({"role": "assistant", "content": "probe done" if who == "probe" else "done"})
            chunk({}, "stop")
        else:
            name, args = step
            chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}", "type": "function",
                                                        "function": {"name": name, "arguments": json.dumps(args)}}]})
            chunk({}, "tool_calls")
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
