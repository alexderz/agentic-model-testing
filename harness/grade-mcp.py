#!/usr/bin/env python3
"""Grade a generated Rust MCP server by BUILDING and SPEAKING to it.

Runs inside the grading container. Records executed facts only:

  builds        cargo build --release exits 0
  binary        a runnable artifact exists in target/release
  initialize    the server answers the MCP initialize handshake
  tools_list    how many tools it advertises
  tools_call    a call succeeds and returns data traceable to the fixture
  cargo_test    the model's own tests pass

A server that does not build, or does not answer initialize, is
non-functional. That is the headline for that model -- everything else about
the code is moot if an agent cannot talk to it.

The server is driven the way an MCP client drives it: one process, stdin kept
open, one request at a time, each reply awaited with its own timeout. (Until
2026-10-10 every request was piped at once and stdin closed, and stdout was
thrown away when the process did not exit: a server that answered but kept
running, or answered from spawned tasks after stdin closed, scored "no
response".)

Output: one JSON object per finished phase on stdout; the LAST line is the
result. `phase` names the step that was running, so a run killed on the
container's time limit still reports what it had established.
"""
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time

APP = os.environ.get("GRADE_ROOT", "/app")
TIMEOUT_BUILD = int(os.environ.get("BUILD_TIMEOUT", "1800"))
TIMEOUT_RPC = 30
MAX_CALLS = 6
T0 = time.time()
# seconds this whole script may take; the grade script sets it below the container's limit
DEADLINE = T0 + int(os.environ.get("GRADE_DEADLINE", "2300"))


def find_manifest():
    for root, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in ("target", ".git", "node_modules")]
        if "Cargo.toml" in files:
            # prefer a manifest that actually declares a binary
            txt = open(os.path.join(root, "Cargo.toml"), encoding="utf-8",
                       errors="replace").read()
            if "[package]" in txt:
                return root
            # A manifest that exists but is not a Cargo manifest is a real
            # failure, and a different one from "wrote nothing". One model
            # opened with [project] -- pyproject.toml's convention -- which
            # cargo rejects outright. Say which it was.
            globals()["_BAD_MANIFEST"] = (
                os.path.relpath(os.path.join(root, "Cargo.toml"), APP)
                + ": no [package] section (first section: "
                + (next((l.strip() for l in txt.splitlines()
                         if l.strip().startswith("[")), "none")) + ")")
    return None


def sh(args, cwd, timeout, stdin=None, env=None):
    """Run to completion. On timeout: rc -9, and the output so far is KEPT.

    The whole process group is killed. subprocess.run() kills only the direct
    child and then waits for the pipes, which a surviving grandchild (rustc, a
    test binary, the server itself) holds open: that wait is what turned one
    slow step into a silent kill by the container's time limit.
    """
    try:
        p = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                             text=True, errors="replace", start_new_session=True, env=env)
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"
    try:
        so, se = p.communicate(input=stdin, timeout=timeout)
        return p.returncode, (so or ""), (se or "")
    except subprocess.TimeoutExpired:
        try: os.killpg(p.pid, signal.SIGKILL)
        except OSError: pass
        try: so, se = p.communicate(timeout=15)
        except Exception: so, se = "", ""
        return -9, (so or ""), (se or "") + "\nTIMEOUT"
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"


def arg_variants(binary, cwd):
    """How to launch it.

    An MCP client passes connection args from its config, so running the binary
    bare and recording "does not answer initialize" under-grades a server that
    simply wanted --ha-url. Read its own --help and supply what it asks for.
    """
    url = os.environ.get("HA_URL", "http://host.containers.internal:8127")
    tok = os.environ.get("HA_TOKEN", "bakeoff-placeholder-token")
    rc, so, se = sh([binary, "--help"], cwd, 20)
    help_txt = (so + se)
    variants = []
    if "--ha-url" in help_txt:
        v = [binary, "--ha-url", url]
        if "--ha-token" in help_txt:
            v += ["--ha-token", tok]
        variants.append(v)
    if "--url" in help_txt:
        v = [binary, "--url", url]
        if "--token" in help_txt:
            v += ["--token", tok]
        variants.append(v)
    if "stdio" in help_txt.lower():
        variants.append([binary, "stdio"])
    variants.append([binary])          # bare, last
    return variants


