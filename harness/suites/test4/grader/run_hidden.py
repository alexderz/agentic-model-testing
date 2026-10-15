#!/usr/bin/env python3
"""Run one ticket's hidden acceptance checks. Runs inside the grading container only.

  run_hidden.py HIDDEN_DIR --list                 names of the checks, one JSON list
  run_hidden.py HIDDEN_DIR BINARY TREE            run them against the built server

HIDDEN_DIR/checks.py defines CHECKS = [(name, function), ...]; a check passes when it returns and
fails when it raises. Prints one JSON object: {"checks": [{"name", "ok", "detail"}, ...]}.
"""
import importlib.util
import json
import os
import signal
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t4lib  # noqa: E402

CHECK_TIMEOUT = int(os.environ.get("HIDDEN_CHECK_TIMEOUT", "120"))


def load(hidden):
    spec = importlib.util.spec_from_file_location("checks", os.path.join(hidden, "checks.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CHECKS


class Timeout(Exception):
    pass


def on_alarm(signum, frame):
    raise Timeout()


def main():
    checks = load(sys.argv[1])
    if sys.argv[2] == "--list":
        print(json.dumps([name for name, _ in checks]))
        return
    t4lib.BINARY, t4lib.TREE = sys.argv[2], sys.argv[3]
    signal.signal(signal.SIGALRM, on_alarm)
    out = []
    for name, fn in checks:
        signal.alarm(CHECK_TIMEOUT)
        try:
            fn()
            out.append({"name": name, "ok": True, "detail": ""})
        except t4lib.CheckFailed as e:
            out.append({"name": name, "ok": False, "detail": str(e)[:600]})
        except Timeout:
            out.append({"name": name, "ok": False, "detail": f"did not finish within {CHECK_TIMEOUT} s"})
        except Exception as e:
            last = traceback.extract_tb(e.__traceback__)[-1]
            out.append({"name": name, "ok": False,
                        "detail": f"{type(e).__name__}: {e} (checks line {last.lineno})"[:600]})
        finally:
            signal.alarm(0)
    print(json.dumps({"checks": out}))


main()
