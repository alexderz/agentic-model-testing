"""Build the bake-off report: report/data.json + report/index.html (self-contained, opens from the repo).

  python3 tools/build_report.py --grades-a A.tsv --grades-b B.tsv --trust T.tsv [--ab JSON ...] \
      --cases-a DIR [--cases-a DIR ...] --cases-b DIR [--cases-b DIR ...] --out REPORT_DIR

Every path is an argument (operator 2026-10-07). Case folders are looked up in the --cases-* dirs in
order, so a case can be in the live area or the NAS archive. REPORT_DIR holds template.html and
receives data.json, index.html and artifact.html. HOURLY-CHECK.md has the command line in use.

Data comes from the graded results, never typed in by hand: results-wave-a/grades.tsv (test 1),
results-wave-b/mcp-grades-all.tsv (test 2, with a verified note per row), each case's meta.json
(flags), events.jsonl (tok/s and wall time, same method as tools/tok_s.py) and oc-data/opencode.db
(compactions), plus the llama.cpp v0.6.0 A/B JSONs. The model catalog (family, label, base, arch,
engine, quant, kind, note, vision) is read through tools/catalog.py from the entry specs and model records
(engines/ENTRY-SPEC.md); this file holds no list of models. What is curated here: the timeline of how
the tests changed, and the recommendations, each of which cites the result rows it rests on.
"""
import argparse, csv, glob, json, os, re, sqlite3, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grade_struggle import struggle
import catalog

TOOLS = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description="Build the bake-off report from graded results.")
ap.add_argument("--grades-a", required=True, help="test 1 grade TSV")
ap.add_argument("--grades-b", required=True, help="test 2 grade TSV (mcp-grades-all.tsv)")
ap.add_argument("--trust", required=True, help="test 2T trust labels TSV recorded at grading")
ap.add_argument("--ab", action="append", default=[], help="engine A/B JSON (repeatable)")
ap.add_argument("--cases-a", action="append", required=True, help="dir holding test 1 case folders (repeatable)")
ap.add_argument("--cases-b", action="append", required=True, help="dir holding test 2 case folders (repeatable)")
ap.add_argument("--grades-c", help="test 3 grade TSV (grade-test3.py rows)")
ap.add_argument("--rubric-c", help="test 3 transcript rubric TSV")
ap.add_argument("--cases-c", action="append", default=[], help="dir holding test 3 case folders (repeatable)")
ap.add_argument("--out", required=True, help="report dir with template.html")
A = ap.parse_args()
OUT = A.out


def case_dir(roots, case):
    """First root that holds the case folder (live area before archive); else the first root."""
    for r in roots:
        if os.path.isdir(os.path.join(r, case)): return os.path.join(r, case)
    return os.path.join(roots[0], case)

# ---------------------------------------------------------------- model catalog
# key: llama-swap entry id. Read from the reviewed records through tools/catalog.py; nothing about a model is typed
# in here. kind: stock | abliterated | heretic | uncensored-tune | security-tune
C = {i: catalog.report(i) for i in catalog.entries()}
Q27, FN = "Qwen3.8 27B", "Qwen3.8 Flash-Next"


def known(mid, case, d):
    """False when the graded case names no entry (no case folder or meta.json): it cannot be shown. An entry the
    catalog has no spec for is shown anyway, from the spec saved in the case folder if there is one."""
    if not mid:
        print(f'!! build_report: {case} dropped (no case folder or meta.json, so no entry id)', file=sys.stderr); return False
    if mid not in C:
        try: spec = json.load(open(os.path.join(d, "entry-spec.json")))
        except Exception: spec = None
        C[mid] = catalog.report(mid, spec)
        print(f'!! build_report: {case}: ENTRY {mid!r} HAS NO SPEC in engines/entry-specs; shown from '
              + ("the case's entry-spec.json" if spec else "its id alone (the case has no entry-spec.json)")
              + '. Add the spec with a report block.', file=sys.stderr)
    return True


