#!/usr/bin/env python3
"""Grade one generated CLI by RUNNING it. Executes inside the container.

LOC measures verbosity, not quality. This executes each tool against the live
read-only Home Assistant proxy and records what actually works:

  help        --help exits 0 and prints usable help
  reads       a states-like command returns data traceable to the recorded fixture
  bad_input   a nonexistent entity fails cleanly, non-zero exit, no traceback
  bad_auth    the same read with a wrong token fails, no traceback
  tests       the model's own tests run and pass
  no_crash    the tool ran and nothing raised an unhandled exception

Writes JSON to stdout, one line per finished phase; the last line is the result
(`pending` lists checks not evaluated yet, so a killed run is not read as a failure).
"""
import json, os, re, subprocess, sys, glob, time

APP = "/app"
HA_URL = os.environ["HA_URL"]
HA_TOKEN = os.environ["HA_TOKEN"]
TIMEOUT = 60
READ_BUDGET = 420     # seconds for the whole search for a working read command
BAD_BUDGET = 180      # seconds for the bad-input search
TEST_BUDGET = 600     # seconds for all of the model's test trees together
TEST_TIMEOUT = 300    # seconds for one test tree

SKIP = ("venv", ".venv", "site-packages", "__pycache__", ".pytest_cache",
        "node_modules", "build", "dist", ".git")


def files():
    out = []
    for p in glob.glob(f"{APP}/**/*", recursive=True):
        if not os.path.isfile(p):
            continue
        if any(s in p.split(os.sep) for s in SKIP):
            continue
        out.append(p)
    return out


def entrypoint():
    """Best guess at the CLI: prefers argparse+main, HA-ish names, bigger files."""
    best, best_score = None, -1
    for p in files():
        if not (p.endswith(".py") or _shebang_py(p)):
            continue
        base = os.path.basename(p).lower()
        if base.startswith(("test_", "conftest", "setup", "mock")) or base.endswith("_test.py"):
            continue
        try:
            src = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        score = 0
        if "argparse" in src or "click" in src: score += 3
        if re.search(r"def main\b", src): score += 3
        if '__main__' in src: score += 2
        if any(k in base for k in ("ha", "hass", "home")): score += 2
        score += min(len(src) // 2000, 3)
        if score > best_score:
            best, best_score = p, score
    return best


def _shebang_py(p):
    try:
        first = open(p, "rb").readline(200).decode("utf-8", "replace")
        return first.startswith("#!") and "python" in first
    except OSError:
        return False


CWD = {"dir": APP}   # set once the entrypoint is chosen


def run(args, env=None, timeout=TIMEOUT, cwd=None):
    e = dict(os.environ)
    e.update(env or {})
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             stdin=subprocess.DEVNULL, env=e, cwd=cwd or CWD["dir"],
                             start_new_session=True, errors="replace")
    except Exception as ex:
        return -1, "", f"{type(ex).__name__}: {ex}"
    try:
        so, se = p.communicate(timeout=timeout)
        return p.returncode, so or "", se or ""
    except subprocess.TimeoutExpired:
        # kill the whole group: a child left holding the pipe would block the read forever
        try: os.killpg(p.pid, 9)
        except OSError: pass
        try: so, se = p.communicate(timeout=10)
        except Exception: so, se = "", ""
        return -9, so or "", (se or "") + "\nTIMEOUT"
    except Exception as ex:
        return -1, "", f"{type(ex).__name__}: {ex}"


def traceback_in(s):
    # A SyntaxError in the script itself is reported without the Traceback header.
    return "Traceback (most recent call last)" in s or bool(
        re.search(r"^(SyntaxError|IndentationError|TabError): ", s, re.M))


def project_dirs():
    """Directories worth treating as the project root.

    A model may nest its package under e.g. ha-cli/ha_cli_package/, and a
    hyphenated parent is not importable, so `-m pkg` only works with cwd set
    to the directory *containing* the package.
    """
    dirs = [APP]
    for p in files():
        d = os.path.dirname(p)
        while d and d.startswith(APP) and d != APP:
            if d not in dirs:
                dirs.append(d)
            d = os.path.dirname(d)
    # parents of packages matter most: that is where -m works from
    ranked = []
    for d in dirs:
        has_pkg = any(os.path.exists(os.path.join(d, e, "__init__.py"))
                      for e in (os.listdir(d) if os.path.isdir(d) else [])
                      if os.path.isdir(os.path.join(d, e)))
        ranked.append((0 if has_pkg else 1, d.count(os.sep), d))
    ranked.sort()
    return [d for _, _, d in ranked][:8]


