"""Struggle score: how hard did the model fight the compiler/interpreter on the way to its result?

  python3 tools/grade_struggle.py <case dir> [...]        # TSV to stdout
  from grade_struggle import struggle; struggle(case_dir)  # dict

Operator 2026-10-06: count Rust compile errors (syntax, invented names) and Python errors, to see
whether a model brute-forced its solution against the compiler or wrote clean code from the start;
"a strong signal towards the smart / not smart axis".

Reads every shell tool call and its output from the transcript (OpenCode events.jsonl, or Pi
session/*.jsonl). Rust: each cargo build/check/test/run/clippy is a compile attempt; it failed if
the output says "could not compile"; the error count comes from "due to N previous errors" (so
output the agent cut with tail still counts), and visible error codes and messages are classified.
A failed build re-run with no file edit in between (only a different tail/grep) is the same broken
state and is counted once.
Python: each output containing a traceback or a compile error counts once per error type.
Normalised per 1,000 lines of the final code (meta.json rs_loc / py_loc, else counted).
"""
import glob, json, os, re, sys

# Rust error classes by code, plus code-less parser messages
NAMES = {"E0425", "E0433", "E0412", "E0599", "E0432", "E0609", "E0560", "E0422", "E0423", "E0574", "E0405", "E0407", "E0061", "E0107"}
TYPES = {"E0308", "E0277", "E0369", "E0282", "E0614", "E0600", "E0604", "E0605", "E0606", "E0053", "E0046", "E0050"}
BORROW = {"E0382", "E0499", "E0502", "E0505", "E0506", "E0507", "E0515", "E0596", "E0597", "E0716", "E0373", "E0384", "E0621"}
SYNTAX_MSG = re.compile(r"^error: (this file contains an unclosed delimiter|unexpected closing delimiter|mismatched closing delimiter|expected .*|unterminated .*|unknown start of token.*|missing .* in .*|unexpected token.*)$", re.M)
CARGO = re.compile(r"\bcargo\s+(build|check|test|run|clippy)\b")
PY_ERR = {"syntax": re.compile(r"\b(SyntaxError|IndentationError|TabError)\b"),
          "names": re.compile(r"\b(NameError|AttributeError|ModuleNotFoundError|ImportError)\b"),
          "types": re.compile(r"\bTypeError\b")}


BASH_WRITE = re.compile(r"sed\s+-i|>\s*[\w./]|\btee\b|cargo\s+(add|update|fix)|\b(mv|cp|rm|patch|git\s+(apply|checkout))\b|python3?\s+-c|<<")
EDITS = {"edit", "write", "patch", "multiedit", "apply_patch"}


def calls(case):
    """Yield (command, output) for every shell tool call in the transcript, and (None, "") for each
    file edit (so a rerun of the same failed build with no edit in between is not counted twice)."""
    ev = os.path.join(case, "events.jsonl")
    if os.path.exists(ev) and os.path.getsize(ev) > 0:
        for l in open(ev, errors="replace"):
            try: e = json.loads(l)
            except ValueError: continue
            p = e.get("part") or {}
            if e.get("type") == "tool_use" and p.get("tool") == "bash":
                st = p.get("state") or {}
                yield str((st.get("input") or {}).get("command", "")), str(st.get("output") or "")
            elif e.get("type") == "tool_use" and p.get("tool") in EDITS:
                yield None, ""
    for f in glob.glob(os.path.join(case, "session", "*.jsonl")):
        cmds = {}
        for l in open(f, errors="replace"):
            try: m = json.loads(l).get("message") or {}
            except ValueError: continue
            if m.get("role") == "assistant":
                for c in m.get("content") or []:
                    if c.get("type") == "toolCall": cmds[c.get("id")] = str((c.get("arguments") or {}).get("command", ""))
            elif m.get("role") == "toolResult" and m.get("toolName") == "bash":
                out = "".join(c.get("text", "") for c in m.get("content") or [] if isinstance(c, dict))
                yield cmds.get(m.get("toolCallId"), ""), out
            elif m.get("role") == "toolResult" and m.get("toolName") in EDITS:
                yield None, ""


def loc(case):
    # count the model's own source only: meta.json's rs_loc includes vendored crates (one run: 210k lines)
    n = 0
    skip = {"target", "vendor", ".venv", "venv", "docs", "mcp-docs", ".git", ".cargo", "registry", "node_modules", "site-packages"}
    for dp, dn, fn in os.walk(os.path.join(case, "work")):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            if f.endswith((".rs", ".py")):
                try: n += sum(1 for _ in open(os.path.join(dp, f), errors="replace"))
                except OSError: pass
    return n


def struggle(case):
    r = dict(compiles=0, failed_compiles=0, first_compile_ok=None, rust_errors=0, rs_syntax=0, rs_names=0,
             rs_types=0, rs_borrow=0, rs_other=0, rs_unclassified=0, py_error_outputs=0, py_syntax=0, py_names=0, py_types=0)
    stale = False   # a build failed and nothing was edited since: further builds re-read the same errors
    for cmd, out in calls(case):
        if cmd is None or BASH_WRITE.search(cmd): stale = False
        if cmd is None: continue
        if CARGO.search(cmd):
            if stale: continue   # same broken state read again (other tail/grep): count it once
            r["compiles"] += 1
            failed = "could not compile" in out or re.search(r"^error(\[E\d{4}\])?:", out, re.M) is not None
            if r["first_compile_ok"] is None: r["first_compile_ok"] = not failed
            if failed:
                r["failed_compiles"] += 1
                n = sum(int(x) for x in re.findall(r"due to (\d+) previous errors?", out))
                stale = True
                codes = re.findall(r"^error\[(E\d{4})\]", out, re.M)
                syn = len(SYNTAX_MSG.findall(out))
                r["rust_errors"] += max(n, len(codes) + syn, 1)
                r["rs_syntax"] += syn
                for c in codes:
                    k = "rs_names" if c in NAMES else "rs_types" if c in TYPES else "rs_borrow" if c in BORROW else "rs_other"
                    r[k] += 1
        if "Traceback (most recent call last)" in out or re.search(r"^\s*File \".*\", line \d+", out, re.M):
            hit = False
            for k, rx in PY_ERR.items():
                if rx.search(out): r["py_" + k] += 1; hit = True
            if hit: r["py_error_outputs"] += 1
    r["rs_unclassified"] = max(0, r["rust_errors"] - r["rs_syntax"] - r["rs_names"] - r["rs_types"] - r["rs_borrow"] - r["rs_other"])
    n = loc(case)
    r["loc"] = n
    r["errors_per_kloc"] = round((r["rust_errors"] + r["py_syntax"] + r["py_names"] + r["py_types"]) * 1000 / n, 1) if n else None
    return r


if __name__ == "__main__":
    cols = ["compiles", "failed_compiles", "first_compile_ok", "rust_errors", "rs_syntax", "rs_names", "rs_types", "rs_borrow",
            "rs_other", "rs_unclassified", "py_error_outputs", "py_syntax", "py_names", "py_types", "loc", "errors_per_kloc"]
    print("case\t" + "\t".join(cols))
    for c in sys.argv[1:]:
        s = struggle(c.rstrip("/"))
        print(os.path.basename(c.rstrip("/")) + "\t" + "\t".join(str(s[k]) for k in cols))