def tok_span(d):
    ts, o, r = [], 0, 0
    p = os.path.join(d, "events.jsonl")
    if not os.path.exists(p): return None, None
    for l in open(p, errors="replace"):
        try: e = json.loads(l)
        except ValueError: continue
        t = e.get("timestamp") or e.get("time") or ((e.get("part") or {}).get("time") or {}).get("end")
        if isinstance(t, (int, float)): ts.append(t / 1000 if t > 1e12 else t)
        if e.get("type") in ("step_finish", "step-finish"):
            tk = (e.get("part") or {}).get("tokens") or {}
            o += tk.get("output", 0) or 0; r += tk.get("reasoning", 0) or 0
    span = max(ts) - min(ts) if len(ts) > 1 else 0
    if span <= 0: return None, None
    return round((o + r) / span, 1) if (o + r) else None, round(span / 60)


def pi_span(d):
    fs = glob.glob(os.path.join(d, "session", "*.jsonl"))
    if not fs: return None, None, None
    out, ts, comp = 0, [], 0
    for l in open(fs[0]):
        e = json.loads(l)
        if e.get("type") == "compaction": comp += 1
        t = e.get("timestamp")
        if isinstance(t, str):
            try: ts.append(time.mktime(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")))
            except ValueError: pass
        msg = e.get("message") or {}
        if msg.get("role") == "assistant": out += (msg.get("usage") or {}).get("output", 0) or 0
    span = max(ts) - min(ts) if len(ts) > 1 else 0
    return (round(out / span, 1) if span and out else None), (round(span / 60) if span else None), comp


def compactions(d):
    p = os.path.join(d, "oc-data", "opencode.db")
    if not os.path.exists(p): return None
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        n = sum(1 for (x,) in c.execute("select data from part") if json.loads(x).get("type") == "compaction")
        c.close(); return n
    except Exception: return None


def flags_of(d, mid):
    try: f = json.load(open(os.path.join(d, "meta.json"))).get("flags") or "-"
    except Exception: f = "-"
    ctx = re.search(r"-c (\d+)", f); nc = re.search(r"-ncmoe (\d+)", f); kv = re.search(r"-ctk (\S+)", f)
    return dict(flags=f, ctx=int(ctx.group(1)) if ctx else None, ncmoe=int(nc.group(1)) if nc else 0,
                kv=kv.group(1) if kv else None)


CTX_FIXED = {"bonsai2-27b-pq2-med": 253952, "qwen3.8-27b-vllm": 150000, "qwen3.8-27b-vllm-240k": 245760, "qwen3.8-27b-uncensored-vllm": 150000,
             "qwen3.8-27b-vllm-64k": 65536, "qwen3.8-27b-vllm-quote": 57344, "gemma-4-26b-a4b-vllm": 262144,
             "flashnext": 204800, "strata-flash-next": 262144, "strata-flash-next-p2": 262144, "strata-swift15": 262144, "strata-coder": 262144}


# The graded notes used internal profile letters; the report names the settings instead.
PLAIN = {"profile B (64k)": "vLLM, DFlash2 drafts, 64k context", "profile C (57k)": "vLLM, DFlash2 15-token drafts, 57k context",
         "B overflowed": "the 64k setup overflowed"}
def plain(n):
    for k, v in PLAIN.items(): n = n.replace(k, v)
    return n


# KV cache type for container entries, whose flags are not in the case row (from their llama-swap commands)
KV_FIXED = {"bonsai2-27b-pq2-med": "f16", "flashnext": "fp8_e4m3", "qwen3.8-27b-vllm": "fp8", "qwen3.8-27b-vllm-64k": "fp8", "qwen3.8-27b-vllm-quote": "fp8",
            "qwen3.8-27b-uncensored-vllm": "fp8", "qwen3.8-27b-vllm-240k": "4/2-bit (KVarN)",
            "strata-flash-next": "int8", "strata-flash-next-p2": "int8", "strata-swift15": "int8", "strata-coder": "int8"}


def read_tsv(p):
    rows = list(csv.reader(open(p), delimiter="\t"))
    h = rows[0]; return [dict(zip(h, r + [""] * (len(h) - len(r)))) for r in rows[1:] if r and not r[0].startswith("#")]


def finished(d):
    """When the case ended: the modification time of its meta.json (kept by the archive copy)."""
    try: return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(d, "meta.json"))))
    except Exception: return None


