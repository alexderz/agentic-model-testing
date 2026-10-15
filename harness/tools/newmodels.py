#!/usr/bin/env python3
"""The standing pipeline for new models (operator 2026-10-15 12:25, CLAW-CHECKS.md "Standing pipeline for new models"):
adds each model's next rows to the queues once its previous stage has run. The models are the rows of newmodels.tsv.

  python3 tools/newmodels.py status              the stage each model has reached
  python3 tools/newmodels.py flags KEY           print "<entry><TAB><test 1's tuned flags>"; exit 1 if test 1 did not run
  python3 tools/newmodels.py aside KEY ...       move KEY's test 1 and test 2 results that did not really run (a failed
                                                 load: run-matrix.sh skips any case with a meta.json) to
                                                 results-wave-[ab]/.retry/, so a rerun of the step tries them again
  python3 tools/newmodels.py t2 KEY ...          give KEY's test 2 row (its t2 matrix) test 1's tuned flags
  python3 tools/newmodels.py t78 KEY ...         append KEY's test 8 (pagoda, orrery) and test 7 run 1 rows to
                                                 matrix-test8.tsv and matrix-test7.tsv; needs test 2 recorded
  python3 tools/newmodels.py rest                append every model's test 3 (3G, 3O) and test 4 (three tickets) run 1
                                                 rows to matrix-newmodels-t3.tsv and -t4.tsv; needs test 2 recorded
  python3 tools/newmodels.py five                append runs 2 to 5 of tests 1, 2, 3 and 4 to the get-to-5 matrices
                                                 (matrix-five-*.tsv); needs the rest recorded. Runs 2 to 5 of the
                                                 one-shots (tests 6, 5) are tools/newmodel_oneshots.sh with REPEATS,
                                                 called by run-next-five.sh for the keys `ready five` prints
  python3 tools/newmodels.py ready five          print the keys whose rest is recorded (one per line)
  options: --dry-run (print, change nothing), --yaml PATH (preflight against a local yaml copy, for tests)

"Recorded" means the case is in <matrix>-tuned.tsv, which tune_and_run.py writes only for a case that really ran
(a failed load, an unreadable result or a harness failure leave the row runnable and out of -tuned.tsv). Every row
carries test 1's tuned flags (the flags column of test 1's row in its -tuned.tsv) and a note with "fixed", so nothing
is tuned again and each case loads the context test 1 ran at (or fails to load and stays runnable). Test 8 runs on the
model's vision entry when it has one (column t8_entry); that entry also holds the vision head on the GPU, which test
1's tune never saw, so its rows start from test 1's line gated at 32k without a budget and without "fixed": the test 8
queue's tune_and_run fills the context for the vision entry itself (Grok review 2026-10-15). A model whose test 1 did
not run gets no rows at all: test 1 is the smoke test.

Appending is idempotent: a case already named in the target matrix (as a row or a commented row) or its -tuned.tsv is
not added again. New rows are first written to tmp/ and checked with tools/preflight.py; they are appended only when
every one of that model's rows passes, so one bad row can never stop a queue's preflight (each queue preflights its
whole matrix) and never holds back another model's rows. A single append per matrix and model (O_APPEND, one write);
the queues read their matrices only when they start a step. An entry whose spec is not multi_agent_ok gets no test 3
rows (test 3 runs several sessions at once; preflight C6).
Exit 1 when a requested model is not ready, a row fails preflight, or the registry is bad.
"""
import argparse, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REG = "newmodels.tsv"
T4_TICKETS = ("bugfix-targets", "config-timeouts", "feature-filter")
T3G_SERVER = "wb-flashnext-sglang"   # the given server for 3G, as in matrix-five-t3.tsv
REST = ("matrix-newmodels-t3.tsv", "matrix-newmodels-t4.tsv")
FIVE = {"a": "matrix-five-a.tsv", "b": "matrix-five-b.tsv", "t3": "matrix-five-t3.tsv", "t4": "matrix-five-t4.tsv"}
TAG = "new-model pipeline"


def p(path):
    return os.path.join(HERE, path)


def rows(path):
    if not os.path.exists(p(path)):
        return []
    return [l.rstrip("\n").split("\t") for l in open(p(path)) if l.strip() and not l.startswith("#")]


def tuned(matrix):
    return matrix[:-4] + "-tuned.tsv"


