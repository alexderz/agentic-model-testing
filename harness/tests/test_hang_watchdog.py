"""Which container processes tools/hang_watchdog.py counts as work. The harness's own processes must not count (a
hung test 8 case looked busy for good, tiel pilot 2026-10-15); anything the agent runs must.
  python3 -I tests/test_hang_watchdog.py
"""
import importlib.util
import os
import sys

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hang_watchdog", os.path.join(here, "tools", "hang_watchdog.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

HARNESS = [   # live lines from bakeoff-t8-pagoda-tiel-p1 (podman top -eo pid,args), shortened prompts
    "1 bash /agent-cmd.sh",
    "15 timeout -k 30 7200 opencode run --auto --pure --format json --log-level INFO --model titan/x --dir /work You are",
    "16 opencode run --auto --pure --format json --log-level INFO --model titan/x --dir /work You are",
    "33 python3 -I /opt/t8/mcp-bridge.py /sock/mcp.sock",
    "34 python3 -I /opt/t8/preview-bridge.py /sock/preview.sock 8000",
    "2 /net-policy.sh bash /agent-cmd.sh",
    "40 python3 /opt/t8fake/fake_llm_t8.py",
    "41 ps -eo pid,args",
    "42 /usr/bin/ps -eo pid,args",
    "17 /usr/local/bin/opencode run --auto",
]
WORK = [
    "50 /bin/bash -c cargo build --release",
    "51 cargo build --release",
    "52 /root/.rustup/toolchains/stable/bin/rustc --crate-name maze src/main.rs",
    "53 sleep 30",
    "54 python3 -m http.server 8000",
    "55 timeout 20 cargo build",
    "56 node /work/check.js",
    "57 bash -lc python3 gen.py --seed 4",
    "58 /work/steps -eo pid",
]
bad = 0
left = w.not_harness(HARNESS)
if left:
    print("FAIL harness lines counted as work:", left)
    bad += 1
for l in WORK:
    if w.not_harness([l]) != [l]:
        print("FAIL work line not counted:", l)
        bad += 1
if w.not_harness(HARNESS + WORK) != WORK:
    print("FAIL mixed list")
    bad += 1
print("ALL PASS" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
