#!/usr/bin/env python3
"""Grade the screening case by EXECUTING the model's module.

Reference cases live here, not in the model's tests -- a model that writes
tests matching its own bug passes its own suite. Both are recorded: `own_tests`
says whether its suite passes, `checks` is whether the code is correct.

Run inside a container: this imports and executes model-written code.

  score-screen.py <case-dir> <case> <model> <flags> <load_s> <vram> <dur_s> [stop]
"""
import json, os, subprocess, sys

# argv matches distil-meta.py so the runner can call either:
#   <case-dir> <case> <model> <flags> <load_s> <vram> <dur> [stop]
CASE_DIR, CASE, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
LOAD_S, VRAM, DUR = sys.argv[5], sys.argv[6], sys.argv[7]
WORK = os.path.join(CASE_DIR, "work")

PARSE = [("PT1H30M", 5400), ("P1D", 86400), ("PT0S", 0), ("P1W", 604800),
         ("P1DT2H3M4S", 93784), ("PT90M", 5400), ("PT1.9S", 1), ("P0D", 0)]
# Lists, not sets: these are written to refcases.json for the in-container
# probe and sets are not JSON serializable. A negative control on a
# known-good module caught this -- otherwise every model would have
# crashed the grader and been recorded as a model failure.
FORMAT = [(5400, ["PT1H30M"]), (0, ["PT0S"]), (86400, ["P1D", "PT24H"]),
          (93784, ["P1DT2H3M4S"])]
# 93784 = 1d 2h 3m 4s. The original expectation here said "2d 3h 4m 5s",
# which is simply wrong, and would have docked every model one check for
# being correct. Reference cases get verified, not eyeballed.
HUMAN = [(0, "0s"), (5400, "1h 30m"), (93784, "1d 2h 3m 4s"), (59, "59s")]
BAD = ["", "nonsense", "P", "1H30M", "PT", None, 5]

probe = r'''
import json, sys, traceback
sys.path.insert(0, ".")
res = {"import": False, "parse": [], "format": [], "human": [], "bad": [],
       "error": None}
try:
    import durations as d
    res["import"] = True
except Exception:
    res["error"] = traceback.format_exc()[-400:]
    print(json.dumps(res)); raise SystemExit
CASES = json.load(open(sys.argv[1]))
for text, want in CASES["parse"]:
    try:
        got = d.parse_duration(text); res["parse"].append([text, want, got, got == want])
    except Exception as e:
        res["parse"].append([text, want, f"{type(e).__name__}", False])
for secs, allowed in CASES["format"]:
    try:
        got = d.format_duration(secs); res["format"].append([secs, got, got in allowed])
    except Exception as e:
        res["format"].append([secs, f"{type(e).__name__}", False])
for secs, want in CASES["human"]:
    try:
        got = d.humanize(secs); res["human"].append([secs, want, got, got.strip() == want])
    except Exception as e:
        res["human"].append([secs, want, f"{type(e).__name__}", False])
for bad in CASES["bad"]:
    try:
        d.parse_duration(bad); res["bad"].append([repr(bad), "no_raise", False])
    except ValueError:
        res["bad"].append([repr(bad), "ValueError", True])
    except Exception as e:
        # Raising the wrong type is a real defect, but distinguish it from
        # silently accepting garbage.
        res["bad"].append([repr(bad), type(e).__name__, False])
print(json.dumps(res))
'''

out = {"case": CASE, "model": MODEL, "status": "unknown", "sandboxed": True,
       "load_s": LOAD_S, "vram_mib": VRAM, "duration_s": DUR}

files = sorted(f for f in os.listdir(WORK) if f.endswith(".py")) if os.path.isdir(WORK) else []
out["py_files"] = files
if "durations.py" not in files:
    out["status"] = "no_module"
    out["reason"] = f"durations.py not written (found: {files})"
    json.dump(out, open(os.path.join(CASE_DIR, "meta.json"), "w"), indent=2)
    print(json.dumps({k: out[k] for k in ("case", "model", "status", "reason")}, indent=2)); raise SystemExit

cases_path = os.path.join(CASE_DIR, "refcases.json")
json.dump({"parse": PARSE, "format": FORMAT, "human": HUMAN, "bad": BAD}, open(cases_path, "w"))
probe_path = os.path.join(WORK, "_probe.py")
open(probe_path, "w").write(probe)

try:
    r = subprocess.run([sys.executable, "_probe.py", cases_path], cwd=WORK,
                       capture_output=True, text=True, timeout=120)
    res = json.loads((r.stdout or "").strip().splitlines()[-1])
except Exception as e:
    res = {"import": False, "error": f"probe failed: {type(e).__name__}: {e}"}

out["detail"] = res
def rate(rows, idx):
    return f"{sum(1 for x in rows if x[idx])}/{len(rows)}" if rows else "0/0"
out["imports"] = bool(res.get("import"))
out["parse_ok"] = rate(res.get("parse", []), 3)
out["format_ok"] = rate(res.get("format", []), 2)
out["human_ok"] = rate(res.get("human", []), 3)
out["badinput_ok"] = rate(res.get("bad", []), 2)

# CLI, exercised as a user would.
cli = {}
for args, want_rc in ([["parse", "PT1H30M"], 0], [["format", "5400"], 0], [["parse", "junk"], "nonzero"]):
    try:
        c = subprocess.run([sys.executable, "durations.py", *args], cwd=WORK,
                           capture_output=True, text=True, timeout=60)
        okrc = (c.returncode == 0) if want_rc == 0 else (c.returncode != 0)
        clean = "Traceback" not in (c.stderr or "")
        cli[" ".join(args)] = {"rc": c.returncode, "out": (c.stdout or "").strip()[:40],
                               "ok": okrc and clean, "no_traceback": clean}
    except Exception as e:
        cli[" ".join(args)] = {"ok": False, "error": type(e).__name__}
out["cli"] = cli
out["cli_ok"] = f"{sum(1 for v in cli.values() if v.get('ok'))}/{len(cli)}"

# The model's own suite, reported separately and never used as the verdict.
try:
    t = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=WORK,
                       capture_output=True, text=True, timeout=300)
    blob = (t.stdout or "") + (t.stderr or "")
    out["own_tests"] = {"rc": t.returncode, "tail": blob.strip().splitlines()[-1][:120] if blob.strip() else ""}
except Exception as e:
    out["own_tests"] = {"error": type(e).__name__}

n_pass = sum(1 for k in ("parse", "format", "human", "bad")
             for x in res.get(k, []) if x[-1])
n_tot = sum(len(res.get(k, [])) for k in ("parse", "format", "human", "bad"))
out["checks"] = f"{n_pass}/{n_tot}"
# Screening verdict: can this model write functional code at all?
if not out["imports"]:
    out["status"] = "broken"
elif n_tot and n_pass / n_tot >= 0.8 and out["cli_ok"].startswith(("2/", "3/")):
    out["status"] = "functional"
elif n_tot and n_pass / n_tot >= 0.5:
    out["status"] = "partial"
else:
    out["status"] = "broken"

json.dump(out, open(os.path.join(CASE_DIR, "meta.json"), "w"), indent=2)
print(json.dumps({k: out[k] for k in ("case", "model", "status", "checks", "imports",
                                      "parse_ok", "format_ok", "human_ok",
                                      "badinput_ok", "cli_ok")}, indent=2))
