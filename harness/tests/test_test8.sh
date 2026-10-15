#!/usr/bin/env bash
# End-to-end check of test 8, offline: run-case-test8.sh with T8_OFFLINE_TEST=1 runs a real OpenCode 1.18.32 session in
# the agent image, with the real browser container, driven by a scripted fake model (tests/fake_llm_t8.py). Once with
# images on (the image probe, answered by a mock on the host: unclear once, then sighted) and once with them off
# (T8_VISION=0). Before that: the vision rule's unit tests (tests/test_t8_vision.py) and a case whose probe stays
# unclear (it must stop as a harness failure before the agent starts). Runs as evalbox; no Titan, no GPU. Every line
# must be PASS.
#   tests/test_test8.sh            (KEEP=1 keeps tmp/t8test)
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
source ./evalbox-lib.sh
T="$HERE/tmp/t8test"; rm -rf "$T" 2>/dev/null || eb_rm "$T"; mkdir -p "$T/fake" "$T/results"
cp tests/fake_llm_t8.py "$T/fake/fake_llm.py"; cp tests/t8-sample-page.html "$T/fake/sample-page.html"
chmod -R a+rX "$T/fake"

# 1. the vision rule (tools/t8_tools.py vision_verdict, 2026-10-15) and the probe's exit codes, no containers
python3 -I tests/test_t8_vision.py; urc=$?

# 2. the runner's probe: a mock on the host answers it (T8_PROBE_BASE, offline only). /unclear/ always answers
# nothing usable, so the case must stop as a rerunnable harness failure before the agent starts; /retry/ answers
# nothing usable once, then "Red on the left, blue on the right", so the vision-1 run below goes through one retry.
python3 -I tests/test_t8_vision.py --serve "$T/probe-port" > "$T/probe-mock.log" 2>&1 &
MOCK=$!
for i in $(seq 1 50); do [ -s "$T/probe-port" ] && break; sleep 0.1; done
PP=$(cat "$T/probe-port")
RESULTS="$T/results" T8_OFFLINE_TEST=1 T8_FAKE_DIR="$T/fake" T8_PROBE_BASE="http://127.0.0.1:$PP/unclear/v1" T8_CAP_S=600 \
  timeout 300 ./run-case-test8.sh "t8-pagoda-offline-unclear-r1" m - 1 > "$T/run-unclear.log" 2>&1
echo "run-case-test8.sh (probe unclear twice) rc=$?"
for vis in 1 0; do
  if [ "$vis" = 1 ]; then probe=(T8_PROBE_BASE="http://127.0.0.1:$PP/retry/v1"); else probe=(T8_VISION=0); fi
  env RESULTS="$T/results" T8_OFFLINE_TEST=1 T8_FAKE_DIR="$T/fake" "${probe[@]}" T8_CAP_S=600 \
    timeout 900 ./run-case-test8.sh "t8-pagoda-offline-v$vis-r1" m - 1 > "$T/run-v$vis.log" 2>&1
  echo "run-case-test8.sh (vision $vis${probe:+, ${probe[0]%%=*}}) rc=$?"
done
kill "$MOCK" 2>/dev/null; wait "$MOCK" 2>/dev/null
python3 -I - "$T" "$HERE" "$urc" <<'EOF'
import json, os, subprocess, sys
T, HERE, urc = sys.argv[1:4]
fails = 0 if urc == "0" else 1   # the rule's unit tests (section 1) printed their own PASS / FAIL lines


def check(ok, what):
    global fails
    print(("PASS  " if ok else "FAIL  ") + what)
    fails += (not ok)


print("--- the runner's image probe")
out = f"{T}/results/t8-pagoda-offline-unclear-r1"
m = json.load(open(f"{out}/meta.json")) if os.path.exists(f"{out}/meta.json") else {}
check(m.get("status") == "harness_failure" and "unclear twice" in m.get("reason", ""),
      f"probe unclear twice: the case stops as harness_failure, rerunnable ({m.get('status')}: {m.get('reason', '')[:60]})")
check(all(os.path.exists(f"{out}/t8-vision-try{i}.json") for i in (1, 2)) and not os.path.exists(f"{out}/events.jsonl"),
      "probe unclear twice: both tries kept, the agent never started")
tr = f"{T}/results/t8-pagoda-offline-v1-r1"
v1 = json.load(open(f"{tr}/t8-vision.json")) if os.path.exists(f"{tr}/t8-vision.json") else {}
t1 = json.load(open(f"{tr}/t8-vision-try1.json")) if os.path.exists(f"{tr}/t8-vision-try1.json") else {}
check(t1.get("vision") is None and v1.get("vision") == 1 and v1.get("answer", "").startswith("Red on the left, blue"),
      f"probe unclear once, then 'Red on the left, blue on the right': retried, vision 1 ({t1.get('answer')!r} -> {v1.get('answer')!r})")


