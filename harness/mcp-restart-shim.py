#!/usr/bin/env python3
"""A stable MCP stdio endpoint in front of a server binary that an agent may rebuild (test 3).

  mcp-restart-shim.py --find DIR [-- ARGS...]     run the newest executable in DIR (target/release)
  mcp-restart-shim.py BINARY [ARGS...]            run this binary
  --args-from-help (first option)                 launch flags from the binary's --help, as test 2's
                                                  grader does: --ha-url/--ha-token, --url/--token,
                                                  `stdio`; values from $HA_URL and $HA_TOKEN

OpenCode starts an MCP server once per session. In test 3 the agent may fix and rebuild the server,
and the fix has to reach its subagent. So before forwarding each client message the shim checks the
binary (path, inode, mtime, size, stable for 1 s). When it changed, the shim stops the old process,
starts the new one, replays the client's initialize and notifications/initialized, and sends the
client notifications/tools/list_changed. It always advertises tools.listChanged so the client listens.

When no runnable binary exists (a server that does not build), the shim answers initialize itself with
no tools, tools/list with an empty list, and tools/call with an error saying the server is not built.
The session keeps its MCP connection, and a build made later is picked up on the next request.

Like mcp-version-shim.py, it rewrites protocolVersion in initialize answers to the version the client
asked for (OpenCode 1.18 asks for 2025-11-25; the servers implement the spec they were given), and logs
what the server really said.

Every message both ways, and every start, stop and restart, is one JSON line in $SHIM_LOG
(default /dev/null), so grading can count the MCP calls the probe made.
"""
import json, os, subprocess, sys, threading, time

LOG = open(os.environ.get("SHIM_LOG", "/dev/null"), "a", buffering=1)
OUT_LOCK = threading.Lock()


def log(kind, **kw):
    kw.update(t=round(time.time(), 3), kind=kind)
    s = json.dumps(kw)
    if len(s) > 40000:                                   # keep the log line valid JSON
        kw["msg"] = {"truncated": s[:2000]}; s = json.dumps(kw)
    LOG.write(s + "\n")


def to_client(msg):
    line = json.dumps(msg)
    with OUT_LOCK:
        sys.stdout.write(line + "\n"); sys.stdout.flush()
    log("s2c", msg=msg)


def parse_args(a):
    if a[:1] == ["--find"]:
        d = a[1]; rest = a[3:] if a[2:3] == ["--"] else a[2:]
        return d, None, rest
    return None, a[0], a[1:]


_argv = sys.argv[1:]
FROM_HELP = _argv[:1] == ["--args-from-help"]
FIND_DIR, FIXED, ARGS = parse_args(_argv[1:] if FROM_HELP else _argv)


def launch_args(path):
    """grade-mcp.py's arg_variants: the first variant the server's own --help asks for."""
    if not FROM_HELP: return ARGS
    url = os.environ.get("HA_URL", "http://host.containers.internal:8126")
    tok = os.environ.get("HA_TOKEN", "bakeoff-placeholder-token")
    try:
        r = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        h = (r.stdout or "") + (r.stderr or "")
    except Exception:
        h = ""
    if "--ha-url" in h: return ["--ha-url", url] + (["--ha-token", tok] if "--ha-token" in h else [])
    if "--url" in h: return ["--url", url] + (["--token", tok] if "--token" in h else [])
    if "stdio" in h.lower(): return ["stdio"]
    return ARGS


def candidate():
    """(path, identity) of the binary to run now, or (None, None)."""
    if FIXED:
        paths = [FIXED] if os.path.isfile(FIXED) and os.access(FIXED, os.X_OK) else []
    else:
        try: names = os.listdir(FIND_DIR)
        except OSError: names = []
        paths = [os.path.join(FIND_DIR, n) for n in names]
        paths = [p for p in paths if os.path.isfile(p) and os.access(p, os.X_OK) and "." not in os.path.basename(p)]
    if not paths: return None, None
    p = max(paths, key=lambda x: os.stat(x).st_mtime_ns)
    st = os.stat(p)
    if time.time() - st.st_mtime < 1.0:          # still being written by the linker
        return None, "settling"
    return p, (p, st.st_ino, st.st_mtime_ns, st.st_size)


