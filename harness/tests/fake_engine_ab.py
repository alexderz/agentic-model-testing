#!/usr/bin/env python3
"""A stand-in for titan's llama-swap in tests/test_engine_ab.sh: /v1/chat/completions, streamed, a few tokens a
request; every request appends a Strata-style speed line to <logdir>/<model>.log (for a model named *rotate*, its
load request first replaces the log with a new 8 kB file; for *regrow*, it truncates the same file in place and
writes a short header, so the round's lines end past the old size). A model named *broken* answers 500. Streamed and
past the load request, *cut* ends without a finish_reason or usage and *errsse* sends an error object; *slow* sends
comments and never finishes. A request that is not streamed (tools/maya_digits_probe.py, the probes and load checks
of the A/B steps) gets one read_file call with offset 85 (as "8 5" for a model named *split*) when it offers tools,
else the needle's answer; *stall* sends HTTP 200 and half its body, then stalls; *oomload* (every request) and
*oomprompt* (all but a 4-token load check) answer 500 after adding a torch out-of-memory error to
<logdir>/podman.log, the exllamav3 container's log as tests/fake_ssh_ab.sh serves it ("EPOCH<tab>line").

  python3 tests/fake_engine_ab.py PORT LOGDIR
"""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, LOGDIR = int(sys.argv[1]), sys.argv[2]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        model = body["model"]
        if "broken" in model:
            self.send_response(500); self.end_headers(); self.wfile.write(b"no"); return
        n = min(int(body.get("max_tokens", 16)), 40)
        prompt = sum(len(m.get("content") or "") for m in body["messages"]) // 4
        if not body.get("stream"):    # tools/maya_digits_probe.py: one canned tool call, or the needle's answer
            if "oomload" in model or ("oomprompt" in model and body.get("max_tokens") != 4):
                with open(os.path.join(LOGDIR, "podman.log"), "a") as f:    # at once: in the cursor's own second
                    f.write(f"{time.time():.6f}\ttorch.OutOfMemoryError: CUDA out of memory. Tried to allocate "
                            f"2.00 GiB\n")
                self.send_response(500); self.end_headers(); self.wfile.write(b"out of memory"); return
            if "stall" in model:      # a 200 whose body never completes
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "1000"); self.end_headers()
                try:
                    self.wfile.write(b'{"choices": [{"index": 0, '); self.wfile.flush(); time.sleep(30)
                except BrokenPipeError:
                    pass
                return
            if body.get("tools"):
                args = {"path": "/srv/data/x.log", "offset": "8 5" if "split" in model else 85, "limit": 1}
                msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                       "function": {"name": "read_file", "arguments": json.dumps(args)}}]}
            else:
                msg = {"role": "assistant", "content": "48213-KESTREL"}
            out = json.dumps({"choices": [{"index": 0, "message": msg}],
                              "usage": {"prompt_tokens": prompt, "completion_tokens": 5}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        if "slow" in model:           # keeps sending, never finishes (a total deadline must stop it)
            try:
                for i in range(100000):
                    self.wfile.write(b": ping\n\n"); self.wfile.flush(); time.sleep(0.5)
            except BrokenPipeError:
                return
        for i in range(n):
            ch = {"choices": [{"index": 0, "delta": {"content": f"t{i} "},
                               "finish_reason": "length" if i == n - 1 and not ("cut" in model and n != 8) else None}]}
            self.wfile.write(f"data: {json.dumps(ch)}\n\n".encode()); self.wfile.flush(); time.sleep(0.002)
        if "cut" in model and n != 8:             # the connection ends in the middle of the answer
            return
        if "errsse" in model and n != 8:          # an error object after part of the answer
            self.wfile.write(b'data: {"error": {"type": "server_error", "message": "engine died"}}\n\n'); return
        u = {"choices": [], "usage": {"prompt_tokens": prompt, "completion_tokens": n}}
        self.wfile.write(f"data: {json.dumps(u)}\n\ndata: [DONE]\n\n".encode())
        p = os.path.join(LOGDIR, model + ".log")
        if "rotate" in model and n == 8:   # the load request of a *rotate* model starts a new log file
            with open(p + ".new", "w") as f: f.write("#" * 8000 + "\n")
            os.replace(p + ".new", p)
        if "regrow" in model and n == 8 and os.path.exists(p):   # copytruncate: same inode, then a new start
            with open(p, "r+") as f: f.truncate(0); f.write("# log truncated in place " + "#" * 300 + "\n")
        with open(p, "a") as f:
            f.write(f"strata serve: prompt {prompt} tokens = 0 reused + {prompt} read in {max(1, prompt // 50)} ms "
                    f"(50.0 tok/s), {n} generated in {n * 40} ms (25.0 tok/s), drafts accepted {n} of {2 * n}, "
                    f"0 checkpoints\n")


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
