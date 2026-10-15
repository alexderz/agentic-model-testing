#!/usr/bin/env python3
"""Grade one test 7 case (suites/test7/README.md): the parts a program can judge.

    python3 -I grade-test7.py results-test7/<case>

A  showcase: work/labyrinth.json against the untouched suites/test7/project/verify.py, and the round trip
   `./generate $(cat SHOWCASE_SEED)` must write the same maze
   2 = every rule passes and the round trip matches; 1 = every rule passes without the round trip, or the file is a
   perfect maze (file format and rules 1-2 pass) but other rules fail; 0 = otherwise
B  generator: work/generate on the ten seeds below; the first seed runs twice and must give the same maze
   2 = ten different passing mazes and the repeat matches; 1 = five or more different passing mazes; 0 = fewer
C  extra credit (only when B = 2), the worst of the ten unseen mazes: +1 for a route of at least 320 cells,
   +1 for at least 6 floor changes along the route
D  (walkable quality) and E (honesty of NOTES.md) are judged by hand (README.md) and are null here until then.

Mazes compare by their cells with each cell's letters sorted, so letter order does not matter.

The agent's program is untrusted. Each seed runs in its own container (no network, one CPU, 2 GiB, 120 s inside,
read-only copy of the work folder copied again to /tmp), so one run cannot touch another run's output. The maze comes
back on the container's stdout, never as a file the program could point elsewhere. Files the agent left on the host
side (labyrinth.json, SHOWCASE_SEED) are read only when they are plain files, not links, and at most 4 MB.

No grade.json is written when the case itself did not run (meta.json missing, or status load_failed,
variant_failed, spec_missing, harness_failure) or when a container failed to start: the grade would measure the
harness, not the model. Exit 2 then. Exit 3 when another grader holds this case's lock (try again later)."""
import fcntl
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE / "suites" / "test7"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SUITE / "project"))
import verify  # noqa: E402  (the untouched copy)

SEEDS = [918273, 4021, 77777, 123456789, 31337, 2718281, 1618033, 600613, 99991, 424242]
STRETCH_PATH, STRETCH_FLOOR_CHANGES = 320, 6
IMAGE = os.environ.get("AGENT_IMAGE", "localhost/bakeoff-agent")
MAX_BYTES = 4_000_000
A1_RULES = ("file format", "file letters", "rule 1 consistent", "rule 2 perfect maze")
NOT_RUN = {"load_failed", "variant_failed", "spec_missing", "harness_failure"}
HARNESS_RC = {120, 125}   # 120: the copy inside the container failed; 125: podman itself failed
assert set(A1_RULES) <= set(verify.RULES), "grade-test7.py: A1_RULES no longer match verify.RULES"


class HarnessError(Exception):
    pass


def read_plain(p, limit=MAX_BYTES):
    """Bytes of p if it is a plain file (not a link) of at most limit bytes; else None and the reason."""
    try:
        st = os.lstat(p)
    except OSError as e:
        return None, f"missing: {e.strerror}"
    if not stat.S_ISREG(st.st_mode):
        return None, "not a plain file (link or special file)"
    if st.st_size > limit:
        return None, f"too large ({st.st_size} bytes)"
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            return fh.read(limit + 1), None
    except OSError as e:
        return None, f"unreadable: {e.strerror}"


def check_bytes(data, why=None):
    if data is None:
        return False, {}, [("file readable", False, why or "no output")], None
    if len(data) > MAX_BYTES:
        return False, {}, [("file readable", False, f"too large (over {MAX_BYTES} bytes)")], None
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        return False, {}, [("file readable", False, str(e)[:200])], None
    try:
        res, stats = verify.check(doc)
    except Exception as e:  # cannot happen with the current verify.py; kept so a crash is a recorded failure
        return False, {}, [("verifier crash", False, f"{type(e).__name__}: {e}"[:200])], None
    ok = len(res) == len(verify.RULES) and all(o is True for _, o, _ in res)
    return ok, stats or {}, res, doc if isinstance(doc, dict) else None


def canon(doc):
    try:
        return json.dumps([[["".join(sorted(c)) for c in row] for row in fl] for fl in doc["cells"]])
    except (TypeError, KeyError, AttributeError):
        return None


