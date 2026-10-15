#!/usr/bin/env python3
"""A scripted, streaming OpenAI-compatible chat endpoint for the offline test 8 check (tests/test_test8.sh).

  fake_llm.py PORT LOG        (LOG gets one JSON line per request: agent, offered tools, step, tool results, images)

It decides by the user messages whether it serves the main agent or the `general` sub-agent started through the task
tool (whose prompt carries T8-SUBAGENT-PROBE), and by how many tool results the conversation already holds:
  main: bash (Internet, DNS, the LAN; writes page.html and notes.txt; the preview from the shell, its port taken,
        the SVG view and fit) -> navigate page.html -> evaluate -> screenshot
        -> navigate notes.txt -> navigate example.com -> run_code_unsafe (must be refused) -> navigate file:// -> task
        -> "done"
  sub:  evaluate location.href (shows whether it shares the main agent's browser) -> navigate page.html -> evaluate
        -> "sub done"
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, LOG = int(sys.argv[1]), sys.argv[2]
B = "browser_browser_"
PAGE = "http://127.0.0.1:8000/page.html"
BASH = ("cp /opt/t8fake/sample-page.html /work/page.html; echo private > /work/notes.txt; "
        "curl -sS -m 8 -o /dev/null https://example.com/ && echo NET-LEAK-PUBLIC || echo NET-BLOCKED-PUBLIC; "
        "curl -sS -m 8 -o /dev/null http://1.1.1.1/ && echo NET-LEAK-IP || echo NET-BLOCKED-IP; "
        "getent hosts example.com && echo NET-LEAK-DNS || echo NET-BLOCKED-DNS; "
        "curl -sS -m 8 -o /dev/null http://192.0.2.10/ && echo NET-LEAK-LAN || echo NET-BLOCKED-LAN; "
        "ls -l /sock; "
        "curl -sS -m 8 http://127.0.0.1:8000/page.html | grep -q __t8 && echo PREVIEW-SHELL-OK || echo PREVIEW-SHELL-FAIL; "
        "(timeout 5 python3 -m http.server 8000 2>&1 | grep -q 'Address already in use') && echo PORT-TAKEN || echo PORT-FREE; "
        "printf '<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\"></svg>' > /work/t.svg; "
        "curl -sS -m 8 http://127.0.0.1:8000/view/t.svg | grep -q 'sandbox=\"allow-same-origin\" src=\"/fit/t.svg\"' "
        "&& echo SVG-VIEW-FRAME || echo SVG-VIEW-OLD; "
        "curl -sS -m 8 http://127.0.0.1:8000/fit/t.svg | grep -q 'width=\"100%\"' && echo SVG-FIT-OK || echo SVG-FIT-FAIL")
MAIN = [("bash", {"command": BASH, "description": "set up and probe the network"}),
        (B + "navigate", {"url": PAGE}),
        (B + "evaluate", {"function": "() => window.__t8"}),
        (B + "take_screenshot", {}),
        (B + "navigate", {"url": "http://127.0.0.1:8000/notes.txt"}),
        (B + "navigate", {"url": "https://example.com/"}),
        (B + "run_code_unsafe", {"code": "async (page) => require('fs').readdirSync('/')"}),
        (B + "navigate", {"url": "file:///opt/t8/playwright-mcp.json"}),
        ("task", {"description": "check the page", "subagent_type": "general",
                  "prompt": "T8-SUBAGENT-PROBE: open the page in the browser and report window.__t8."}),
        None]
SUB = [(B + "evaluate", {"function": "() => 'T8-AT ' + location.href"}),   # a shared browser is not at about:blank
       (B + "navigate", {"url": PAGE}), (B + "evaluate", {"function": "() => window.__t8"}), None]


def text(c):
    return c if isinstance(c, str) else json.dumps(c)


def plan(req):
    msgs = req.get("messages") or []
    sub = any("T8-SUBAGENT-PROBE" in text(m.get("content")) for m in msgs if m.get("role") == "user")
    done = sum(1 for m in msgs if m.get("role") == "tool")
    steps = SUB if sub else MAIN
    return ("sub" if sub else "main"), (steps[done] if done < len(steps) else None)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "m", "object": "model"}]}).encode())

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        req = json.loads(raw)
        tools = [t.get("function", {}).get("name") for t in req.get("tools") or []]
        who, step = plan(req) if tools else ("title", None)
        results = [text(m.get("content")) for m in req.get("messages") or [] if m.get("role") == "tool"]
        with open(LOG, "a") as f:
            f.write(json.dumps({"agent": who, "tools_offered": sorted(tools), "step": step and step[0],
                                "tool_results": [r[:600] for r in results],
                                "images": raw.count(b"data:image/")}) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def chunk(delta, finish=None):
            c = {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": "m",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
            self.wfile.flush()
        if step is None:
            chunk({"role": "assistant", "content": {"sub": "sub done", "main": "done"}.get(who, "t8 title")})
            chunk({}, "stop")
        else:
            name, args = step
            chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}", "type": "function",
                                                        "function": {"name": name, "arguments": json.dumps(args)}}]})
            chunk({}, "tool_calls")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