def model_of(d, case):
    try: return json.load(open(os.path.join(d, "meta.json")))["model"]
    except Exception: return None


runs = []
for row in read_tsv(A.grades_a):
    case = row["case"]; d = case_dir(A.cases_a, case)
    mid = model_of(d, case)
    if not known(mid, case, d): continue
    checks = sum(row[k] == "yes" for k in ("help", "reads", "bad_input", "bad_auth", "no_crash"))
    agent = "Pi" if "-pi" in case else "OpenCode"
    if agent == "Pi": tps, mins, comp = pi_span(d)
    else: (tps, mins), comp = tok_span(d), compactions(d)
    f = flags_of(d, mid)
    runs.append(dict(case=case, model=mid, test=1, agent=agent, checks=checks,
                     tests_pass=int(row["tests_pass"]) if row["tests_pass"].isdigit() else None,
                     tests_fail=int(row["tests_fail"]) if row["tests_fail"].isdigit() else None,
                     subcmds=int(row["subcmds"]) if row["subcmds"].isdigit() else 0,
                     tps=tps, minutes=mins, compactions=comp,
                     ctx=f["ctx"] or CTX_FIXED.get(mid), ncmoe=f["ncmoe"], kv=f["kv"] or KV_FIXED.get(mid), flags=f["flags"],
                     verdict="pass" if checks == 5 else ("partial" if checks >= 3 else "fail")))
    runs[-1]["struggle"] = struggle(d)
    runs[-1]["finished"] = finished(d)

TRUST = {r["case"]: r["trust"] for r in read_tsv(A.trust)}
for row in read_tsv(A.grades_b):
    case = row["case"]; d = case_dir(A.cases_b, case)
    mid = model_of(d, case)
    if not known(mid, case, d): continue
    tps, mins = tok_span(d); f = flags_of(d, mid)
    trust = None
    if case.startswith("wt-") and case in TRUST:
        trust = TRUST[case]            # recorded at grading; the replay access log does not survive a reboot
    elif case.startswith("wt-"):
        import subprocess
        out = subprocess.run([sys.executable, os.path.join(TOOLS, "grade_trust.py"), d], capture_output=True, text=True).stdout.splitlines()
        trust = out[1].split("\t")[-1] if len(out) > 1 else None
    full = row["builds"] == "yes" and row["init"] == "yes" and row["tool_call"] == "yes" and row["tools"] not in ("", "-", "0")
    # partial = builds AND a client gets something: an initialize answer or a tool list
    part = row["builds"] == "yes" and not full and (row["init"] == "yes" or row["tools"] not in ("", "-", "0"))
    runs.append(dict(case=case, model=mid, test=2, agent="OpenCode",
                     builds=row["builds"] == "yes", init=row["init"] == "yes",
                     tools=int(row["tools"]) if row["tools"].isdigit() else 0,
                     tool_call=row["tool_call"], tests_pass=int(row["tests_pass"]) if row["tests_pass"].isdigit() else None,
                     note=plain(row.get("note", "")), tps=tps, minutes=mins, compactions=compactions(d),
                     ctx=f["ctx"] or CTX_FIXED.get(mid), ncmoe=f["ncmoe"], kv=f["kv"] or KV_FIXED.get(mid), flags=f["flags"],
                     verdict="pass" if full else ("partial" if part else "fail")))
    runs[-1]["struggle"] = struggle(d)
    runs[-1]["finished"] = finished(d)
    if trust: runs[-1]["trust"] = trust; runs[-1]["variant"] = "2T (planted docs)"

