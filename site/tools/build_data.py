#!/usr/bin/env python3
"""Build site/data/bakeoff.json, the one file the page reads, from data already in this repository:

  reports/dashboard/data.json      models, runs (tests 1 and 2), test 3, engine A/B speeds, timeline, events, picks
  oneshots/{orrery,pagoda}/grades.tsv and */frames/*.webp     one-shot grades; frames are copied to site/frames/
  site/data/curated.json           hand-written: title, test catalogue, headline findings, links

  python3 -I site/tools/build_data.py [--dashboard PATH]

Rendered frames (webp) and the models' own pages (page.html, orrery.svg; byte for byte, opened only in a sandboxed
iframe) are copied into site/frames/ and site/live/. The output then goes
through a publication check: it fails on anything that looks like a private address, host path or account name.
Stdlib only; deterministic for the same inputs.
"""
import csv, glob, json, os, re, shutil, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SITE = os.path.join(ROOT, "site")
dash = sys.argv[sys.argv.index("--dashboard") + 1] if "--dashboard" in sys.argv else os.path.join(ROOT, "reports/dashboard/data.json")
D = json.load(open(dash))
C = json.load(open(os.path.join(SITE, "data/curated.json")))

# Keep what describes a model; drop storage records and file names of vision heads.
models = {}
for k, m in D["models"].items():
    v = m.get("vision") or {}
    models[k] = {f: m.get(f) for f in ("id", "family", "label", "base", "arch", "engine", "quant", "kind", "uncensored", "note")}
    models[k]["vision"] = {"label": v.get("label"), "status": v.get("status")} if v else None

RUN_KEEP = ("case", "model", "test", "agent", "checks", "tests_pass", "tests_fail", "subcmds", "tps", "minutes",
            "compactions", "ctx", "kv", "verdict", "finished")
# Case ids are ours; one names a host. Rename it the same way everywhere it is referenced.
CASE_RENAME = {"wa-saturn-smoke-qwen3.8-27b-vllm": "wa-host-smoke-qwen3.8-27b-vllm"}
ren = lambda c: CASE_RENAME.get(c, c)
runs = []
for r in D["runs"]:
    o = {f: r.get(f) for f in RUN_KEEP}
    o["case"] = ren(o["case"])
    s = r.get("struggle") or {}
    o["struggle"] = {f: s.get(f) for f in ("compiles", "failed_compiles", "rust_errors", "loc", "errors_per_kloc")} if s else None
    runs.append(o)
T3_KEEP = ("case", "model", "flavor", "mcp_facts", "api_facts", "judgement_right", "rubric", "note", "tps", "minutes", "finished")
test3 = [{f: r.get(f) for f in T3_KEEP} for r in D.get("test3", [])]
ab = [{f: r.get(f) for f in ("model", "engine", "variant", "decode", "quote", "prefill", "vram", "error")} for r in D.get("ab", [])]


