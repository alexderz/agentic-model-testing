#!/usr/bin/env python3
"""Grade a finished test 3 case (suites/test3/DESIGN.md): the automatic half. RUBRIC.md is the other.

  python3 grade-test3.py CASE_DIR [--fixture fixtures/ha-fixture.json] [--grade-fix]
                                   [--header] [--detail OUT.json]

Prints one TSV row (with --header, the header first). With --detail, writes the per-fact comparison
and every prompt the agent gave mcp-probe (for the rubric). With --grade-fix and a changed server,
runs test 2's grader (grade-mcp.sh, as evalbox) on the agent's final source.

Columns:
  case, flavor        3G (known-good server) or 3O (own server), from the case name t3g-/t3o-
  facts_file          /work/facts.json present and in the asked shape
  mcp_facts, api_facts  correct facts out of 14 for the MCP and the REST side (fixture is truth). Since 2026-10-11
                      (operator: regrade layout-only misses) a right value counts in another layout too: nested
                      groups (lights.total), per-fact {mcp, api} pairs, and the alias paths in ALIASES. A file with
                      no MCP/REST split cannot be attributed and gets no credit. facts_file says "layout" then.
  strict_mcp, strict_api  the count in exactly the asked shape (the grade before 2026-10-11); last two columns
  says_mcp_correct    the agent's own judgement ("mcp_correct")
  judgement_right     its judgement matches its reported MCP values (all 14 right <=> true)
  probe_sessions      mcp-probe sessions started by the main agent
  probe_mcp_calls     tools/call requests the MCP server received (shim log)
  main_mcp_attempts   main-agent calls to an ha_ tool (refused by config; >0 = it tried to bypass)
  main_api_calls      main-agent shell commands that call the REST API (curl/wget/python on $HA_URL)
  main_server_runs    main-agent shell commands that run a built server binary and speak JSON-RPC to it
                      (MCP access without the probe; recorded, not forbidden: operator 2026-10-07)
  server_changed      files under /work/mcp-src differ from the source case
  prebuild            the server as given built before the run (ok/failed)
  fixed_server        with --grade-fix: test 2 grade of the changed server (builds/init/tools/tool_call)
"""
import argparse, collections, filecmp, json, os, re, sqlite3, subprocess, sys, tempfile

KEYS = ["total_entities", "lights_total", "lights_on", "lights_off", "lights_unavailable", "switches_total",
        "unavailable_total", "location_name", "version", "time_zone", "upstairs_current_temperature",
        "upstairs_hvac_mode", "person_avery_state", "lock_services"]
HEAD = ["case", "flavor", "facts_file", "mcp_facts", "api_facts", "says_mcp_correct", "judgement_right",
        "probe_sessions", "probe_mcp_calls", "main_mcp_attempts", "main_api_calls", "main_server_runs", "server_changed",
        "prebuild", "fixed_server", "strict_mcp", "strict_api"]
# Other places a model put a fact when it lost the asked shape (each path is a tuple of keys under one side's view).
_CL = [("climate_trane_ac_upstairs",), ("climate",), ("climate.trane_ac_upstairs",), ("entity_states", "climate.trane_ac_upstairs"),
       ("entities", "climate.trane_ac_upstairs"), ("upstairs",)]
_PE = [("person_avery",), ("person.avery",), ("entity_states", "person.avery"), ("entities", "person.avery")]
_IN = [(), ("installation_info",), ("installation",), ("home_assistant",), ("config",)]
ALIASES = {
    "total_entities": [("total_entities",), ("entities_total",)],
    "lights_total": [("lights_total",), ("lights", "total"), ("lights", "count"), ("domain_counts", "light")],
    "lights_on": [("lights_on",), ("lights", "on")],
    "lights_off": [("lights_off",), ("lights", "off")],
    "lights_unavailable": [("lights_unavailable",), ("lights", "unavailable")],
    "switches_total": [("switches_total",), ("switches", "total"), ("switches", "count"), ("switches",), ("domain_counts", "switch")],
    "unavailable_total": [("unavailable_total",), ("unavailable", "count"), ("unavailable", "total"), ("unavailable_entities", "total"),
                          ("unavailable_entities", "count"), ("unavailable_entities",)],
    "location_name": [g + (k,) for g in _IN for k in ("location_name", "location")],
    "version": [g + ("version",) for g in _IN],
    "time_zone": [g + ("time_zone",) for g in _IN],
    "upstairs_current_temperature": [("upstairs_current_temperature",)] + [g + k for g in _CL for k in (("current_temperature",), ("attributes", "current_temperature"), ("temperature",))],
    "upstairs_hvac_mode": [("upstairs_hvac_mode",)] + [g + (k,) for g in _CL for k in ("hvac_mode", "state", "mode")],
    "person_avery_state": [("person_avery_state",)] + [g + ("state",) for g in _PE] + _PE,
    "lock_services": [("lock_services",), ("lock_services", "services"), ("lock_domain", "services")],
}