# Test 3: use and check an MCP server through a subagent (suites/test3/DESIGN.md)
test3 = []
if A.grades_c:
    RUB = {r["case"]: r for r in read_tsv(A.rubric_c)} if A.rubric_c else {}
    for row in read_tsv(A.grades_c):
        case = row["case"]; d = case_dir(A.cases_c, case)
        mid = model_of(d, case)
        if not known(mid, case, d): continue
        tps, mins = tok_span(d); rb = RUB.get(case, {})
        fx = dict(kv.split("=", 1) for kv in row["fixed_server"].split() if "=" in kv)
        test3.append(dict(case=case, model=mid, flavor=row["flavor"], mcp_facts=row["mcp_facts"], api_facts=row["api_facts"],
                          judgement_right=row["judgement_right"] == "yes", probe_sessions=int(row["probe_sessions"] or 0),
                          probe_calls=int(row["probe_mcp_calls"] or 0), server_runs=int(row["main_server_runs"] or 0),
                          changed=row["server_changed"] == "yes", fixed_tools=fx.get("tools"), fixed_tests=fx.get("tests", "").split("/")[0] or None,
                          rubric=int(rb["total"]) if rb.get("total", "").isdigit() else None, note=plain(rb.get("note", "")),
                          tps=tps, minutes=mins, finished=finished(d), facts_file=row.get("facts_file")))

ab = []
for p in A.ab:
    fn = os.path.basename(p)
    if not os.path.exists(p): continue
    for mid, rows in json.load(open(p)).items():
        for r in rows:
            if "full-context" in r["label"]: continue
            ab.append(dict(model=mid, engine=r["engine"], variant=r["label"], decode=r.get("decode"),
                           quote=r.get("quote"), prefill=r.get("prefill"), vram=r.get("vram"),
                           error=(r.get("error") or "")[-120:].strip(), source=fn))

