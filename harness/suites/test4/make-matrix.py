#!/usr/bin/env python3
"""Print the test 4 matrix rows for one model: every ticket, N runs each.

  suites/test4/make-matrix.py SHORT_NAME ENTRY [FLAGS] [--runs 5] [--tickets a,b] > matrix-test4-SHORT_NAME.tsv

SHORT_NAME goes into the case name (t4-<ticket>-<short name>-r<n>), ENTRY is the llama-swap entry,
FLAGS its flag line or "-" for an entry used as configured (take it from the model's test 3 row).
Rows are in the format tools/tune_and_run.py and run-matrix.sh read: case, entry, flags, note, tab
separated. The note starts with "fixed" so tune_and_run.py does not re-tune the flags between runs
(every run of a model must use the same settings) and carries ticket=<id>, which run-case-test4.sh
reads. Runs are interleaved by ticket, so a queue stopped early still covers every ticket.
"""
import argparse, os

here = os.path.dirname(os.path.abspath(__file__))
known = sorted(t for t in os.listdir(os.path.join(here, "tickets"))
               if os.path.exists(os.path.join(here, "tickets", t, "TICKET.md")))
ap = argparse.ArgumentParser()
ap.add_argument("short"); ap.add_argument("entry"); ap.add_argument("flags", nargs="?", default="-")
ap.add_argument("--runs", type=int, default=5)
ap.add_argument("--tickets", default=",".join(known))
a = ap.parse_args()
if "-r" in a.short and a.short.rsplit("-r", 1)[1].isdigit():
    ap.error("the short name must not end in -r<digits>: that suffix is the run number")
print(f"# Test 4 (suites/test4/DESIGN.md): {a.entry}, {a.runs} runs of each ticket, identical settings.")
for n in range(1, a.runs + 1):
    for t in a.tickets.split(","):
        if t not in known: ap.error(f"unknown ticket {t}; known: {', '.join(known)}")
        print(f"t4-{t}-{a.short}-r{n}\t{a.entry}\t{a.flags}\tfixed: ticket={t} run={n}")
