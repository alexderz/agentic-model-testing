#!/usr/bin/env python3
"""Reference generator for bake-off test 7 (not shown to the agents): proves the rules can all be met, for any seed.

    python3 generate.py SEED OUT.json

Plan: lay the solution path first, in five segments (floor 0, 1, 2, 1, 2) that each own a part of their floor, as a
zig-zag that is then lengthened by "bumps" (an edge a-b becomes a-a'-b'-b); add the spare stairs; grow the rest
with a randomized Kruskal that refuses loops and straight runs over five cells; retry on the rare dead end."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import verify  # noqa: E402

F, W, D, MAXRUN = 3, 16, 16, 5
STEP = {"E": (1, 0), "W": (-1, 0), "S": (0, 1), "N": (0, -1)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E", "U": "D", "D": "U"}


def dir_of(a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    return {(1, 0): "E", (-1, 0): "W", (0, 1): "S", (0, -1): "N"}[(dx, dz)]


def zigzag(rng, a, b):
    path, (x, z) = [a], a
    while (x, z) != b:
        opts = []
        if x != b[0]:
            opts.append((x + (1 if b[0] > x else -1), z))
        if z != b[1]:
            opts.append((x, z + (1 if b[1] > z else -1)))
        x, z = rng.choice(opts)
        path.append((x, z))
    return path


def runs(path):
    """Longest straight run of the segment, as cells."""
    best, cur, prev = 1, 1, None
    for i in range(len(path) - 1):
        d = dir_of(path[i], path[i + 1])
        cur = cur + 1 if d == prev else 2
        best, prev = max(best, cur), d
    return best


def stretch(rng, path, target, ok_cell, used):
    tries, cur = 0, runs(path)
    while (len(path) < target or cur > MAXRUN) and tries < 6000:
        tries += 1
        i = rng.randrange(len(path) - 1)
        a, b = path[i], path[i + 1]
        dx, dz = b[0] - a[0], b[1] - a[1]
        for px, pz in rng.sample([(dz, dx), (-dz, -dx)], 2):
            a2, b2 = (a[0] + px, a[1] + pz), (b[0] + px, b[1] + pz)
            if ok_cell(a2) and ok_cell(b2) and a2 not in used and b2 not in used:
                new = path[:i + 1] + [a2, b2] + path[i + 1:]
                rn = runs(new)
                if rn <= max(MAXRUN, cur) and (rn < cur or len(path) < target):
                    path[:] = new
                    used.update((a2, b2))
                    cur = rn
                break
    return len(path) >= target and cur <= MAXRUN


def build(seed):
    rng = random.Random(seed)
    r = lambda lo, hi: rng.randint(lo, hi)  # noqa: E731
    s1, s2, s3, s4 = (r(2, 5), r(9, 12)), (r(2, 5), r(2, 5)), (r(10, 13), r(2, 5)), (r(10, 13), r(10, 13))
    segs = [  # floor, start, end, region, target length
        (0, (0, 0), s1, lambda c: True, 62),
        (1, s1, s2, lambda c: c[0] <= 7, 46),
        (2, s2, s3, lambda c: c[1] <= 7, 50),
        (1, s3, s4, lambda c: c[0] >= 8, 46),
        (2, s4, (15, 15), lambda c: c[1] >= 8, 52),
    ]
    stairs = {0: {s1}, 1: {s1, s2, s3, s4}, 2: {s2, s3, s4}}
    used = {f: set() for f in range(F)}
    for f, a, b, reg, _ in segs:
        used[f].update((a, b))
    paths = []
    for f, a, b, reg, tgt in segs:
        p = zigzag(rng, a, b)
        if any(c in used[f] for c in p[1:-1]):
            return None
        used[f].update(p)

        def ok(c, f=f, reg=reg):
            return 0 <= c[0] < W and 0 <= c[1] < D and reg(c) and not any(
                abs(c[0] - s[0]) <= 1 and abs(c[1] - s[1]) <= 1 for s in stairs[f])
        if not stretch(rng, p, tgt, ok, used[f]):
            return None
        paths.append((f, p))

    cells = [[[set() for _ in range(W)] for _ in range(D)] for _ in range(F)]
    parent = {}

    def find(u):
        while parent.setdefault(u, u) != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def link(u, v, ch):
        cells[u[0]][u[2]][u[1]].add(ch)
        cells[v[0]][v[2]][v[1]].add(OPP[ch])
        parent[find(u)] = find(v)

    full = []
    for f, p in paths:
        for i in range(len(p) - 1):
            link((f, *p[i]), (f, *p[i + 1]), dir_of(p[i], p[i + 1]))
        full += [(f, *c) for c in p]
    link((0, *s1), (1, *s1), "U")
    link((1, *s2), (2, *s2), "U")
    link((1, *s3), (2, *s3), "U")
    link((1, *s4), (2, *s4), "U")
    cells[0][0][0].add("W")
    cells[2][15][15].add("E")
    onpath = {f: {c for g, p in paths if g == f for c in p} for f in range(F)}

    def straight_ok(u, ch):
        """Would joining u to its neighbour in direction ch make a straight run longer than MAXRUN?"""
        f, x, z = u
        dx, dz = STEP[ch]
        inside = lambda a, b: 0 <= a < W and 0 <= b < D  # noqa: E731
        back, cx, cz = 0, x, z
        while OPP[ch] in cells[f][cz][cx] and inside(cx - dx, cz - dz):
            cx, cz, back = cx - dx, cz - dz, back + 1
        fwd, cx, cz = 0, x + dx, z + dz
        while ch in cells[f][cz][cx] and inside(cx + dx, cz + dz):
            cx, cz, fwd = cx + dx, cz + dz, fwd + 1
        return back + 1 + fwd + 1 <= MAXRUN

    # spare stairs: 3 more between floors 0-1, 1 more between 1-2, each end joined sideways once
    for f, extra in ((0, 3), (1, 1)):
        for _ in range(extra):
            for _ in range(400):
                c = (r(1, 14), r(1, 14))
                if any(c in onpath[g] for g in (f, f + 1)):
                    continue
                if any(abs(c[0] - s[0]) <= 1 and abs(c[1] - s[1]) <= 1 for g in (f, f + 1) for s in stairs[g]):
                    continue
                if find((f, *c)) == find((f + 1, *c)):
                    continue
                stairs[f].add(c)
                stairs[f + 1].add(c)
                link((f, *c), (f + 1, *c), "U")
                break
            else:
                return None
    stair_set = {(f, *c) for f in range(F) for c in stairs[f]}
    for u in sorted(stair_set):
        if any(ch in "NESW" for ch in cells[u[0]][u[2]][u[1]]):
            continue
        for ch in rng.sample("NESW", 4):
            dx, dz = STEP[ch]
            v = (u[0], u[1] + dx, u[2] + dz)
            if 0 <= v[1] < W and 0 <= v[2] < D and v not in stair_set and find(u) != find(v) and straight_ok(u, ch):
                link(u, v, ch)
                break
        else:
            return None

    edges = []
    for f in range(F):
        for z in range(D):
            for x in range(W):
                for ch in "ES":
                    dx, dz = STEP[ch]
                    if x + dx < W and z + dz < D:
                        edges.append(((f, x, z), ch))
    rng.shuffle(edges)
    for u, ch in edges:
        dx, dz = STEP[ch]
        v = (u[0], u[1] + dx, u[2] + dz)
        if u in stair_set or v in stair_set or find(u) == find(v) or not straight_ok(u, ch):
            continue
        link(u, v, ch)
    out = [[["".join(ch for ch in "NESWUD" if ch in cells[f][z][x]) for x in range(W)] for z in range(D)]
           for f in range(F)]
    starts, n = [], 0
    for f, p in paths:
        starts.append((n, n + len(p) - 1))
        n += len(p)
    cps, last = [], 0
    for k, si in enumerate((0, 2, 3, 4)):
        lo, hi = starts[si]
        lo, hi = max(lo + 1, last + 30), min(hi - 1, n - 31 if k == 3 else hi - 1)
        cand = [i for i in range(lo, hi + 1) if (full[i][1], full[i][2]) not in stairs[full[i][0]]
                and len(out[full[i][0]][full[i][2]][full[i][1]]) >= 3]
        if not cand:
            return None
        i = cand[min(len(cand) - 1, 3)] if k < 3 else cand[len(cand) // 2]
        f, x, z = full[i]
        cps.append({"name": ["Lantern Hall", "Sky Bridge", "Undercroft", "Crown Room"][k], "floor": f, "x": x, "z": z})
        last = i
    return {"format": "bakeoff-labyrinth/1", "title": f"Reference labyrinth {seed % 100000}", "cells": out,
            "checkpoints": cps, "palette": {"0": "mossy_stone_bricks", "1": "deepslate_tiles", "2": "quartz_block"}}


def main():
    seed, outp = int(sys.argv[1]), sys.argv[2]
    for k in range(200):
        doc = build(seed * 1000 + k)
        if doc is None:
            continue
        res, _ = verify.check(doc)
        if all(ok for _, ok, _ in res):
            with open(outp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            return 0
    print("no maze found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