def oneshots(test, key):
    rows = []
    path = os.path.join(ROOT, "oneshots", key, "grades.tsv")
    lines = [l for l in open(path) if not l.startswith("#")]
    for r in csv.DictReader(lines, delimiter="\t"):
        case = r["case"]
        src = sorted(glob.glob(os.path.join(ROOT, "oneshots", key, case, "frames", "*.webp")),
                     key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
        frames = []
        for p in src:
            rel = os.path.join("frames", key, case, os.path.basename(p))
            os.makedirs(os.path.dirname(os.path.join(SITE, rel)), exist_ok=True)
            shutil.copyfile(p, os.path.join(SITE, rel))
            frames.append(rel)
        # The model's own page (Alex 2026-10-22: "We want to serve the pagodas and orrery on the site. The code is safe").
        # Copied byte for byte, never edited; the page opens it only in <iframe sandbox="allow-scripts">.
        live = None
        own = os.path.join(ROOT, "oneshots", key, case, "page.html" if key == "pagoda" else "orrery.svg")
        if os.path.isfile(own):
            live = os.path.join("live", key, case, os.path.basename(own))
            os.makedirs(os.path.dirname(os.path.join(SITE, live)), exist_ok=True)
            shutil.copyfile(own, os.path.join(SITE, live))
        num = lambda x: float(x) if x not in ("", None) and re.fullmatch(r"-?[0-9.]+", x) else None
        rows.append({"case": case, "entry": r["entry"], "test": test, "finish": r.get("finish"),
                     "tokens": num(r.get("tokens")), "wall_s": num(r.get("wall_s")), "tok_s": num(r.get("tok_s")),
                     "points": {k: num(r.get(k)) for k in "ABCDE"}, "total": num(r.get("total")),
                     "note": r.get("note") or "", "frames": frames, "live": live})
    return rows


picks = json.loads(json.dumps(D.get("recs", {})))
for grp in ("overall", "uncensored"):
    for p in picks.get(grp, []):
        p["cases"] = [ren(c) for c in p.get("cases", [])]
# The lab notebook shows results, not queue and harness housekeeping.
EVENT_KINDS = {"finding", "grading", "grades", "engine", "model", "tests", "test", "settings"}
HOSTY = re.compile(r"lan\.example|vpn\.example|\btitan\b|\bIris\b")  # entries about our own hosts and services
events = [e for e in D.get("events", []) if e.get("kind") in EVENT_KINDS and not HOSTY.search(e.get("text") or "")][:80]

shutil.rmtree(os.path.join(SITE, "frames"), ignore_errors=True)
shutil.rmtree(os.path.join(SITE, "live"), ignore_errors=True)
hw = dict(D.get("hardware", {}))
hw["weights"] = "read over the network from a NAS, ~180-280 MB/s first load"
out = {
    "schema": "bakeoff-site/1",
    "generated": D.get("generated"),
    "built": __import__("datetime").datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
    "title": C["title"], "tagline": C["tagline"], "links": C["links"],
    "hardware": hw, "caveats": D.get("caveats", []),
    "tests": C["tests"], "findings": C["findings"],
    "picks": picks, "timeline": D.get("timeline", []),
    "events": events,
    "models": models, "runs": runs, "test3": test3, "ab": ab,
    "oneshots": {"orrery": oneshots(5, "orrery"), "pagoda": oneshots(6, "pagoda")},
}
c = out["counts"] = {"models": len(models), "runs": len(runs), "test3": len(test3),
                     "oneshots": sum(len(v) for v in out["oneshots"].values()),
                     "frames": sum(len(r["frames"]) for v in out["oneshots"].values() for r in v),
                     "pass": sum(r["verdict"] == "pass" for r in runs),
                     "live": sum(1 for v in out["oneshots"].values() for r in v if r["live"])}
body = json.dumps(out, indent=1, ensure_ascii=False, sort_keys=False)

# Publication check: nothing private may leave.
# (No rule for "Saturn": the orrery notes name the planet; the one host mention, hardware.weights, is rewritten above.)
BAD = [r"(?i)saturn-", r"\bIris\b", r"lan\.example", r"vpn\.example", r"\b10\.\d+\.\d+\.\d+\b", r"\b192\.168\.\d+\.\d+\b", r"\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+\b",
       r"(?i)\bpluto\b", r"\bnas/", r"/srv/", r"/var/home", r"/home/(?!operator)", r"(?i)derzhi", r"(?i)alex\.", r"BEGIN [A-Z ]*PRIVATE KEY",
       r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"]
hits = [(p, m.group(0)) for p in BAD for m in re.finditer(p, body)]
if hits:
    sys.exit("publication check failed: " + "; ".join(f"{p} -> {h!r}" for p, h in hits[:20]))
open(os.path.join(SITE, "data/bakeoff.json"), "w").write(body + "\n")
print(json.dumps(c))
