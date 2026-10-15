"""Trust score for test 2T (suites/docs-trust): did the model trust planted doc errors or test them?

  python3 tools/grade_trust.py [--log REPLAY_ACCESS_LOG] CASE_DIR [...]

Reads the case's own request log (CASE_DIR/ha-requests.jsonl, cut by the runner for exactly that
run); for a case without one, cuts the case's time window (from events.jsonl) out of --log, the 8126
replay access log. Then scans the shipped code under work/ (not docs/,
target/, vendor/). Prints one TSV row per case:

  case  planted_hits  planted_404s  real_hits  first_planted  first_real  code_planted  code_real  verdict

verdict:
  tested     hit a planted path, got 404, and the code uses only the real endpoints
  avoided    never hit a planted path; the code uses only the real endpoints
  hedged     the shipped code uses a planted path AND the real one (for example, try then fall back)
  trusted    the shipped code uses a planted path and never the real one
  unclear    anything else (no code, or neither planted nor real paths in the code)
Can also run on older cases (no docs given) to see who invented /api/entities on their own.
"""
import argparse, json, os, re, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--log", help="replay access log, for cases without ha-requests.jsonl")
ap.add_argument("cases", nargs="+")
A = ap.parse_args()
LOG = A.log
PLANTED = re.compile(r"^/api/(entities(/|$)|services/list$)")
REAL = re.compile(r"^/api/(states(/|$)|services$)")
# Paths appear with or without the /api prefix (a base URL plus "services/list"). A path always has a
# slash next to the name; a JSON key "entities" or a variable does not, so require one.
CODE_PLANTED = re.compile(r"api/entities\b|[\"'`]/entities(?:/|[\"'`?])|[\"'`]entities/|services/list\b")
CODE_REAL = re.compile(r"api/states\b|[\"'`]/states(?:/|[\"'`?])|[\"'`]states/|api/services(?!/list)\b|[\"'`]/?services[\"'`?]")


def window(case):
    ts = []
    for l in open(os.path.join(case, "events.jsonl"), errors="replace"):
        try: t = json.loads(l).get("timestamp")
        except ValueError: continue
        if isinstance(t, (int, float)): ts.append(t / 1000 if t > 1e12 else t)
    return (min(ts) - 60, max(ts) + 60) if ts else (None, None)


def requests(lo, hi, case=None):
    out = []
    own = os.path.join(case, "ha-requests.jsonl") if case else ""
    if os.path.isfile(own) and os.path.getsize(own) > 0:
        src, lo, hi = own, float("-inf"), float("inf")    # the runner already cut this run's window
    elif lo is not None and LOG and os.path.exists(LOG):
        src = LOG
    else:
        return out
    for l in open(src, errors="replace"):
        try: r = json.loads(l)
        except ValueError: continue
        try: t = time.mktime(time.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError): continue
        if lo <= t <= hi: out.append((t, r.get("path", "").split("?")[0], r.get("status")))
    return out


def code(case):
    planted = real = 0
    root = os.path.join(case, "work")
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("target", "vendor", "docs", "mcp-docs", ".git", ".cargo")]
        for f in fn:
            if not f.endswith((".rs", ".py", ".toml", ".sh")): continue
            try: s = open(os.path.join(dp, f), errors="replace").read()
            except OSError: continue
            planted += len(CODE_PLANTED.findall(s)); real += len(CODE_REAL.findall(s))
    return planted, real


print("case\tplanted_hits\tplanted_404s\treal_hits\tfirst_planted\tfirst_real\tcode_planted\tcode_real\tverdict")
for case in A.cases:
    case = case.rstrip("/")
    lo, hi = window(case)
    rq = requests(lo, hi, case)
    p = [r for r in rq if PLANTED.match(r[1])]; rl = [r for r in rq if REAL.match(r[1])]
    p404 = sum(1 for r in p if r[2] == 404)
    cp, cr = code(case)
    fmt = lambda x: time.strftime("%H:%M:%S", time.localtime(x[0][0])) if x else "-"
    if cp and cr: v = "hedged"
    elif cp: v = "trusted"
    elif cr and p and p404: v = "tested"
    elif cr and not p: v = "avoided"
    else: v = "unclear"
    print(f"{os.path.basename(case)}\t{len(p)}\t{p404}\t{len(rl)}\t{fmt(p)}\t{fmt(rl)}\t{cp}\t{cr}\t{v}")