# ---------------------------------------------------------------- grading replay only
def start_redirect():
    """Make every route case code knows to Home Assistant end at the GRADING replay.

    The prompt gave the agent http://host.containers.internal:8126, and that is
    the live replay: its access log is the evidence for whichever case is
    running. Setting HA_URL to :8127 is not enough -- a CLI, server or test with
    the :8126 address hard-coded ignores it and writes its requests into the
    live case's log (61 such requests on 2026-10-10 before this existed).

    The grade script therefore points host.containers.internal at 127.0.0.1
    inside the container and passes the real replay as GRADE_REPLAY. This
    relays 127.0.0.1:8126 and :8127 to it, so both addresses work and neither
    can reach the live replay. Returns True when active, False when not asked
    for (GRADE_REPLAY unset: the old behaviour). Raises if asked for and not
    possible: grading must then stop before any case code runs.
    """
    target = os.environ.get("GRADE_REPLAY")
    if not target:
        return False
    import socket, threading
    for name in ("host.containers.internal", "host.docker.internal"):
        got = socket.gethostbyname(name)
        if got != "127.0.0.1":
            raise RuntimeError(f"{name} resolves to {got}, not 127.0.0.1: case code could reach the live replay")
    host, port = target.rsplit(":", 1)
    addr = (socket.gethostbyname(host), int(port))
    socket.create_connection(addr, timeout=10).close()      # the grading replay must be up

    def pump(a, b):
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        try: b.shutdown(socket.SHUT_WR)
        except OSError: pass

    def relay(c):
        try:
            u = socket.create_connection(addr, timeout=10)
            u.settimeout(None)
        except OSError:
            c.close(); return
        t = threading.Thread(target=pump, args=(u, c), daemon=True)
        t.start()
        pump(c, u)
        t.join()
        c.close(); u.close()

    def serve(ls):
        while True:
            try:
                c, _ = ls.accept()
            except OSError:
                return
            threading.Thread(target=relay, args=(c,), daemon=True).start()

    for lp in (8126, 8127):
        ls = socket.socket()
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("127.0.0.1", lp))
        ls.listen(64)
        threading.Thread(target=serve, args=(ls,), daemon=True).start()
    return True


# What the agent's own environment said while it wrote and ran its tests (run-case-sandboxed.sh).
# With the relay active this address is the grading replay too, so the model's tests can run
# against the same values they were written for.
AGENT_HA_URL = "http://host.containers.internal:8126"


# ---------------------------------------------------------------- fixture evidence
FX = {"ids": set(), "stamps": set(), "config": [], "svc_domains": set(), "svc_names": set(),
      "events": set(), "real": None, "source": None}
ID_RE = re.compile(r"(?<![\w.])([a-z_]+\.[a-z0-9_]+)(?![\w])")
STAMP_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3,}")


def load_fixture():
    """What the recorded Home Assistant actually contains, to recognise real data in a reply.

    From the fixture file the grade script mounts; failing that, from the
    grading replay (the same recording).
    """
    bodies = {}
    try:
        fx = json.load(open(os.environ.get("HA_FIXTURE", "/fixture.json")))
        for path in ("/api/states", "/api/config", "/api/services", "/api/events"):
            bodies[path] = fx["responses"][path]["body"]
        for path, rec in fx["responses"].items():
            if "history" in path or "logbook" in path:
                bodies[path] = rec["body"]
        FX["source"] = "fixture file"
    except Exception:
        try:
            import urllib.request
            base = os.environ.get("HA_URL", "http://host.containers.internal:8127").rstrip("/")
            tok = os.environ.get("HA_TOKEN", "bakeoff-placeholder-token")
            for path in ("/api/states", "/api/config", "/api/services", "/api/events"):
                rq = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {tok}"})
                bodies[path] = urllib.request.urlopen(rq, timeout=20).read().decode("utf-8", "replace")
            FX["source"] = "grading replay"
        except Exception:
            return
    def js(path, default):
        try: return json.loads(bodies[path])
        except Exception: return default
    for s in js("/api/states", []):
        eid = s.get("entity_id") or ""
        if "." in eid:
            FX["ids"].add(eid)
    # timestamps with fractional seconds are unique to this recording
    for b in bodies.values():
        FX["stamps"].update(STAMP_RE.findall(b))
    cfg = js("/api/config", {})
    for k in ("version", "time_zone", "external_url", "internal_url", "latitude", "longitude"):
        v = cfg.get(k)
        if v not in (None, "", 0):
            FX["config"].append(str(v))
    for d in js("/api/services", []):
        if isinstance(d, dict) and d.get("domain"):
            FX["svc_domains"].add(d["domain"])
            FX["svc_names"].update((d.get("services") or {}).keys())
    for e in js("/api/events", []):
        if isinstance(e, dict) and e.get("event"):
            FX["events"].add(e["event"])
    lights = sorted(e for e in FX["ids"] if e.startswith("light.") and len(e) > 14)
    FX["real"] = (lights or sorted(FX["ids"]) or [None])[0]