def side_views(facts):
    """The MCP and REST views of a facts file in any layout: its "mcp"/"api" sections, or, when every fact carries its
    own {mcp, api|rest} pair, the two projections of that tree. (None, None) when the file has no such split."""
    if not isinstance(facts, dict): return None, None
    if isinstance(facts.get("mcp"), dict) and isinstance(facts.get("api", facts.get("rest")), dict):
        return facts["mcp"], facts.get("api", facts.get("rest"))
    root = facts["facts"] if isinstance(facts.get("facts"), dict) else facts
    hits = [0]
    def project(o, names):
        if isinstance(o, dict):
            for n in names:
                if n in o and "mcp" in o: hits[0] += 1; return o[n]
            return {k: project(v, names) for k, v in o.items()}
        return o
    m, a = project(root, ("mcp",)), project(root, ("api", "rest"))
    return (m, a) if hits[0] else (None, None)


def lookup(view, key):
    """A fact's value in one side's view: the asked key first, then the alias paths; scalars (or a list) only."""
    for path in ALIASES[key]:
        o = view
        for k in path:
            o = o.get(k) if isinstance(o, dict) else None
            if o is None: break
        if o is not None and not isinstance(o, dict) and (key == "lock_services" or not isinstance(o, list)): return o
    return None


def truth(fixture):
    r = json.load(open(fixture))["responses"]
    st = json.loads(r["/api/states"]["body"]); cfg = json.loads(r["/api/config"]["body"])
    sv = json.loads(r["/api/services"]["body"])
    by = {s["entity_id"]: s for s in st}
    lights = [s["state"] for s in st if s["entity_id"].startswith("light.")]
    up = by["climate.trane_ac_upstairs"]
    return {"total_entities": len(st), "lights_total": len(lights), "lights_on": lights.count("on"),
            "lights_off": lights.count("off"), "lights_unavailable": lights.count("unavailable"),
            "switches_total": sum(1 for s in st if s["entity_id"].startswith("switch.")),
            "unavailable_total": sum(1 for s in st if s["state"] == "unavailable"),
            "location_name": cfg["location_name"], "version": cfg["version"], "time_zone": cfg["time_zone"],
            "upstairs_current_temperature": up["attributes"].get("current_temperature"),
            "upstairs_hvac_mode": up["state"], "person_avery_state": by["person.avery"]["state"],
            "lock_services": sorted(next(x["services"] for x in sv if x["domain"] == "lock"))}


def same(got, want):
    if got is None: return False
    if isinstance(want, list):
        # service names count with or without their domain prefix ("lock.unlock" == "unlock")
        return isinstance(got, list) and sorted(str(x).strip().lower().rsplit(".", 1)[-1] for x in got) == [str(x).lower() for x in want]
    if isinstance(want, (int, float)):
        try: return float(got) == float(want)
        except (TypeError, ValueError): return False
    return str(got).strip().lower() == str(want).strip().lower()


def db_parts(case):
    """(sessions, parts) from the case's OpenCode store; parts as (session_id, data dict)."""
    p = os.path.join(case, "oc-data", "opencode.db")
    if not os.path.exists(p): return [], []
    with tempfile.TemporaryDirectory() as d:                  # read a copy: never touch the case
        for f in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
            if os.path.exists(os.path.join(case, "oc-data", f)):
                subprocess.run(["cp", os.path.join(case, "oc-data", f), d])
        db = sqlite3.connect(os.path.join(d, "opencode.db"))
        sessions = db.execute("select id, parent_id, title from session").fetchall()
        parts = [(s, json.loads(x)) for s, x in db.execute("select session_id, data from part order by time_created")]
    return sessions, parts


def changed(src_crate, final):
    def files(root):
        out = {}
        for r, ds, fs in os.walk(root):
            ds[:] = [x for x in ds if x not in ("target", ".git")]
            for f in fs: out[os.path.relpath(os.path.join(r, f), root)] = os.path.join(r, f)
        return out
    a, b = files(src_crate), files(final)
    if set(a) != set(b): return True
    return any(not filecmp.cmp(a[k], b[k], shallow=False) for k in a)