def invocations():
    """Candidate ways to launch the tool, best first.

    Models ship real packages as often as single files. Running
    `python3 pkg/cli.py` on a package module fails on relative imports, so a
    file-only grader reports a working tool -- tests passing and all -- as
    non-functional. Try `python3 -m pkg` too.
    """
    out = []
    # packages with a __main__.py are launchable as modules
    for p in files():
        if os.path.basename(p) == "__main__.py":
            pkg = os.path.basename(os.path.dirname(p))
            if pkg and pkg != os.path.basename(APP):
                out.append(([sys.executable, "-m", pkg], f"{pkg} (module)"))
    # packages whose __init__.py defines a main()
    for p in files():
        if os.path.basename(p) == "__init__.py":
            try:
                src = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if re.search(r"def main\b", src) or "argparse" in src:
                pkg = os.path.basename(os.path.dirname(p))
                cand = ([sys.executable, "-m", pkg], f"{pkg} (module)")
                if pkg and cand not in out:
                    out.append(cand)
    # declared console_scripts, e.g. "ha-cli=ha_cli.main:main"
    for meta in ("setup.py", "pyproject.toml"):
        mp = os.path.join(APP, meta)
        if not os.path.exists(mp):
            continue
        try:
            txt = open(mp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r"[\"']?[\w.-]+\s*=\s*[\"']?([\w.]+):(\w+)", txt):
            mod = m.group(1)
            cand = ([sys.executable, "-m", mod], f"{mod} (declared)")
            if cand not in out:
                out.append(cand)

    # any module inside a package: python3 -m pkg.mod
    for p in files():
        if not p.endswith(".py"):
            continue
        d = os.path.dirname(p)
        if not os.path.exists(os.path.join(d, "__init__.py")):
            continue
        mod = os.path.basename(p)[:-3]
        if mod in ("__init__", "__main__"):
            continue
        pkg = os.path.basename(d)
        if pkg.startswith("test") or mod.startswith("test"):
            continue
        cand = ([sys.executable, "-m", f"{pkg}.{mod}"], f"{pkg}.{mod} (module)")
        if cand not in out:
            out.append(cand)

    ep = entrypoint()
    if ep:
        out.append(([sys.executable, ep], os.path.relpath(ep, APP)))
    return out


def pick(cands):
    """Best invocation, giving the tool the benefit of the doubt.

    A package can expose several entry points, and the one declared in
    setup.py is not always the one that works. Prefer a candidate whose help
    works; among those, later checks decide. Falls back to the best guess.
    """
    ok = []
    for d in project_dirs():
        for argv, label in cands:
            try:
                r = subprocess.run(argv + ["--help"], capture_output=True, text=True,
                                   timeout=45, cwd=d, env=dict(os.environ))
                if r.returncode == 0 and len(r.stdout or "") > 80:
                    lbl = label if d == APP else f"{label} @{os.path.relpath(d, APP)}"
                    CWD["dir"] = d
                    ok.append((argv, lbl, r.stdout))
            except Exception:
                continue
        if ok:
            break
    # A tool whose --help prints usage but exits non-zero is still a tool.
    # Scoring it "no entrypoint" skipped every check: bonsai2-27b-pq2-r2 was
    # graded 0/5 while its `states` and `config` read the replay correctly.
    # The help check itself still demands rc 0; this only picks what to run.
    if not ok:
        for d in project_dirs():
            for argv, label in cands:
                try:
                    r = subprocess.run(argv + ["--help"], capture_output=True, text=True,
                                       timeout=45, cwd=d, env=dict(os.environ))
                except Exception:
                    continue
                blob = (r.stdout or "") + (r.stderr or "")
                if "usage" in blob.lower() and len(blob) > 80 and not traceback_in(blob):
                    lbl = label if d == APP else f"{label} @{os.path.relpath(d, APP)}"
                    CWD["dir"] = d
                    ok.append((argv, lbl + " [help rc!=0]", blob))
            if ok:
                break
    if ok:
        a, l, h = ok[0]
        return a, l, h, [(x[0], x[1]) for x in ok]
    if cands:
        return cands[-1][0], cands[-1][1], "", [cands[-1]]
    return None, None, "", []


def pick_readable(cands, probe):
    """Among help-passing candidates, prefer one that can actually read."""
    for argv, label in cands:
        if probe(argv):
            return argv, label
    return None, None


def _subcommands_of(out):
    """Scrape subcommand names from a help or usage blob."""
    names = []
    # argparse prints aliases after the name: "    list (ls)    list entities"
    for m in re.finditer(r"^\s{2,}([a-z][a-z0-9_-]{1,24})(?: \([a-z0-9_, -]+\))?\s{2,}\S", out, re.M):
        w = m.group(1)
        if w not in ("options", "usage", "positional", "optional", "commands",
                     "help", "arguments", "args", "flags"):
            names.append(w)
    return list(dict.fromkeys(names))[:12]


def _looks_like_group_help(out):
    """True when the output is a command group's help rather than data."""
    # argparse with a custom metavar (`ACTION ...`) shows no choices and, called bare,
    # only "error: the following arguments are required: ACTION"; count that too.
    return bool(re.search(r"(Commands:|COMMAND|Subcommands|\{[a-z0-9_,-]{5,}\}|"
                          r"arguments are required: [A-Z_]+\b)", out))


