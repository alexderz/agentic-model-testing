#!/usr/bin/env python3
"""Speed A/B of two (or more) llama-swap entries on titan, one round per entry load, in a fixed order such as
A,B,B,A (operator 2026-10-15: compare the new Strata, exllamav3 and Maya builds with the ones they would replace;
Model Master 2). Lesson of the 2026-10-11 Strata probe: warm up first and measure in both orders.

  python3 -I tools/engine_ab.py --out DIR --entry A=ID [--log A=TITAN_LOG] --entry B=ID ... \
      [--order A,B,B,A] [--workload agentic|bench] [--load-s 1800]

Runs on Saturn under the bakeoff GPU lease with nothing else sending requests (a queue-new.d step). Each round:
unload (titan's llama-swap :8081, bounded), load the entry with a tiny request (load seconds), one uncounted warm-up
request (a ~4k-token prompt), then the workload, every request streamed (client-side numbers: time to first piece,
completion tokens, decode tok/s after the first piece):
  agentic  tools/strata_tune_probe.py's workload: r1 a ~20k-token prompt (this repo's tools/*.py) with a short
           answer, r2-r6 five follow-ups adding ~700 tokens each, r7 a long reply at ~25k context, r8 a new short
           conversation with a long reply; temperature 0, the entry's own thinking settings
  bench    tools/bench_tasks.py: code, prose and structured, 5 prompts each, 400 tokens, thinking off
With --log for an entry, the engine's own speed lines written during the round (Strata and Maya print
"prompt N tokens = R reused + F read in MS ms ..., G generated in MS ms ..., drafts accepted X of Y") give read and
decode rates as well. Writes DIR/round<N>-<label>.json and appends DIR/summary.tsv; prints the mean per label.
Exit 0 all rounds done, 1 a round failed (its row says why; later rounds still run), 2 a model would not unload
(stops at once).
"""
import argparse, glob, json, os, re, signal, statistics, subprocess, sys, time, urllib.request

T = os.environ.get("TITAN", "192.0.2.62")
SSH = os.environ.get("AB_SSH", "").split() or ["ssh", "-n", "-o", "BatchMode=yes", "-o", "HostKeyAlias=titan", T]
BASE = os.environ.get("AB_BASE", f"http://{T}:8080")          # AB_BASE and AB_SSH only for a dry test with mocks
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LINE = re.compile(r"prompt (\d+) tokens = (\d+) reused \+ (\d+) read in (\d+) ms .*?, (\d+) generated in (\d+) ms .*?"
                  r"drafts accepted (\d+) of (\d+)")
COLS = ["round", "label", "entry", "status", "load_s", "wall_s", "requests", "ttft_r1_s", "client_decode_tok_s",
        "client_decode_long_tok_s", "log_read_big_tok_s", "log_read_small_tok_s", "log_decode_tok_s",
        "log_decode_long_tok_s", "drafts_accepted", "generated", "error"]


class Stuck(Exception):
    pass


def sh(cmd, timeout=120):
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode: raise RuntimeError(f"titan: {cmd[:80]}: {r.stderr.strip()[-300:]}")
    return r.stdout


def unload():
    """run-next-new.sh's method: :8081/unload, then /running must be empty; 30 tries."""
    for _ in range(30):
        try:
            r = sh("curl -s --max-time 10 http://127.0.0.1:8081/unload >/dev/null; sleep 5; "
                   "curl -s --max-time 10 http://127.0.0.1:8081/running", timeout=60)
            if '"running":[]' in r: return
        except Exception as e:
            print(f"  unload: {e}", flush=True)
        time.sleep(10)
    raise Stuck("a model is still loaded after 30 unload tries")


def _expired(*_):
    raise TimeoutError("deadline passed")