def named(matrix):
    """Every case named in a matrix (rows and commented rows) and its -tuned.tsv."""
    out = set()
    for f in (matrix, tuned(matrix)):
        if os.path.exists(p(f)):
            for l in open(p(f)):
                m = re.match(r"^(?:#\s*(?:[^\t]*:\s*)?)?([A-Za-z0-9._-]+)\t", l)
                if m:
                    out.add(m.group(1))
    return out


def registry():
    models, bad = [], []
    for r in rows(REG):
        if len(r) != 5:
            bad.append(f"{REG}: not five columns: {r}"); continue
        key, entry, t8, m1, m2 = r
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", key):
            bad.append(f"{REG}: bad key {key!r}"); continue
        one = [x for x in rows(m1) if x[1] == entry]
        two = [x for x in rows(m2) if x[1] == entry]
        if len(one) != 1:
            bad.append(f"{key}: {m1} has {len(one)} rows for {entry}, expected 1"); continue
        if len(two) > 1:
            bad.append(f"{key}: {m2} has {len(two)} rows for {entry}, expected at most 1"); continue
        models.append(dict(key=key, entry=entry, t8=entry if t8 == "-" else t8, m1=m1, m2=m2, c1=one[0][0],
                           c2=two[0][0] if two else None))
    if len({m["key"] for m in models}) != len(models):
        bad.append(f"{REG}: duplicate keys")
    return models, bad


def ran(matrix, case):
    """test 1's (or any stage's) recorded flags for <case>, or None when it did not run."""
    hit = [r for r in rows(tuned(matrix)) if r[0] == case]
    return hit[-1][2] if hit else None


def stage(m):
    f1 = ran(m["m1"], m["c1"])
    if f1 is None:
        return "test 1 not run", f1
    if not m["c2"] or ran(m["m2"], m["c2"]) is None:
        return "test 1 ran", f1
    rest = rest_rows(m, f1)
    if not all(ran(mx, r[0]) is not None for mx, rs in rest.items() for r in rs):
        return "test 2 ran", f1
    return "rest ran", f1


def note(m, what):
    return f"fixed: {what}; test 1's tuned flags ({m['c1']}); {TAG}"


def vis_gated(f1):
    """test 1's line at 32k without a budget: the start of the vision entry's own tune."""
    g = re.sub(r"(^| )-c \d+", r"\1-c 32768", f1)
    return re.sub(r" --reasoning-budget \S+", "", g)


def t78_rows(m, f1):
    if m["t8"] != m["entry"]:   # the head on the GPU: tune the vision entry (no "fixed" in the note)
        f8 = vis_gated(f1)
        n8 = [f"tuned for {m['t8']} with its vision head (gated from test 1's line, {m['c1']}); {w}; {TAG}"
              for w in ("pagoda, run 1", "orrery, run 1")]
    else:
        f8, n8 = f1, [note(m, "pagoda, run 1"), note(m, "orrery, run 1")]
    return {"matrix-test8.tsv": [
                [f"t8-pagoda-{m['key']}-r1", m["t8"], f8, n8[0]],
                [f"t8-orrery-{m['key']}-r1", m["t8"], f8, n8[1]]],
            "matrix-test7.tsv": [[f"t7-{m['key']}-r1", m["entry"], f1, note(m, "run 1")]]}


def multi_ok(entry):
    """The entry's spec says it serves several sessions at once (preflight C6: test 3 needs it)."""
    import json
    try:
        return json.load(open(p(f"engines/entry-specs/{entry}.json"))).get("multi_agent_ok") is True
    except (OSError, ValueError):
        return False


def rest_rows(m, f1, runs=(1,), out=REST):
    # test 3 runs several sessions at once: an entry whose spec is not multi_agent_ok gets no test 3 rows (preflight
    # C6 would fail them), only test 4; "rest ran" then means test 4 ran
    t3, t4 = [], []
    for n in runs:
        if multi_ok(m["entry"]):
            t3 += [[f"t3g-{m['key']}-r{n}", m["entry"], f1, note(m, f"mcp={T3G_SERVER} (run {n})")],
                   [f"t3o-{m['key']}-r{n}", m["entry"], f1, note(m, f"mcp={m['c2']} (run {n})")]]
        t4 += [[f"t4-{t}-{m['key']}-r{n}", m["entry"], f1, note(m, f"ticket={t} run={n}")] for t in T4_TICKETS]
    return {out[0]: t3, out[1]: t4}


