#!/usr/bin/env python3
"""Reply identity and draft acceptance for the llama.cpp + DFlash2 arm.  analyze.py RESULTS_DIR"""
import glob, json, os, re, sys

R = sys.argv[1]


def texts(n):
    return [x["text"] for x in json.load(open(os.path.join(R, n + ".json")))["runs"]]


def same(a, b):
    return sum(x == y for x, y in zip(texts(a), texts(b)))


def have(n):
    return os.path.exists(os.path.join(R, n + ".json"))


pairs = [
    ("lcpp-dflash2-r1", "lcpp-dflash2-r2"), ("lcpp-dflash2-r1", "lcpp-dflash2-r3"),
    ("lcpp-mtp-r1", "lcpp-mtp-r2"), ("lcpp-mtp-r1", "lcpp-mtp-r3"),
    ("tf-dflash2-s3-r1", "tf-dflash2-s3-r2"), ("tf-dflash2-s3-r1", "tf-dflash2-s3-r3"),
    ("lcpp-nodraft", "lcpp-dflash2-r1"), ("lcpp-nodraft", "lcpp-dflash2-bf16-np1"),
    ("lcpp-nodraft", "lcpp-dflash2-q4-np1"), ("lcpp-nodraft", "lcpp-dflash2-q4-np4"),
    ("lcpp-nodraft", "lcpp-dflash2-smoke"),
]
for a, b in pairs:
    if have(a) and have(b):
        print(f"identical replies {a} vs {b}: {same(a, b)}/15")
for f in sorted(glob.glob(os.path.join(R, "*.json"))):
    d = json.load(open(f))
    think = sum("<think>" in x["text"] for x in d["runs"])
    short = sum(x["completion_tokens"] < 400 for x in d["runs"])
    print(os.path.basename(f), "runs", len(d["runs"]), "think-tags", think, "short", short)
for f in sorted(glob.glob(os.path.join(R, "lcpp-*.server.log"))):
    a = g = n = 0
    for line in open(f, errors="replace"):
        m = re.search(r"draft acceptance = [0-9.]+ \(\s*(\d+) accepted /\s*(\d+) generated\)", line)
        if m:
            a += int(m.group(1)); g += int(m.group(2)); n += 1
    print(os.path.basename(f), f"requests with drafts {n}, accepted {a} of {g}" + (f" ({100*a/g:.0f} %)" if g else ""))