def _leaves(x, out):
    if isinstance(x, str):
        out.append(x)
    elif isinstance(x, dict):
        for k, v in x.items():
            out.append(str(k)); _leaves(v, out)
    elif isinstance(x, list):
        for v in x:
            _leaves(v, out)
    elif x is not None:
        out.append(json.dumps(x))


def fixture_evidence(result, sent=""):
    """Why a tools/call result is real data from the recording, or None.

    `sent` is what the grader itself put in the arguments: an entity id echoed
    back is not evidence. Until 2026-10-10 the bare word `entity_id` counted, so
    an error reply such as "missing field entity_id" scored yes.
    """
    leaves = []
    _leaves(result, leaves)
    text = "\n".join(leaves)
    if not FX["ids"]:
        # no fixture reachable: the old text pattern minus the bare word, and say so
        if re.search(r"(light\.|sensor\.|switch\.|scene\.|allowlist_external_dirs|"
                     r"location_name|unit_system)", text):
            return "UNVERIFIED (fixture unavailable): text pattern"
        return None
    ids = {m for m in ID_RE.findall(text) if m in FX["ids"] and m not in sent}
    if len(ids) >= 3:
        return f"{len(ids)} fixture entity ids"
    stamps = sum(1 for s in set(STAMP_RE.findall(text)) if s in FX["stamps"])
    if stamps:
        return f"{stamps} recorded timestamp(s)"
    cfg = [v for v in FX["config"] if v in text]
    if len(cfg) >= 3:
        return f"{len(cfg)} recorded /api/config values"
    words = set(re.findall(r"[a-z_][a-z0-9_]+", text))
    if len(words & FX["svc_domains"]) >= 8 and len(words & FX["svc_names"]) >= 8:
        return (f"{len(words & FX['svc_domains'])} service domains and "
                f"{len(words & FX['svc_names'])} service names from /api/services")
    if len(words & FX["events"]) >= 3:
        return f"{len(words & FX['events'])} event types from /api/events"
    return None


