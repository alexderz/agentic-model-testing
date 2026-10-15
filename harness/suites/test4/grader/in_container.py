#!/usr/bin/env python3
"""Test 4 grading, the part that executes code. Runs inside the grading container only
(grade-test4.sh starts it as evalbox; the tree under test is model-written).

Copies /src (read-only) to $GRADE_ROOT, then:
  1. cargo build --release
  2. cargo test --release --no-fail-fast, every test recorded by target and name
  3. the ticket's hidden checks (/hidden, when mounted) against the built binary

Prints one JSON object on the last line of stdout.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

SRC = "/src"
ROOT = os.environ.get("GRADE_ROOT", "/home/agent/grading")
HIDDEN = "/hidden"
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT", "1800"))
TEST_TIMEOUT = int(os.environ.get("TEST_TIMEOUT", "1800"))
HIDDEN_TIMEOUT = int(os.environ.get("HIDDEN_TIMEOUT", "1200"))


def sh(args, cwd, timeout):
    """(exit code, stdout and stderr merged in the order they were written)."""
    try:
        r = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace", timeout=timeout)
        return r.returncode, r.stdout or ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        return -9, (out.decode(errors="replace") if isinstance(out, bytes) else out) + "\nTIMEOUT"
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def find_manifest():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in ("target", ".git", "node_modules"))
        if "Cargo.toml" in files and "[package]" in open(os.path.join(root, "Cargo.toml"), errors="replace").read():
            return root
    return None


RUNNING = re.compile(r"^\s*Running (?:unittests )?(\S+) \(")
DOCTEST = re.compile(r"^\s*Doc-tests (\S+)")
TEST = re.compile(r"^test (.+?) \.\.\. (ok|FAILED|ignored)\b")
RESULT = re.compile(r"^test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored")


def parse_tests(blob):
    """Per-test outcomes keyed "<target>::<test name>", and the totals of the "test result" lines."""
    tests, target, passed, failed = {}, "?", 0, 0
    for line in blob.splitlines():
        m = RUNNING.match(line)
        if m:
            target = m.group(1); continue
        m = DOCTEST.match(line)
        if m:
            target = "doc-tests"; continue
        m = TEST.match(line)
        if m:
            tests[f"{target}::{m.group(1)}"] = {"ok": "pass", "FAILED": "fail", "ignored": "ignored"}[m.group(2)]
            continue
        m = RESULT.match(line)
        if m:
            passed += int(m.group(1)); failed += int(m.group(2))
    return tests, passed, failed


def hidden_names():
    rc, out = sh([sys.executable, os.path.join(HERE, "run_hidden.py"), HIDDEN, "--list"], "/", 60)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []


def main():
    res = {"builds": False, "build_error": None, "tests": {}, "tests_passed": 0, "tests_failed": 0,
           "tests_rc": None, "hidden": None, "note": None}
    have_hidden = os.path.exists(os.path.join(HIDDEN, "checks.py"))
    if have_hidden:
        # a tree that does not build fails every hidden check
        res["hidden"] = [{"name": n, "ok": False, "detail": "not run: the tree did not build"} for n in hidden_names()]

    if os.path.exists(ROOT):
        shutil.rmtree(ROOT)
    shutil.copytree(SRC, ROOT, symlinks=True)
    root = find_manifest()
    if not root:
        res["note"] = "no Cargo.toml with a [package] section"
        print(json.dumps(res)); return
    res["manifest"] = os.path.relpath(root, ROOT)

    t0 = time.time()
    rc, out = sh(["cargo", "build", "--release"], root, BUILD_TIMEOUT)
    res["build_seconds"] = round(time.time() - t0, 1)
    res["builds"] = rc == 0
    if rc != 0:
        errs = [l for l in out.splitlines() if l.startswith("error")]
        res["build_error"] = ("; ".join(errs[:3]) or out[-300:])[:300]
        print(json.dumps(res)); return

    rel = os.path.join(root, "target", "release")
    cands = sorted(os.path.join(rel, f) for f in os.listdir(rel)
                   if "." not in f and os.path.isfile(os.path.join(rel, f)) and os.access(os.path.join(rel, f), os.X_OK))
    binary = next((c for c in cands if os.path.basename(c) == "ha-mcp"), cands[0] if cands else None)
    res["binary"] = os.path.basename(binary) if binary else None

    t0 = time.time()
    rc, out = sh(["cargo", "test", "--release", "--no-fail-fast"], root, TEST_TIMEOUT)
    res["test_seconds"] = round(time.time() - t0, 1)
    res["tests_rc"] = rc
    res["tests"], res["tests_passed"], res["tests_failed"] = parse_tests(out)
    if rc != 0 and not res["tests"]:
        errs = [l for l in out.splitlines() if l.startswith("error")]
        res["note"] = ("tests did not run: " + ("; ".join(errs[:3]) or out[-200:]))[:300]

    if have_hidden and binary:
        t0 = time.time()
        rc, out = sh([sys.executable, os.path.join(HERE, "run_hidden.py"), HIDDEN, binary, root], "/", HIDDEN_TIMEOUT)
        res["hidden_seconds"] = round(time.time() - t0, 1)
        try:
            res["hidden"] = json.loads(out.strip().splitlines()[-1])["checks"]
        except (ValueError, IndexError, KeyError, TypeError):
            for h in res["hidden"]:
                h["detail"] = "the hidden check runner failed: " + out[-200:]
    elif have_hidden:
        for h in res["hidden"]:
            h["detail"] = "not run: the build left no runnable binary"
    print(json.dumps(res))


main()