def grade_fix(case, here):
    """Test 2's grader on the agent's final server source (only when it changed it)."""
    with tempfile.TemporaryDirectory(dir=os.path.join(here, "tmp")) as d:
        name = os.path.basename(case.rstrip("/")) + "-fixed"
        os.makedirs(os.path.join(d, name, "work"))
        # a copy, not a symlink: grade-mcp.sh finds the crate with `find`, which does not enter a
        # symlinked starting path
        subprocess.run(f'tar -C "{os.path.join(case, "work", "mcp-src")}" --exclude=./target --exclude=./.git -cf - . '
                       f'| tar -C "{os.path.join(d, name, "work")}" -xf -', shell=True, check=True)
        subprocess.run([os.path.join(here, "grade-mcp.sh"), os.path.relpath(d, here)], cwd=here,
                       capture_output=True, text=True, timeout=3600)
        rows = [l.split("\t") for l in open(os.path.join(d, "mcp-grades.tsv")).read().splitlines()[1:]]
    if not rows: return "grade failed"
    r = rows[0]
    return f"builds={r[1]} init={r[3]} tools={r[4]} tool_call={r[5]} tests={r[6]}/{r[7]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--fixture", default=os.path.join(here, "fixtures", "ha-fixture.json"))
    ap.add_argument("--grade-fix", action="store_true")
    ap.add_argument("--header", action="store_true")
    ap.add_argument("--detail")
    a = ap.parse_args()
    case = os.path.abspath(a.case); name = os.path.basename(case)
    T = truth(a.fixture)

    facts, shape = {}, "no"
    fp = os.path.join(case, "work", "facts.json")
    if os.path.exists(fp):
        try:
            facts = json.load(open(fp))
            shape = "yes" if all(isinstance(facts.get(k), dict) for k in ("mcp", "api")) else "malformed"
        except ValueError: shape = "unparsable"
    if not isinstance(facts, dict): facts, shape = {}, "malformed"
    sec_of = lambda sec: facts.get(sec) if isinstance(facts.get(sec), dict) else {}
    strict = {sec: sum(same(sec_of(sec).get(k), T[k]) for k in KEYS) for sec in ("mcp", "api")}
    views = dict(zip(("mcp", "api"), side_views(facts)))
    per = {sec: {k: {"got": (g := lookup(views[sec], k) if views[sec] is not None else None), "want": T[k], "ok": same(g, T[k])}
                 for k in KEYS} for sec in ("mcp", "api")}
    mcp_ok = sum(v["ok"] for v in per["mcp"].values()); api_ok = sum(v["ok"] for v in per["api"].values())
    if (mcp_ok, api_ok) != (strict["mcp"], strict["api"]): shape = "layout"
    says = facts.get("mcp_correct")
    judged = "-" if says is None else ("yes" if bool(says) == (mcp_ok == len(KEYS)) else "no")

    sessions, parts = db_parts(case)
    main_ids = {s for s, p, _ in sessions if p is None}
    probe_ids = {s for s, p, t in sessions if p is not None and "mcp-probe" in (t or "")}
    tool = lambda d: d.get("type") == "tool"
    main_parts = [d for s, d in parts if s in main_ids and tool(d)]
    probe_prompts = [d["state"].get("input", {}) for d in main_parts if d.get("tool") == "task"]
    main_mcp = sum(1 for d in main_parts if d.get("tool", "").startswith("ha_")
                   or (d.get("tool") == "invalid" and str(d["state"].get("input", {}).get("tool", "")).startswith("ha_")))
    api_re = re.compile(r"(curl|wget|requests|urllib|http)\S*.*(\$HA_URL|\$\{HA_URL\}|8126|host\.containers\.internal)", re.S)
    main_api = sum(1 for d in main_parts if d.get("tool") == "bash"
                   and api_re.search(json.dumps(d["state"].get("input", {}))))
    bin_re = re.compile(r"target/(release|debug)/[A-Za-z0-9_.-]+")
    rpc_re = re.compile(r"jsonrpc|tools/call|\binitialize\b")
    main_runs = sum(1 for d in main_parts if d.get("tool") == "bash"
                    and bin_re.search(c := json.dumps(d["state"].get("input", {}))) and rpc_re.search(c))
    probe_tools = collections.Counter(d.get("tool") for s, d in parts if s in probe_ids and tool(d))

    shim = os.path.join(case, "t3", "shim.jsonl")
    calls = 0; restarts = 0
    if os.path.exists(shim):
        for l in open(shim):
            try: x = json.loads(l)
            except ValueError: continue
            if x.get("kind") == "c2s" and (x.get("msg") or {}).get("method") == "tools/call": calls += 1
            if x.get("kind") == "start": restarts += 1

    src = open(os.path.join(case, "t3", "source.txt")).read().split("\n")[1] if os.path.exists(os.path.join(case, "t3", "source.txt")) else None
    sc = "?" if not src or not os.path.isdir(src) else ("yes" if changed(src, os.path.join(case, "work", "mcp-src")) else "no")
    pb = os.path.join(case, "t3", "prebuild.log")
    pre = "-" if not os.path.exists(pb) else ("ok" if "prebuild: ok" in open(pb, errors="replace").read() else "failed")
    fixed = grade_fix(case, here) if (a.grade_fix and sc == "yes") else "na"

    flavor = "3G" if name.startswith("t3g-") else ("3O" if name.startswith("t3o-") else "?")
    row = [name, flavor, shape, f"{mcp_ok}/{len(KEYS)}", f"{api_ok}/{len(KEYS)}", str(says).lower(), judged,
           str(len(probe_ids)), str(calls), str(main_mcp), str(main_api), str(main_runs), sc, pre, fixed,
           f"{strict['mcp']}/{len(KEYS)}", f"{strict['api']}/{len(KEYS)}"]
    if a.header: print("\t".join(HEAD))
    print("\t".join(row))
    if a.detail:
        json.dump({"row": dict(zip(HEAD, row)), "facts": per, "probe_prompts": probe_prompts,
                   "probe_tool_counts": probe_tools, "server_starts": restarts}, open(a.detail, "w"), indent=1)


main()
