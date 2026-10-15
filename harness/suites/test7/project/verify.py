#!/usr/bin/env python3
"""Verifier for bake-off test 7, the labyrinth (rules in TASK.md). Standard library only.

    python3 verify.py labyrinth.json            # human report, exit 0 when every rule passes
    python3 verify.py --json labyrinth.json     # machine report
    python3 verify.py --map labyrinth.json      # also print each floor as ASCII art

The same file is used by the grader, from an untouched copy."""
import json
import sys
from collections import deque

FLOORS, W, D = 3, 16, 16
DIRS = {"N": (0, 0, -1), "S": (0, 0, 1), "E": (1, 0, 0), "W": (-1, 0, 0), "U": (0, 1, 0), "D": (0, -1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E", "U": "D", "D": "U"}
ENTRANCE, ENTRANCE_SIDE = (0, 0, 0), "W"     # (floor, x, z)
EXIT, EXIT_SIDE = (2, 15, 15), "E"
CHECKPOINT_FLOORS = [0, 2, 1, 2]
MIN_PATH, MIN_PATH_JUNCTIONS, MIN_DEAD_ENDS, MAX_STRAIGHT = 250, 45, 120, 5
MIN_FLOOR_CHANGES, MIN_CP_GAP, MIN_CP_OPENINGS = 4, 30, 3
RULES = ["file format", "file letters", "rule 1 consistent", "rule 2 perfect maze", "rule 3 stairs",
         "rule 4 long way", "rule 5 up and down", "rule 6 checkpoints", "rule 7 decisions", "rule 8 dead ends",
         "rule 9 corridors", "rule 10 materials"]
STAIRS_PER_PAIR = (3, 6)
PALETTE = {"stone_bricks", "mossy_stone_bricks", "cracked_stone_bricks", "deepslate_bricks", "deepslate_tiles",
           "polished_blackstone_bricks", "bricks", "mud_bricks", "sandstone", "red_sandstone", "prismarine_bricks",
           "nether_bricks", "end_stone_bricks", "quartz_block", "purpur_block", "oak_planks", "spruce_planks",
           "dark_oak_planks", "cherry_planks", "bamboo_planks", "copper_block", "tuff_bricks"}


def check(doc):
    """Returns (results, stats): results lists (rule, ok, message) for all 12 rules; ok is None for a rule that could
    not be checked because an earlier one failed (shown as SKIP, counts as not passed)."""
    res, stats = [], {}
    try:
        _check(doc, res, stats)
    except Exception as e:  # odd input must give a FAIL line, never a traceback
        res.append(("file readable", False, f"the checker could not read this file ({type(e).__name__})"))
    done = {r for r, _, _ in res}
    first_fail = next((r for r, ok, _ in res if not ok), None)
    for r in RULES:
        if r not in done:
            res.append((r, None, f"not checked: fix '{first_fail}' first"))
    return res, stats


def _check(doc, res, stats):

    def rule(name, ok, msg):
        res.append((name, bool(ok), msg))
        return ok

    if not isinstance(doc, dict):
        rule("file format", False, "the top level must be a JSON object")
        return

    # R1 shape
    try:
        cells = doc["cells"]
        shape_ok = (doc.get("format") == "bakeoff-labyrinth/1" and isinstance(doc.get("title"), str)
                    and 1 <= len(doc["title"]) <= 40 and isinstance(cells, list) and len(cells) == FLOORS
                    and all(isinstance(fl, list) and len(fl) == D
                            and all(isinstance(row, list) and len(row) == W for row in fl) for fl in cells)
                    and all(isinstance(c, str) for fl in cells for row in fl for c in row))
    except (KeyError, TypeError):
        shape_ok = False
    if not rule("file format", shape_ok, "format, title (1-40 chars) and a 3 x 16 x 16 array of strings"
                if shape_ok else "need format 'bakeoff-labyrinth/1', a title of 1-40 chars and cells[3][16][16] strings"):
        return

    def at(p):
        f, x, z = p
        return cells[f][z][x]

    bad = []
    for f in range(FLOORS):
        for z in range(D):
            for x in range(W):
                s = cells[f][z][x]
                if len(set(s)) != len(s) or any(ch not in DIRS for ch in s):
                    bad.append(f"floor {f} x {x} z {z}: '{s}' (letters NESWUD, each at most once)")
    if not rule("file letters", not bad, "only N E S W U D, no repeats" if not bad else "; ".join(bad[:5])):
        return

    # R2 consistency: openings match both ways, nothing leaves the grid except the entrance and the exit
    probs, edges, adj = [], set(), {}
    for f in range(FLOORS):
        for z in range(D):
            for x in range(W):
                p = (f, x, z)
                adj.setdefault(p, [])
                for ch in cells[f][z][x]:
                    dx, df, dz = DIRS[ch]
                    q = (f + df, x + dx, z + dz)
                    if not (0 <= q[0] < FLOORS and 0 <= q[1] < W and 0 <= q[2] < D):
                        if (p, ch) not in ((ENTRANCE, ENTRANCE_SIDE), (EXIT, EXIT_SIDE)):
                            probs.append(f"floor {f} x {x} z {z}: '{ch}' leads off the grid")
                        continue
                    if OPP[ch] not in at(q):
                        probs.append(f"floor {f} x {x} z {z}: '{ch}' has no matching '{OPP[ch]}' in the next cell")
                        continue
                    edges.add(frozenset((p, q)))
                    adj[p].append(q)
    if ENTRANCE_SIDE not in at(ENTRANCE):
        probs.append("entrance: floor 0 x 0 z 0 must open 'W' to the outside")
    if EXIT_SIDE not in at(EXIT):
        probs.append("exit: floor 2 x 15 z 15 must open 'E' to the outside")
    if not rule("rule 1 consistent", not probs, "openings match on both sides; entrance and exit open outwards"
                if not probs else f"{len(probs)} problems: " + "; ".join(probs[:6])):
        return

    # R3 perfect maze: one connected tree over all 768 cells
    seen, dq = {ENTRANCE}, deque([ENTRANCE])
    while dq:
        p = dq.popleft()
        for q in adj[p]:
            if q not in seen:
                seen.add(q)
                dq.append(q)
    n = FLOORS * W * D
    stats.update(cells=n, reached=len(seen), passages=len(edges))
    tree = len(seen) == n and len(edges) == n - 1
    rule("rule 2 perfect maze", tree, f"all {n} cells reachable, {len(edges)} passages, no loops" if tree else
         f"{len(seen)} of {n} cells reachable from the entrance, {len(edges)} passages (a perfect maze has "
         f"{n - 1}: every cell reachable and exactly one route between any two cells)")

    # R4 stairs
    sp, sprobs = {}, []
    for f in range(FLOORS - 1):
        for z in range(D):
            for x in range(W):
                if "U" in cells[f][z][x]:
                    sp.setdefault(f, []).append((x, z))
    stair_cells = {f: set() for f in range(FLOORS)}
    for f, lst in sp.items():
        for x, z in lst:
            stair_cells[f].add((x, z))
            stair_cells[f + 1].add((x, z))
    for f in range(FLOORS - 1):
        k = len(sp.get(f, []))
        if not STAIRS_PER_PAIR[0] <= k <= STAIRS_PER_PAIR[1]:
            sprobs.append(f"floors {f}-{f + 1}: {k} stairs (need {STAIRS_PER_PAIR[0]}-{STAIRS_PER_PAIR[1]})")
    for f in range(FLOORS):
        for x, z in sorted(stair_cells[f]):
            s = cells[f][z][x]
            h = sum(ch in "NESW" for ch in s)
            if h != 1:
                sprobs.append(f"floor {f} x {x} z {z}: stair cell has {h} side openings (need exactly 1)")
            if "U" in s and "D" in s:
                sprobs.append(f"floor {f} x {x} z {z}: a stair cell may not go both up and down")
            if x in (0, W - 1) or z in (0, D - 1):
                sprobs.append(f"floor {f} x {x} z {z}: stair on the outer ring")
            for ox in (-1, 0, 1):
                for oz in (-1, 0, 1):
                    if (ox or oz) and (x + ox, z + oz) in stair_cells[f]:
                        sprobs.append(f"floor {f} x {x} z {z}: stair touches another stair cell")
    stats["stairs"] = {f"{f}-{f + 1}": len(sp.get(f, [])) for f in range(FLOORS - 1)}
    rule("rule 3 stairs", not sprobs, "3-6 stairs per pair of floors, each stair cell with one side opening, apart from "
         "each other and off the outer ring" if not sprobs else "; ".join(sorted(set(sprobs))[:6]))
    if not tree:
        return

    # solution path (unique in a tree)
    prev, dq = {ENTRANCE: None}, deque([ENTRANCE])
    while dq:
        p = dq.popleft()
        for q in adj[p]:
            if q not in prev:
                prev[q] = p
                dq.append(q)
    path, p = [], EXIT
    while p is not None:
        path.append(p)
        p = prev[p]
    path.reverse()
    idx = {p: i for i, p in enumerate(path)}
    deg = {p: len(at(p)) for p in adj}
    floors_seq = [path[0][0]]
    for p in path[1:]:
        if p[0] != floors_seq[-1]:
            floors_seq.append(p[0])
    junctions = sum(1 for p in path if deg[p] >= 3)
    dead = sum(1 for p in adj if deg[p] == 1)
    stats.update(path_length=len(path), floor_sequence=floors_seq, path_junctions=junctions, dead_ends=dead)

    rule("rule 4 long way", len(path) >= MIN_PATH, f"solution path {len(path)} cells (need at least {MIN_PATH})")
    rule("rule 5 up and down", len(floors_seq) - 1 >= MIN_FLOOR_CHANGES,
         f"the solution path changes floor {len(floors_seq) - 1} times, sequence "
         f"{'-'.join(map(str, floors_seq))} (need at least {MIN_FLOOR_CHANGES})")

    # R7 checkpoints
    cps, cprobs = doc.get("checkpoints"), []
    if not isinstance(cps, list) or len(cps) != 4:
        cprobs.append("need a list of exactly 4 checkpoints")
    else:
        last = None
        for i, cp in enumerate(cps):
            try:
                name, p = cp["name"], (cp["floor"], cp["x"], cp["z"])
                if not all(type(v) is int for v in p):
                    raise TypeError
            except (KeyError, TypeError, ValueError):
                cprobs.append(f"checkpoint {i + 1}: need name, floor, x, z")
                continue
            if not isinstance(name, str) or not 1 <= len(name) <= 24:
                cprobs.append(f"checkpoint {i + 1}: name of 1-24 characters")
            if p[0] != CHECKPOINT_FLOORS[i]:
                cprobs.append(f"checkpoint {i + 1}: on floor {p[0]}, must be on floor {CHECKPOINT_FLOORS[i]}")
            if p not in idx:
                cprobs.append(f"checkpoint {i + 1}: floor {p[0]} x {p[1]} z {p[2]} is not on the solution path")
                continue
            if len(at(p)) < MIN_CP_OPENINGS:
                cprobs.append(f"checkpoint {i + 1}: has {len(at(p))} openings, needs at least {MIN_CP_OPENINGS} (a junction)")
            if (p[1], p[2]) in stair_cells[p[0]]:
                cprobs.append(f"checkpoint {i + 1}: may not be a stair cell")
            if last is not None and idx[p] - last < MIN_CP_GAP:
                cprobs.append(f"checkpoint {i + 1}: {idx[p] - last} moves after the previous one along the path "
                              f"(need at least {MIN_CP_GAP}, in order)")
            if i == 0 and idx[p] < MIN_CP_GAP:
                cprobs.append(f"checkpoint 1: {idx[p]} moves from the entrance (need at least {MIN_CP_GAP})")
            last = idx[p]
        if last is not None and len(path) - 1 - last < MIN_CP_GAP:
            cprobs.append(f"checkpoint 4: {len(path) - 1 - last} moves before the exit (need at least {MIN_CP_GAP})")
    rule("rule 6 checkpoints", not cprobs, "4 checkpoints on the path, in order, on floors 0, 2, 1, 2, each a junction, at least "
         f"{MIN_CP_GAP} moves apart" if not cprobs else "; ".join(cprobs[:6]))

    rule("rule 7 decisions", junctions >= MIN_PATH_JUNCTIONS, f"{junctions} junctions (cells with 3 or more openings) on "
         f"the solution path (need at least {MIN_PATH_JUNCTIONS})")
    rule("rule 8 dead ends", dead >= MIN_DEAD_ENDS, f"{dead} dead ends (need at least {MIN_DEAD_ENDS})")

    # R10 straight runs: cells joined in a line along one axis
    longest, where = 0, None
    for f in range(FLOORS):
        for z in range(D):
            for x in range(W):
                for a, b in (("W", "E"), ("N", "S")):
                    s = cells[f][z][x]
                    dxa, _, dza = DIRS[a]
                    back_inside = 0 <= x + dxa < W and 0 <= z + dza < D
                    if b in s and (a not in s or not back_inside):   # start of a run (a door off the grid ends it)
                        n, (cx, cz) = 1, (x, z)
                        while b in cells[f][cz][cx]:
                            dx, _, dz = DIRS[b]
                            nx, nz = cx + dx, cz + dz
                            if not (0 <= nx < W and 0 <= nz < D):
                                break
                            cx, cz, n = nx, nz, n + 1
                        if n > longest:
                            longest, where = n, (f, x, z, b)
    stats["longest_straight"] = longest
    rule("rule 9 corridors", longest <= MAX_STRAIGHT, f"longest straight corridor {longest} cells (at most "
         f"{MAX_STRAIGHT})" + ("" if longest <= MAX_STRAIGHT or not where else
                               f", from floor {where[0]} x {where[1]} z {where[2]} going {where[3]}"))

    # R11 palette
    pal, pprobs = doc.get("palette"), []
    if not isinstance(pal, dict) or sorted(pal) != ["0", "1", "2"]:
        pprobs.append('need {"0": block, "1": block, "2": block}')
    else:
        for k, v in sorted(pal.items()):
            if not isinstance(v, str) or v not in PALETTE:
                pprobs.append(f"floor {k}: '{v}' is not on the block list")
        if len({v for v in pal.values() if isinstance(v, str)}) != 3:
            pprobs.append("each floor needs a different block")
    rule("rule 10 materials", not pprobs, "three different wall blocks from the list" if not pprobs else "; ".join(pprobs))
    return


def ascii_map(doc):
    cells, out = doc["cells"], []
    for f in range(FLOORS):
        out.append(f"floor {f}")
        top = "+"
        for x in range(W):
            top += "   +" if "N" in cells[f][0][x] else "---+"
        out.append(top)
        for z in range(D):
            line = " " if "W" in cells[f][z][0] else "|"
            bot = "+"
            for x in range(W):
                s = cells[f][z][x]
                mark = ("^" if "U" in s else "") + ("v" if "D" in s else "")
                line += f"{mark:^3}" + (" " if "E" in s else "|")
                bot += "   +" if "S" in s else "---+"
            out += [line, bot]
    return "\n".join(out)


def main(argv):
    as_json = "--json" in argv
    show_map = "--map" in argv
    files = [a for a in argv if not a.startswith("--")]
    if len(files) != 1:
        sys.exit("usage: verify.py [--json] [--map] labyrinth.json")
    try:
        with open(files[0], encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        res, stats = [("file readable", False, f"cannot read JSON: {e}")], {}
    else:
        res, stats = check(doc)
    passed = len(res) == len(RULES) and all(ok is True for _, ok, _ in res)
    if as_json:
        print(json.dumps({"pass": passed, "rules": [{"rule": r, "ok": ok, "detail": m} for r, ok, m in res],
                          "stats": stats}, indent=1))
    else:
        for r, ok, m in res:
            print(f"{'PASS' if ok else 'SKIP' if ok is None else 'FAIL'}  {r}: {m}")
        print("ALL RULES PASS" if passed else "NOT YET: fix the FAIL lines above")
        if show_map and passed or show_map and stats.get("cells"):
            print(ascii_map(doc))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