# ---------------------------------------------------------------- fixture evidence
# Until 2026-10-10 `reads` matched the text `sensor.` / `light.` / "state" in the
# output. That missed a CLI printing domain and entity in separate columns
# (wa-bonsai2-27b-ada: `sensor | backup_manager_state | ...`), and it could be
# satisfied by any text that merely looks like an entity id. Evidence is now
# tied to the recorded Home Assistant itself: real entity ids, table rows that
# pair a real domain with one of that domain's real entities, or the recorded
# /api/config values.
FX = {"ids": set(), "by_domain": {}, "names": {}, "config": [], "real": None,
      "real_name": "", "source": None}
MIN_HITS = 3          # distinct fixture entities an output must show
ID_RE = re.compile(r"(?<![\w.])([a-z_]+\.[a-z0-9_]+)(?![\w])")
CELL_SPLIT = re.compile(r"\s{2,}|\t|[|│┃║]")
TOKEN_SPLIT = re.compile(r"[\s|│┃║,;\"'\[\](){}]+")


def load_fixture():
    """Entity ids and config values of the recorded Home Assistant.

    From the fixture file the grade script mounts; failing that, from the
    grading replay itself, which serves the same recording.
    """
    states, cfg = None, None
    try:
        fx = json.load(open(os.environ.get("HA_FIXTURE", "/fixture.json")))
        states = json.loads(fx["responses"]["/api/states"]["body"])
        cfg = json.loads(fx["responses"]["/api/config"]["body"])
        FX["source"] = "fixture file"
    except Exception:
        try:
            import urllib.request
            def get(path):
                rq = urllib.request.Request(HA_URL.rstrip("/") + path,
                                            headers={"Authorization": f"Bearer {HA_TOKEN}"})
                return json.load(urllib.request.urlopen(rq, timeout=20))
            states, cfg = get("/api/states"), get("/api/config")
            FX["source"] = "grading replay"
        except Exception:
            return
    for s in states or []:
        eid = s.get("entity_id") or ""
        if "." not in eid:
            continue
        dom, obj = eid.split(".", 1)
        FX["ids"].add(eid)
        FX["by_domain"].setdefault(dom, set()).add(obj)
        fn = str((s.get("attributes") or {}).get("friendly_name") or "").strip().lower()
        if len(fn) >= 4:
            FX["names"].setdefault(dom, set()).add(fn)
    # values only this installation has: a tool cannot print them without reading /api/config
    for k in ("version", "time_zone", "external_url", "internal_url", "latitude", "longitude"):
        v = (cfg or {}).get(k)
        if v not in (None, "", 0):
            FX["config"].append(str(v))
    # a real entity for the positive control of the bad-input check
    plain = {s.get("entity_id") for s in states or []
             if not any(i in FX["ids"] for i in ID_RE.findall(json.dumps(s.get("attributes") or {})))}
    lights = sorted(e for e in FX["ids"] if e.startswith("light.") and len(e) > 14 and e in plain)
    FX["real"] = (lights or sorted(FX["ids"]) or [None])[0]
    for s in states or []:
        if s.get("entity_id") == FX["real"]:
            FX["real_name"] = str((s.get("attributes") or {}).get("friendly_name") or "")


def fixture_ids_in(text):
    return {m for m in ID_RE.findall(text) if m in FX["ids"]}


def table_rows_in(text):
    """(domain, entity) pairs printed as separate cells of one line.

    A line counts when one token is a fixture domain and another token is the
    object id of an entity in THAT domain (or a cell is its friendly name).
    A cell cut short by the table renderer ("backup_manager_st…") matches on
    its prefix.
    """
    hits = set()
    for line in text.splitlines():
        toks = [t.lower() for t in TOKEN_SPLIT.split(line) if t]
        doms = [t for t in toks if t in FX["by_domain"]]
        if not doms:
            continue
        cells = [c.strip().lower() for c in CELL_SPLIT.split(line) if c.strip()]
        for dom in dict.fromkeys(doms):
            objs, names = FX["by_domain"][dom], FX["names"].get(dom, set())
            found = None
            for t in toks:
                if t == dom and toks.count(dom) < 2:
                    continue
                if t in objs:
                    found = t; break
                cut = re.sub(r"(…|\.\.\.)$", "", t)
                if cut != t and len(cut) >= 8 and any(o.startswith(cut) for o in objs):
                    found = cut; break
            if not found:
                found = next((c for c in cells if c in names), None)
            if found:
                hits.add((dom, found))
    return hits


def looks_like_help(out):
    return bool(re.match(r"\s*usage:", out, re.I))


OLD_READ_RE = re.compile(r"(light\.|sensor\.|switch\.|binary_sensor\.|scene\.|"
                         r"climate\.|media_player\.|\"state\"|'state')")


