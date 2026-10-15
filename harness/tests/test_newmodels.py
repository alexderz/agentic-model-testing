"""Offline test of the standing new-model pipeline (CLAW-CHECKS.md "Standing pipeline for new models", operator
2026-10-15 12:25) and its Saluki and DSpark parts, all in a temporary copy of the repo (nothing on titan, nothing in
the checkout changes):
  1. Saluki: tools/add_saluki_entry.py --simulate on titan's lcpp6-q38-27b-cyber-q5 entry, tools/write_saluki_spec.py
     --yaml, the spec references (add_entry_specs.new_yaml), tools/preflight.py --yaml on matrix-saluki-a/b.tsv
  2. DSpark: tools/add_dspark_entry.py --simulate on the base entry tools/add_engine_entries.py(.new) would add
  3. tools/newmodels.py on faked -tuned.tsv files: status, flags, aside, t2, t78, rest, five, idempotency, the
     preflight gate, a model that has not run test 1
  4. the queue steps and run-next-five.sh(.new): bash -n, order of calls
  python3 -I tests/test_newmodels.py
"""
import glob, importlib.machinery, importlib.util, json, os, re, shutil, subprocess, sys, tempfile

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT, VIS = "lcpp6-saluki-27b-iq2", "lcpp6-saluki-27b-iq2-vis"
UD = ["lcpp6-lfm25-24b-ud-q4kxl", "lcpp6-lfm25-24b-ud-q5kxl", "lcpp6-lfm25-24b-ud-q6kxl"]
SRC = """  lcpp6-q38-27b-cyber-q5:
    name: "Qwen3.8 27B Uncensored Cyber Q5_K_M on llama.cpp 0.6"
    description: "fixture: titan's entry as of 2026-10-15"
    proxy: "http://llamacpp6:8096"
    checkEndpoint: /health
    cmd: |
      podman run --name llamacpp6 --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/lcpp6-q38-27b-cyber-q5.json
      -e LLAMA_SERVER_SLOTS_DEBUG=1
      --network llama
      --device nvidia.com/gpu=all
      --security-opt label=disable
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      ghcr.io/ggml-org/llama.cpp@sha256:a863a2d1dc2cbc5326c995ae380eec9c57f37a7e1cac944f0c6f43e4e9afff23
      --host 0.0.0.0 --port 8096 -fa on --metrics
      -m /models/llm/q38-27b-cyber-q5/Qwen3.8-27B-Uncensored-Cyber-Q5_K_M.gguf
      --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0
      --chat-template-kwargs '{"enable_thinking":true}'
      -ngl 999 -c 81920 -ctk q8_0 -ctv q8_0 -fit off --reasoning-budget 14480
    cmdStop: /bin/sh -c "podman stop -t 30 llamacpp6 || podman rm -f llamacpp6"
"""
fails = 0


def check(ok, what):
    global fails
    print(("ok    " if ok else "FAIL  ") + what)
    fails += not ok