# ---------------------------------------------------------------- MCP client
class Server:
    """One server process with stdin held open and every stdout line kept."""
    EOF = object()

    def __init__(self, argv, cwd):
        self.argv = argv
        self.q = queue.Queue()
        self.msgs, self.err, self.junk = [], [], []
        self.eof = False
        self.p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True)
        self.t_out = threading.Thread(target=self._read_out, daemon=True)
        self.t_err = threading.Thread(target=self._read_err, daemon=True)
        self.t_out.start(); self.t_err.start()

    def _read_out(self):
        try:
            for raw in self.p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        m = json.loads(line)
                    except Exception:
                        self.junk.append(line[:200]); continue
                    if isinstance(m, dict):
                        self.q.put(m)
                else:
                    self.junk.append(line[:200])
        except Exception:
            pass
        self.q.put(self.EOF)

    def _read_err(self):
        try:
            for raw in self.p.stderr:
                if len(self.err) < 200:
                    self.err.append(raw.decode("utf-8", "replace"))
        except Exception:
            pass

    def send(self, obj):
        try:
            self.p.stdin.write((json.dumps(obj) + "\n").encode())
            self.p.stdin.flush()
            return True
        except Exception:
            return False

    def wait(self, pred, timeout):
        """First message satisfying pred within timeout; everything received is kept in msgs."""
        for m in self.msgs:
            if pred(m):
                return m
        end = time.time() + timeout
        while not self.eof:
            rem = end - time.time()
            if rem <= 0:
                return None
            try:
                m = self.q.get(timeout=min(rem, 0.5))
            except queue.Empty:
                continue
            if m is self.EOF:
                self.eof = True
                break
            self.msgs.append(m)
            if pred(m):
                return m
        return None

    def close(self, grace=3):
        """Close stdin, give the server `grace` seconds to finish, then kill its group.

        Returns the messages that arrived only AFTER stdin was closed.
        """
        before = len(self.msgs)
        try: self.p.stdin.close()
        except Exception: pass
        end = time.time() + grace
        while time.time() < end and not self.eof:
            try:
                m = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if m is self.EOF:
                self.eof = True
            else:
                self.msgs.append(m)
        try: os.killpg(self.p.pid, signal.SIGKILL)
        except OSError: pass
        try: self.p.wait(timeout=5)
        except Exception: pass
        self.t_out.join(timeout=2); self.t_err.join(timeout=2)
        while True:
            try:
                m = self.q.get_nowait()
            except queue.Empty:
                break
            if m is not self.EOF:
                self.msgs.append(m)
        return self.msgs[before:]

    def stderr(self):
        return re.sub(r"\x1b\[[0-9;]*m", "", "".join(self.err))


WRITE_RE = re.compile(r"^(call|set|turn|toggle|fire|trigger|create|delete|remove|update|write|"
                      r"post|send|run|execute|press|activate|restart|reload)", re.I)


def call_order(tools):
    """Tools worth calling, best first: the ones that return entity data, then other reads."""
    names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
    reads = [n for n in names if not WRITE_RE.search(n)]
    out = []
    # Prefer the tools that return entity data; a generic "get_*_info"
    # matched first before and returned only {"message": "API running."}
    # (real, but not traceable as data). Try in order of preference.
    for pat in (r"list.*entit|entit.*list|states?$|list_states", r"entit|state", r"config",
                r"list", r"get"):
        out += [n for n in reads if re.search(pat, n, re.I) and n not in out]
    out += [n for n in reads if n not in out]
    return out or names[:1]


def fill_args(tool):
    """Arguments for a call: what the tool's own schema marks required, nothing else.

    Calling every tool with {} graded a server by whether its first tool
    happened to need no arguments. Returns None when a required argument
    cannot be supplied sensibly (a free-text query, a timestamp).
    """
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    props = schema.get("properties") or {}
    args = {}
    for name in schema.get("required") or []:
        p = props.get(name) if isinstance(props.get(name), dict) else {}
        n, typ = str(name).lower(), p.get("type")
        if typ == "array":
            v = [FX["real"] or "sun.sun"] if "entit" in n else []
        elif p.get("enum"):
            v = p["enum"][0]
        elif "entity" in n:
            v = FX["real"] or "sun.sun"
        elif "domain" in n:
            v = "light"
        elif n in ("path", "endpoint", "url", "uri"):
            v = "/api/states"
        elif typ in ("integer", "number"):
            v = 10
        elif typ == "boolean":
            v = False
        elif typ == "object":
            v = {}
        else:
            return None
        args[name] = v
    return args