def floor_changes(st):
    seq = st.get("floor_sequence") if isinstance(st, dict) else None
    return len(seq) - 1 if isinstance(seq, list) and seq else 0


def evalbox(cmd, timeout=None):
    return subprocess.run(["bash", "-c", f'source "{HERE}/evalbox-lib.sh"; {cmd}'], timeout=timeout,
                          capture_output=True)


def plain_only(src, names):
    """copytree ignore: skip FIFOs, sockets and devices (opening one could hang the grader); keep links as links."""
    skip = []
    for n in names:
        try:
            m = os.lstat(os.path.join(src, n)).st_mode
        except OSError:
            skip.append(n)
            continue
        if not (stat.S_ISREG(m) or stat.S_ISDIR(m) or stat.S_ISLNK(m)):
            skip.append(n)
    return skip


def prepare(case_dir, gdir):
    if gdir.exists() or gdir.is_symlink():
        evalbox(f'eb_rm "{gdir}"')
        if gdir.exists() or gdir.is_symlink():
            raise HarnessError(f"could not clear {gdir}")
    gdir.mkdir(parents=True)
    shutil.copytree(case_dir / "work", gdir / "work0", symlinks=True, ignore=plain_only)
    r = evalbox(f'eb_take "{gdir}"')
    if r.returncode:
        raise HarnessError(f"eb_take failed: {r.stderr.decode(errors='replace')[:200]}")