def stream(model, messages, max_tokens, extra=None, timeout=1800, deadline=None):
    """One streamed request; `timeout` (and `deadline`, a time.time() value) bound the whole request, not one socket
    read: SIGALRM interrupts a stream that keeps sending. A stream counts only when it ends with a finish_reason and
    a usage block with completion_tokens (Strata and Maya send both in their last chunk; TabbyAPI with include_usage);
    an error object, EOF before that, or a chunk that is not JSON raises."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True}}
    body.update(extra or {})
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    left = timeout if deadline is None else min(timeout, deadline - time.time())
    if left <= 0: raise TimeoutError("deadline passed before the request")
    start = time.perf_counter(); first = last = None; usage = finish = None; text, reasoning = [], 0
    old = signal.signal(signal.SIGALRM, _expired); signal.setitimer(signal.ITIMER_REAL, left)
    try:
        with urllib.request.urlopen(req, timeout=left) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line == "data: [DONE]": continue
                ch = json.loads(line[5:])
                if ch.get("error"): raise RuntimeError(f"engine error: {json.dumps(ch['error'])[:300]}")
                if ch.get("usage"): usage = ch["usage"]
                for c in ch.get("choices", []):
                    d = c.get("delta") or {}
                    piece = d.get("content") or ""; rp = d.get("reasoning_content") or d.get("reasoning") or ""
                    if piece or rp or d.get("tool_calls"):
                        now = time.perf_counter(); first = now if first is None else first; last = now
                    text.append(piece); reasoning += len(rp)
                    finish = c.get("finish_reason") or finish
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, old)
    end = time.perf_counter()
    if not finish: raise RuntimeError("the stream ended without a finish_reason (cut off)")
    if not isinstance((usage or {}).get("completion_tokens"), int):
        raise RuntimeError(f"the stream ended without usage.completion_tokens (finish {finish})")
    n = usage["completion_tokens"]
    span = (last - first) if first is not None else 0.0
    return {"seconds": round(end - start, 2), "ttft_s": round((first or end) - start, 2), "finish": finish,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": n,
            "decode_tok_s": round((n - 1) / span, 1) if n > 1 and span > 0 else None,
            "content": "".join(text), "reasoning_chars": reasoning}


def load(model, cap):
    """The first request starts the entry; retried (30 s apart) until it answers. <cap> seconds is a hard deadline
    for the whole load: each try gets only the time that is left."""
    t0 = time.time(); end = t0 + cap; last = None
    while time.time() < end:
        try:
            stream(model, [{"role": "user", "content": "Say OK."}], 8, timeout=cap, deadline=end)
            return round(time.time() - t0, 1)
        except Exception as e:
            last = e; time.sleep(max(0, min(30, end - time.time())))
    raise RuntimeError(f"no answer within {cap} s: {last}")


def agentic_workload():
    files = sorted(glob.glob(os.path.join(HERE, "tools", "*.py")))
    text = "".join(f"\n# ==== {os.path.basename(f)} ====\n" + open(f).read() for f in files)
    return text[:64000], [text[64000 + i * 2400:64000 + (i + 1) * 2400] for i in range(5)]


def warmup(model):
    doc, _ = agentic_workload()
    stream(model, [{"role": "user", "content": "Here is some code.\n" + doc[-14000:] +
                    "\n\nIn two sentences, what does it do?"}], 200)


def run_agentic(model, reqs):
    # the text is fixed at the first round: tools/*.py as it is when the step starts (DOC below)
    doc, chunks = DOC
    msgs = [{"role": "user", "content": "Here is a set of Python tools.\n" + doc +
             "\n\nName the ten most important functions above, one line each."}]
    def step(tag, max_tokens, m):
        r = stream(model, m, max_tokens); r["tag"] = tag
        reqs.append({k: v for k, v in r.items() if k != "content"})
        print(f"    {tag}: {r['seconds']} s, ttft {r['ttft_s']} s, {r['completion_tokens']} tok, "
              f"{r['decode_tok_s']} tok/s", flush=True)
        return r
    r = step("r1", 400, msgs)
    for i, c in enumerate(chunks):
        msgs += [{"role": "assistant", "content": r["content"] or "(no answer)"},
                 {"role": "user", "content": "More code:\n" + c + "\n\nSay in three sentences what this part does."}]
        r = step(f"r{i + 2}", 300, msgs)
    msgs += [{"role": "assistant", "content": r["content"] or "(no answer)"},
             {"role": "user", "content": "Write a complete, well-commented Python module with unit tests that parses "
              "the engine log lines these tools read and prints a speed summary per run. Write all of it."}]
    step("r7", 2500, msgs)
    step("r8", 1500, [{"role": "user", "content": "Write a complete Python command-line tool, with argparse and unit "
                       "tests, that reads a CSV of temperature readings and prints hourly minimum, mean and maximum."}])


def run_bench(model, reqs):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import bench_tasks
    for task, prompts in bench_tasks.TASKS.items():
        for i, p in enumerate(prompts):
            r = stream(model, [{"role": "user", "content": p}], 400,
                       {"chat_template_kwargs": {"enable_thinking": False}})
            r.update(tag=f"{task}{i}", task=task); reqs.append({k: v for k, v in r.items() if k != "content"})
            print(f"    {task} {i}: {r['completion_tokens']} tok, ttft {r['ttft_s']} s, {r['decode_tok_s']} tok/s",
                  flush=True)


FP = 4096    # bytes before the round's offset whose hash must still be there when the round's lines are read


def log_pos(path):
    """(inode, size, hash of the last FP bytes) of the engine log; (0, 0, "") when it does not exist yet."""
    try:
        i, s, f = (sh(f"set -- $(stat -c '%i %s' {path} 2>/dev/null || echo '0 0'); k=$(( $2 < {FP} ? $2 : {FP} )); "
                      f"echo $1 $2 $(tail -c +$(( $2 - k + 1 )) {path} 2>/dev/null | head -c $k | sha256sum | "
                      f"cut -c1-16)").split() + ["0", "0", ""])[:3]
        return int(i), int(s), f
    except Exception: return 0, 0, ""


def log_rows(path, pos):
    # Strata and Maya open their log in append mode (serve/server.py StrataEngine), so a round's lines start at the
    # size taken before its load, as long as the same file still holds the same bytes before that offset. A log with
    # another inode, a smaller size, or other bytes before the offset (truncated in place, then grown past it) was
    # replaced or truncated since then: all of it is this round's.
    ino, off, fp = pos
    k = min(off, FP)
    raw = sh(f"set -- $(stat -c '%i %s' {path} 2>/dev/null || echo '0 0'); o=1; "
             f"if [ \"$1\" = {ino} ] && [ \"$2\" -ge {off} ] && [ {off} -gt 0 ] && [ \"$(tail -c +{off - k + 1} {path} "
             f"2>/dev/null | head -c {k} | sha256sum | cut -c1-16)\" = '{fp}' ]; then o={off + 1}; fi; "
             f"tail -c +$o {path} 2>/dev/null | tail -c 4000000", timeout=120)
    return raw, [tuple(map(int, m.groups())) for m in LINE.finditer(raw)]


def rate(rows, sel, num, den):
    x = [r for r in rows if sel(r)]; n = sum(r[num] for r in x); ms = sum(r[den] for r in x)
    return round(n / ms * 1000, 1) if ms else None


def main():
    global DOC
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--entry", action="append", required=True, help="LABEL=ENTRY")
    ap.add_argument("--log", action="append", default=[], help="LABEL=TITAN_LOG_PATH")
    ap.add_argument("--order", default="A,B,B,A")
    ap.add_argument("--workload", choices=("agentic", "bench"), default="agentic")
    ap.add_argument("--load-s", type=int, default=1800)
    a = ap.parse_args()
    entries = dict(x.split("=", 1) for x in a.entry); logs = dict(x.split("=", 1) for x in a.log)
    order = a.order.split(",")
    assert all(l in entries for l in order), "every label in --order needs an --entry"
    os.makedirs(a.out, exist_ok=True)
    DOC = agentic_workload()
    tsv = os.path.join(a.out, "summary.tsv")
    with open(tsv, "a") as f:
        if f.tell() == 0: f.write("\t".join(COLS) + "\n")
    failed = 0; results = []
    for n, label in enumerate(order, 1):
        model = entries[label]
        print(f"### round {n} {label}={model} {time.strftime('%H:%M:%S')}", flush=True)
        s = {c: "-" for c in COLS}; s.update(round=n, label=label, entry=model, status="ok", error="-")
        reqs = []; t0 = time.time()
        try:
            unload()
            lp = logs.get(label); off = log_pos(lp) if lp else (0, 0, "")
            s["load_s"] = load(model, a.load_s); print(f"  loaded in {s['load_s']} s", flush=True)
            warmup(model)
            (run_agentic if a.workload == "agentic" else run_bench)(model, reqs)
        except Stuck:
            raise
        except Exception as e:
            s["status"] = "FAILED"; s["error"] = str(e).replace("\t", " ").replace("\n", " ")[:300]; failed += 1
            print(f"!! round {n} failed: {e}", flush=True)
        s["wall_s"] = round(time.time() - t0, 1); s["requests"] = len(reqs)
        dec = [r["decode_tok_s"] for r in reqs if r.get("decode_tok_s")]
        s["client_decode_tok_s"] = round(statistics.mean(dec), 1) if dec else "-"
        long_ = [r["decode_tok_s"] for r in reqs if r.get("decode_tok_s") and r["completion_tokens"] >= 1000]
        s["client_decode_long_tok_s"] = round(statistics.mean(long_), 1) if long_ else "-"
        s["ttft_r1_s"] = next((r["ttft_s"] for r in reqs if r.get("tag") == "r1"), "-")
        s["generated"] = sum(r["completion_tokens"] for r in reqs)
        rows, raw = [], ""
        if logs.get(label):
            try:
                raw, rows = log_rows(logs[label], off)
                rows = [r for r in rows if r[0] > 100]          # drop the load ping and health requests
                s["log_read_big_tok_s"] = rate(rows, lambda r: r[2] >= 1024, 2, 3)
                s["log_read_small_tok_s"] = rate(rows, lambda r: 100 <= r[2] < 1024, 2, 3)
                s["log_decode_tok_s"] = rate(rows, lambda r: True, 4, 5)
                s["log_decode_long_tok_s"] = rate(rows, lambda r: r[4] >= 1000, 4, 5)
                s["drafts_accepted"] = round(sum(r[6] for r in rows) / max(1, sum(r[7] for r in rows)), 2)
            except Exception as e:
                s["error"] = (s["error"] if s["error"] != "-" else "") + f" log: {e}"[:200]
            open(os.path.join(a.out, f"round{n}-{label}.log"), "w").write(raw)
        json.dump({"summary": s, "requests": reqs, "log_rows": rows},
                  open(os.path.join(a.out, f"round{n}-{label}.json"), "w"), indent=1)
        with open(tsv, "a") as f: f.write("\t".join(str(s[c] if s[c] is not None else "-") for c in COLS) + "\n")
        print("  ", {k: s[k] for k in COLS if k not in ("round", "entry")}, flush=True)
        results.append(s)
    unload()
    for label in dict.fromkeys(order):
        ok = [r for r in results if r["label"] == label and r["status"] == "ok"]
        def m(k):
            v = [r[k] for r in ok if isinstance(r[k], (int, float))]
            return round(statistics.mean(v), 1) if v else "-"
        print(f"mean {label} ({entries[label]}, {len(ok)} rounds): client decode {m('client_decode_tok_s')}, "
              f"long {m('client_decode_long_tok_s')}, r1 ttft {m('ttft_r1_s')} s; log read big "
              f"{m('log_read_big_tok_s')}, small {m('log_read_small_tok_s')}, decode {m('log_decode_tok_s')}, "
              f"long {m('log_decode_long_tok_s')}; load {m('load_s')} s", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try: sys.exit(main())
    except Stuck as e:
        print(f"!! {e}", flush=True); sys.exit(2)
