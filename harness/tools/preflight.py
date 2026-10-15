#!/usr/bin/env python3
"""Preflight: run every MODEL-CHECKLIST.md check before a queue starts (and in the hourly check).

  preflight.py MATRIX.tsv [MATRIX.tsv ...]     check each row against titan's live specs (read-only ssh)
  preflight.py --harness                       check the operator's daily-driver configs (OpenCode, Pi) against the
                                               specs and print the corrected values (never edits them)
  options: --yaml PATH (a local yaml copy whose references resolve to the repo copies, for dry runs)
           --skip-done (skip rows already in <matrix>-tuned.tsv, as the runner does)

Exit 1 when any row FAILs. WARN lines do not block. Each check names its checklist item (C1, C2, ...), so a failure
points at the rule and the lesson behind it. A queue script runs this first:

  python3 -u tools/preflight.py --skip-done matrix-a.tsv matrix-b.tsv || { echo "!! preflight failed"; exit 1; }
"""
import argparse, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entry_spec as E

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SUFFIXES = {"-pp": "presence_penalty 1.5", "-tb": "thinking budget", "-nothink": "thinking off"}


def rows(path, skip_done):
    done = set()
    tuned = path[:-4] + "-tuned.tsv"
    if skip_done and os.path.exists(tuned):
        done = {l.split("\t")[0] for l in open(tuned) if l.strip() and not l.startswith("#")}
    for l in open(path):
        if not l.strip() or l.startswith("#"): continue
        f = l.rstrip("\n").split("\t")
        if len(f) < 3 or f[0] in done: continue
        yield f[0], f[1], f[2], (f[3] if len(f) > 3 else "")


def effective(spec, flags, note):
    """The spec as set_variant will leave it for this row."""
    ovr = E.note_override(note)
    if flags in ("", "-") and not ovr:
        return spec
    f = flags if flags not in ("", "-") else ""
    if " -ncmoe" in " " + f and " -lm " not in " " + f: f += " -lm none"   # set_variant adds it
    return E.apply_flags(spec, f, ovr) if f or ovr else spec


def case_exists(name):
    arch = subprocess.run(["bash", "-c", f"source {HERE}/evals.env; echo $EVALS_ARCHIVE_RESULTS"],
                          capture_output=True, text=True).stdout.strip()
    for root in (os.path.join(HERE, "results-wave-b"), os.path.join(arch, "results-wave-b") if arch else None):
        if root and os.path.isdir(os.path.join(root, name)): return True
    return False


