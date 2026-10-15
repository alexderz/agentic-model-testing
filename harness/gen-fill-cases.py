#!/usr/bin/env python3
"""Turn fill-probe results into new matrix cases.

Same models, a second parameter set that actually fills the card. The original
cases stay exactly as they are -- these are additional variants, not edits.
"""
import csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
probe = os.path.join(HERE, "results", "fill-probe.tsv")
matrix = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "matrix-r2.tsv")

# existing cases, so we can name the new ones after them and skip duplicates
rows = []
with open(matrix) as fh:
    for line in fh:
        if line.startswith("#") or not line.strip():
            continue
        rows.append(line.rstrip("\n").split("\t"))
existing = {r[0] for r in rows}

def base_case(model, ctx):
    for r in rows:
        if r[1] == model and f"-c {ctx}" in r[2]:
            return r[0]
    return None

added = []
with open(probe) as fh:
    for rec in csv.DictReader(fh, delimiter="\t"):
        if rec["best_ncmoe"] in ("NONE", ""):
            continue
        model, ctx, start, best = rec["model"], rec["ctx"], rec["start_ncmoe"], rec["best_ncmoe"]
        if str(best) == str(start):
            continue  # already optimal, nothing to add
        base = base_case(model, ctx)
        name = (base + "-fill") if base else f"{model}-{ctx}-fill"
        if name in existing:
            continue
        flags = f"-ngl 999 -ncmoe {best} -c {ctx}"
        note = (f"fill variant: ncmoe {start}->{best}, "
                f"{rec['vram_mib']} MiB resident ({rec['headroom_mib']} MiB spare)")
        added.append((name, model, flags, note))

if not added:
    print("no fill cases to add")
    sys.exit(0)

with open(matrix, "a") as fh:
    fh.write("# ---- fill variants: same models, parameters that use the whole card ----\n")
    fh.write("# The original cases were tuned for context and left 5-15 GB of VRAM idle.\n")
    for a in added:
        fh.write("\t".join(a) + "\n")

for a in added:
    print(f"added {a[0]:<24} {a[2]}")
