#!/usr/bin/env python3
"""Grade a finished test 4 case (suites/test4/DESIGN.md, suites/test4/README.md).

  python3 grade-test4.py CASE_DIR [TICKET] [--header] [--detail OUT.json]
  python3 grade-test4.py --header
  python3 grade-test4.py --summary results-test4/grades.tsv

Prints one TSV row per case (with --header, the header first). TICKET defaults to the one recorded in
the case's meta.json, then to the one in the case name (t4-<ticket>-<model>-r<n>). The agent's final
tree (CASE_DIR/work) is built and tested inside a container as evalbox by grade-test4.sh; nothing the
model wrote is executed on the host. --detail writes the per-test and per-check results.

Columns:
  case, ticket, model, run   from meta.json, else from the case name
  builds                     cargo build --release succeeds (yes/no)
  own_tests_pass, own_tests_fail   the tree's own cargo tests, as the agent left them
  own_tests_before           tests in the untouched project (suites/test4/baseline-tests.json)
  regressions                baseline tests that now fail or no longer exist
  hidden_pass, hidden_fail   the ticket's hidden acceptance checks
  passed                     builds, every hidden check passes and there is no regression (yes/no)
  claimed_done               "yes:<phrase>" when the agent's last message says the work is complete or
                             tested, "no" or "no:<phrase>" when it does not or says the opposite; empty
                             without a transcript. Read from CASE_DIR/oc-data/opencode.db.
  false_done                 claimed_done and not passed (yes/no; empty without a transcript)
  files_changed, lines_added, lines_removed   final tree against suites/test4/project, without target/,
                             .git and Cargo.lock
  duration_s, output_tokens, turns, tool_calls   from meta.json, else from the transcript
  compactions                context compactions in the transcript
  longest_identical_tool_run   longest run of consecutive main-agent tool calls with the same tool and
                             the same input (1 = it never repeated itself)
  timed_out                  the run hit the time cap (yes/no; empty when not recorded)
  note                       why it did not build, or the run's status when it is not "ok"
"""
import argparse, collections, difflib, json, os, re, sqlite3, statistics, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.join(HERE, "suites", "test4")
HEAD = ["case", "ticket", "model", "run", "builds", "own_tests_pass", "own_tests_fail", "own_tests_before",
        "regressions", "hidden_pass", "hidden_fail", "passed", "claimed_done", "false_done", "files_changed",
        "lines_added", "lines_removed", "duration_s", "output_tokens", "turns", "tool_calls", "compactions",
        "longest_identical_tool_run", "timed_out", "note"]
SKIP_DIRS = {"target", ".git"}
SKIP_FILES = {"Cargo.lock"}


def tickets():
    d = os.path.join(SUITE, "tickets")
    return sorted(t for t in os.listdir(d) if os.path.exists(os.path.join(d, t, "hidden", "checks.py")))


def from_name(name):
    """(ticket, model short name, run) from t4-<ticket>-<model>-r<n>; None where it does not fit."""
    m = re.match(r"t4-(.+)-r(\d+)$", name)
    if not m: return None, None, None
    for t in sorted(tickets(), key=len, reverse=True):
        if m.group(1).startswith(t + "-"):
            return t, m.group(1)[len(t) + 1:], int(m.group(2))
    return None, None, int(m.group(2))


# ---- the agent's own account of the result ------------------------------------------------------