class Backend:
    def __init__(self):
        self.proc = None; self.ident = None; self.pending = {}
        self.init_req = None; self.init_note = None; self.client_version = None
        self.waiters = {}
        self.client_ready = False      # the client has had an initialize answer (from a server or the shim)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, why):
        if self.proc is not None:
            log("stop", why=why, pid=self.proc.pid, rc=self.proc.poll())
            try: self.proc.terminate(); self.proc.wait(5)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
        self.proc = None

    def start(self, path, ident):
        args = launch_args(path)
        self.proc = subprocess.Popen([path] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.ident = ident
        log("start", path=path, args=args, pid=self.proc.pid, ident=list(ident))
        threading.Thread(target=self.pump, args=(self.proc,), daemon=True).start()

    def write(self, msg):
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n"); self.proc.stdin.flush(); return True
        except Exception as e:
            log("write_failed", error=str(e)); return False

    def pump(self, proc):
        for line in proc.stdout:
            try: msg = json.loads(line)
            except ValueError:
                log("server_noise", line=line[:500]); continue
            mid = msg.get("id")
            if mid in self.waiters:                      # answer to a request the shim made itself
                self.waiters.pop(mid).append(msg); log("s2shim", msg=msg); continue
            if isinstance(msg.get("result"), dict) and mid is not None and mid == self.pending.get("init"):
                msg = fix_init(msg, self.client_version)
            to_client(msg)
        log("server_eof", pid=proc.pid, rc=proc.poll())

    def replay_init(self):
        """Hand the new process the handshake the client did with the old one."""
        if not self.init_req: return
        rid = f"shim-init-{time.time_ns()}"
        box = []; self.waiters[rid] = box
        self.write(dict(self.init_req, id=rid))
        end = time.time() + 20
        while not box and time.time() < end and self.alive(): time.sleep(0.05)
        self.waiters.pop(rid, None)
        log("replayed_initialize", answered=bool(box))
        if self.init_note: self.write(self.init_note)


def fix_init(msg, want):
    res = msg["result"]
    got = res.get("protocolVersion")
    if want and got != want:
        log("protocol_version", server=got, client=want); res["protocolVersion"] = want
    caps = res.setdefault("capabilities", {})
    tools = caps.setdefault("tools", {})
    if isinstance(tools, dict): tools["listChanged"] = True
    return msg


B = Backend()


def ensure_backend(current):
    """Start or restart the server if the binary appeared or changed. True if one is running.

    `current` is the client message about to be forwarded. If it is the initialize itself, the new
    process gets it directly; otherwise the stored handshake is replayed first, and the client, which
    already has an initialize answer, is told the tool list changed."""
    path, ident = candidate()
    if path is None:
        return B.alive()
    if B.alive() and ident == B.ident:
        return True
    B.stop("binary changed" if B.alive() else "not running")
    B.start(path, ident)
    if current.get("method") != "initialize" and B.init_req:
        B.replay_init()
        if B.client_ready:
            to_client({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
    return B.alive()


def answer_without_server(msg):
    m, mid = msg.get("method"), msg.get("id")
    if mid is None: return
    if m == "initialize":
        to_client({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": B.client_version or "2025-11-25",
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "mcp-restart-shim (no server binary yet)", "version": "0"}}})
    elif m == "tools/list":
        to_client({"jsonrpc": "2.0", "id": mid, "result": {"tools": []}})
    elif m == "ping":
        to_client({"jsonrpc": "2.0", "id": mid, "result": {}})
    else:
        to_client({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603,
                   "message": "MCP server is not running: no runnable binary has been built"}})


def main():
    log("shim_up", find=FIND_DIR, binary=FIXED, args=ARGS)
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: msg = json.loads(line)
        except ValueError:
            log("client_noise", line=line[:500]); continue
        log("c2s", msg=msg)
        if msg.get("method") == "initialize":
            B.init_req = msg; B.client_version = (msg.get("params") or {}).get("protocolVersion")
            B.pending["init"] = msg.get("id")
        elif msg.get("method") == "notifications/initialized":
            B.init_note = msg
        if not ensure_backend(msg):
            answer_without_server(msg)
        elif not B.write(msg):
            B.stop("write failed")
            if ensure_backend(msg): B.write(msg)
            else: answer_without_server(msg)
        if msg.get("method") == "initialize": B.client_ready = True
    B.stop("client closed")
    log("shim_down")


main()
