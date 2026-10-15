"""Generation tok/s over a whole agent run: (output + reasoning tokens) / wall span.

OpenCode reports reasoning separately when the server splits it out (vLLM's
qwen3 reasoning parser); llama.cpp runs report it inside output. Counting only
output undercounted the vLLM run 3x (22 vs 70 tok/s), so both are summed from
the per-step token records in events.jsonl.

events.jsonl holds the MAIN session only. A case that delegates to a subagent
(test 3's probe) spends most of its wall time generating in the child session,
so main-only tokens over the whole span showed about 3 tok/s where streaming
was 12 to 15. The line therefore ends with a second figure that adds every
session in oc-data/opencode.db (2026-10-10).

Output, tab-separated; the first five fields are unchanged:
  case, "span N min", "out N", "reasoning N", "X tok/s"          main session (events.jsonl)
  "all-sessions out N", "reasoning N", "X tok/s", "sessions N"   every session (opencode.db),
                                                                 or "all-sessions n/a" without a db
The all-sessions rate divides by the same wall span, so with subagents that
run one at a time it is the average generation rate of the whole case.
"""
import json, os, sqlite3, sys


def all_sessions(d):
    """(output, reasoning, session count) summed over every session's step-finish parts, or None."""
    p = os.path.join(d, "oc-data", "opencode.db")
    if not os.path.exists(p):
        return None
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        o = r = 0
        sessions = set()
        for sid, data in c.execute("select session_id, data from part"):
            try: e = json.loads(data)
            except ValueError: continue
            if e.get("type") not in ("step-finish", "step_finish"): continue
            tk = e.get("tokens") or {}
            o += tk.get("output", 0) or 0; r += tk.get("reasoning", 0) or 0
            sessions.add(sid)
        n = c.execute("select count(*) from session").fetchone()[0]
        c.close()
        return o, r, n or len(sessions)
    except sqlite3.Error:
        return None


if __name__ == "__main__":
    for d in sys.argv[1:]:
        ts, o, r = [], 0, 0
        for l in open(f"{d}/events.jsonl"):
            try: e = json.loads(l)
            except ValueError: continue
            t = e.get("timestamp") or e.get("time") or (e.get("part", {}).get("time", {}) or {}).get("end")
            if isinstance(t, (int, float)): ts.append(t / 1000 if t > 1e12 else t)
            if e.get("type") in ("step_finish", "step-finish"):
                tk = (e.get("part") or {}).get("tokens") or {}
                o += tk.get("output", 0) or 0; r += tk.get("reasoning", 0) or 0
        span = max(ts) - min(ts) if ts else 0
        line = f"{d.rstrip('/').split('/')[-1]}\tspan {span/60:.0f} min\tout {o}\treasoning {r}\t{(o+r)/span if span else 0:.1f} tok/s"
        a = all_sessions(d)
        if a is None:
            line += "\tall-sessions n/a"
        else:
            ao, ar, n = a
            line += f"\tall-sessions out {ao}\treasoning {ar}\t{(ao+ar)/span if span else 0:.1f} tok/s\tsessions {n}"
        print(line)
