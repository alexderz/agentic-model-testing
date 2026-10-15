#!/usr/bin/env python3
"""Unit checks for the engine A/B tools (Model Master 2, 2026-10-15), run by tests/test_engine_ab.sh: the scoring of
tools/maya_digits_probe.py, and the specs tools/add_clone_entry.py wrote into a --sim root (valid by
tools/entry_spec.py's rules, cmd_sha256 of the new cmd, the overrides applied). Prints PASS / FAIL lines.
  python3 -I tests/test_engine_ab.py SIMROOT"""
import json, os, re, sys
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(HERE, "tools"))
import maya_digits_probe as P
import entry_spec as ES
fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def call(name, args):
    return {"tool_calls": [{"function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}]}


W = {"path": "/srv/data/out-504.csv", "offset": 8571, "limit": 20}
check("digits: exact", P.score("read_file", W, call("read_file", W))[:2] == (True, False))
check("digits: integer as a digit string", P.score("read_file", W, call("read_file", dict(W, offset="8571")))[0])
check("digits: split by spaces", P.score("read_file", W, call("read_file", dict(W, offset="8 5 7 1")))[:2] == (False, True))
check("digits: split by a comma", P.score("read_file", W, call("read_file", dict(W, offset="8,571")))[:2] == (False, True))
check("digits: a digit doubled", P.score("read_file", W, call("read_file", dict(W, path="/srv/data/out-5504.csv")))[:2] == (False, True))
check("digits: wrong number, not split", P.score("read_file", W, call("read_file", dict(W, limit=21)))[:2] == (False, False))
check("digits: wrong tool", not P.score("read_file", W, call("run_command", W))[0])
check("digits: no call", P.score("read_file", W, {"content": "8571"})[3] == "no tool call")
check("digits: arguments not JSON", P.score("read_file", W, call("read_file", "{offset: 8571"))[3].startswith("arguments"))
C = {"command": "head -n 20 /srv/data/part-504.txt", "timeout": 600000}
check("digits: command, whitespace and backticks", P.score("run_command", C, call("run_command",
      {"command": "`head  -n 20 /srv/data/part-504.txt`", "timeout": 600000}))[0])
check("digits: command split", P.score("run_command", C, call("run_command",
      {"command": "head -2 0 /srv/data/part-504.txt", "timeout": 600000}))[:2] == (False, True))
recs, text = P.joblog(640, 41)
cs = P.cases(recs, 41)
check("digits: four cases, lookups name a record in the log",
      len(cs) == 4 and all(f"Record {q.split('record ')[1][:5]}" in text for _, q, _, _ in cs[2:]))
check("digits: the log is deterministic", P.joblog(640, 41)[1] == text)

root = sys.argv[1] if len(sys.argv) > 1 else ""
if root:
    import yaml
    y = yaml.safe_load(open(root + ES.YAML_PATH))["models"]
    for new, src in (("strata44-flash-next-pcie", "strata42-flash-next-pcie"),
                     ("exl3-qwen3.8-27b-dflash2-162", "exl3-qwen3.8-27b-dflash2"),
                     ("exl3-qwen3.8-27b-dflash2-162-ctx128k", "exl3-qwen3.8-27b-dflash2"),
                     ("maya1111-glm-5.3-flash", "maya-glm-5.3-flash")):
        if not os.path.exists(f"{root}/home/operator/ai/config/specs/{new}.json"):
            check(f"sim: {new} spec written", False); continue
        s = json.load(open(f"{root}/home/operator/ai/config/specs/{new}.json"))
        o = json.load(open(f"{root}/home/operator/ai/config/specs/{src}.json"))
        check(f"sim: {new} spec valid", ES.validate(s, new) == [])
        check(f"sim: {new} cmd_sha256 matches the new cmd", new in y and s["cmd_sha256"] == ES.cmd_hash(y[new]["cmd"]))
        check(f"sim: {new} label points at its own spec",
              ES.LABEL_RE.findall(y[new]["cmd"]) == [f"/home/operator/ai/config/specs/{new}.json"])
        check(f"sim: {new} engine_version changed", s["engine_version"] != o["engine_version"])
        same = {k for k in o if k not in ("generated", "cmd_sha256", "model_id", "engine_version", "report",
                                          "served_context", "thinking", "role")}
        check(f"sim: {new} other spec fields as the source's", all(s[k] == o[k] for k in same))
    s = json.load(open(f"{root}/home/operator/ai/config/specs/exl3-qwen3.8-27b-dflash2-162-ctx128k.json"))
    c = y.get("exl3-qwen3.8-27b-dflash2-162-ctx128k", {}).get("cmd", "")
    check("sim: ctx128k window, budget and volume", s["served_context"] == 131072 and s["thinking"]["server_budget"] == 24000
          and "TABBY_MODEL_CACHE_SIZE=131072" in c and "TABBY_MODEL_REASONING_BUDGET_TOKENS=24000" in c
          and "-v exllamav3-162-cache:/cache" in c and "exllamav3-cache:" not in c)
    m = json.load(open(f"{root}/home/operator/ai/maya/configs/glm-5.3-flash-v1111.json"))
    check("sim: maya config env", m.get("env") == {"STRATA_GLM_RAM_GB": "95", "STRATA_GLM_RAM_RESIDENT": "1"}
          and m["log"] == "/logs/glm-5.3-flash-v1111.log")
    st = json.load(open(f"{root}/home/operator/ai/strata/data/configs/flash-next-44-pcie.json"))
    check("sim: strata config log", st["log"] == "/logs/flash-next-44-pcie.log")

# add_clone_entry.rewrite(): a write that fails puts the original bytes back (same inode); a changed file is refused
import tempfile
import add_clone_entry as A
d = tempfile.mkdtemp(); yp = os.path.join(d, "llama-swap.yaml"); orig = b"models:\n  a:\n    cmd: x\n" * 50
open(yp, "wb").write(orig); ino = os.stat(yp).st_ino
real_fsync, calls = os.fsync, []
def bad_fsync(fd):
    calls.append(fd)
    if len(calls) == 1: raise OSError(28, "No space left on device")
    real_fsync(fd)
os.fsync = bad_fsync
try: A.rewrite(yp, orig, b"models: {}\n", yp + ".bak"); raised = ""
except RuntimeError as e: raised = str(e)
finally: os.fsync = real_fsync
check("rewrite: a failed write raises and the original is back, same inode",
      "the original is back" in raised and open(yp, "rb").read() == orig and os.stat(yp).st_ino == ino)
try: A.rewrite(yp, orig + b"#", b"models: {}\n", yp + ".bak"); raised = ""
except RuntimeError as e: raised = str(e)
check("rewrite: a yaml that changed since the plan is refused, untouched",
      "changed while" in raised and open(yp, "rb").read() == orig)
A.rewrite(yp, orig, b"models: {}\n", yp + ".bak")
check("rewrite: a good write, same inode", open(yp, "rb").read() == b"models: {}\n" and os.stat(yp).st_ino == ino)
print("unit:", "all PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
