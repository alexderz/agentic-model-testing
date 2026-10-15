#!/usr/bin/env python3
"""One-shot test runner (tests 5 and 6): one user message per llama-swap entry, no tools, no agent.

  python3 tools/run_oneshot.py <results-dir> <prompt-file> <cases.tsv>

Environment: ONESHOT_ARTIFACT=svg (default, test 5: orrery.svg) or html (test 6: page.html); ONESHOT_TEST names the
test in meta.json; TITAN_API the endpoint; ONESHOT_NO_UNLOAD=1 skips the llama-swap unload between cases (for a
server started by hand); ONESHOT_NO_THINK=1 sends chat_template_kwargs enable_thinking false (Qwen and Gemma templates); vLLM entries (-vllm) get
thinking_token_budget min(cap - 6000, 24000) as in the agent harness, unless ONESHOT_NO_BUDGET=1; ONESHOT_THINK_BUDGET sets
that budget instead (capped at cap - 6000). ONESHOT_SEED sends a sampling seed (vLLM replies are otherwise the same on
every repeat). A case line may carry a third column, the model id to send, when it differs from the entry.

cases.tsv: case<TAB>model per line. A case with a meta.json is skipped. Every case leaves a meta.json.
"""
import json, os, re, subprocess, sys, time, urllib.request
import xml.dom.minidom

RES, PROMPT, CASES = sys.argv[1:4]
BASE = os.environ.get("TITAN_API", "http://192.0.2.62:8080/v1")
MAXTOK = int(os.environ.get("ONESHOT_MAX_TOKENS", "32000"))
TIMEOUT = int(os.environ.get("ONESHOT_TIMEOUT", "9000"))
ARTIFACT = os.environ.get("ONESHOT_ARTIFACT", "svg")
TEST = os.environ.get("ONESHOT_TEST", "test5-orrery" if ARTIFACT == "svg" else "test6-pagoda")
prompt = open(PROMPT).read().strip()


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S%z"), *a, flush=True)