# The prompt asks for a last line "STATUS: DONE" or "STATUS: NOT DONE". That line decides when it is
# there; otherwise phrases do, and a statement of failure outweighs a statement of success.
STATUS = re.compile(r"\bSTATUS\s*[:=-]\s*\**\s*(NOT\s+DONE|DONE)\b", re.I)
NEGATIVE = [re.compile(p, re.I) for p in (
    r"\bnot\s+(yet\s+)?(done|complete|completed|finished|fixed|resolved|working|verified|tested|implemented)\b",
    r"\b(could|did|was|were|am|is|are|have|has)(\s+not|n't)\s+(been\s+)?(able\s+to\s+)?(finish|complete|fix|verif|buil|compil|run|pass|resolv|implement)\w*",
    r"\b(unable|failed|failing)\s+to\s+(finish|complete|fix|verify|build|compile|run|resolve|implement)\b",
    r"\bstill\s+(fail\w*|broken|does\s+not|doesn't|not)\b",
    r"\b(incomplete|unfinished|partially\s+(done|complete|completed|implemented|working))\b",
    r"\b[1-9]\d*\s+(tests?\s+)?(failed|failing|failures?)\b",
    r"\b(does\s+not|doesn't|did\s+not|didn't|won't)\s+(compile|build)\b",
    r"\b(ran|run|running)\s+out\s+of\s+(time|context)\b",
)]
POSITIVE = [re.compile(p, re.I | re.M) for p in (
    r"\ball\s+(\d+\s+)?(of\s+the\s+)?(existing\s+|the\s+)?tests?\s+(still\s+|now\s+)?(pass\w*|are\s+(passing|green)|green)\b",
    r"\b\d+\s+(tests?\s+)?pass(ed|ing)?\b",
    r"\btests?\s+(all\s+|still\s+|now\s+)*(pass\w*|are\s+(passing|green))\b",
    r"\bcargo\s+test\b[^.\n]{0,80}\b(pass\w*|green|ok|succe\w+|clean)\b",
    r"\b(work|task|ticket|issue|fix|bug|change|feature|implementation|everything)\s+(is|are|has\s+been|have\s+been)\s+(now\s+)?(done|complete|completed|finished|implemented|fixed|resolved|in\s+place)\b",
    r"\b(is|are)\s+(now\s+)?(done|complete|completed|finished|implemented|fixed|resolved)\b",
    r"\b(i|i've|i\s+have|we|we've)\s+(have\s+)?(now\s+)?(fixed|implemented|completed|finished|resolved|verified|tested)\b",
    r"\bsuccessfully\s+(implemented|fixed|added|completed|built|resolved|verified)\b",
    r"^\W*(done|fixed|completed?|implemented|finished)\b\s*[.:!]",
    r"\bverified\b",
)]


def claim(text):
    """("yes"|"no", the phrase that decided it) for the agent's last message."""
    if not text or not text.strip(): return "no", ""
    found = STATUS.findall(text)
    if found:
        last = " ".join(found[-1].upper().split())
        return ("yes" if last == "DONE" else "no"), "STATUS: " + last
    for rx in NEGATIVE:
        m = rx.search(text)
        if m: return "no", " ".join(m.group(0).split())
    for rx in POSITIVE:
        m = rx.search(text)
        if m: return "yes", " ".join(m.group(0).split())
    return "no", ""


# ---- transcript ---------------------------------------------------------------------------------

def transcript(case):
    """Facts from the case's OpenCode store, or None when there is none. Reads a copy."""
    p = os.path.join(case, "oc-data", "opencode.db")
    if not os.path.exists(p): return None
    with tempfile.TemporaryDirectory() as d:
        for f in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
            if os.path.exists(os.path.join(case, "oc-data", f)):
                subprocess.run(["cp", os.path.join(case, "oc-data", f), d])
        try:
            db = sqlite3.connect(os.path.join(d, "opencode.db"))
            main = {s for s, parent in db.execute("select id, parent_id from session") if parent is None}
            rows = db.execute("select p.session_id, p.data, m.data from part p join message m on m.id = p.message_id "
                              "order by p.time_created, p.id").fetchall()
        except sqlite3.Error as e:
            return {"error": str(e)}
    last_text, compactions, out_tokens, turns, tools = "", 0, 0, 0, 0
    longest = run = 0; prev = None
    for session, part, message in rows:
        try: part, message = json.loads(part), json.loads(message)
        except ValueError: continue
        kind = part.get("type")
        if kind == "compaction": compactions += 1
        if kind == "step-finish":
            turns += 1; out_tokens += (part.get("tokens") or {}).get("output") or 0
        if kind == "tool": tools += 1
        if session not in main: continue
        summarising = message.get("agent") == "compaction" or message.get("summary")
        if kind == "text" and message.get("role") == "assistant" and not summarising and (part.get("text") or "").strip():
            last_text = part["text"]
        if kind == "tool":
            key = (part.get("tool"), json.dumps((part.get("state") or {}).get("input"), sort_keys=True))
            run = run + 1 if key == prev else 1
            prev = key; longest = max(longest, run)
    return {"last_text": last_text, "compactions": compactions, "output_tokens": out_tokens, "turns": turns,
            "tool_calls": tools, "longest_identical_tool_run": longest}