timeline = [
    dict(date="2026-09-23", era="Round 1", title="One prompt, Pi agent, API coverage",
         what="Write a Python CLI for the Home Assistant REST API. Pi agent, llama.cpp only, 17 cases. Scored by endpoints touched (of 9) and whether the code compiles.",
         why="A first look at which local models write working code at all."),
    dict(date="2026-09-27", era="Tests 2, 3A, 3B", title="Build an MCP server, then use one",
         what="OpenCode in a container against a recorded Home Assistant. Test 2: build a Rust MCP server from the spec on disk. Test 3A/3B: describe the house through your own server / someone else's.",
         why="Separate building a tool from using one; test 1 did not separate models."),
    dict(date="2026-09-29", era="Abliteration cohort", title="Can uncensored Flash-Next still do the work?",
         what="Three uncensored Flash-Next routes (orcarouter fine-tune, Heretic2, abliterated s1.5) plus the stock model through the MCP test.",
         why="Red-team work on our own software needs models that do not refuse."),
    dict(date="2026-09-30", era="Harness fixes", title="Offloaded models produced zero output",
         what="mmap + experts in RAM page-faulted the weights off NFS during the first request. Fix: -lm none (load eagerly). Also: 3 h case cap, longer client timeouts, guaranteed result records.",
         why="Several early 'failures' were the harness, not the model."),
    dict(date="2026-10-01", era="Wave A", title="Test 1 graded by running the tool",
         what="Same CLI task, now graded by executing it in a sandbox: entry point + help, real reads, bad input, bad auth, no crash, plus the model's own tests. fill_vram tunes context and offload per model with real loads.",
         why="Counting endpoints in the source credited argparse help text and invented APIs."),
    dict(date="2026-10-03", era="Wave B", title="Test 2 graded by driving the server",
         what="The Rust MCP server is built and spoken to as a real MCP client: initialize, tools/list, a real tools/call against the replay. Every failure verified by hand.",
         why="Test 2 separates models that test 1 cannot: invented endpoints, broken handshakes, networking bugs."),
    dict(date="2026-10-04", era="Client settings", title="Context margin and thinking budget",
         what="OpenCode is told the context limit minus max(10%, 16k); a thinking budget of min(24k, reply cap − 6k) on every engine.",
         why="Runs died on context overflow, and on single thinks that ate the whole reply."),
    dict(date="2026-10-04", era="New engines", title="vLLM, SGLang, Strata",
         what="vLLM (HyperQwen) for the dense 27B, SGLang (EXL3) and Strata for Flash-Next, each behind llama-swap as a container.",
         why="Engine mattered as much as model: same weights, 2-5x speed."),
    dict(date="2026-10-05", era="llama.cpp 0.6", title="A second llama.cpp, and long-horizon runs",
         what="Official llama.cpp v0.6.0 A/B against 0.4.1; 8 h long-horizon test 2 with Qwen's own long-run sampling; small-window vLLM profiles with OpenCode and Pi; Kolibri.",
         why="0.6.0 is 2.5-4x faster on Flash-Next MoE; the uncensored Flash-Next finally finished test 2."),
    dict(date="2026-10-06", era="Uncensored round", title="Long runs for the slower uncensored models",
         what="ThinkingCap-27B Heretic (new), and 8 h test 2 for Flash-Next Heretic2, Abliterated s1.5 and q38-27b-cyber.",
         why="Find the smartest uncensored model, not just the fastest."),
    dict(date="2026-10-07", era="Test 3", title="Use an MCP server through a subagent, and fix it",
         what="The agent gets an MCP server's source and a subagent whose only tools are that server's. It must extract 14 facts through the subagent, check them against the REST API and fix the server if it is wrong. 3G: a known-good server; 3O: the model's own test-2 server. Transcripts scored on a 12-point rubric.",
         why="Measures how well a model briefs and checks subagents, which tests 1 and 2 cannot see."),
]

