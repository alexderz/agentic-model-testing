#!/usr/bin/env python3
"""Audit every case ever run (live area, NAS archive, superseded folders, rejected models) for the failure signature
of each MODEL-CHECKLIST.md lesson. When a lesson is learned, its signature goes in SIGNATURES below and this runs over
everything, so results we wrote off as the model's fault get a second look.

  audit_runs.py [--out tmp/audit-YYYY-MM-DD.tsv] [--case SUBSTR]

Output columns: case, verdict (from the report or test 3 grades), status, lesson, evidence.
status: SUSPECT (signature found and the case did not pass: the result may be the harness's fault),
        AFFECTED-PASS (signature found, the case passed anyway: it paid in time or compactions),
        INFO (a weaker signal worth a look).
"""
import argparse, datetime, glob, json, os, re, sqlite3, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entry_spec as E

HERE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OVERFLOW = re.compile(r"ContextOverflowError|maximum context length is (\d+)|exceeds the available context size \((\d+)")
MAXLEN = re.compile(r"maximum context length (?:is|of) (\d+)|available context size \((\d+) tokens\)")


def roots():
    arch = subprocess.run(["bash", "-c", f"source {HERE}/evals.env; echo $EVALS_ARCHIVE_RESULTS"],
                          capture_output=True, text=True).stdout.strip()
    out = []
    for base in (HERE, arch):
        for d in sorted(glob.glob(os.path.join(base, "results-*"))):
            if os.path.isdir(d): out += [d, os.path.join(d, "superseded")]
    return [d for d in out if os.path.isdir(d)]


def verdicts():
    v = {}
    try:
        for r in json.load(open(os.path.join(HERE, "report", "data.json")))["runs"]:
            v[r["case"]] = r["verdict"]
    except Exception:
        pass
    g = os.path.join(HERE, "results-test3", "grades.tsv")
    if os.path.exists(g):
        for l in open(g).read().splitlines()[1:]:
            f = l.split("\t")
            if len(f) > 6: v.setdefault(f[0], "pass" if f[6] == "yes" else "fail")
    return v


def scan(case_dir):
    """Signals found in one case folder."""
    s = {"overflow": 0, "served": None, "length_stops": 0, "span_min": None, "steps": 0, "out_tokens": 0}
    ev = os.path.join(case_dir, "events.jsonl")
    first = last = None
    if os.path.exists(ev):
        with open(ev, errors="replace") as f:
            for l in f:
                if OVERFLOW.search(l):
                    s["overflow"] += 1
                    m = MAXLEN.search(l)
                    if m: s["served"] = int(m.group(1) or m.group(2))
                if '"step_finish"' in l:
                    s["steps"] += 1
                    if '"reason":"length"' in l: s["length_stops"] += 1
                    m = re.search(r'"output":(\d+)', l)
                    if m: s["out_tokens"] += int(m.group(1))
                m = re.search(r'"timestamp":(\d{13})', l)
                if m:
                    t = int(m.group(1)); first = first or t; last = t
    # Pi harness sessions: a turn that ends on "length" is a runaway; the session's last stop tells how it ended
    for sf in glob.glob(os.path.join(case_dir, "session", "*.jsonl")):
        stops = re.findall(r'"stopReason":"([a-zA-Z]+)"', open(sf, errors="replace").read())
        s["length_stops"] += stops.count("length")
        if stops: s["pi_last_stop"] = stops[-1]
    if first and last: s["span_min"] = round((last - first) / 60000, 1)
    oc = os.path.join(case_dir, "oc", "opencode.json")
    s["ctx"] = s["out"] = None
    if os.path.exists(oc):
        try:
            c = json.load(open(oc))
            for p in (c.get("provider") or {}).values():
                for m in (p.get("models") or {}).values():
                    lim = m.get("limit") or {}; s["ctx"], s["out"] = lim.get("context"), lim.get("output")
        except Exception:
            pass
    meta = os.path.join(case_dir, "meta.json")
    s["meta"] = json.load(open(meta)) if os.path.exists(meta) else {}
    return s