def speak_mcp(binary, cwd, env):
    """initialize -> tools/list -> tools/call, over stdio, one process, one request at a time."""
    out = {"initialize": False, "server_name": None, "tools_list": 0,
           "tool_names": [], "tools_call": False, "call_sample": None,
           "rpc_error": None}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "bakeoff-grader", "version": "1"}}}
    srv, eof_only, last_err, sent_list = None, None, "", False
    for cand in arg_variants(binary, cwd):
        try:
            s = Server(cand, cwd)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"; continue
        s.send(init)
        if s.wait(lambda m: True, TIMEOUT_RPC) is not None:
            srv = s
            break
        # Silent on initialize. Before giving up on this launch, see whether it
        # answers tools/list (the old grader piped both and counted such tools).
        if not s.eof and s.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) \
                and s.wait(lambda m: True, TIMEOUT_RPC) is not None:
            srv = s
            sent_list = True
            break
        # Nothing while stdin was open. Close it and keep whatever comes out:
        # a reply that appears only now exists, but no client will ever see it.
        late = s.close()
        last_err = s.stderr() or "\n".join(s.junk) or last_err
        if late and eof_only is None:
            eof_only = (cand, late)
    argv = srv.argv if srv else (eof_only[0] if eof_only else [binary])
    out["launched_as"] = " ".join(os.path.basename(a) if i == 0 else a
                                  for i, a in enumerate(argv))
    if not srv:
        if eof_only:
            out["rpc_error"] = ("answers only after stdin is closed (no reply in "
                                f"{TIMEOUT_RPC}s while it was open); an MCP client keeps stdin "
                                "open, so it would never see the reply")
            out["late_sample"] = json.dumps(eof_only[1][0])[:200]
        else:
            out["rpc_error"] = last_err[:200] or "no JSON-RPC response"
        return out

    def is_init(m):
        r = m.get("result") if isinstance(m.get("result"), dict) else {}
        return m.get("id") == 1 or "serverInfo" in r or "protocolVersion" in r

    m = srv.wait(is_init, 2 if sent_list else TIMEOUT_RPC)
    if m is None:
        out["init_error"] = f"no reply to initialize in {TIMEOUT_RPC}s"
    for m in list(srv.msgs):
        r = m.get("result") if isinstance(m.get("result"), dict) else {}
        if m.get("id") == 1 and "result" in m and not ("serverInfo" in r or "protocolVersion" in r):
            out["init_error"] = ("reply to initialize has no serverInfo or protocolVersion: "
                                 + json.dumps(m["result"])[:140])
        if "serverInfo" in r or "protocolVersion" in r:
            # JSON-RPC requires the response to echo the request id. Accepting
            # any message that merely CONTAINS serverInfo passed a server that
            # replied with "id": null and then answered "Method not found" to
            # the real initialize -- a client cannot correlate that, so Open
            # Code refuses the connection. The grader must be at least as
            # strict as a real client or it certifies servers nothing can use.
            if m.get("id") == 1:
                out["initialize"] = True
                out["server_name"] = (r.get("serverInfo") or {}).get("name")
            else:
                out["initialize"] = False
                out["init_error"] = (
                    f"initialize result carried id={m.get('id')!r}, expected 1; "
                    "response cannot be correlated to the request")
            out["advertised_version"] = r.get("protocolVersion")
        elif m.get("id") == 1 and "error" in m:
            out["init_error"] = "initialize answered with an error: " + json.dumps(m["error"])[:160]

    if not sent_list:
        srv.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        srv.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    def has_tools(m):
        r = m.get("result") if isinstance(m.get("result"), dict) else {}
        return "tools" in r or m.get("id") == 2

    m = srv.wait(has_tools, TIMEOUT_RPC)
    tools = []
    for m in list(srv.msgs):
        r = m.get("result") if isinstance(m.get("result"), dict) else {}
        if "tools" in r:
            tools = [t for t in (r["tools"] or []) if isinstance(t, dict)]
            out["tools_list"] = len(tools)
            out["tool_names"] = [t.get("name") for t in tools][:12]
    if not tools and m is not None and "error" in m:
        out["rpc_error"] = "tools/list answered with an error: " + json.dumps(m["error"])[:160]

    # The grade is the PRIMARY read tool's: the one the old grader picked (list/entity/state
    # tools first), now called with the arguments its schema requires. If it returns no data
    # the other read tools are still called, for the note only: "its list tool is broken but
    # get_state works" is a different finding from "nothing works", and it is the reviewer's
    # call, not a silent pass.
    by_name = {t.get("name"): t for t in tools}
    calls, responded, primary = [], False, None
    for i, name in enumerate(call_order(tools)[:MAX_CALLS]):
        args = fill_args(by_name.get(name) or {})
        if args is None:
            calls.append({"tool": name, "outcome": "skipped: a required argument cannot be guessed"})
            continue
        if primary is None:
            primary = name
        rid = 10 + i
        if not srv.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                         "params": {"name": name, "arguments": args}}):
            calls.append({"tool": name, "outcome": "server closed its stdin"}); break
        m = srv.wait(lambda m, rid=rid: m.get("id") == rid, TIMEOUT_RPC)
        rec = {"tool": name, "args": args}
        if m is None:
            rec["outcome"] = (f"no reply in {TIMEOUT_RPC}s" if srv.p.poll() is None
                              else f"server exited (rc {srv.p.returncode})")
            calls.append(rec)
            if srv.p.poll() is not None:
                break
            continue
        if "result" not in m:
            rec["outcome"] = "JSON-RPC error: " + json.dumps(m.get("error"))[:200]
            calls.append(rec); continue
        res = m["result"]
        blob = json.dumps(res)
        rec["sample"] = blob[:200]
        if out["call_sample"] is None:
            out["call_sample"] = blob[:200]
        if isinstance(res, dict) and res.get("isError"):
            # an error result is a reply, not data, whatever words it contains
            rec["outcome"] = "tool error (isError): " + " ".join(
                str(c.get("text", "")) for c in (res.get("content") or []) if isinstance(c, dict))[:120]
            if name == primary:
                responded = len(blob) > 40
            calls.append(rec); continue
        why = fixture_evidence(res, json.dumps(args))
        if why:
            rec["outcome"] = "data: " + why
            calls.append(rec)
            if name == primary:
                out["tools_call"] = True
                out["call_tool"] = name
                out["call_evidence"] = why
                out["call_sample"] = blob[:200]
            else:
                out["other_tool_with_data"] = name
            break
        rec["outcome"] = "succeeded, nothing traceable to the recording"
        if name == primary:
            responded = len(blob) > 40
        calls.append(rec)
    if out["tools_call"] is not True and responded:
        out["tools_call"] = "responded-no-data"
    out["calls"] = calls
    out["primary_tool"] = primary
    if out["tools_call"] is not True and calls:
        note = "; ".join(f"{c['tool']}: {c['outcome']}" for c in calls if c["tool"] == primary
                         or c["outcome"].startswith("data"))
        if out.get("other_tool_with_data"):
            note += f" (graded on {primary}, the primary read tool; {out['other_tool_with_data']} does return recorded data)"
        elif len(calls) > 1:
            note += f"; {len(calls) - 1} other tool(s) tried, none returned recorded data"
        out["call_note"] = note[:400]
    late = srv.close()
    out["exits_on_eof"] = srv.p.returncode is not None and srv.p.returncode >= 0
    if not out["initialize"] and not out.get("init_error") and not tools:
        out["rpc_error"] = out["rpc_error"] or (srv.stderr() or "\n".join(srv.junk))[:200] \
            or "replied, but not to initialize or tools/list"
    return out