recs = {
    "overall": [
        dict(role="Smartest", model="flashnext", verdict="Built the best test-2 server of every run.", tradeoff="This build crashed under several sessions. The newer phase-d build served several at once (probe 11 of 11) and passed test 1 at 25.3 tok/s; its test 2 is queued, so the pick still rests on the older build.", cases=["wb-flashnext-sglang"]),
        dict(role="Fastest competent", model="qwen3.8-27b-vllm", verdict="Full passes on both tests; the default agent model.", tradeoff="The same weights on llama.cpp scored the same and ran 2-4x slower.", cases=["wb-qwen3.8-27b-vllm", "wa-qwen3.8-27b-vllm"]),
    ],
    "uncensored": [
        dict(role="Smartest", model="lcpp6-orcarouter-fn-uncensored", verdict="Orcarouter fine-tune of Flash-Next; full test-2 pass with long-horizon settings, the most tools and tests and the fewest compiler errors of the big uncensored runs.", tradeoff="Slow: 7.6 tok/s, 191 min. Flash-Next Heretic2 is twice as fast for a thinner result (7 tools, 33 tests in 120 min).", cases=["wb-orcarouter-fn-uncensored-long-lcpp6-r2"]),
        dict(role="Fastest competent", model="qwen3.8-27b-uncensored-vllm", verdict="Two test-2 full passes and 5/5 on test 1; run it with the thinking budget.", tradeoff="OrcaSAQ-2-Cyber is faster (about 80 tok/s) but one of its two test-2 runs shipped a broken HTTP client.", cases=["wb-qwen3.8-27b-uncensored-vllm-pp", "wa-qwen3.8-27b-uncensored-vllm-pp"]),
    ],
    "families": [
        dict(family=Q27, smartest="qwen3.8-27b-vllm", fastest="qwen3.8-27b-vllm", unc_smartest="qwen3.8-27b-uncensored-vllm", unc_fastest="orcasaq2-cyber-27b",
             note="vLLM with MTP drafts at 150k context is both: llama.cpp on the same weights scored the same and ran 2-4x slower. Uncensored: the AWQ uncensored checkpoint is the steadier, OrcaSAQ the faster (DFlash2) but variable."),
        dict(family=FN, smartest="flashnext", fastest="strata-swift15", unc_smartest="lcpp6-flashnext-heretic2", unc_fastest="lcpp6-flashnext-heretic2",
             note="SGLang built the best server; Strata runs the GSQ-RCO quants at 21-24 tok/s over a run with full passes. Only llama.cpp runs the uncensored tunes (0.6 is 2.5-4x faster than 0.4)."),
        dict(family="Tiel Coder 35B", smartest="cyber-tiel-coder-35b", fastest="tiel-coder-35b", unc_smartest="cyber-tiel-coder-35b", unc_fastest="cyber-tiel-coder-35b",
             note="IQ4_XS is the fastest model that writes working test-1 code (101 tok/s) but its test-2 server called an invented endpoint; the Q6 security tune passed test 2."),
        dict(family="Qwen3.6", smartest="qwen3.6-27b", fastest=None, unc_smartest=None, unc_fastest=None,
             note="Good on test 1, both failed test 2 (no initialize / no tools). Superseded by Qwen3.8."),
        dict(family="Gemma 4", smartest="gemma-4-31b", fastest="gemma-4-26b-a4b-vllm", unc_smartest=None, unc_fastest=None,
             note="Fast (45-91 tok/s) but thin: 3 tools on test 2. Needs enable_thinking."),
        dict(family="Kolibri", smartest="kolibri-1", fastest=None, unc_smartest=None, unc_fastest=None,
             note="Test 1 thin, test 2 partial (no initialize); ~19 tok/s. Not competitive here."),
        dict(family="GLM", smartest=None, fastest=None, unc_smartest=None, unc_fastest=None,
             note="GLM-4.7-Flash rejected numeric JSON-RPC ids, GLM-4.5-Air never answered initialize and ran at 3-6 tok/s. Dropped."),
        dict(family="Nemotron", smartest=None, fastest=None, unc_smartest=None, unc_fastest=None,
             note="Nano 30B quit within minutes (2/5 twice); Super 120B passed test 1 with no tests at 8.5 tok/s. Not taken to test 2."),
        dict(family="Other", smartest=None, fastest=None, unc_smartest=None, unc_fastest=None,
             note="Devstral Small 2, Bonsai 2 (invented APIs), Nanbeige 3B, Qwen3-VL-8B, Jan Nano: inconsistent or failing on test 1. Excluded."),
    ],
}

caveats = [
    "This is a living snapshot of the current state, not an apples-to-apples benchmark. The harness, prompts, grading, engines and client settings changed as we learned (see the timeline); results from different eras are not directly comparable.",
    "n = 1 per row. One model swung 5/5, 5/5, 2/5 on identical settings; OrcaSAQ wrote a broken HTTP client once and a correct one the next time. A one- or two-check difference is noise. Read pass / partial / fail.",
    "tok/s is generation throughput averaged over the whole agent run (output + reasoning tokens over wall time). It includes prompt processing, tool time and compaction, so it is lower than a short-prompt benchmark and depends on the task.",
    "Settings were tuned per model (context, expert offload, KV type, thinking budget) to fill one RTX 3090. Each model ran at its own best fit, not at identical settings.",
    "Uncensored models are tested for capability on our own software only; the tasks are the same coding tasks as for every other model.",
]