def check_row(case, entry, flags, note, S, exists):
    out = []
    def r(level, item, msg): out.append((level, item, msg))
    e = S.get(entry)
    if e is None: r("FAIL", "C0", f"no llama-swap entry {entry}"); return out
    if e["spec"] is None: r("FAIL", "C1", f"{entry} has no bakeoff.spec ({'; '.join(e['problems']) or 'no reference'})"); return out
    hard = [p for p in e["problems"] if not p.startswith("stale")]
    if hard: r("FAIL", "C1", "; ".join(hard)); return out
    if any(p.startswith("stale") for p in e["problems"]):
        r("WARN" if flags not in ("", "-") else "FAIL", "C1", "spec is stale against the entry's cmd"
          + (" (this row's flags rewrite it)" if flags not in ("", "-") else "; review it"))
    s = effective(e["spec"], flags, note); m = e["meta"] or {}
    served, reply, ctx, think = E.limits(s)
    # C2/C3: limits
    if served - ctx < E.opencode_margin(served, reply):
        r("FAIL", "C3", f"margin {served - ctx} is below {E.opencode_margin(served, reply)} (engines/ENTRY-SPEC.md)")
    if not think < reply: r("FAIL", "C4", f"thinking {think} is not below the reply limit {reply}")
    sb = s["thinking"]["server_budget"]
    if sb is not None and sb >= reply: r("FAIL", "C4", f"server thinking budget {sb} leaves no room in a {reply}-token reply")
    nc = m.get("native_context")
    if nc is None: r("WARN", "C2", "the model record has no native context")
    elif served > nc: r("WARN", "C2", f"served {served} exceeds the model's native {nc} (rope scaling?)")
    # C5: case suffixes
    ref = re.search(r"mcp=(\S+)", note)
    for suf, what in SUFFIXES.items():
        if ref and ref.group(1).endswith(suf) and not case.endswith(suf):
            r("FAIL", "C5", f"its reference case {ref.group(1)} passed with {suf} ({what}); this case does not "
              f"carry it (name the case {case}{suf}, or put ignore=C5 in the note with the reason)")
    if case.endswith("-nothink") and s["thinking"]["default_on"]:
        r("FAIL", "C5", "case says -nothink but the entry turns thinking on")
    # C6: multi-agent
    if case.startswith("t3") and not s["multi_agent_ok"]:
        r("FAIL", "C6", f"test 3 runs several sessions at once; {entry} is not multi_agent_ok (Strata needs -p2, never SGLang)")
    # C7: required template kwargs (Gemma thinking)
    req = (m.get("requires") or {}).get("chat_template_kwargs") or {}
    have = s["templates"]["chat_template_kwargs"] or {}
    for k, v in req.items():
        if have.get(k) != v: r("FAIL", "C7", f"the model requires chat_template_kwargs {k}={v}; the entry has {have.get(k)!r}")
    # C13: the model's recommended sampling (entry flags plus what the client adds per request)
    for lvl, msg in E.sampling_check(s, m, entry, case): r(lvl, "C13", msg)
    # C8: -ncmoe needs -lm none
    if (s["placement"]["experts_on_cpu"] or 0) > 0 and s["placement"]["mmap"]:
        r("FAIL", "C8", "experts on CPU with mmap on: the first request page-faults the experts off NFS (-lm none)")
    # C9: observability for KrakenViz
    o = s["observability"]
    if s["engine"] == "llama.cpp" and not (o["metrics"] and o["slots_debug"]):
        r("FAIL", "C9", "llama.cpp entry without --metrics and LLAMA_SERVER_SLOTS_DEBUG=1")
    if s["engine"] == "vllm" and not (o["prompt_tokens_details"] and o["force_include_usage"]):
        r("FAIL", "C9", "vLLM entry without --enable-prompt-tokens-details --enable-force-include-usage")
    if s["engine"] in ("strata", "maya", "sglang", "exllamav3") and all(v is None for v in o.values()):
        r("WARN", "C9", f"{s['engine']}: KrakenViz's needs not established yet")
    # C10: weights present
    mf = s.get("model_file")
    if mf and exists and not exists.get(mf, False): r("FAIL", "C10", f"model file {mf} missing on titan")
    if s["storage"] == "ssd" and "hyperqwen" not in (mf or ""):
        r("WARN", "C10", "weights on titan's SSD: rule 8a (stage, then delete or symlink after the run)")
    # C15: a dense model on llama.cpp stays on the GPU
    msg = E.gpu_fit_check(s, m)
    if msg: r("FAIL", "C15", msg)
    # C12: TAKEOVER rule 1, the container entry checklist (a lint of the command; limits never come from it)
    c = " ".join(e["cmd"].split())
    if c.startswith("podman run"):
        need = {"--cap-drop ALL": "cap-drop ALL", "no-new-privileges": "no-new-privileges", "--name ": "a fixed --name"}
        for k, what in need.items():
            if k not in c: r("FAIL", "C12", f"container entry without {what}")
        if re.search(r"(?:^| )-p \d", c): r("FAIL", "C12", "container entry publishes a port (-p)")
        if "--env-file" in c: r("FAIL", "C12", "--env-file is read inside the llama-swap container; use -e")
        img = re.search(r" (\S+@sha256:[0-9a-f]{64}|[0-9a-f]{64}|localhost/\S+)(?: |$)", c)
        if not img: r("WARN", "C12", "image not pinned by digest or ID")
        for v in re.findall(r"-v (\S+):(/models\S*)", c):
            if not v[1].endswith(":ro"): r("FAIL", "C12", f"model mount {v[0]} is not read-only")
    # C11: test 3's source case
    if case.startswith("t3o") and ref and not case_exists(ref.group(1)):
        r("WARN", "C11", f"test-2 source case {ref.group(1)} not found yet (fine if an earlier queue step makes it)")
    ign = set(re.findall(r"ignore=([C0-9,]+)", note)[0].split(",")) if "ignore=" in note else set()
    return [(("IGNORED" if lvl == "FAIL" and item in ign else lvl), item, msg) for lvl, item, msg in out]