def run(case, model):
    out = os.path.join(RES, case); os.makedirs(out, exist_ok=True)
    meta = {"case": case, "model": model, "test": TEST, "max_tokens": MAXTOK, "timeout_s": TIMEOUT,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": MAXTOK, "stream": True,
            "stream_options": {"include_usage": True}}
    if os.environ.get("ONESHOT_NO_THINK") == "1":
        body["chat_template_kwargs"] = {"enable_thinking": False}; meta["thinking"] = "off (chat_template_kwargs)"
    elif re.search(r"-vllm($|-)", model) and os.environ.get("ONESHOT_NO_BUDGET") != "1":
        # Same rule as run-case-sandboxed.sh: vLLM takes the thinking budget per request, min(cap - 6,000, 24,000).
        # Before 2026-10-14 the one-shots sent none, so vLLM entries thought without a budget (ONESHOT_NO_BUDGET=1).
        budget = int(os.environ.get("ONESHOT_THINK_BUDGET") or 24000)
        body["thinking_token_budget"] = meta["thinking_budget"] = min(MAXTOK - 6000, budget)
    if os.environ.get("ONESHOT_SEED"):
        body["seed"] = meta["seed"] = int(os.environ["ONESHOT_SEED"])
    req = urllib.request.Request(BASE + "/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    text, think, usage, finish, timings = [], [], None, None, None
    t0 = time.time(); t_first = None
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            for raw in r:
                if time.time() - t0 > TIMEOUT:
                    finish = "timeout"; break
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                usage = ev.get("usage") or usage
                timings = ev.get("timings") or timings
                for ch in ev.get("choices") or []:
                    d = ch.get("delta") or {}
                    piece = d.get("content"); rp = d.get("reasoning_content") or d.get("reasoning")
                    if (piece or rp) and t_first is None:
                        t_first = time.time()
                    if piece: text.append(piece)
                    if rp: think.append(rp)
                    finish = ch.get("finish_reason") or finish
        meta["status"] = "ok" if finish != "timeout" else "timeout"
    except Exception as e:  # every case leaves a record
        meta["status"] = "error"; meta["reason"] = f"{type(e).__name__}: {e}"[:500]
    t1 = time.time()
    reply, reasoning = "".join(text), "".join(think)
    open(os.path.join(out, "reply.txt"), "w").write(reply)
    if reasoning:
        open(os.path.join(out, "reasoning.txt"), "w").write(reasoning)
    if ARTIFACT == "html":
        static = html_static(reply, out)
    else:
        static = svg_static(reply, out)
    gen = (usage or {}).get("completion_tokens")
    meta.update(finish_reason=finish, usage=usage, timings=timings, static=static, wall_s=round(t1 - t0, 1),
                first_token_s=round(t_first - t0, 1) if t_first else None,
                tok_s=round(gen / (t1 - t_first), 1) if gen and t_first and t1 > t_first else None,
                reply_chars=len(reply), reasoning_chars=len(reasoning))
    json.dump(meta, open(os.path.join(out, "meta.json"), "w"), indent=1)
    found = static.get("svg_found", static.get("html_found"))
    log(f"### done {case} status={meta['status']} finish={finish} {ARTIFACT}={found} parses={static.get('parses')} "
        f"wall={meta['wall_s']}s tok/s={meta['tok_s']}")


def html_static(reply, out):
    """Test 6: cut the HTML page out of the reply. Candidates are every ```html fence and the <!doctype or <html ... </html>
    span (which survives backticks inside the page's scripts); the longest one that ends with </html> wins, else the
    longest fence."""
    fences = [m.group(1) for m in re.finditer(r"```html?\s*\n(.*?)```", reply, re.S | re.I)]
    spans = [m.group(1) for m in re.finditer(r"(<!doctype html.*</html\s*>|<html\b.*</html\s*>)", reply, re.S | re.I)]
    whole = [c for c in fences + spans if re.search(r"</html\s*>\s*$", c, re.I)]
    page = max(whole, key=len) if whole else (max(fences, key=len) if fences else None)
    static = {"html_found": bool(page)}
    if page:
        open(os.path.join(out, "page.html"), "w").write(page)
        static.update(bytes=len(page.encode()), complete=bool(re.search(r"</html\s*>", page, re.I)),
                      three_module=bool(re.search(r"three(?:@[\w.\-]+)?/build/three\.module", page)),
                      importmap="importmap" in page, umd_three=bool(re.search(r"three(?:\.min)?\.js[\"']", page)),
                      external_urls=sorted(set(re.findall(r"https?://[^\s\"'`()<>]+", page)))[:20],
                      boxes=len(re.findall(r"BoxGeometry", page)), instanced="InstancedMesh" in page,
                      prose_chars_outside_html=len(reply) - len(page))
    elif "<html" in reply.lower() or "<!doctype" in reply.lower():
        i = min(x for x in (reply.lower().find("<!doctype"), reply.lower().find("<html")) if x >= 0)
        static["truncated"] = True
        open(os.path.join(out, "page-truncated.html"), "w").write(reply[i:])
    return static


def svg_static(reply, out):
    m = re.search(r"<svg\b.*</svg\s*>", reply, re.S | re.I)
    svg = m.group(0) if m else None
    static = {"svg_found": bool(svg)}
    if svg:
        open(os.path.join(out, "orrery.svg"), "w").write(svg)
        try:
            xml.dom.minidom.parseString(svg.encode()); static["parses"] = True
        except Exception as e:
            static["parses"] = False; static["parse_error"] = str(e)[:200]
        static.update(bytes=len(svg.encode()), animateTransform=len(re.findall(r"<animateTransform\b", svg)),
                      animate=len(re.findall(r"<animate\b", svg)), animateMotion=len(re.findall(r"<animateMotion\b", svg)),
                      keyframes=len(re.findall(r"@keyframes", svg)), script=len(re.findall(r"<script\b", svg, re.I)),
                      prose_chars_outside_svg=len(reply) - len(svg))
        if "</svg" not in reply.lower():
            static["truncated"] = True
    elif "<svg" in reply.lower():
        static["truncated"] = True
        open(os.path.join(out, "orrery-truncated.svg"), "w").write(reply[reply.lower().index("<svg"):])
    return static


for line in open(CASES):
    if not line.strip() or line.startswith("#"):
        continue
    cols = line.rstrip("\n").split("\t")
    case, model = cols[0], (cols[2] if len(cols) > 2 and cols[2] else cols[1])
    if os.path.exists(os.path.join(RES, case, "meta.json")):
        log(f"--- skip {case} (recorded)"); continue
    log(f"--- run {case} : {model}")
    # Start every case against an empty card: unload, and stop llama.cpp containers a swap can leave behind
    # (run-matrix.sh does the same; 2026-10-06 a leftover container held 23.5 GB and every later start failed).
    if os.environ.get("ONESHOT_NO_UNLOAD") != "1":
      subprocess.run(["ssh", "-n", "-o", "HostKeyAlias=titan", os.environ.get("TITAN", "192.0.2.62"),
                    "curl -s -m 60 http://127.0.0.1:8081/unload >/dev/null; sleep 5; "
                    "podman stop -t 15 llamacpp6 llamacpp-kolibri llamacpp-prism >/dev/null 2>&1; true"], timeout=180)
    run(case, model)