def read_evidence(out, help_ids=frozenset()):
    """What in `out` proves the tool fetched the recording: (kind, detail) or (None, '').

    kind is 'entities' (real entity ids), 'table' (domain and entity in separate
    columns) or 'config' (the recorded /api/config values). Entity ids that the
    tool's own help text already prints as examples do not count, and neither
    does any output that is itself a usage message.
    """
    if not out.strip() or looks_like_help(out):
        return None, ""
    if not FX["ids"]:
        # no fixture reachable: the pre-2026-10-10 text pattern, and say so
        return ("entities", "UNVERIFIED: fixture unavailable, text pattern only") \
            if OLD_READ_RE.search(out) else (None, "")
    ids = fixture_ids_in(out) - set(help_ids)
    if len(ids) >= MIN_HITS:
        return "entities", f"{len(ids)} fixture entity ids in stdout"
    rows = table_rows_in(out)
    if len(rows) >= MIN_HITS:
        return "table", f"{len(rows)} lines pairing a fixture domain with one of its entities"
    cfg = [v for v in FX["config"] if v in out]
    if len(cfg) >= 3:
        return "config", f"{len(cfg)} recorded /api/config values in stdout"
    return None, ""


USAGE_RE = re.compile(
    r"unrecognized arguments|invalid choice|no such command|no such option|"
    r"unexpected extra argument|the following arguments are required|missing argument|"
    r"missing option|expected (one|at least one) argument|too many arguments|"
    r"unknown (sub)?command|unknown option|ambiguous option|requires an argument|"
    r"not a valid (sub)?command|unexpected argument", re.I)
NOT_FOUND_RE = re.compile(r"not found|no such entity|does not exist|404|unknown entity|"
                          r"no entity", re.I)
# With exit code 0 only an explicit "nothing matched" counts (and no data alongside it): a bare
# "404" matches any number in a listing, which credited a command that ignored the bad id.
NO_MATCH_RE = re.compile(r"not found|no such entity|does not exist|unknown entity|no results?\b|"
                         r"no match|no entit|nothing found|\b0 entities|no states?\b", re.I)


def usage_error(rc, out, err):
    """True when the tool rejected the COMMAND LINE rather than handling the request.

    An argparse/Click usage error (rc 2, "usage: ...", "unrecognized arguments")
    says the argument never reached the code that talks to Home Assistant, so it
    proves nothing about how a bad entity or a bad token is handled.
    """
    if rc == 0:
        return False
    blob = out + err
    if USAGE_RE.search(blob):
        return True
    return rc == 2 and bool(re.search(r"^\s*usage:", blob, re.I | re.M)) \
        and not NOT_FOUND_RE.search(blob)


def json_variants(toks, helpblob):
    """The same command in the tool's machine-readable output mode, if its help names one."""
    out = []
    for flag, extra in (("--json", ["--json"]), ("--format", ["--format", "json"]),
                        ("--output", ["--output", "json"]), ("-o", ["-o", "json"]),
                        ("-f", ["-f", "json"]), ("--output-format", ["--output-format", "json"]),
                        ("--raw", ["--raw"])):
        if re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", helpblob):
            out.append(toks + extra)       # flag on the subcommand
            out.append(extra + toks)       # global flag before the subcommand
    return out


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


REDIRECT = {"on": False}


def emit(res):
    """One JSON line per finished phase; the grade script keeps the last one.

    If the container is killed on its time limit the facts gathered so far
    survive, and `pending` names the checks that were never evaluated.
    """
    print(json.dumps(res), flush=True)


