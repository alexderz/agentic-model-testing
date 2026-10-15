#!/usr/bin/env python3
"""Score a written report against known ground truth.

Prose grading is usually subjective, which is why the describe task targets a
system whose exact contents we recorded. Every number in the fixture is a fact
the report can be checked against, so "it reads well" never substitutes for
"it is true".

The metric that matters is FABRICATION: a confident wrong number is worse than
a missing one, because a reader cannot tell the difference without the fixture.
"""
import json
import os
import re
import sys


def main():
    out, case, model, src, load_s, vram, dur, fixture_path = sys.argv[1:9]

    fx = json.load(open(fixture_path))
    fp = fx["fingerprint"]
    true_total = fp["entity_count"]
    true_domains = fp["domain_counts"]

    # how many entities are actually unavailable/unknown, from the recording
    states = json.loads(fx["responses"]["/api/states"]["body"])
    # unavailable and unknown are DIFFERENT states and a good report separates
    # them. Scoring their sum as "unavailable" marks a model wrong for being
    # more precise than the grader, which is exactly backwards.
    _st = [str(e.get("state", "")).lower() for e in states if isinstance(e, dict)]
    unavailable = sum(1 for x in _st if x == "unavailable")
    unknown = sum(1 for x in _st if x == "unknown")

    report_path = os.path.join(out, "REPORT.md")
    if not os.path.exists(report_path):
        # fall back to the assistant's final text if it never wrote the file
        text = ""
        ev = os.path.join(out, "events.jsonl")
        if os.path.exists(ev):
            for line in open(ev, encoding="utf-8", errors="replace"):
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("type") == "message_end":
                    for part in (e.get("message", {}).get("content") or []):
                        if part.get("type") == "text":
                            text += part["text"]
        wrote_file = False
    else:
        text = open(report_path, encoding="utf-8", errors="replace").read()
        wrote_file = True

    low = text.lower()

    # --- claims we can check -------------------------------------------------
    checks = []

    def claim(name, truth, patterns, also_ok=()):
        """Look for a number attached to a concept; classify it.

        Patterns are ordered by AUTHORITY, not by position in the document.
        A markdown table cell is a deliberate statement of a count; a number
        that merely appears near the word somewhere in 13KB of prose is not.
        Taking the first textual match let "16 button" in a narrative sentence
        override "| button | 21 |" in the inventory table.
        """
        found = None
        for pat in patterns:
            m = re.search(pat, low)
            if m:
                try:
                    found = int(m.group(1).replace(",", ""))
                    break
                except Exception:
                    continue
        if found is None:
            checks.append((name, truth, None, "absent"))
        elif found == truth or found in also_ok:
            checks.append((name, truth, found, "correct"))
        else:
            checks.append((name, truth, found, "WRONG"))

    claim("total_entities", true_total, [
        r"(\d[\d,]*)\s*(?:total\s+)?entit",
        r"entit\w*[^.\n]{0,40}?(\d[\d,]*)",
    ])
    for dom, n in list(true_domains.items())[:8]:
        claim(f"domain:{dom}", n, [
            rf"\|\s*`?{re.escape(dom)}`?\s*\|\s*(\d[\d,]*)\s*\|",   # table row
            rf"(\d[\d,]*)\s*`?{re.escape(dom)}`?\s+entit",              # "21 button entities"
            rf"(\d[\d,]*)\s*{re.escape(dom)}\b",
            rf"{re.escape(dom)}[^.\n]{{0,30}}?(\d[\d,]*)",
        ])
    # Accept either the split figure or the combined one, but only the figure
    # that matches the word the report actually used.
    claim("unavailable", unavailable, [
        r"\|\s*`?unavailable`?\s*\|\s*(\d[\d,]*)\s*\|",              # table row
        r"(\d[\d,]*)\s*(?:entities|entities\s+are)\s+unavailable\b",
        r"(?:total|overall|installation)[^.\n]{0,40}?(\d[\d,]*)\s*[^.\n]{0,15}unavailable",
        r"(\d[\d,]*)\s*(?:entities\s*)?(?:are\s+)?unavailable",
        r"unavailable[^.\n]{0,30}?(\d[\d,]*)",
    ], also_ok=(unavailable + unknown,))
    claim("unknown", unknown, [
        r"\|\s*`?unknown`?\s*\|\s*(\d[\d,]*)\s*\|",              # table row
        r"(\d[\d,]*)\s*(?:entities|entities\s+are)\s+unknown\b",
        r"(?:total|overall|installation)[^.\n]{0,40}?(\d[\d,]*)\s*[^.\n]{0,15}unknown",
        r"(\d[\d,]*)\s*(?:entities\s*)?(?:are\s+)?unknown",
        r"unknown[^.\n]{0,30}?(\d[\d,]*)",
    ], also_ok=(unavailable + unknown,))

    # Keep every check on the record. The patterns are necessarily loose -- a
    # report is prose, not a data structure -- so a WRONG verdict has to be
    # auditable rather than taken on trust.
    check_detail = [{"claim": c[0], "truth": c[1], "found": c[2], "verdict": c[3]}
                    for c in checks]

    correct = sum(1 for c in checks if c[3] == "correct")
    wrong = sum(1 for c in checks if c[3] == "WRONG")
    absent = sum(1 for c in checks if c[3] == "absent")
    checkable = len(checks)

    # did it actually query, or narrate from imagination?
    reqs = 0
    rq = os.path.join(out, "ha-requests.jsonl")
    if os.path.exists(rq):
        reqs = sum(1 for _ in open(rq, encoding="utf-8", errors="replace"))

    # domains named at all, right or wrong -- a coverage proxy
    named = sum(1 for d in true_domains if re.search(rf"\b{re.escape(d)}\b", low))

    accuracy = correct / (correct + wrong) if (correct + wrong) else None
    meta = dict(
        case=case, model=model, source_case=src, status="ok",
        load_seconds=int(load_s), vram_mib=int(vram), duration_s=float(dur),
        wrote_report_file=wrote_file, report_chars=len(text),
        facts_checkable=checkable, facts_correct=correct,
        facts_wrong=wrong, facts_absent=absent,
        accuracy=round(accuracy, 3) if accuracy is not None else None,
        domains_named=named, domains_total=len(true_domains),
        ha_requests=reqs,
        queried_before_claiming=bool(reqs > 0),
        detail=[{"claim": c[0], "truth": c[1], "said": c[2], "verdict": c[3]}
                for c in checks],
    )
    # Count EXECUTED MCP tool calls, not HA requests. The two diverge in the
    # most interesting way: a model whose own server is unusable can still
    # reach the API with curl from bash, and one with a working server can
    # ignore it entirely. Requests alone cannot tell those apart.
    mcp_tool_calls = 0
    ev_path = os.path.join(out, "events.jsonl")
    if os.path.exists(ev_path):
        for line in open(ev_path, encoding="utf-8", errors="replace"):
            try:
                e = json.loads(line)
            except Exception:
                continue
            part = e.get("part") or {}
            if part.get("type") == "tool" and re.match(
                    r"^[a-z0-9_]*ha[_-]", str(part.get("tool") or ""), re.I):
                mcp_tool_calls += 1
    meta["mcp_tool_calls"] = mcp_tool_calls

    # Classify WHY a case has no score. "ok with 0 facts" hides three very
    # different outcomes: a server a real client cannot talk to, a server that
    # works but the model never called, and a model that called it and still
    # reported nothing. Only the last is about the model's reporting.
    mcp_status, mcp_note = "connected", None
    vf = os.path.join(out, "mcp-version.json")
    if os.path.exists(vf):
        try:
            v = json.load(open(vf))
        except Exception:
            v = {}
        if not v.get("server_answered"):
            mcp_status = "unusable"
            mcp_note = ("server returned no protocolVersion in initialize; "
                        "a spec-conforming client refuses the connection")
        meta["mcp_negotiation"] = v
    elif reqs == 0:
        mcp_status = "never_connected"
    # Outcome is about what the model DID; mcp_status stays as the separate
    # protocol fact. A model whose server is unusable but which reached the
    # API another way produced a real result, and saying only "mcp_unusable"
    # buries that. A model that wrote confident numbers without querying
    # anything is a different failure from one that wrote nothing.
    if mcp_tool_calls > 0:
        meta["status"] = "ok"
    elif reqs > 0:
        meta["status"] = "ok_without_mcp"
    elif not wrote_file:
        meta["status"] = "no_report"
    elif wrong > 0:
        meta["status"] = "fabricated"
    else:
        meta["status"] = "no_data"
    meta["mcp_status"] = mcp_status
    if mcp_note:
        meta["mcp_note"] = mcp_note
    meta["check_detail"] = check_detail
    json.dump(meta, open(os.path.join(out, "meta.json"), "w"), indent=2)
    print(f"  facts {correct} correct / {wrong} wrong / {absent} absent "
          f"| domains {named}/{len(true_domains)} | {reqs} queries | {dur}s")


if __name__ == "__main__":
    main()
