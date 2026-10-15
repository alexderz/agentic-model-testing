"""For each matrix row: fill VRAM with tools/fill_vram.py, then run that one case
with the tuned flags through run-wave-a.sh. Interleaved so testing starts after
the first tune rather than after all of them.

  python3 tools/tune_and_run.py matrix-wave-a2.tsv   (writes <matrix>-tuned.tsv)
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = sys.argv[1]
out = src.replace(".tsv", "-tuned.tsv")
done = set()
if os.path.exists(out):
    done = {l.split("\t")[0] for l in open(out) if l.strip() and not l.startswith("#")}
for line in open(src):
    if not line.strip() or line.startswith("#"):
        continue
    case, mid, flags, note = (line.rstrip("\n").split("\t") + [""])[:4]
    if case in done:
        print(f"skip {case}: already run", flush=True); continue
    if "fixed" in note:
        # Deliberately untuned: a control at the old settings.
        print(f"### fixed {case}: {flags}", flush=True)
        r = subprocess.CompletedProcess([], 0, stdout=flags, stderr="")
    else:
        print(f"### tune {case}", flush=True)
        r = subprocess.run([sys.executable, f"{HERE}/tools/fill_vram.py", mid, flags],
                           capture_output=True, text=True)
    sys.stdout.write(r.stderr); sys.stdout.flush()
    if r.returncode != 0:
        print(f"### TUNE FAILED {case}: keeping gated flags", flush=True)
        tuned = flags
    else:
        tuned = r.stdout.strip().splitlines()[-1]
    # Thinking budget (operator, 2026-10-04): 24k inside the 32k reply cap on
    # every llama.cpp case. Container (vLLM) rows carry "-" and get it per
    # request instead (run-case-sandboxed.sh).
    if tuned != "-" and "--reasoning-budget" not in tuned:
        # The budget must sit well inside the reply cap OpenCode is given
        # (run-case-sandboxed.sh: ctx*0.9/4, max 32000). At 106k context the cap
        # is 23,961, BELOW a flat 24k budget, so the budget never fired and
        # wb-orcasaq2-cyber-27b spent its whole reply thinking (2026-10-05).
        import re as _re
        m = _re.search(r"-c (\d+)", tuned)
        served = int(m.group(1)) if m else 131072
        # Same numbers as entry_spec.limits. The old formula went negative at 32k
        # (--reasoning-budget -1904) and llama-server exited before warm.
        reply = min(32000, served // 4)
        thinking = min(24000, reply - 6000)
        if thinking <= 0 or thinking >= reply:
            print(f"### no reasoning budget at -c {served}: reply {reply}", flush=True)
        else:
            tuned = f"{tuned} --reasoning-budget {thinking}"
    # keep the matrix note: runners read settings from it (test 3: mcp=<case>)
    row = f"{case}\t{mid}\t{tuned}\tfilled (gated: {flags}); {note}\n"
    one = f"{HERE}/tmp/.one-{case}.tsv"
    open(one, "w").write(row)
    print(f"### run {case}: {tuned}", flush=True)
    rc = subprocess.run([f"{HERE}/" + os.environ.get("RUN_SCRIPT", "run-wave-a.sh")], env={**os.environ, "MATRIX": one}).returncode
    # A row is done only when the case really ran: a refused case (no meta.json: replay down, lease refused) or a
    # failed load must stay runnable. 2026-10-10: a restart before the replay was up marked 16 rows done.
    import glob as _glob, json as _json
    st = None
    for mf in _glob.glob(f"{HERE}/results-*/{case}/meta.json"):
        try: st = _json.load(open(mf)).get("status")
        except Exception: st = "unreadable"
    if st is None or st in ("load_failed", "variant_failed", "unreadable", "harness_failure", "no_output", "unrecorded"):
        print(f"### NOT done {case} rc={rc} status={st}: row left runnable", flush=True)
    else:
        open(out, "a").write(row)
        print(f"### done {case} rc={rc}", flush=True)
print("=== BATCH DONE ===", flush=True)
