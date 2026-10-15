# Test 7: the labyrinth

**Operator, 2026-10-14 (Model Master 2):** "1, agent. This should be a high complexity ask with verifier.
2, your call. Challenge the model. This is meant to separate by intelligence. 3, do it IN Minecraft?"

The showcase mazes are built in Minecraft on a separate Maze Gallery server, which is not part of this
repository.

## The task

`project/TASK.md` asks the agent to write a seeded generator for a three-floor labyrinth of 16 x 16 cells per
floor. Every maze it makes must meet ten rules at once:

- a perfect maze;
- spaced stairs;
- a route of at least 250 cells that changes floor at least 4 times;
- four ordered checkpoints that are junctions, at least 30 moves apart;
- at least 45 junctions on the route;
- at least 120 dead ends;
- no straight corridor over 5 cells;
- three wall blocks.

The agent also writes a showcase `labyrinth.json` with its seed in `SHOWCASE_SEED`, and `NOTES.md`. It gets
`project/verify.py` to check against.

The prompt is `prompt-preamble.txt` followed by TASK.md. TASK.md also stays in /work, because a compaction drops the
first message. The cap is 3 hours, with compaction on (OpenCode limits from the entry spec).

## Why it separates models

Each rule alone is easy. A plain random spanning tree, for example, is a perfect maze with many dead ends. Meeting
them together needs a plan:

- The route length and the floor order (0, then 2 by checkpoint 2, back to 1, then 2) force the solution path to be
  laid out first.
- The corridor limit forbids the long straight halls that a long path tends to grow.
- The stair rules (one side opening, apart from each other, off the outer ring) clash with naive "add a U anywhere".
- The checkpoints have to be junctions on the route at spacing.

A generator must hold for unseen seeds, so tuning one maze by hand does not pay.

`reference/generate.py` (not shown to agents) proves the rules can all be met. It plans a five-segment path, stretches
it with bumps, adds spare stairs, then fills the rest with a constrained Kruskal. 40 of 40 seeds pass in about 0.1 s
each, with route 257-261 cells, 45-65 route junctions, 167-192 dead ends and longest corridor 5. The reference does
not reach the extra credit.

## Grading

`grade-test7.py` (automatic; each seed in its own container with no network) gives these three marks:

- **A**, 0-2: the showcase passes and `./generate $(cat SHOWCASE_SEED)` reproduces it.
- **B**, 0-2: ten unseen seeds give ten different passing mazes, and a repeat run is identical.
- **C**, 0-2: extra credit, as the worst of the ten: a route of at least 320 cells, and at least 6 floor changes.

Two marks are judged by hand, 0-2 each:

- **D**, walkable quality. Use the ASCII map (`verify.py --map`) and the walk in Minecraft.
  - **2:** checkpoints sit where branches meet, stairs are spread over the floors, there is no long entrance tunnel
    or obvious snake, and choices along the route lead into real side passages.
  - **1:** some of that.
  - **0:** a rule-beating snake or comb that is dull to walk.
- **E**, honesty of NOTES.md.
  - Diff the pasted verify output against a fresh run of the untouched verifier.
  - Regenerate the claimed seed.
  - Re-run the stated test command where it is given.
  - **2:** everything checks out.
  - **1:** small slips.
  - **0:** claims that do not reproduce, or pass counts that cannot be audited.

## History

- 2026-10-14: designed. Review by Grok (grok-4.7; the build-fast attempt failed with no output) found:
  - **Blocker:** a straight hall starting at the entrance was not counted.
  - **Major:**
    - a constant maze passed B;
    - the showcase was not tied to the generator;
    - the thresholds did not bind (dead ends 77, against 167+ in the reference);
    - checkpoints could be plain corridor cells;
    - the palette crashed the verifier.

  All of these are fixed before any run. Rule 9 was cross-checked against an independent count on 200 random mazes
  (0 mismatches).
- 2026-10-14: a second Grok review, of the runner, grader and queue, found four blockers: a duplicated heredoc line in
  the runner, all seeds in one container (one run could forge another's output), host reads that followed links, and
  grading that could overlap or grade cases that never ran. A third look found a FIFO hang. All fixed before any run.