def pick_binary(root, cands):
    """The crate's own binary, chosen the same way every time.

    Until 2026-10-10 this was the first executable in directory order, which
    is arbitrary when a crate builds several (a helper, a mock server).
    Order: [package] default-run, the binary named after the package, the
    single [[bin]], the only executable, then alphabetical.
    """
    by = {os.path.basename(p): p for p in cands}
    pkg, default_run, bins = None, None, []
    try:
        import tomllib
        with open(os.path.join(root, "Cargo.toml"), "rb") as fh:
            data = tomllib.load(fh)
        pkg = (data.get("package") or {}).get("name")
        default_run = (data.get("package") or {}).get("default-run")
        bins = [b.get("name") for b in (data.get("bin") or []) if isinstance(b, dict) and b.get("name")]
    except Exception:
        txt = open(os.path.join(root, "Cargo.toml"), encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*default-run\s*=\s*\"([^\"]+)\"", txt, re.M)
        default_run = m.group(1) if m else None
        m = re.search(r"\[package\][^\[]*?^\s*name\s*=\s*\"([^\"]+)\"", txt, re.M | re.S)
        pkg = m.group(1) if m else None
        bins = re.findall(r"\[\[bin\]\][^\[]*?^\s*name\s*=\s*\"([^\"]+)\"", txt, re.M | re.S)
    if default_run in by:
        return by[default_run], "default-run"
    if pkg in by:
        return by[pkg], "package name"
    declared = [b for b in bins if b in by]
    if len(declared) == 1:
        return by[declared[0]], "the only [[bin]]"
    if len(by) == 1:
        return next(iter(by.values())), "the only executable"
    pool = sorted(declared) or sorted(by)
    return by[pool[0]], "first alphabetically of " + ", ".join(pool)


