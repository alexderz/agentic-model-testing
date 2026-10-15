#!/usr/bin/env python3
"""Summary table of bench_tasks.py result files: summarize.py DIR ARM=GLOB [ARM=GLOB ...] (tab-separated on stdout)."""
import glob, json, statistics, sys

d = sys.argv[1]
print("arm\trounds\tcode\tprose\tstructured\tcode_min_max\tprose_min_max\tstructured_min_max\tttft_s_median\tshort_replies")
for spec in sys.argv[2:]:
    arm, pat = spec.split("=", 1)
    files = sorted(glob.glob(f"{d}/{pat}"))
    runs = [r for f in files for r in json.load(open(f))["runs"]]
    cols, ranges = [], []
    for task in ("code", "prose", "structured"):
        means = [json.load(open(f))["tok_s"][task] for f in files]
        per = [r["tok_s"] for r in runs if r["task"] == task]
        cols.append(f"{statistics.mean(means):.1f}")
        ranges.append(f"{min(per):.0f}-{max(per):.0f}")
    ttft = statistics.median(r["ttft_s"] for r in runs)
    short = sum(r["completion_tokens"] < 400 for r in runs)
    print("\t".join([arm, str(len(files))] + cols + ranges + [f"{ttft:.2f}", str(short)]))