GENERATORS = {"run-case-sandboxed.sh": "test 1/2/2T OpenCode config", "tools/test3_config.py": "test 3 OpenCode config",
              "run-case-test7.sh": "test 7 OpenCode config", "run-case-test8.sh": "test 8 OpenCode config"}


def loop_guard():
    """C14: the harness generators set OpenCode's doom_loop to deny (headless `opencode run` approves "ask")."""
    bad = 0
    for f, what in GENERATORS.items():
        txt = open(os.path.join(HERE, f)).read()
        if re.search(r'"doom_loop":\s*"deny"', txt):
            print(f"ok    C14 {f} ({what}) sets doom_loop deny")
        else:
            bad += 1; print(f"FAIL  C14 {f} ({what}) does not set \"doom_loop\": \"deny\"")
    return bad


def harness(S):
    """Daily-driver configs: OpenCode and Pi limits against the specs."""
    problems = 0
    oc = os.path.expanduser("~/.config/opencode/opencode.json"); pi = os.path.expanduser("~/.pi/agent/models.json")
    rowsout = []
    o = json.load(open(oc)) if os.path.exists(oc) else {}
    for pn, p in (o.get("provider") or {}).items():
        for k, m in (p.get("models") or {}).items():
            lim = m.get("limit") or {}; rowsout.append(("opencode", k, lim.get("context"), lim.get("output"),
                                                        (m.get("options") or {}).get("thinking_token_budget")))
    p = json.load(open(pi)) if os.path.exists(pi) else {}
    for pn, pv in (p.get("providers") or {}).items():
        for m in pv.get("models") or []:
            rowsout.append(("pi", m.get("id"), m.get("contextWindow"), m.get("maxTokens"), None))
    dl = (o.get("permission") or {}).get("doom_loop", "ask (default)") if o else None
    if o:
        print(("WARN" if dl == "allow" else "ok  ") + f"  opencode doom_loop: {dl}"
              + (" (allow turns OpenCode's loop guard off)" if dl == "allow" else " (interactive: ask is right)"))
    for tool, k, ctx, out, tb in rowsout:
        e = S.get(k)
        if not e or e["spec"] is None:
            print(f"WARN  {tool:8} {k}: no spec to check against"); continue
        served, reply, c, think = E.limits(e["spec"])
        bad = []
        if ctx is None or ctx > c: bad.append(f"context {ctx} -> {c}")
        if out is None or out > reply: bad.append(f"output {out} -> {reply}")
        if tb is not None and tb >= (out or reply): bad.append(f"thinking_token_budget {tb} -> {think}")
        if bad:
            problems += 1
            print(f"FAIL  {tool:8} {k} (served {served}): " + "; ".join(bad))
        else:
            print(f"ok    {tool:8} {k}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("matrices", nargs="*"); ap.add_argument("--yaml"); ap.add_argument("--harness", action="store_true")
    ap.add_argument("--skip-done", action="store_true")
    a = ap.parse_args()
    S = E.load(titan=not a.yaml, yaml_path=a.yaml)
    if a.harness:
        sys.exit(1 if harness(S) else 0)
    files = sorted({e["spec"]["model_file"] for e in S.values() if e["spec"] and e["spec"].get("model_file")})
    exists = {}
    if files and not a.yaml:   # --yaml is an offline dry run: no ssh, C10 unchecked
        prog = "import json,os,sys\nprint(json.dumps({p: os.path.exists(p) for p in sys.argv[1:]}))"
        exists = json.loads(E.ssh("python3 - " + " ".join(files), stdin=prog))
    fails = loop_guard() if a.matrices else 0
    for mx in a.matrices:
        for case, entry, flags, note in rows(mx, a.skip_done):
            res = check_row(case, entry, flags, note, S, exists)
            f = [x for x in res if x[0] == "FAIL"]; fails += bool(f)
            print(f"{'FAIL' if f else 'ok  '}  {os.path.basename(mx)}  {case}  ({entry})")
            for lvl, item, msg in res: print(f"      {lvl} {item}: {msg}")
    print(f"preflight: {fails} row(s) failing")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