def ucat(p):
    r = subprocess.run(["bash", "-c", 'cd "$1" && source ./evalbox-lib.sh && podman unshare cat "$2"', "-", HERE, p],
                       capture_output=True, text=True)
    return r.stdout


for vis in (1, 0):
    out = f"{T}/results/t8-pagoda-offline-v{vis}-r1"
    print(f"--- vision {vis} ({out})")
    llm = [json.loads(l) for l in ucat(f"{out}/t8/llm.jsonl").splitlines() if l.startswith("{")]
    main = [x for x in llm if x["agent"] == "main"]
    sub = [x for x in llm if x["agent"] == "sub"]
    mt = set(main[0]["tools_offered"]) if main else set()
    check({"browser_browser_navigate", "browser_browser_take_screenshot", "browser_browser_evaluate", "task"} <= mt,
          f"main agent is offered the browser and task ({len(mt)} tools)")
    bad = sorted(t for t in mt if t in ("webfetch", "websearch", "browser_browser_run_code_unsafe",
                 "browser_browser_file_upload") or any(k in t for k in ("route", "cookie", "storage", "offline", "config")))
    check(not bad, f"no web tools, run_code_unsafe, file_upload or settings tools offered ({bad})")

    def res(i):   # the result of main step i (0-based), as seen in the request after it
        return main[i + 1]["tool_results"][i] if len(main) > i + 1 and len(main[i + 1]["tool_results"]) > i else ""
    r = res(0)
    check(all(f"NET-BLOCKED-{k}" in r for k in ("PUBLIC", "IP", "DNS", "LAN")) and "NET-LEAK" not in r,
          f"agent container: no Internet, no DNS, no LAN ({r[-300:]!r})")
    check("PREVIEW-SHELL-OK" in r and "PORT-TAKEN" in r,
          "the agent's shell reaches the preview on 127.0.0.1:8000 and cannot start its own server there")
    check("SVG-VIEW-FRAME" in r and "SVG-FIT-OK" in r,
          "the SVG view is the grader's sandboxed frame around the fitted copy")
    check("three 186" in res(2), f"the page loads the local three.js in the browser ({res(2)[:160]!r})")
    imgs = main[4]["images"] if len(main) > 4 else -1
    check(imgs > 0 if vis else imgs == 0, f"screenshot reaches the model as an image only with vision on ({imgs} images)")
    check("404" in res(4) or "Not served" in res(4), f"notes.txt is not served ({res(4)[:160]!r})")
    check("example.com" not in res(5) or "ERR_" in res(5) or "blocked" in res(5).lower(),
          f"the browser cannot open example.com ({res(5)[:200]!r})")
    check("proc" not in res(6) and "etc" not in res(6), f"run_code_unsafe does not run ({res(6)[:160]!r})")
    check("blocked" in res(7) and "browser_snapshot" not in res(7) and "allowedOrigins" not in res(7),
          f"the browser cannot open file:// URLs ({res(7)[:160]!r})")
    st = set(sub[0]["tools_offered"]) if sub else set()
    check(bool(sub) and "browser_browser_navigate" in st, f"the task tool started a sub-agent that has the browser")

    def sres(i):
        return sub[i + 1]["tool_results"][i] if len(sub) > i + 1 and len(sub[i + 1]["tool_results"]) > i else ""
    check("T8-AT " in sres(0) and "T8-AT about:blank" not in sres(0),
          f"the sub-agent shares the main agent's browser ({sres(0)[:100]!r})")
    check("three 186" in sres(2), f"the sub-agent's browser call works ({sres(2)[:120]!r})")
    check(any("sub done" in t for t in (main[-1]["tool_results"] if main else [])), "the sub-agent's answer reaches the main agent")
    blog = open(f"{out}/browser.log", errors="replace").read() if os.path.exists(f"{out}/browser.log") else ""
    check('GET /page.html HTTP/1.1" 200' in blog and "three.module.js" in blog,
          "the preview served page.html and the local three.js")
    tail = blog.split("--- end of case")[-1] if "--- end of case" in blog else ""
    check("Filesystem" in tail and "oom_kill" in tail,
          "browser.log ends with the browser's /tmp space and memory events")
    m = json.load(open(f"{out}/meta.json")) if os.path.exists(f"{out}/meta.json") else {}
    frames = os.listdir(f"{out}/frames") if os.path.isdir(f"{out}/frames") else []
    check(m.get("artifact") == "page.html" and any(f.endswith(".png") for f in frames),
          f"page.html kept and rendered by the grader ({len(frames)} frame files)")
    s = m.get("t8_stats") or {}
    check(s.get("task_calls") == 1 and s.get("screenshots", 0) >= 1, f"stats count the task and the screenshot ({s.get('tool_calls')})")
    check(m.get("vision") == vis, f"meta records vision {vis}")
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
EOF
rc=$?
[ "${KEEP:-0}" = 1 ] || eb_rm "$T"
exit $rc