def main():
    T0 = time.time()
    try:
        REDIRECT["on"] = start_redirect()
    except Exception as ex:
        # asked to isolate the live replay and could not: run nothing
        print(json.dumps({"grader_error": f"grading-replay relay failed: {ex}"}), flush=True)
        sys.exit(3)
    load_fixture()
    cands = invocations()
    base, label, _, help_ok = pick(cands)
    ep = label
    res = {"entrypoint": ep,
           "help": False, "reads": False, "bad_input": False,
           "bad_auth": False, "tests": None, "no_crash": True,
           "subcommands": [], "notes": [],
           "pending": ["help", "reads", "bad_input", "bad_auth", "no_crash", "tests"]}
    if not FX["ids"]:
        res["notes"].append("fixture unavailable: reads judged by text pattern only")
    if not base:
        # Nothing ran, so "nothing crashed" was never observed. This defaulted
        # to yes until 2026-10-10 and gave an empty work tree one check.
        res["no_crash"] = False
        res["notes"].append("no runnable entrypoint found (no_crash not credited: nothing ran)")
        res["pending"] = []
        emit(res); return

    res["tried"] = [l for _, l in cands]
    def mkenv(url, tok=HA_TOKEN):
        return {"HA_URL": url, "HA_TOKEN": tok,
                "HOMEASSISTANT_URL": url, "HASS_URL": url,
                "HA_BASE_URL": url, "HASS_TOKEN": tok,
                "HOMEASSISTANT_TOKEN": tok, "HA_SERVER": url}
    # some tools expect the base to already include /api, some append it
    ENVS = [mkenv(HA_URL), mkenv(HA_URL.rstrip("/") + "/api")]
    env = ENVS[0]

    def crash(blob):
        if traceback_in(blob):
            res["no_crash"] = False

    # 1. help
    rc, out, err = run(base + ["--help"], env)
    main_help = out + err
    # ... and it has to BE help. Length alone credited a probe script that ignores its
    # arguments and prints JSON (wa-qwen3.8-27b-vllm-64k-pi's explore.py, once /work existed).
    res["help"] = rc == 0 and len(out) > 80 and bool(
        re.search(r"usage|options|commands|arguments|--[a-z]", out, re.I))
    crash(out + err)
    # scrape subcommand names out of the help text
    for m in re.finditer(r"^\s{2,}([a-z][a-z0-9_-]{2,20})\s{2,}\S", out, re.M):
        w = m.group(1)
        if w not in ("options", "usage", "positional", "optional", "commands", "help"):
            res["subcommands"].append(w)
    res["subcommands"] = sorted(set(res["subcommands"]))[:25]
    # entity ids the help prints as examples are not evidence of a read
    help_ids = fixture_ids_in(main_help)
    res["pending"].remove("help")
    emit(res)

    # 2. reads -- try the model's own subcommand names first, then common ones
    cands = [c for c in res["subcommands"]
             if any(k in c for k in ("state", "entit", "list", "get", "status"))]
    cands += ["states", "state", "list", "entities", "get-states", "list-states", "status"]
    url_flags = [[], ["--url", HA_URL], ["--url", HA_URL, "--token", HA_TOKEN],
                 ["--host", HA_URL], ["--base-url", HA_URL]]
    entries = [(base, label)] + [(a, l) for a, l in help_ok if a != base]
    read_deadline = T0 + READ_BUDGET
    sub_help = {}

    def help_of(bse, c, ev):
        if (tuple(bse), c) not in sub_help:
            _, ho, he = run(bse + [c, "--help"], ev, timeout=45)
            sub_help[(tuple(bse), c)] = ho + he
        return sub_help[(tuple(bse), c)]

    def try_read(bse, toks, uf, ev):
        """Run one command; evidence kind if it shows the recording, else None."""
        rc, out, err = run(bse + toks + uf, ev, timeout=45)
        crash(out + err)
        # A read means the tool FETCHED data, so require rc == 0 and look at
        # stdout only (argparse usage text mentions entity ids too).
        kind, why = read_evidence(out, help_ids) if rc == 0 else (None, "")
        if len(read_trace) < 24 and not (rc == 2 and usage_error(rc, out, err) and len(read_trace) >= 8):
            read_trace.append({"cmd": " ".join(toks + uf), "rc": rc, "evidence": kind,
                               "stdout": " ".join(out.split())[:110],
                               "stderr": " ".join(err.split())[-110:]})
        return kind, why, rc, out, err

    def with_json_mode(bse, toks, uf, ev, rc, out):
        """The command ran and printed something unrecognised: ask for its JSON mode."""
        if rc != 0 or not out.strip() or looks_like_help(out):
            return None
        for v in json_variants(toks, main_help + help_of(bse, toks[0], ev)):
            kind, why, _, _, _ = try_read(bse, v, uf, ev)
            if kind in ("entities", "table"):
                return v, kind, why + " (machine-readable mode)"
        return None

    read_trace = []   # what the first commands tried actually printed, for the reviewer
    res["read_trace"] = read_trace
    hit = None        # (bse, lbl, toks, uf, ev, kind, why)
    fallback = None   # same, for config-only evidence
    timed_out = False
    for bse, lbl in entries:
        for ev in ENVS:
            for c in dict.fromkeys(cands):
                for uf in url_flags:
                    if time.time() > read_deadline:
                        timed_out = True; break
                    kind, why, rc, out, err = try_read(bse, [c], uf, ev)
                    toks = [c]
                    if not kind:
                        j = with_json_mode(bse, [c], uf, ev, rc, out)
                        if j:
                            toks, kind, why = j
                    # A CLI built from command GROUPS needs two tokens --
                    # `ha states list`, not `ha states`. Walk one level in.
                    # NOT gated on rc: Click exits 2 when a group is invoked
                    # with no subcommand, and argparse exits 2 for a missing
                    # positional. Only the leaf's exit code says anything.
                    if not kind and _looks_like_group_help(out + err):
                        subs = _subcommands_of(out + err)
                        if not subs:
                            # the usage error lists no names; the group's own --help does
                            subs = _subcommands_of(help_of(bse, c, ev))
                        for sub in subs:
                            k2, w2, rc2, out2, _ = try_read(bse, [c, sub], uf, ev)
                            t2 = [c, sub]
                            if not k2:
                                j = with_json_mode(bse, [c, sub], uf, ev, rc2, out2)
                                if j:
                                    t2, k2, w2 = j
                            if k2 in ("entities", "table"):
                                toks, kind, why = t2, k2, w2
                                res["group_subs"] = subs
                                break
                            if k2 == "config" and not fallback:
                                fallback = (bse, lbl, t2, uf, ev, k2, w2)
                    if kind in ("entities", "table"):
                        hit = (bse, lbl, toks, uf, ev, kind, why)
                        break
                    if kind == "config" and not fallback:
                        fallback = (bse, lbl, toks, uf, ev, kind, why)
                if hit or timed_out: break
            if hit or timed_out: break
        if hit or timed_out: break
    if timed_out:
        res["notes"].append(f"read search stopped at its {READ_BUDGET}s budget")
    if not hit and fallback:
        hit = fallback
        res["notes"].append("reads credited from recorded /api/config values; "
                            "no command listed entities")
    read_toks, uf = [], []
    if hit:
        bse, lbl, read_toks, uf, env, kind, why = hit
        res["reads"] = True
        res["read_cmd"] = " ".join(read_toks + uf)
        res["read_env"] = env["HA_URL"]
        res["read_evidence"] = f"{kind}: {why}"
        res["exit_code_ok"] = True
        base = bse
        if lbl != label:
            res["working_entry"] = lbl
            res["notes"].append(f"declared/primary entry {label} does not read; {lbl} does")
    res["pending"].remove("reads")
    emit(res)

    # 3. bad input -- a nonexistent entity must fail cleanly.
    # Until 2026-10-10 this ran `<first word of the read command> <bad id>`
    # with the subcommand and the URL flags dropped, and counted any non-zero
    # exit: an argparse "unrecognized arguments" error scored as correct
    # handling. Now the bad id must reach a command that looks an entity up:
    # a usage error is skipped, and the same command line must succeed for a
    # REAL entity (positive control) before its answer to a fake one counts.
    BAD = "light.definitely_not_real_xyz"
    if hit:
        real = FX["real"]
        ENT = re.compile(r"state|entit|get|show|info|describe|inspect|read|query|detail")
        shapes = [read_toks + ["{}"]]
        tops = [s for s in res["subcommands"] if ENT.search(s)]
        tops += [s for s in ("state", "get", "entity", "show", "get-state", "states") if s not in tops]
        shapes += [[s, "{}"] for s in tops]
        if len(read_toks) >= 2:
            grp = read_toks[0]
            subs = res.get("group_subs") or []
            subs = [s for s in subs if ENT.search(s)] + ["get", "show", "info"]
            shapes += [[grp, s, "{}"] for s in dict.fromkeys(subs)]
        shapes += [[s, g, "{}"] for s in tops[:6] for g in ("get", "show") if s != g]
        for flag in ("--entity-id", "--entity", "--entity_id", "-e", "--id"):
            shapes.append(read_toks + [flag, "{}"])
        # a generic "fetch this path" command is an entity lookup too
        for s in ("get", "raw", "api", "request", "fetch"):
            if s in res["subcommands"]:
                shapes += [[s, "/api/states/{}"], [s, "states/{}"], [s, "/states/{}"]]
        seen, tried, verified, unverified, trace = set(), 0, None, None, []
        bad_deadline = time.time() + BAD_BUDGET
        for shape in shapes:
            if tuple(shape) in seen or time.time() > bad_deadline or tried >= 60:
                continue
            seen.add(tuple(shape)); tried += 1
            argv = [t.replace("{}", BAD) for t in shape]
            rc, out, err = run(base + argv + uf, env, timeout=45)
            blob = out + err
            crash(blob)
            if usage_error(rc, out, err):
                trace.append({"cmd": " ".join(argv + uf), "rc": rc, "usage_error": True})
                continue                       # the bad id never reached a handler
            # non-zero exit, or exit 0 with an explicit "nothing matched" and no entity data
            clean = (rc != 0 or (bool(NO_MATCH_RE.search(blob)) and not fixture_ids_in(out))) \
                and not traceback_in(blob)
            rec = {"cmd": " ".join(argv + uf), "rc": rc, "clean": clean,
                   "said": (err.strip() or out.strip())[-160:]}
            trace.append(rec)
            if unverified is None:
                unverified = rec
            if not real:
                continue
            # positive control: the same command line with an entity that exists
            rargv = [t.replace("{}", real) for t in shape]
            rc2, out2, err2 = run(base + rargv + uf, env, timeout=45)
            crash(out2 + err2)
            low = out2.lower()
            # ... and shows THAT entity, not a listing that happens to include it
            shows_real = rc2 == 0 and len(fixture_ids_in(out2)) <= 5 and (
                real in out2 or real.split(".", 1)[1] in low
                or (len(FX["real_name"]) >= 4 and FX["real_name"].lower() in low))
            if not shows_real:
                rec["control"] = f"FAILED: {' '.join(rargv)} -> rc {rc2}, " + (
                    "a whole listing" if rc2 == 0 and len(fixture_ids_in(out2)) > 5
                    else "does not show the entity")
                continue
            rec["control"] = f"{' '.join(rargv)} -> rc 0, shows the entity"
            # best: verified and a non-zero exit. A verified "(no results)" with exit 0 counts
            # too, but keep looking for a command that says no with its exit code.
            rank = 3 if (clean and rc != 0) else 2 if clean else 1
            if verified is None or rank > verified["rank"]:
                verified = dict(rec, rank=rank)
            if rank == 3:
                break
        chosen = verified or unverified
        res["bad_input_tried"] = trace[:60]
        if chosen:
            res["bad_input"] = bool(chosen["clean"])
            res["bad_input_cmd"] = chosen["cmd"]
            res["bad_input_rc"] = chosen["rc"]
            res["bad_input_said"] = chosen["said"]
            res["bad_input_verified"] = bool(verified)
            if not verified:
                res["notes"].append("bad_input: no command returned a real entity, so the answer to a "
                                    "fake one is unverified (the lookup may fail for every id)")
        else:
            res["notes"].append("bad_input: no command accepts an entity id (every attempt was a "
                                "usage error), so the check could not be exercised")
    res["pending"].remove("bad_input")
    emit(res)

    # 4. bad auth -- the SAME read command, same flags, with a wrong token.
    # (Before 2026-10-10 the subcommand and URL flags were dropped here too, so
    # a tool that needed `--url` failed for that reason and was credited.)
    if hit:
        bad = dict(env)
        for k in list(bad):
            if "TOKEN" in k:
                bad[k] = "totally-wrong-token"
        buf = ["totally-wrong-token" if i and uf[i - 1] == "--token" else a
               for i, a in enumerate(uf)]
        rc, out, err = run(base + read_toks + buf, bad, timeout=45)
        crash(out + err)
        res["bad_auth"] = rc != 0 and not traceback_in(out + err) \
            and not usage_error(rc, out, err)
        res["bad_auth_cmd"] = " ".join(read_toks + buf)
        res["bad_auth_rc"] = rc
        res["bad_auth_said"] = (err.strip() or out.strip())[-160:]
        if rc == 0 and read_evidence(out, help_ids)[0]:
            res["notes"].append("bad_auth: the read still returned data with a wrong token "
                                "(token not taken from the environment or flags)")
    res["pending"].remove("bad_auth")
    res["pending"].remove("no_crash")
    emit(res)

    # 5. the model's own tests
    # The tests run with the HA_* values the agent's sandbox had, not the grader's: tests that
    # mock "the configured URL" were written against that address and fail under any other.
    # Only when the relay guarantees that address is the grading replay.
    tenv = {"HA_URL": AGENT_HA_URL, "HA_BASE_URL": AGENT_HA_URL, "HA_TOKEN": HA_TOKEN} \
        if REDIRECT["on"] else env
    res["tests"] = run_tests(tenv, res)
    if res["tests"]:
        res["tests"]["ha_url"] = tenv["HA_URL"]
    res["pending"] = []
    res["seconds"] = round(time.time() - T0)
    emit(res)


