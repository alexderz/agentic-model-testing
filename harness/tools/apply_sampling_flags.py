"""Apply recommended sampling to llama.cpp entries on titan (operator 2026-10-09: "we should follow the recommendations";
checklist C13). Input: a JSON object {entry: "flags"} on stdin, from tmp/sampling-entry-changes-*.tsv. For each entry,
existing values of the keys being set (--temp, --top-p, --top-k, --min-p) are removed from its cmd, and the flags go on
their own line right before the `-ngl` line (the line set_variant rewrites), or at the end of the cmd if there is none.
Runs ON TITAN with nothing loaded; in place, same inode, backed up; asserts every other entry is unchanged and each
changed entry differs only in sampling flags.
"""
import io, json, os, re, shutil, sys, time, urllib.request, yaml
P = "/home/operator/ai/config/llama-swap.yaml"
W = json.load(sys.stdin)
KEYS = ("--temp", "--top-p", "--top-k", "--min-p")
s = io.open(P).read(); M0 = yaml.safe_load(s)["models"]
for mid, fl in W.items():
    assert mid in M0, mid
    keys = [k for k in KEYS if k + " " in fl + " "]
    m = re.search(r"^  %s:\n(?:(?:    .*|      .*|)\n)*" % re.escape(mid), s, re.M); blk = m.group(0)
    lines = blk.split("\n"); out = []; incmd = False; placed = False
    for l in lines:
        if l.startswith("    cmd: |"): incmd = True; out.append(l); continue
        if incmd and l.startswith("      "):
            for k in keys: l = re.sub(r"\s%s\s+\S+" % re.escape(k), "", l)
            if l.startswith("      -ngl") and not placed: out.append("      " + fl); placed = True
            if l.strip(): out.append(l)
            continue
        if incmd and not l.startswith("      "):
            if not placed: out.append("      " + fl); placed = True
            incmd = False
        out.append(l)
    nb = "\n".join(out); s = s[:m.start()] + nb + s[m.end():]
M = yaml.safe_load(s)["models"]
assert set(M) == set(M0)
strip = lambda c: re.sub(r"\s(--temp|--top-p|--top-k|--min-p)\s+\S+", "", " ".join(c.split()))
for k in M0:
    if k not in W: assert M[k] == M0[k], k
    else:
        assert strip(M[k]["cmd"]) == strip(M0[k]["cmd"]), k
        assert {x: M[k][x] for x in M[k] if x != "cmd"} == {x: M0[k][x] for x in M0[k] if x != "cmd"}, k
if "--dry" in sys.argv:
    for k in W: print(k, "|", " ".join(M[k]["cmd"].split())[-200:])
    sys.exit()
if json.load(urllib.request.urlopen("http://127.0.0.1:8081/running", timeout=10))["running"]:
    sys.exit("a model is loaded; nothing changed")
stamp = time.strftime("%Y%m%d-%H%M%S"); shutil.copy2(P, P + ".bak-sampling-" + stamp); ino = os.stat(P).st_ino
with open(P, "r+") as f: f.seek(0); f.write(s); f.truncate(); f.flush(); os.fsync(f.fileno())
assert os.stat(P).st_ino == ino; time.sleep(20)
print(f"sampling applied to {len(W)} entries; backup .bak-sampling-{stamp}")