def tool_streaks(case_dir):
    """Runs of identical consecutive tool calls (same tool, same input) per session: what OpenCode's doom_loop guard
    (3 in a row) now stops. Reads oc-data/opencode.db (main and subagent sessions); falls back to events.jsonl."""
    seqs = {}
    db = os.path.join(case_dir, "oc-data", "opencode.db")
    if os.path.exists(db):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for sid, data in con.execute("select session_id, data from part where json_extract(data,'$.type')='tool' "
                                         "order by session_id, time_created"):
                d = json.loads(data)
                seqs.setdefault(sid, []).append((d.get("tool"), json.dumps((d.get("state") or {}).get("input"), sort_keys=True)))
            con.close()
        except Exception:
            seqs = {}
    if not seqs:
        ev = os.path.join(case_dir, "events.jsonl")
        if os.path.exists(ev):
            for l in open(ev, errors="replace"):
                if '"tool_use"' not in l: continue
                try: e = json.loads(l)
                except Exception: continue
                pt = e.get("part") or {}
                seqs.setdefault(e.get("sessionID"), []).append((pt.get("tool"), json.dumps((pt.get("state") or {}).get("input"), sort_keys=True)))
    runs, longest, what = 0, 0, None
    for seq in seqs.values():
        i = 0
        while i < len(seq):
            j = i
            while j + 1 < len(seq) and seq[j + 1] == seq[i]: j += 1
            n = j - i + 1
            if n >= 3:
                runs += 1
                if n > longest: longest, what = n, f"{seq[i][0]} {seq[i][1][:80]}"
            i = j + 1
    return runs, longest, what


def case_spec(case_dir, model, flags):
    """The spec a finished case ran with (its saved entry-spec.json, else today's repo spec with the case's flags) and
    its model record."""
    saved = os.path.join(case_dir, "entry-spec.json")
    if os.path.exists(saved):
        spec, src = json.load(open(saved)), "saved entry-spec.json"
    else:
        f = os.path.join(HERE, "engines", "entry-specs", f"{model}.json")
        if not model or not os.path.exists(f): return None, None, None
        spec, src = json.load(open(f)), "today's spec + case flags"
        if flags and flags != "-": spec = E.apply_flags(spec, flags)
    rp = E.meta_repo_path(spec.get("model_meta") or "")
    return spec, (json.load(open(rp)) if rp and os.path.exists(rp) else None), src


def case_sampling(case_dir, model, flags, case):
    """C13 results for a finished case: its saved entry-spec.json, else today's repo spec with the case's flags."""
    saved = os.path.join(case_dir, "entry-spec.json")
    if os.path.exists(saved):
        spec, src = json.load(open(saved)), "saved entry-spec.json"
    else:
        f = os.path.join(HERE, "engines", "entry-specs", f"{model}.json")
        if not model or not os.path.exists(f): return None, None
        spec, src = json.load(open(f)), "today's spec + case flags"
        if flags and flags != "-": spec = E.apply_flags(spec, flags)
    rp = E.meta_repo_path(spec.get("model_meta") or "")
    meta = json.load(open(rp)) if rp and os.path.exists(rp) else None
    if meta is None: return None, None
    return E.sampling_check(spec, meta, model, case), src