# ---------------------------------------------------------------- the model's own tests
def _is_test_file(p):
    b = os.path.basename(p)
    if not p.endswith(".py") or b in ("conftest.py", "__init__.py"):
        return False
    if b.startswith("test_") or b.endswith("_test.py"):
        return True
    in_tests = any(part.lower() in ("tests", "test") for part in
                   os.path.relpath(os.path.dirname(p), APP).split(os.sep))
    if not (in_tests or b in ("tests.py", "test.py")):
        return False
    try:
        src = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return bool(re.search(r"^\s*(async\s+)?def test_|unittest\.TestCase|\(TestCase\)", src, re.M))


def _test_trees():
    """Test files grouped by test tree: the outermost tests/ folder, else the file's folder."""
    trees = {}
    for p in sorted(files()):
        if not _is_test_file(p):
            continue
        d = os.path.dirname(p)
        parts = [x for x in os.path.relpath(d, APP).split(os.sep) if x != "."]
        root = d
        for i, part in enumerate(parts):
            if part.lower() in ("tests", "test"):
                root = os.path.join(APP, *parts[:i + 1]); break
        trees.setdefault(root, []).append(p)
    return trees


def _junit(path):
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    n = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for s in suites:
        for k in n:
            try: n[k] += int(s.get(k) or 0)
            except ValueError: pass
    first = None
    for tc in root.iter("testcase"):
        e = tc.find("error")
        if e is not None:
            body = (e.text or "").strip().splitlines()
            el = [l for l in body if l.startswith("E ")]
            msg = (el[-1][1:].strip() if el else (e.get("message") or "")).strip()
            first = f"{tc.get('classname') or tc.get('name')}: {msg}"[:200]
            break
    n["first_error"] = first
    fails = []
    for tc in root.iter("testcase"):
        f = tc.find("failure")
        if f is not None and len(fails) < 3:
            fails.append(f"{tc.get('name')}: {(f.get('message') or '').strip()}"[:220])
    n["fail_sample"] = fails
    return n