def five_rows(m, f1):
    runs = range(2, 6)
    out = rest_rows(m, f1, runs, (FIVE["t3"], FIVE["t4"]))
    out[FIVE["a"]] = [[f"wa-{m['key']}-five-r{n}", m["entry"], f1, note(m, f"repeat {n} (run 1 is {m['c1']})")]
                      for n in runs]
    out[FIVE["b"]] = [[f"wb-{m['key']}-five-r{n}", m["entry"], f1, note(m, f"repeat {n} (run 1 is {m['c2']})")]
                      for n in runs]
    # the one-shots' runs 2-5 are not rows: run-next-five.sh runs tools/newmodel_oneshots.sh with REPEATS, which sets
    # test 1's flags and the reply cap from its context (tools/run_oneshot.py has neither a flags nor a cap column)
    return out


def preflight(plan, yaml_path):
    """Run tools/preflight.py on the new agent rows (one-shot rows have no flags and are not checked). True if ok."""
    os.makedirs(p("tmp"), exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    files = []
    for mx, rs in plan.items():
        rs = [r for r in rs if len(r) == 4]
        if not rs:
            continue
        f = p(f"tmp/.newmodels-{stamp}-{mx}")   # preflight goes by the case names, not the file name
        open(f, "w").write("".join("\t".join(r) + "\n" for r in rs))
        files.append(f)
    if not files:
        return True
    cmd = [sys.executable, "-u", p("tools/preflight.py")] + (["--yaml", yaml_path] if yaml_path else []) + files
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    for l in (r.stdout + r.stderr).splitlines():
        if not l.startswith("ok ") and "IGNORED" not in l:
            print("   preflight: " + l)
    for f in files:
        os.remove(f)
    return r.returncode == 0


def append(plan, dry, yaml_path):
    """Drop rows already named, preflight the rest, append them. True when nothing failed."""
    todo = {}
    for mx, rs in plan.items():
        have = named(mx)
        new = [r for r in rs if r[0] not in have]
        for r in rs:
            if r[0] in have:
                print(f"   {mx}: {r[0]} already there")
        if new:
            todo[mx] = new
    if not todo:
        return True
    if not preflight(todo, yaml_path):
        print("!! preflight failed on the new rows; nothing appended")
        return False
    for mx, rs in todo.items():
        body = "".join("\t".join(r) + "\n" for r in rs)
        for r in rs:
            print(f"   {mx}: + {r[0]}  {r[1]}  {r[2] if len(r) > 2 else '(entry as configured)'}")
        if dry:
            continue
        if not os.path.exists(p(mx)):
            raise SystemExit(f"{mx} does not exist")
        with open(p(mx), "rb") as f:   # a matrix without a final newline would glue the first new row to its last
            f.seek(0, 2)
            if f.tell():
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    body = "\n" + body
        fd = os.open(p(mx), os.O_WRONLY | os.O_APPEND)
        try:
            data = body.encode()
            assert os.write(fd, data) == len(data)
            os.fsync(fd)
        finally:
            os.close(fd)
    return True


def flags_ok(m, f1):
    """test 1's tuned line is a plain llama.cpp flag line with a context (not '-', not a stray note)."""
    return bool(f1) and f1 != "-" and re.fullmatch(r"-ngl \S+ -c \d+( \S+)*", f1) is not None


def cmd_t2(models, keys, dry):
    ok = True
    for m in models:
        if m["key"] not in keys:
            continue
        f1 = ran(m["m1"], m["c1"])
        if not m["c2"]:
            print(f"!! {m['key']}: {m['m2']} has no row for {m['entry']}"); ok = False; continue
        if ran(m["m2"], m["c2"]) is not None:
            print(f"{m['key']}: test 2 ({m['c2']}) already ran"); continue
        if f1 is None:
            print(f"!! {m['key']}: test 1 ({m['c1']}) did not run; no test 2"); ok = False; continue
        if not flags_ok(m, f1):
            print(f"!! {m['key']}: test 1's recorded flags {f1!r} are not a flag line"); ok = False; continue
        lines = open(p(m["m2"])).read().split("\n")
        hit = [i for i, l in enumerate(lines) if l.split("\t")[:1] == [m["c2"]]]
        assert len(hit) == 1, (m["m2"], m["c2"])
        r = lines[hit[0]].split("\t")
        if len(r) < 4 or "fixed" not in r[3]:
            print(f"!! {m['key']}: {m['c2']} note has no 'fixed'; tune_and_run would tune it again"); ok = False; continue
        if r[2] == f1:
            print(f"{m['key']}: {m['c2']} already at test 1's flags {f1}"); continue
        print(f"{m['key']}: {m['c2']} {r[2]} -> {f1} (test 1's)")
        if not dry:
            r[2] = f1
            lines[hit[0]] = "\t".join(r)
            tmp = p(m["m2"]) + ".tmp"
            open(tmp, "w").write("\n".join(lines))
            os.replace(tmp, p(m["m2"]))
    return ok


NOT_RUN = ("load_failed", "variant_failed", "unreadable", "harness_failure", "no_output", "unrecorded")   # tune_and_run


def cmd_aside(models, keys, dry):
    import glob, json
    ok, stamp = True, time.strftime("%Y%m%d-%H%M%S")
    for m in models:
        if m["key"] not in keys:
            continue
        for mx, case in ((m["m1"], m["c1"]), (m["m2"], m["c2"])):
            if not case or ran(mx, case) is not None:
                continue
            for mf in glob.glob(p(f"results-*/{case}/meta.json")):
                d = os.path.dirname(mf)
                try:
                    st = json.load(open(mf)).get("status")
                except Exception:
                    st = "unreadable"
                if st not in NOT_RUN:   # it ran but tune_and_run did not record it: a person decides
                    print(f"!! {case}: status {st} but not in {tuned(mx)}; record it or move it by hand"); ok = False
                    continue
                to = os.path.join(os.path.dirname(d), ".retry", f"{case}-{stamp}")
                print(f"{case}: status {st}, not run; result moved to {to} so the step tries it again")
                if not dry:
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    os.rename(d, to)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "flags", "aside", "t2", "t78", "rest", "five", "ready"])
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yaml")
    a = ap.parse_args()
    models, bad = registry()
    for b in bad:
        print("!! " + b)
    if bad:
        sys.exit(1)
    if a.cmd != "ready" and set(a.keys) - {m["key"] for m in models}:
        sys.exit(f"!! unknown keys: {' '.join(sorted(set(a.keys) - {m['key'] for m in models}))}")
    if a.cmd in ("flags", "aside", "t2", "t78") and not a.keys:
        sys.exit(f"!! {a.cmd} needs model keys")
    if a.cmd == "ready":
        if a.keys != ["five"]:
            sys.exit("!! usage: ready five")
        for m in models:
            st, f1 = stage(m)
            if st == "rest ran" and flags_ok(m, f1):
                print(m["key"])
        return
    if a.cmd == "status":
        for m in models:
            print(f"{m['key']}\t{m['entry']}\t{stage(m)[0]}")
        return
    if a.cmd == "flags":
        if len(a.keys) != 1:
            sys.exit("!! flags takes one key")
        m = [m for m in models if m["key"] == a.keys[0]][0]
        f1 = ran(m["m1"], m["c1"])
        if not flags_ok(m, f1):
            sys.exit(f"!! {m['key']}: test 1 ({m['c1']}) not recorded with a flag line ({f1!r})")
        print(f"{m['entry']}\t{f1}")
        return
    if a.cmd == "aside":
        sys.exit(0 if cmd_aside(models, a.keys, a.dry_run) else 1)
    if a.cmd == "t2":
        sys.exit(0 if cmd_t2(models, a.keys, a.dry_run) else 1)
    ok = True
    for m in models:   # one preflight and append per model: one model's bad row never holds back another's
        if a.cmd == "t78" and m["key"] not in a.keys:
            continue
        st, f1 = stage(m)
        need = "rest ran" if a.cmd == "five" else "test 2 ran"
        order = ["test 1 not run", "test 1 ran", "test 2 ran", "rest ran"]
        if order.index(st) < order.index(need):
            print(f"{m['key']}: {st}; no {a.cmd} rows yet")
            if a.cmd == "t78":
                ok = False
            continue
        if not flags_ok(m, f1):
            print(f"!! {m['key']}: test 1's recorded flags {f1!r} are not a flag line"); ok = False; continue
        if a.cmd in ("rest", "five") and not multi_ok(m["entry"]):
            print(f"{m['key']}: {m['entry']} is not multi_agent_ok; no test 3 rows (test 4 only)")
        add = {"t78": t78_rows, "rest": rest_rows, "five": five_rows}[a.cmd](m, f1)
        print(f"{m['key']}: {a.cmd}")
        if not append(add, a.dry_run, a.yaml):
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