def run_seed(case, gdir, name, seed):
    """One seed, one container. Returns (exit code, seconds, stdout bytes, log text)."""
    cname = re.sub(r"[^A-Za-z0-9_.-]", "_", f"t7g-{case}-{name}")[:120]
    inner = ("export HOME=/root PATH=/root/.cargo/bin:/opt/cargo/bin:$PATH; "
             "cp -r /src /tmp/w 2>/dev/null && cd /tmp/w || exit 120; "
             f"timeout -k 5 120 ./generate {int(seed)} /o/out.json > /o/log 2>&1; rc=$?; "
             "case $rc in 120|125) rc=1 ;; esac; "   # the program cannot pose as a harness failure
             # the program may leave a FIFO in /o; a bounded read cannot hang, and a cut read fails that seed only
             f"[ -f /o/out.json ] && [ ! -L /o/out.json ] && timeout -k 1 5 head -c {MAX_BYTES + 1} /o/out.json; "
             "[ -f /o/log ] && [ ! -L /o/log ] && timeout -k 1 5 head -c 20000 /o/log >&2; exit $rc")
    cmd = (f'podman rm -f "{cname}" >/dev/null 2>&1; '
           f'podman run --rm --name "{cname}" --network none --cpus 1 --memory 2g --pids-limit 256 --cap-drop=ALL '
           f'--security-opt=no-new-privileges --user root '
           f'--mount type=tmpfs,destination=/o,tmpfs-size=64m '
           f'-v "{gdir}/work0":/src:ro,Z "{IMAGE}" bash -c \'{inner}\'')
    t = time.time()
    try:
        r = evalbox(cmd, timeout=300)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = "host-timeout", b"", b"container ran past 300 s; removed"
    finally:
        evalbox(f'podman rm -f "{cname}" >/dev/null 2>&1 || true', timeout=120)
    return rc, round(time.time() - t, 1), out, err.decode("utf-8", "replace")[-2000:]


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # so the finally blocks remove containers
    case_dir = Path(sys.argv[1]).resolve()
    lock = open(case_dir / ".grade7.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"{case_dir.name}: another grader holds the lock; skipped")
        return 3
    try:
        status = json.loads((case_dir / "meta.json").read_text(encoding="utf-8")).get("status")
    except (OSError, ValueError, AttributeError):
        status = None
    if status is None or status in NOT_RUN:
        print(f"{case_dir.name}: not graded, the case did not run (meta status {status!r})")
        return 2

    g = {"case": case_dir.name, "graded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "meta_status": status}
    ok, stats, res, doc = check_bytes(*read_plain(case_dir / "work" / "labyrinth.json"))
    if doc:
        g["title"] = re.sub(r"[^\x20-\x7e]", "", str(doc.get("title", "")))[:40]
    raw, _ = read_plain(case_dir / "work" / "SHOWCASE_SEED", 64)
    sseed = raw.decode("ascii", "replace").strip() if raw is not None else ""
    sseed = int(sseed) if re.fullmatch(r"[0-9]{1,10}", sseed) and int(sseed) <= 2147483647 else None

    runs = [(f"s{i}", s) for i, s in enumerate(SEEDS)] + [("s0b", SEEDS[0])]
    if sseed is not None:
        runs.append(("show", sseed))
    gdir = case_dir / "grade7"
    try:
        prepare(case_dir, gdir)
        per, out = [], {}
        for name, seed in runs:
            rc, secs, data, log = run_seed(case_dir.name, gdir, name, seed)
            if rc in HARNESS_RC or rc == "host-timeout":
                raise HarnessError(f"run {name}: container exit {rc}: {log[-300:]}")
            okf, st, rs, gdoc = check_bytes(data if data else None, f"no maze written (exit {rc})")
            if rc in (124, 137):
                okf = False   # past the 120 s limit
                rs = [("time limit", False, "did not finish within 120 s")] + list(rs)
            out[name] = (okf, st, canon(gdoc) if gdoc else None)
            per.append({"run": name, "seed": seed, "exit": rc, "seconds": secs, "pass": okf,
                        "failed": [r for r, o, _ in rs if o is not True][:4], "path": st.get("path_length"),
                        "floor_changes": floor_changes(st) if st else None, "log_tail": log[-300:]})
    except (HarnessError, OSError, shutil.Error) as e:
        print(f"{case_dir.name}: not graded, harness failure: {e}")
        return 2

    round_trip = bool(ok and sseed is not None and out.get("show", (0, 0, None))[2] == canon(doc))
    perfect = {r: o for r, o, _ in res}
    if ok and round_trip:
        a = 2
    elif ok or all(perfect.get(k) is True for k in A1_RULES):
        a = 1
    else:
        a = 0
    g["A"] = {"score": a, "showcase_seed": sseed, "round_trip": round_trip, "stats": stats,
              "failed": [f"{r}: {m}" for r, o, m in res if o is not True]}

    seen, good = set(), []
    for i in range(len(SEEDS)):
        okf, st, key = out[f"s{i}"]
        if okf and key is not None and key not in seen:   # a generator that ignores the seed scores one pass
            seen.add(key)
            good.append(st)
    same = out["s0"][2] is not None and out["s0"][2] == out["s0b"][2]
    b = 2 if len(good) == len(SEEDS) and same else 1 if len(good) >= 5 else 0
    g["B"] = {"score": b, "distinct_passing": len(good), "of": len(SEEDS), "repeat_identical": same, "runs": per}
    if b == 2:
        worst_path = min(int(st.get("path_length") or 0) for st in good)
        worst_fc = min(floor_changes(st) for st in good)
        c = (worst_path >= STRETCH_PATH) + (worst_fc >= STRETCH_FLOOR_CHANGES)
        g["C"] = {"score": c, "worst_path": worst_path, "worst_floor_changes": worst_fc}
    else:
        g["C"] = {"score": 0, "note": "extra credit needs B = 2"}
    g["D"] = {"score": None, "note": "walkable quality, by hand (README.md rubric)"}
    try:
        notes = stat.S_ISREG(os.lstat(case_dir / "work" / "NOTES.md").st_mode)
    except OSError:
        notes = False
    g["E"] = {"score": None, "note": "NOTES.md against these results, by hand (README.md rubric)",
              "notes_present": notes}
    g["auto_total"] = a + b + g["C"]["score"]
    tmp = case_dir / "grade.json.tmp"
    tmp.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, case_dir / "grade.json")
    print(f"{case_dir.name}: A {a} (round trip {'yes' if round_trip else 'no'})  B {b} ({len(good)}/{len(SEEDS)} "
          f"distinct, repeat {'same' if same else 'differs'})  C {g['C']['score']}  (D, E by hand)  "
          f"title {g.get('title', '')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