def run(args, cwd, env=None):
    r = subprocess.run([sys.executable, "-I"] + args, cwd=cwd, capture_output=True, text=True,
                       env=dict(os.environ, **(env or {})), stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


def data(path):
    return [l.rstrip("\n").split("\t") for l in open(path) if l.strip() and not l.startswith("#")]


tmp = tempfile.mkdtemp(prefix="test-newmodels-")
try:
    shutil.copytree(os.path.join(here, "tools"), os.path.join(tmp, "tools"), ignore=shutil.ignore_patterns("__pycache__"))
    for d in ("engines/entry-specs", "engines/model-meta"):
        shutil.copytree(os.path.join(here, d), os.path.join(tmp, d))
    os.makedirs(os.path.join(tmp, "tmp"))
    for f in ["evals.env", "newmodels.tsv", "run-case-sandboxed.sh", "run-case-test3.sh", "run-case-test4.sh",
              "run-case-test7.sh", "run-case-test8.sh"] + sorted(
            os.path.basename(x) for x in glob.glob(os.path.join(here, "matrix-*.tsv"))):
        if os.path.exists(os.path.join(here, f)):
            shutil.copy2(os.path.join(here, f), os.path.join(tmp, f))
    for i in (TEXT, VIS):   # the step writes these; a stale copy must not make the test pass
        for x in glob.glob(os.path.join(tmp, "engines/entry-specs", i + ".json")): os.remove(x)
    sys.path.insert(0, os.path.join(tmp, "tools"))
    import yaml, entry_spec as E, add_entry_specs as A

    # 1. Saluki entries, specs, references, preflight
    y0, y1, y2 = (os.path.join(tmp, n) for n in ("s0.yaml", "s1.yaml", "s2.yaml"))
    lfm = open(os.path.join(here, "tests/test_lfm25_ud.py")).read().split('FIXTURE = """models:\n', 1)[1].split('"""', 1)[0]
    open(y0, "w").write("models:\n" + SRC + lfm)
    rc, out = run(["tools/add_lfm25_ud_entry.py", "--simulate", y0, y2], tmp)
    check(rc == 0 and all(i in out for i in UD), "fixture: the LFM2.5 UD entries")
    rc, out = run(["tools/add_saluki_entry.py", "--simulate", y2, y1], tmp)
    check(rc == 0 and TEXT in out and VIS in out, f"saluki add --simulate adds both ({out.strip()[-200:]})")
    rc, out = run(["tools/add_saluki_entry.py", "--simulate", y1, y2], tmp)
    check(rc == 0 and "nothing" in out and open(y1).read() == open(y2).read(), "saluki add is idempotent")
    M = yaml.safe_load(open(y1))["models"]
    t, v = M[TEXT]["cmd"].split("\n"), M[VIS]["cmd"].split("\n")
    check([l for l in t if l.startswith("-ngl ")] == ["-ngl 999 -c 32768 -ctk q8_0 -ctv q8_0 -fit off"], "saluki: gated line")
    check("-m /models/llm/underdog-saluki-27b/Underdog-Saluki-27B-1.0-IQ2-mix.gguf" in t
          and "--temp 0.6 --top-p 0.95 --top-k 20 --min-p 0" in t and not any(l.startswith("--label") for l in t)
          and not any("cyber" in l.lower() for l in t), "saluki: own weights, card sampling, no copied label")
    check([l for l in v if not l.startswith("--mmproj ")] == t
          and v.index("--mmproj /models/llm/underdog-saluki-27b/mmproj-Underdog-Saluki-27B-1.0-Q8_0.gguf")
          == t.index("-m /models/llm/underdog-saluki-27b/Underdog-Saluki-27B-1.0-IQ2-mix.gguf") + 1,
          "saluki -vis: the text cmd plus the head right after -m")
    rc, out = run(["tools/write_saluki_spec.py", "--yaml", y1], tmp)
    check(rc == 0, "saluki spec writer runs" + ("" if rc == 0 else ": " + out[-600:]))
    for i in (TEXT, VIS):
        s = json.load(open(os.path.join(tmp, "engines/entry-specs", i + ".json")))
        check(s["model_id"] == i and s["served_context"] == 32768 and s["kv_type"] == "q8_0"
              and s["thinking"]["server_budget"] is None and s["cmd_sha256"] == E.cmd_hash(M[i]["cmd"])
              and s["sampling"]["temp"] == 0.6 and not E.validate(s, i), f"{i}: spec")
    yt = os.path.join(tmp, "st.yaml")   # a rerun after the tune: titan carries the tuned line
    open(yt, "w").write(open(y1).read().replace(
        "-ngl 999 -c 32768 -ctk q8_0 -ctv q8_0 -fit off",
        "-ngl 999 -c 262144 -ctk q8_0 -ctv q8_0 -fit off --reasoning-budget 24000", 1))
    rc, out = run(["tools/add_saluki_entry.py", "--simulate", yt, y2], tmp)
    check(rc == 0 and "nothing" in out, "saluki add leaves a tuned entry alone")
    rc, out = run(["tools/write_saluki_spec.py", "--yaml", yt], tmp)
    check(rc == 0, "saluki spec writer accepts a tuned entry" + ("" if rc == 0 else ": " + out[-400:]))
    rc, out = run(["tools/write_saluki_spec.py", "--yaml", y1], tmp)
    refs = {k: f"{E.SPEC_DIR}/{k}.json" for k in ["lcpp6-q38-27b-cyber-q5", "lcpp6-lfm25-24b-q6k", TEXT, VIS] + UD}
    y3 = os.path.join(tmp, "s3.yaml")
    open(y3, "w").write(A.new_yaml(open(y1).read(), refs))
    R = E.refs(open(y3).read())
    check(all(R[i][1] == refs[i] for i in (TEXT, VIS)), "saluki: spec references placed")
    rc, out = run(["tools/preflight.py", "--yaml", y3, "matrix-saluki-a.tsv", "matrix-saluki-b.tsv"], tmp)
    rows = re.findall(r"^(ok  |FAIL)  (matrix-saluki-[ab]\.tsv)  (\S+)", out, re.M)
    check(rc == 0 and len(rows) == 2 and all(r[0] == "ok  " for r in rows), f"saluki preflight: 2 rows ok (rc {rc})")
    if rc: print(out[-2000:])

    # 2. DSpark entry on the base entry as add_engine_entries would write it
    src = [x for x in ("tools/add_engine_entries.py", "tools/add_engine_entries.py.new") if os.path.exists(os.path.join(tmp, x))]
    check(bool(src), "add_engine_entries present")
    if src:
        ld = importlib.machinery.SourceFileLoader("aee", os.path.join(tmp, src[0]))
        aee = importlib.util.module_from_spec(importlib.util.spec_from_loader("aee", ld)); ld.exec_module(aee)
        d0, d1, d2 = (os.path.join(tmp, n) for n in ("d0.yaml", "d1.yaml", "d2.yaml"))
        open(d0, "w").write("models:\n" + aee.block("lcpp7-minicpm-v47-35b-a3b"))
        rc, out = run(["tools/add_dspark_entry.py", "--simulate", d0, d1], tmp)
        check(rc == 0 and "added lcpp7-minicpm-v47-35b-a3b-dspark" in out, f"dspark add ({out.strip()[-300:]})")
        rc, out = run(["tools/add_dspark_entry.py", "--simulate", d1, d2], tmp)
        check(rc == 0 and "nothing" in out and open(d1).read() == open(d2).read(), "dspark add is idempotent")
        D = yaml.safe_load(open(d1))["models"]
        b, n = D["lcpp7-minicpm-v47-35b-a3b"]["cmd"].split("\n"), D["lcpp7-minicpm-v47-35b-a3b-dspark"]["cmd"].split("\n")
        line = ("-md /models/vision/minicpm-v4.7-35b-a3b-dspark/dspark-MiniCPM-V-4_7-35B-A3B-Q8_0.gguf "
                "--spec-type draft-dspark --spec-draft-n-max 15 -ngld 99")
        check([l for l in n if l != line] == b and n.index(line) == b.index(
            "-mm /models/vision/minicpm-v4.7-35b-a3b/mmproj-model-f16.gguf") + 1, "dspark: base cmd + the draft line after -mm")
        open(d2, "w").write("models:\n" + SRC)
        rc, out = run(["tools/add_dspark_entry.py", "--simulate", d2, d1], tmp)
        check(rc != 0 and "not on titan" in out, "dspark add refuses without the base entry")

    # 3. tools/newmodels.py
    NM = ["tools/newmodels.py"]
    rc, out = run(NM + ["status"], tmp)
    check(rc == 0 and len([l for l in out.splitlines() if l.count("\t") == 2]) == 4, f"status lists the four models (rc {rc})")
    for f in glob.glob(os.path.join(tmp, "matrix-lfm25-ud-*-tuned.tsv")) + glob.glob(os.path.join(tmp, "matrix-saluki-*-tuned.tsv")):
        os.remove(f)
    for mx in ("matrix-newmodels-t3.tsv", "matrix-newmodels-t4.tsv"):
        assert not data(os.path.join(tmp, mx)), mx
    rc, out = run(NM + ["flags", "saluki-27b"], tmp)
    check(rc == 1, "flags: exit 1 before test 1")
    rc, out = run(NM + ["t78", "saluki-27b", "--yaml", y3], tmp)
    check(rc == 1 and "no t78 rows" in out, "t78: refuses before test 2")
    F1 = "-ngl 999 -c 262144 -ctk q8_0 -ctv q8_0 -fit off --reasoning-budget 24000"
    open(os.path.join(tmp, "matrix-saluki-a-tuned.tsv"), "w").write(
        f"wa-saluki-27b-iq2\t{TEXT}\t{F1}\tfilled (gated: ...); test 1 once\n")
    rc, out = run(NM + ["flags", "saluki-27b"], tmp)
    check(rc == 0 and out.strip() == f"{TEXT}\t{F1}", f"flags: entry and test 1's flags ({out.strip()})")
    # aside: a failed test 2 load moves, an unrecorded real run stops the step
    os.makedirs(os.path.join(tmp, "results-wave-b/wb-saluki-27b-iq2"))
    mj = os.path.join(tmp, "results-wave-b/wb-saluki-27b-iq2/meta.json")
    json.dump({"status": "ok"}, open(mj, "w"))
    rc, out = run(NM + ["aside", "saluki-27b"], tmp)
    check(rc == 1 and os.path.exists(mj), "aside: an unrecorded real run stops it, nothing moved")
    json.dump({"status": "load_failed"}, open(mj, "w"))
    rc, out = run(NM + ["aside", "saluki-27b"], tmp)
    check(rc == 0 and not os.path.exists(mj) and glob.glob(os.path.join(tmp, "results-wave-b/.retry/wb-saluki-27b-iq2-*")),
          "aside: a failed load moves to .retry")
    bp = os.path.join(tmp, "matrix-saluki-b.tsv")
    rc, out = run(NM + ["t2", "saluki-27b"], tmp)
    b1 = open(bp).read()
    rb = [r for r in data(bp) if r[0] == "wb-saluki-27b-iq2"]
    check(rc == 0 and len(rb) == 1 and rb[0][2] == F1 and rb[0][3].startswith("fixed"), "t2: test 2 row at test 1's flags")
    rc, out = run(NM + ["t2", "saluki-27b"], tmp)
    check(rc == 0 and open(bp).read() == b1, "t2: idempotent")
    open(os.path.join(tmp, "matrix-saluki-b-tuned.tsv"), "w").write(f"wb-saluki-27b-iq2\t{TEXT}\t{F1}\tfixed: ...\n")
    t8, t7 = (os.path.join(tmp, f) for f in ("matrix-test8.tsv", "matrix-test7.tsv"))
    t8a, t7a = open(t8).read(), open(t7).read()
    rc, out = run(NM + ["t78", "saluki-27b", "--yaml", y3], tmp)
    n8 = [r for r in data(t8) if "saluki" in r[0]]
    n7 = [r for r in data(t7) if "saluki" in r[0]]
    G8 = "-ngl 999 -c 32768 -ctk q8_0 -ctv q8_0 -fit off"
    check(rc == 0 and [(r[0], r[1], r[2]) for r in n8] == [("t8-pagoda-saluki-27b-r1", VIS, G8), ("t8-orrery-saluki-27b-r1", VIS, G8)]
          and [(r[0], r[1], r[2]) for r in n7] == [("t7-saluki-27b-r1", TEXT, F1)], f"t78: rows on the -vis / text entries (rc {rc})")
    check(all("fixed" not in r[3] for r in n8) and "fixed" in n7[0][3],
          "t78: the -vis rows are tuned with the head (no fixed, gated at 32k), test 7 keeps test 1's flags")
    if rc: print(out[-1500:])
    check(open(t8).read().startswith(t8a) and open(t7).read().startswith(t7a), "t78: appended, nothing else changed")
    t8b = open(t8).read()
    rc, out = run(NM + ["t78", "saluki-27b", "--yaml", y3], tmp)
    check(rc == 0 and open(t8).read() == t8b and "already there" in out, "t78: idempotent")
    # rest: saluki and the UD Q4 are past test 2 (Q5 and Q6 have no test 1 in this copy); the UD entries are not
    # multi_agent_ok, so the Q4 gets test 4 only
    FL = "-ngl 999 -c 131072 -ctk f16 -ctv f16 -fit off --reasoning-budget 24000"
    open(os.path.join(tmp, "matrix-lfm25-ud-a-tuned.tsv"), "w").write(f"wa-lfm25-24b-ud-q4kxl\t{UD[0]}\t{FL}\tfilled\n")
    open(os.path.join(tmp, "matrix-lfm25-ud-b-tuned.tsv"), "w").write(f"wb-lfm25-24b-ud-q4kxl\t{UD[0]}\t{FL}\tfixed\n")
    rc, out = run(NM + ["rest", "--yaml", y3], tmp)
    r3, r4 = data(os.path.join(tmp, "matrix-newmodels-t3.tsv")), data(os.path.join(tmp, "matrix-newmodels-t4.tsv"))
    tk = ["bugfix-targets", "config-timeouts", "feature-filter"]
    check(rc == 0 and [r[0] for r in r3] == ["t3g-saluki-27b-r1", "t3o-saluki-27b-r1"]
          and "mcp=wb-flashnext-sglang " in r3[0][3] and "mcp=wb-saluki-27b-iq2 " in r3[1][3]
          and [r[0] for r in r4] == [f"t4-{t}-lfm25-ud-q4kxl-r1" for t in tk] + [f"t4-{t}-saluki-27b-r1" for t in tk]
          and all("ticket=" + r[0].split("-lfm25")[0].split("-saluki")[0][3:] + " " in r[3] for r in r4)
          and "not multi_agent_ok" in out, f"rest: 3G and 3O for saluki, three tickets each, no t3 for the UD Q4 (rc {rc})")
    rc, out = run(NM + ["status"], tmp)
    check("lfm25-ud-q4kxl\tlcpp6-lfm25-24b-ud-q4kxl\ttest 2 ran" in out, "status: UD Q4 test 2 ran")
    if rc: print(out[-1500:])
    rc, out = run(NM + ["five", "--yaml", y3], tmp)
    check(rc == 0 and "no five rows yet" in out and not [r for r in data(os.path.join(tmp, "matrix-five-a.tsv")) if "saluki" in r[0]],
          "five: waits until the rest ran")
    with open(os.path.join(tmp, "matrix-newmodels-t3-tuned.tsv"), "w") as f:
        f.write("".join("\t".join(r) + "\n" for r in r3))
    with open(os.path.join(tmp, "matrix-newmodels-t4-tuned.tsv"), "w") as f:
        f.write("".join("\t".join(r) + "\n" for r in r4 if "saluki" in r[0]))   # the UD Q4's test 4 not run yet
    rc, out = run(NM + ["status"], tmp)
    check("saluki-27b\tlcpp6-saluki-27b-iq2\trest ran" in out, "status: rest ran")
    rc, out = run(NM + ["ready", "five"], tmp)
    check(rc == 0 and out.split() == ["saluki-27b"], f"ready five: only saluki ({out.split()})")
    before = {f: open(os.path.join(tmp, f)).read() for f in ("matrix-five-a.tsv", "matrix-five-b.tsv", "matrix-five-t3.tsv",
                                                              "matrix-five-t4.tsv", "matrix-five-t5.tsv", "matrix-five-t6.tsv")}
    rc, out = run(NM + ["five", "--yaml", y3], tmp)
    got = {f: [r for r in data(os.path.join(tmp, f)) if "saluki" in r[0]] for f in before}
    lf = [r for r in data(os.path.join(tmp, "matrix-five-a.tsv")) if "lfm25-ud" in r[0]]
    check(not lf and "lfm25-ud-q4kxl: test 2 ran; no five rows yet" in out, "five: the UD Q4 waits for its test 4")
    check(rc == 0 and [len(got[f]) for f in sorted(got)] == [4, 4, 8, 12, 0, 0], f"five: runs 2-5 of tests 1-4, no one-shot rows (rc {rc}; "
          + ", ".join(f"{f} {len(got[f])}" for f in sorted(got)) + ")")
    if rc: print(out[-1500:])
    check(all(open(os.path.join(tmp, f)).read().startswith(before[f]) for f in before), "five: appended only")
    check([r[0] for r in got["matrix-five-a.tsv"]] == [f"wa-saluki-27b-five-r{n}" for n in range(2, 6)]
          and all(r[2] == F1 for f in ("matrix-five-a.tsv", "matrix-five-t4.tsv") for r in got[f]), "five: names and flags")
    after = {f: open(os.path.join(tmp, f)).read() for f in before}
    rc, out = run(NM + ["five", "--yaml", y3], tmp)
    check(rc == 0 and all(open(os.path.join(tmp, f)).read() == after[f] for f in before), "five: idempotent")
    # the preflight gate: a row that fails preflight is never appended
    a3 = os.path.join(tmp, "matrix-saluki-a-tuned.tsv")
    open(a3, "w").write(f"wa-saluki-27b-iq2\t{TEXT}\t-ngl 999 -c 262144 -ctk q8_0 -ctv q8_0 -fit off --reasoning-budget 999999\t-\n")
    os.remove(os.path.join(tmp, "matrix-newmodels-t3-tuned.tsv"))
    t3p = os.path.join(tmp, "matrix-newmodels-t3.tsv")
    open(t3p, "w").write("# header\n")
    t4p = os.path.join(tmp, "matrix-newmodels-t4.tsv")
    open(t4p, "w").write("# header\n")
    rc, out = run(NM + ["rest", "--yaml", y3], tmp)
    check(rc == 1 and "nothing appended" in out and not data(t3p)
          and [r[0] for r in data(t4p)] == [f"t4-{t}-lfm25-ud-q4kxl-r1" for t in tk],
          "rest: a model whose row fails preflight gets nothing, the other model's rows still go in")
    check(not glob.glob(os.path.join(tmp, "tmp/.newmodels-*")), "preflight temp files removed")

    # 4. steps and run-next-five
    q = os.path.join(here, "queue-new.d")
    steps = {}
    for n in ("16-lfm25-ud-oneshots", "17-lfm25-ud-publish", "18-lfm25-ud-test2", "19a-saluki-test1", "19b-saluki-oneshots",
              "19c-saluki-publish", "19d-saluki-test2", "35-minicpm-dspark-check"):
        x = [os.path.join(q, n + s) for s in (".sh", ".sh.new") if os.path.exists(os.path.join(q, n + s))]
        check(len(x) == 1 and subprocess.run(["bash", "-n", x[0]]).returncode == 0, f"step {n}: one file, bash -n")
        steps[n] = open(x[0]).read() if x else ""
    o = open(os.path.join(here, "tools/newmodel_oneshots.sh")).read()
    check(o.find("free ||") < o.find('set_variant "$entry"') and "8080" not in o.replace("never :8080", ""),
          "newmodel_oneshots: frees the GPU (loopback 8081) before set_variant")
    s = steps["18-lfm25-ud-test2"]
    ix = [s.find(k) for k in ("python3 tools/lfm25_ud_test2.py --aside", "python3 tools/lfm25_ud_test2.py ||", "tune_and_run.py matrix-lfm25-ud-b.tsv", "newmodels.py t78 $ready")]
    check(all(i >= 0 for i in ix) and ix == sorted(ix), "18: aside, flags, test 2, t78 in that order")
    s = steps["19d-saluki-test2"]
    ix = [s.find(k) for k in ("python3 tools/newmodels.py aside", "python3 tools/newmodels.py t2", "tune_and_run.py matrix-saluki-b.tsv", "newmodels.py t78 saluki")]
    check(all(i >= 0 for i in ix) and ix == sorted(ix), "19d: aside, t2, test 2, t78 in that order")
    five = [os.path.join(here, x) for x in ("run-next-five.sh.new", "run-next-five.sh")
            if os.path.exists(os.path.join(here, x)) and "newmodels.py" in open(os.path.join(here, x)).read()]
    check(len(five) >= 1, "run-next-five with the new-model section")
    if five:
        s = open(five[0]).read()
        check(subprocess.run(["bash", "-n", five[0]]).returncode == 0, "run-next-five: bash -n")
        check('REPEATS="2 3 4 5"' in s and "newmodels.py ready five" in s, "run-next-five: one-shot repeats with the cap")
        ix = [s.find(k) for k in ("python3 -u tools/newmodels.py rest", "tune_and_run.py matrix-newmodels-t3.tsv",
                                  "tune_and_run.py matrix-newmodels-t4.tsv", "python3 -u tools/newmodels.py five", "# 1. one-shots")]
        check(all(i >= 0 for i in ix) and ix == sorted(ix), "run-next-five: rest, t3, t4, five, then its own work")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
