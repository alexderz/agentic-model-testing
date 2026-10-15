"""Helpers for the test 4 hidden acceptance checks. Runs inside the grading container only.

Black box: the checks start the built server binary, speak MCP to it over stdio, and point it
either at the Home Assistant replay ($HA_URL) or at a small fake Home Assistant in this process.
Nothing here depends on how the server is written inside. Standard library only.
"""
import http.server
import json
import os
import select
import socket
import subprocess
import threading
import time
import urllib.request

PROTO = "2026-07-28"
REPLAY_URL = os.environ.get("HA_URL", "http://host.containers.internal:8127")
REPLAY_TOKEN = os.environ.get("HA_TOKEN", "bakeoff-placeholder-token")
FAKE_TOKEN = "placeholder-fake-token"
BINARY = None          # set by run_hidden.py
TREE = None            # the graded source tree, set by run_hidden.py
# variables a check may set; removed from the inherited environment so each check starts clean
KNOBS = ["HA_URL", "HA_BASE_URL", "HA_TOKEN", "HA_LONG_LIVED_ACCESS_TOKEN", "HA_MCP_TIMEOUT_SECS",
         "HA_MCP_CONNECT_TIMEOUT_SECS", "HA_MCP_RETRIES", "HA_MCP_RETRY_DELAY_MS", "HA_MCP_LOG_LEVEL",
         "HA_MCP_MAX_RESPONSE_BYTES", "HA_MCP_TLS_NO_VERIFY", "HA_MCP_STRICT_META", "HA_MCP_TOOL_PAGE_SIZE"]


class CheckFailed(Exception):
    pass


def check(cond, message):
    if not cond:
        raise CheckFailed(message)


def server_env(url, token, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in KNOBS}
    env.update({"HA_URL": url, "HA_TOKEN": token})
    env.update(extra or {})
    return env


class Mcp:
    """The server under test, driven over stdio."""

    def __init__(self, url=None, token=None, env=None, handshake=True):
        url = REPLAY_URL if url is None else url
        token = (REPLAY_TOKEN if url == REPLAY_URL else FAKE_TOKEN) if token is None else token
        self.p = subprocess.Popen([BINARY], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                  env=server_env(url, token, env))
        self.n = 0
        if handshake:
            r = self.send("initialize", {"protocolVersion": PROTO, "capabilities": {},
                                         "clientInfo": {"name": "t4-hidden", "version": "1"}})
            check("result" in r, f"initialize failed: {json.dumps(r)[:200]}")
            self.send("notifications/initialized", notify=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.p.kill()

    def send(self, method, params=None, notify=False, timeout=60):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        try:
            self.p.stdin.write(json.dumps(msg) + "\n")
            self.p.stdin.flush()
        except OSError as e:
            raise CheckFailed(f"the server is not reading its input ({e}); exit code {self.p.poll()}")
        if notify:
            return None
        end = time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([self.p.stdout], [], [], max(0, end - time.time()))
            if not ready:
                break
            line = self.p.stdout.readline()
            if not line:
                raise CheckFailed(f"the server closed its output while answering {method}; exit code {self.p.poll()}")
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get("id") == self.n:
                return m
        raise CheckFailed(f"no answer to {method} within {timeout} s")

    def tools(self):
        out, cursor = [], None
        for _ in range(20):
            r = self.send("tools/list", {"cursor": cursor} if cursor else {})
            res = r.get("result") or {}
            out += res.get("tools") or []
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return out

    def call_raw(self, tool, args=None, timeout=60):
        return self.send("tools/call", {"name": tool, "arguments": args or {}}, timeout=timeout)

    def call(self, tool, args=None, timeout=60):
        """structuredContent of a successful call; a tool error or protocol error fails the check."""
        r = self.call_raw(tool, args, timeout)
        check("result" in r, f"{tool}({json.dumps(args or {})}) was refused: {json.dumps(r.get('error'))[:300]}")
        res = r["result"]
        check(not res.get("isError"), f"{tool}({json.dumps(args or {})}) returned an error: {result_text(res)[:300]}")
        sc = res.get("structuredContent")
        if sc is None:
            try:
                sc = json.loads(result_text(res))
            except ValueError:
                raise CheckFailed(f"{tool}: the result has neither structuredContent nor JSON text")
        return sc

    def call_fails(self, tool, args=None, timeout=60):
        """True when the call is refused, either as a tool error or as a JSON-RPC error."""
        r = self.call_raw(tool, args, timeout)
        return "error" in r or bool((r.get("result") or {}).get("isError"))

    def call_all(self, tool, args, key, limit):
        """Every item of a paged list tool, following next_cursor."""
        items, cursor, first = [], "", None
        for _ in range(200):
            page = self.call(tool, dict(args, limit=limit, cursor=cursor))
            first = first or page
            items += page.get(key) or []
            cursor = page.get("next_cursor")
            if not cursor:
                return items, first
        raise CheckFailed(f"{tool}: paging did not end after 200 pages")


def result_text(res):
    return "".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))


def error_kind(raw):
    return ((raw.get("result") or {}).get("_meta") or {}).get("errorKind")


def run_to_exit(env, url="http://127.0.0.1:9", token=FAKE_TOKEN, timeout=20):
    """Start the server with its input already closed. Returns (exit code, stderr text)."""
    try:
        p = subprocess.run([BINARY], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=timeout, env=server_env(url, token, env))
    except subprocess.TimeoutExpired:
        raise CheckFailed(f"the server did not exit within {timeout} s of its input closing")
    return p.returncode, p.stderr


def replay_json(path):
    req = urllib.request.Request(REPLAY_URL + path, headers={"Authorization": "Bearer " + REPLAY_TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def closed_port():
    """A loopback port nothing listens on."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeHA:
    """A scripted Home Assistant on loopback.

    routes: path -> list of steps, or one step used for every request. A step is
    (status, body) or (status, body, delay_seconds); body may be a JSON-serialisable value or text.
    A list is consumed one step per request and its last step repeats. Paths without a route get 404.
    Every request is recorded in .requests (path without the query string).
    """

    def __init__(self, routes):
        self.routes = {k: (list(v) if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.requests = []
        self.lock = threading.Lock()
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                with fake.lock:
                    fake.requests.append(path)
                    steps = fake.routes.get(path)
                    step = (404, {"message": "not found"}) if not steps else (steps.pop(0) if len(steps) > 1 else steps[0])
                status, body = step[0], step[1]
                if len(step) > 2:
                    time.sleep(step[2])
                if self.headers.get("Authorization") != "Bearer " + FAKE_TOKEN:
                    status, body = 401, {"message": "bad token"}
                data = (body if isinstance(body, str) else json.dumps(body)).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain" if isinstance(body, str) else "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass                      # the client gave up (a timeout check)
                self.close_connection = True

        class S(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass

        self.httpd = S(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def count(self, path):
        with self.lock:
            return self.requests.count(path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


CONFIG = {"location_name": "Fake Home", "version": "2026.9.1", "time_zone": "UTC", "components": ["light", "lock"],
          "unit_system": {"temperature": "°C"}, "state": "RUNNING"}