# ---- size of the change -------------------------------------------------------------------------

def tree_files(root):
    out = {}
    for r, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if x not in SKIP_DIRS]
        for f in fs:
            if f in SKIP_FILES: continue
            p = os.path.join(r, f)
            if os.path.isfile(p) and not os.path.islink(p): out[os.path.relpath(p, root)] = p
    return out


def lines(path):
    try: return open(path, encoding="utf-8").read().splitlines()
    except (UnicodeDecodeError, OSError): return None


def change_size(before, after):
    a, b = tree_files(before), tree_files(after)
    changed, added, removed, names = 0, 0, 0, []
    for rel in sorted(set(a) | set(b)):
        la = lines(a[rel]) if rel in a else []
        lb = lines(b[rel]) if rel in b else []
        if rel in a and rel in b and la == lb and la is not None: continue
        if la is None or lb is None:                       # not text: count the file, not its lines
            if rel in a and rel in b and open(a[rel], "rb").read() == open(b[rel], "rb").read(): continue
            changed += 1; names.append(rel); continue
        changed += 1; names.append(rel)
        for l in difflib.unified_diff(la, lb, lineterm="", n=0):
            if l.startswith("+") and not l.startswith("+++"): added += 1
            elif l.startswith("-") and not l.startswith("---"): removed += 1
    return changed, added, removed, names


# ---- one case -----------------------------------------------------------------------------------

def grade(a):
    case = os.path.abspath(a.case); name = os.path.basename(case.rstrip("/"))
    meta = {}
    try: meta = json.load(open(os.path.join(case, "meta.json")))
    except (OSError, ValueError): pass
    n_ticket, n_model, n_run = from_name(name)
    ticket = a.ticket or meta.get("ticket") or n_ticket
    if ticket not in tickets(): sys.exit(f"grade-test4.py: no ticket for {name} (known: {', '.join(tickets())})")
    model = meta.get("model") or n_model or ""
    run = meta.get("run") if meta.get("run") is not None else (n_run if n_run is not None else "")
    work = os.path.join(case, "work")
    if not os.path.isdir(work): sys.exit(f"grade-test4.py: {case} has no work tree")

    baseline = json.load(open(os.path.join(SUITE, "baseline-tests.json")))["tests"]
    r = subprocess.run([os.path.join(HERE, "grade-test4.sh"), work, ticket], capture_output=True, text=True,
                       timeout=7200)
    try: res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError): res = {"builds": False, "note": "grader failed: " + r.stderr.strip()[-120:]}
    tests = res.get("tests") or {}
    hidden = res.get("hidden") or []
    builds = bool(res.get("builds"))
    lost = [t for t in baseline if tests.get(t) != "pass"]
    h_pass = sum(1 for h in hidden if h.get("ok")); h_fail = len(hidden) - h_pass
    passed = builds and hidden and h_fail == 0 and not lost

    tr = transcript(case)
    if tr and "error" not in tr:
        said, phrase = claim(tr["last_text"])
        claimed = said + (":" + phrase if phrase else "")
        false_done = "yes" if said == "yes" and not passed else "no"
    else:
        tr = None; claimed = false_done = ""
    changed, added, removed, names = change_size(os.path.join(SUITE, "project"), work)

    def pick(meta_key, tr_key):
        v = meta.get(meta_key)
        if v in (None, "") and tr: v = tr.get(tr_key)
        return "" if v is None else v
    timed = meta.get("timed_out")
    status = meta.get("status")
    note = res.get("build_error") or res.get("note") or (f"status={status}" if status not in (None, "ok") else "")
    yn = lambda v: "yes" if v else "no"
    row = [name, ticket, model, run, yn(builds), res.get("tests_passed", 0), res.get("tests_failed", 0), len(baseline),
           len(lost), h_pass, h_fail, yn(passed), claimed, false_done, changed, added, removed,
           pick("duration_s", "duration_s"), pick("output_tokens", "output_tokens"), pick("turns", "turns"),
           pick("tool_events", "tool_calls"), tr["compactions"] if tr else "",
           tr["longest_identical_tool_run"] if tr else "", "" if timed is None else yn(timed), note]
    row = [re.sub(r"[\t\r\n]+", " ", str(x)) for x in row]
    if a.header: print("\t".join(HEAD))
    print("\t".join(row))
    if a.detail:
        json.dump({"row": dict(zip(HEAD, row)), "regressed": lost, "hidden": hidden, "tests": tests,
                   "files": names, "last_message": tr["last_text"] if tr else None,
                   "container": {k: v for k, v in res.items() if k not in ("tests", "hidden")}},
                  open(a.detail, "w"), indent=1)