# Vision (operator 2026-10-15): which models see images and what that costs. The per-model facts come from
# engines/vision through tools/catalog.py; this is the method note shown with them.
vision_method = [
    "Vision: \"yes (head)\" means a separate vision head (an mmproj file) exists for the model and matches its text weights; "
    "\"yes (built in)\" means the vision tower is inside the served checkpoint (vLLM, SGLang, exllamav3); \"base head, "
    "unverified\" means only the base model's head is available, so image understanding may not have survived the "
    "fine-tune; \"no\" means the model has no vision tower.",
    "Loading a head costs VRAM: its weights plus a compute buffer, about 1.1 to 2.7 GB by head type. On a card already "
    "full with the model and its context, the head goes on the CPU instead (llama.cpp --no-mmproj-offload, or the "
    "engine's host-RAM offload): then it costs almost no VRAM but system RAM, and every image is encoded on the CPU, "
    "which takes longer per screenshot.",
    "Every screenshot also takes context: about 400 to 1,200 tokens for a 1280x720 image, depending on the head. A long "
    "agent run that takes screenshots often fills its context and compacts sooner. For example, with a head that "
    "costs about 920 tokens per screenshot (the Qwen3-VL style), 100 screenshots in a 2-hour run are about 92,000 "
    "tokens, over a third of a 262k window.",
    "Extra VRAM and tokens per screenshot marked \"est.\" are estimates from the head files (engines/vision/README.md); "
    "they are replaced by measurements once the vision smoke test has run on that setup. Planned setups are not "
    "configured yet.",
]

hardware = dict(gpu="RTX 3090, 24 GB (sm86)", ram="125 GB", cpu="AVX2 (no AVX-512)", weights="NFS from Saturn, ~180-280 MB/s first load",
                router="llama-swap (one model at a time)", agent="OpenCode 1.18 in a sandboxed container (some runs: Pi)")

# Recent happenings that are not test results: report/happenings.tsv (when, kind, text). Results come from the grades.
events = []
HAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "report", "happenings.tsv")
if os.path.exists(HAP):
    for l in open(HAP):
        f = l.rstrip("\n").split("\t")
        if len(f) >= 3 and not l.startswith("#"): events.append(dict(when=f[0], kind=f[1], text=f[2]))

data = dict(generated=time.strftime("%Y-%m-%d %H:%M %Z"), models=C, runs=runs, test3=test3, ab=ab, timeline=timeline, events=events,
            recs=recs, caveats=caveats, hardware=hardware, vision=dict(catalog.vision_overview(list(C)), method=vision_method))
os.makedirs(OUT, exist_ok=True)
json.dump(data, open(os.path.join(OUT, "data.json"), "w"), indent=1)
tpl = open(os.path.join(OUT, "template.html")).read()


def page_data(d):
    """data.json minus the vision fields the page does not show: model record paths, head file names, engine notes and
    llama-swap flags name storage and engine folders. The full data.json keeps them for export_model_docs.py."""
    d = json.loads(json.dumps(d))
    drop = ("record", "engine_note", "head_file", "flags")
    vs = [m["vision"] for m in d["models"].values() if m.get("vision")] + d["vision"]["records"]
    for v in vs:
        for k in drop: v.pop(k, None)
        for s in ([v["setup"]] if v.get("setup") else []) + v.get("setups", []):
            for k in drop: s.pop(k, None)
    return d


page = tpl.replace("/*__DATA__*/null", json.dumps(page_data(data), separators=(",", ":")).replace("</", "<\\/"))
# artifact.html: the bare page (the Artifact publisher adds the document skeleton);
# index.html: the same page as a full document, so it opens straight from the repo.
open(os.path.join(OUT, "artifact.html"), "w").write(page)
open(os.path.join(OUT, "index.html"), "w").write(
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '<style>[hidden]{display:none!important}img{max-width:100%}</style>\n</head>\n<body>\n' + page + "\n</body>\n</html>\n")
print(f"test3 {len(test3)}, runs {len(runs)} (t1 {sum(r['test']==1 for r in runs)}, t2 {sum(r['test']==2 for r in runs)}), ab {len(ab)}, models {len(C)}")
