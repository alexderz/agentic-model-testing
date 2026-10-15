"""Stop an agent case whose OpenCode process has hung.

Hang signature (wb-q38-27b-cyber, 2026-10-03): the LLM reply arrived, OpenCode
never acted on it, no further events for 17 min, and the container held no
process but OpenCode itself. A long cargo build also produces no events, but
it shows up as child processes, and a slow model writing a long reply keeps
the GPU busy, so all three conditions are required.

The harness's own processes do not count as children: the agent script, timeout, OpenCode, and test 8's
browser and preview bridges (tiel pilot 2026-10-15: they made a hung test 8 case look busy for good).

  python3 tools/hang_watchdog.py results-wave-b   (runs until killed)
  tests/test_hang_watchdog.py checks which container processes count.
"""
import glob, json, os, re, subprocess, sys, time

IDLE = int(os.environ.get("HANG_IDLE_S", "600"))


def gpu_idle():
    """True when Titan's GPU shows no work across three samples: a slow model
    generating a long reply also emits no events and spawns no processes."""
    vals = []
    for _ in range(3):
        r = subprocess.run(["ssh", "-n", "-o", "ConnectTimeout=10", "titan",
                            "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits"],
                           capture_output=True, text=True)
        try:
            vals.append(int(r.stdout.strip()))
        except ValueError:
            return False                      # cannot tell: never kill on doubt
        time.sleep(5)
    return max(vals) < 5


PODMAN = os.environ.get("PODMAN") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "podman-eb")  # runs as evalbox


HARNESS = re.compile(r"\d+\s+(bash /agent-cmd\.sh|\S*net-policy\.sh|timeout .*opencode|\S*opencode( |$)|"
                     r"python3 -I /opt/t8/(mcp|preview)-bridge\.py|python3 /opt/t8fake/|(\S*/)?ps -eo)")


def procs(name):
    """The container's processes other than the harness's own, or None when they cannot be read."""
    r = subprocess.run([PODMAN, "top", name, "-eo", "pid,args"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return not_harness(r.stdout.splitlines()[1:])


def not_harness(lines):
    """The `pid args` lines that are not the harness's own processes."""
    return [l.strip() for l in lines if l.strip() and not HARNESS.match(l.strip())]


def main(res):
    while True:
        names = subprocess.run([PODMAN, "ps", "--format", "{{.Names}}"], capture_output=True,
                               text=True).stdout.split()
        for n in names:
            if not n.startswith("bakeoff-"):
                continue
            case = n[len("bakeoff-"):]
            ev = os.path.join(res, case, "events.jsonl")
            if not os.path.exists(ev):
                continue
            idle = time.time() - os.path.getmtime(ev)
            p = procs(n)
            if idle > IDLE and p is not None and not p and gpu_idle():
                with open(os.path.join(res, case, "interventions.tsv"), "a") as f:
                    f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\twatchdog: no events for {idle:.0f}s and no "
                            f"child processes in the container, GPU idle; OpenCode hang, container stopped\n")
                print(f"{time.ctime()} hang: stopping {n} (idle {idle:.0f}s)", flush=True)
                subprocess.run([PODMAN, "stop", "-t", "10", n], capture_output=True)
        time.sleep(60)


if __name__ == "__main__":
    main(sys.argv[1])