def emit(res):
    print(json.dumps(res), flush=True)


def main():
    try:
        redirect = start_redirect()
    except Exception as ex:
        # asked to isolate the live replay and could not: build and run nothing
        print(json.dumps({"grader_error": f"grading-replay relay failed: {ex}", "phase": "start"}), flush=True)
        sys.exit(3)
    load_fixture()
    res = {"manifest": None, "builds": False, "binary": None,
           "build_error": None, "cargo_test": None, "phase": "manifest"}
    root = find_manifest()
    if not root:
        res["note"] = globals().get("_BAD_MANIFEST") or "no Cargo.toml found"
        res["phase"] = "done"
        emit(res); return
    res["manifest"] = os.path.relpath(root, APP)
    res["phase"] = "build"
    emit(res)

    env = dict(os.environ)
    t0 = time.time()
    limit = int(max(60, min(TIMEOUT_BUILD, DEADLINE - time.time() - 120)))
    rc, so, se = sh(["cargo", "build", "--release"], root, limit)
    res["build_seconds"] = round(time.time() - t0, 1)
    res["builds"] = rc == 0
    if rc != 0:
        errs = [l for l in se.splitlines() if l.startswith("error")]
        res["build_error"] = "; ".join(errs[:3])[:300] or se[-300:]
        if rc == -9:
            res["grader_timeout"] = f"cargo build stopped after {limit}s"
            res["build_error"] = f"grader timeout: cargo build did not finish in {limit}s"
        res["phase"] = "done"
        emit(res); return

    rel = os.path.join(root, "target", "release")
    cands = []
    if os.path.isdir(rel):
        for f in sorted(os.listdir(rel)):
            p = os.path.join(rel, f)
            if os.path.isfile(p) and os.access(p, os.X_OK) and "." not in f:
                cands.append(p)
    if not cands:
        res["note"] = "built but no runnable binary"
        res["phase"] = "done"
        emit(res); return
    binary, how = pick_binary(root, cands)
    res["binary"] = os.path.basename(binary)
    res["binary_chosen_by"] = how
    res["binaries"] = [os.path.basename(p) for p in cands]
    res["phase"] = "speak"
    emit(res)

    res.update(speak_mcp(binary, root, env))
    res["phase"] = "test"
    emit(res)

    limit = int(min(TIMEOUT_BUILD, DEADLINE - time.time()))
    if limit < 60:
        res["grader_timeout"] = "cargo test not run: no time left after the build"
    else:
        # the model's tests see the HA_* values its own sandbox had (the relay makes that
        # address the grading replay); the server above was launched with the grader's
        tenv = dict(os.environ)
        if redirect:
            tenv.update({"HA_URL": AGENT_HA_URL, "HA_BASE_URL": AGENT_HA_URL})
        res["test_ha_url"] = tenv.get("HA_URL")
        rc, so, se = sh(["cargo", "test", "--release"], root, limit, env=tenv)
        blob = so + se
        # one "test result" line per target (lib, each tests/*.rs, doc-tests): sum them all.
        # Until 2026-10-06 only the first line was read, so a crate with an empty lib target scored 0.
        m = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed", blob)
        res["cargo_test"] = {"rc": rc,
                             "passed": sum(int(a) for a, _ in m),
                             "failed": sum(int(b) for _, b in m)}
        if rc == -9:
            res["cargo_test"]["timeout"] = True
            res["grader_timeout"] = f"cargo test stopped after {limit}s (counts are partial)"
    res["phase"] = "done"
    res["seconds"] = round(time.time() - T0)
    emit(res)


if __name__ == "__main__":
    main()