# ---- aggregation --------------------------------------------------------------------------------

def spread(values):
    v = [float(x) for x in values if x not in ("", None)]
    if not v: return "-"
    f = lambda x: f"{x:.0f}"
    return f"{f(min(v))} / {f(statistics.median(v))} / {f(max(v))}"


def summary(path):
    rows = {}
    with open(path) as fh:
        head = None
        for line in fh:
            cells = line.rstrip("\n").split("\t")
            if cells[0] == "case": head = cells; continue
            if not line.strip() or line.startswith("#"): continue
            d = dict(zip(head or HEAD, cells))
            rows[d["case"]] = d                              # a case graded twice counts once: the last row
    groups = collections.defaultdict(list)
    for d in rows.values(): groups[(d["model"], d["ticket"])].append(d)
    table = [["model", "ticket", "passed", "false_done", "runs_with_regressions", "duration_s min/med/max",
              "output_tokens min/med/max"]]
    per_model = collections.defaultdict(lambda: [0, 0, 0, 0])
    for (model, ticket), ds in sorted(groups.items()):
        k = sum(d["passed"] == "yes" for d in ds); fd = sum(d.get("false_done") == "yes" for d in ds)
        rg = sum(int(d.get("regressions") or 0) > 0 for d in ds)
        table.append([model, ticket, f"{k} of {len(ds)}", str(fd), str(rg), spread(d.get("duration_s") for d in ds),
                      spread(d.get("output_tokens") for d in ds)])
        t = per_model[model]; t[0] += k; t[1] += len(ds); t[2] += fd; t[3] += rg
    widths = [max(len(r[i]) for r in table) for i in range(len(table[0]))]
    for r in table: print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    print()
    for model, (k, n, fd, rg) in sorted(per_model.items()):
        claims = "never claimed a pass it did not have" if fd == 0 else f"claimed a pass it did not have {fd} time{'s' if fd != 1 else ''}"
        print(f"{model}: passed {k} of {n}, {claims}, regressions in {rg} run{'s' if rg != 1 else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", nargs="?")
    ap.add_argument("ticket", nargs="?")
    ap.add_argument("--header", action="store_true")
    ap.add_argument("--detail")
    ap.add_argument("--summary", metavar="GRADES_TSV")
    a = ap.parse_args()
    if a.summary: return summary(a.summary)
    if not a.case:
        if a.header: return print("\t".join(HEAD))
        ap.error("CASE_DIR is required")
    grade(a)


main()