def served_now(model, flags):
    """What the entry serves today, for cases without an overflow message: the repo spec, or the case's own -c."""
    m = re.search(r"(?:^| )-c (\d+)", flags or "")
    if m: return int(m.group(1)), "the case's -c"
    f = os.path.join(HERE, "engines", "entry-specs", f"{model}.json")
    if os.path.exists(f): return json.load(open(f))["served_context"], "today's spec"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "tmp", f"audit-{datetime.date.today()}.tsv"))
    ap.add_argument("--case")
    a = ap.parse_args()
    V = verdicts()
    cases = {}
    for r in roots():
        for d in sorted(glob.glob(os.path.join(r, "*"))):
            n = os.path.basename(d)
            if not os.path.isdir(d) or n == "superseded" or not re.match(r"(wa|wb|wt|t3[go]|wf|wo)-", n): continue
            if a.case and a.case not in n: continue
            cases.setdefault(n if "superseded" not in r else n + " [superseded]", d)
    pp_pass = {}
    for n, d in cases.items():
        if n.split(" ")[0].endswith("-pp") and V.get(n.split(" ")[0]) == "pass":
            mdl = (scan(d)["meta"] or {}).get("model")
            if mdl: pp_pass[mdl] = n
    rows = []
    for n, d in cases.items():
        s = scan(d); base = n.split(" ")[0]; v = V.get(base, "-")
        bad = v not in ("pass",)
        hit = lambda lesson, ev, strong=True: rows.append((n, v, ("SUSPECT" if bad else "AFFECTED-PASS") if strong else "INFO", lesson, ev))
        model = s["meta"].get("model"); flags = s["meta"].get("flags", "")
        if s["overflow"]:
            hit("C2 served context / C3 margin", f"{s['overflow']} context-overflow errors"
                + (f"; server limit {s['served']}" if s["served"] else ""))
        served, src = (s["served"], "the server's own error") if s["served"] else served_now(model, flags)
        if s["ctx"] and served:
            if s["ctx"] > served:
                hit("C2 served context", f"OpenCode context {s['ctx']} > served {served} ({src})", strong=src != "today's spec")
            elif s["out"] and served - s["ctx"] < s["out"]:
                hit("C3 margin", f"margin {served - s['ctx']} < reply limit {s['out']} (served {served}, {src})", strong=bool(s["overflow"]))
        if s.get("pi_last_stop") in ("length", "error"):
            hit("Pi session ended on " + s["pi_last_stop"], "last turn stopReason " + s["pi_last_stop"]
                + (" (a 400 from the server: context)" if s["pi_last_stop"] == "error" and s["overflow"] else ""),
                strong=s["pi_last_stop"] == "error" and bool(s["overflow"]))
        if s["length_stops"]:
            hit("runaway (length stop)", f"{s['length_stops']} steps hit the reply limit", strong=False)
        if bad and s["span_min"] is not None and s["span_min"] < 10 and s["steps"] < 60:
            hit("early exit", f"{s['span_min']} min, {s['steps']} steps, {s['out_tokens']} output tokens", strong=False)
        res, ssrc = case_sampling(d, model, flags, base)
        fails = [m for lvl, m in (res or []) if lvl == "FAIL"]
        if fails:
            hit("C13 recommended sampling", f"{'; '.join(fails)} [{ssrc}]", strong=ssrc == "saved entry-spec.json")
        spec, meta, ssrc = case_spec(d, model, flags)
        if spec and E.gpu_fit_check(spec, meta):
            hit("C15 dense weights spill to RAM", f"{E.gpu_fit_check(spec, meta).split(';')[0]} [{ssrc}]", strong=ssrc == "saved entry-spec.json")
        runs, longest, what = tool_streaks(d)
        if runs:
            hit("C14 identical tool calls", f"{runs} runs of 3+ identical consecutive tool calls; longest {longest}x: {what}",
                strong=longest >= 10)
        if model in pp_pass and not base.endswith("-pp") and bad and base.startswith(("wa-", "wb-", "wt-", "t3")):
            hit("C5 case suffix", f"{pp_pass[model]} passed with -pp; this case ran without it", strong=False)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        f.write("case\tverdict\tstatus\tlesson\tevidence\n")
        for r in sorted(rows, key=lambda r: ({"SUSPECT": 0, "AFFECTED-PASS": 1, "INFO": 2}[r[2]], r[0])):
            f.write("\t".join(map(str, r)) + "\n")
    from collections import Counter
    c = Counter(r[2] for r in rows)
    print(f"{len(cases)} cases scanned; {c['SUSPECT']} SUSPECT, {c['AFFECTED-PASS']} AFFECTED-PASS, {c['INFO']} INFO -> {a.out}")


if __name__ == "__main__":
    main()