def run_tests(env, res):
    """Run every test tree from the root where it collects the most tests.

    Until 2026-10-10 this was one `pytest -x` from the CLI's folder. `-x` stops
    at the first failure (97 test functions graded "1 passed, 1 failed"), a
    tree whose imports are relative to another folder collected nothing and
    was graded 0/0, and collection errors never left the JSON. Now: no `-x`;
    each tree is collected from the work root, the folder holding the tests
    and that folder's parent, and run where the most tests collect; errors and
    timeouts are reported in `error`.
    """
    trees = _test_trees()
    if not trees:
        return None
    t_end = time.time() + TEST_BUDGET
    tot = {"files": sum(len(v) for v in trees.values()), "rc": 0, "passed": 0, "failed": 0,
           "errors": 0, "skipped": 0, "collected": 0, "roots": {}, "error": None}
    errs = []
    for n, (tree, tfiles) in enumerate(sorted(trees.items())):
        rel = os.path.relpath(tree, APP)
        if time.time() > t_end - 20:
            errs.append(f"{rel}: not run, test time budget ({TEST_BUDGET}s) used up"); continue
        roots = [APP, CWD["dir"], tree, os.path.dirname(tree)]
        src = os.path.join(os.path.dirname(tree), "src")
        if os.path.isdir(src):
            roots.append(src)
        roots = [r for r in dict.fromkeys(roots) if r.startswith(APP) and os.path.isdir(r)]
        common = [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "--no-header",
                  "-p", "no:cacheprovider"]
        best, best_n = roots[0], -1
        for r in roots:
            rc, out, err = run(common + ["--collect-only"] + tfiles, env, timeout=90, cwd=r)
            m = re.search(r"(\d+)(?:/\d+)? tests? collected", out + err)
            got = int(m.group(1)) if m else 0
            if got > best_n:
                best, best_n = r, got
        tot["roots"][rel] = os.path.relpath(best, APP)
        jx = f"/tmp/junit-{n}.xml"
        limit = int(max(30, min(TEST_TIMEOUT, t_end - time.time())))
        rc, out, err = run(common + ["--timeout=120", f"--junitxml={jx}"] + tfiles,
                           env, timeout=limit, cwd=best)
        blob = out + err
        j = _junit(jx)
        if rc == -9:
            errs.append(f"{rel}: pytest timed out after {limit}s, counts incomplete")
        # pytest's own summary line is the count of record (junit also counts subtests as
        # tests); junit is the fallback and the source of the error and failure text.
        summ = [l for l in out.splitlines()
                if re.search(r"\b(passed|failed|errors?|skipped|no tests ran)\b.* in [\d.]+s", l)]
        if summ:
            def num(pat):
                m = re.search(pat, summ[-1])
                return int(m.group(1)) if m else 0
            passed, failed, errors, skipped = (num(r"(\d+) passed"), num(r"(\d+) failed"),
                                               num(r"(\d+) errors?\b"), num(r"(\d+) skipped"))
        elif j:
            failed, errors, skipped = j["failures"], j["errors"], j["skipped"]
            passed = max(j["tests"] - failed - errors - skipped, 0)
        else:
            passed = failed = errors = skipped = 0
        tot["passed"] += passed; tot["failed"] += failed
        tot["errors"] += errors; tot["skipped"] += skipped
        tot["collected"] += max(best_n, 0)
        if j and j.get("fail_sample"):
            tot.setdefault("fail_sample", []).extend(j["fail_sample"])
        tot["rc"] = tot["rc"] or rc
        if errors:
            first = (j or {}).get("first_error")
            if not first:
                el = [l for l in blob.splitlines() if l.startswith("E ")]
                first = el[0][1:].strip() if el else ""
            errs.append(f"{rel}: {errors} error(s) (run from {tot['roots'][rel]}): {first}"[:260])
        elif rc not in (0, 1, -9) and passed + failed == 0:
            last = blob.strip().splitlines()[-1] if blob.strip() else ""
            errs.append(f"{rel}: pytest rc={rc}, nothing ran: {last}"[:260])
        elif passed + failed + skipped == 0 and rc != -9:
            errs.append(f"{rel}: no tests collected from {len(tfiles)} file(s)")
    tot["error"] = "; ".join(errs) or None
    return tot


if __name__ == "__main__":
    main()
