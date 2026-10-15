# The labyrinth

Design a three-floor labyrinth that people will build and walk through in Minecraft. Do not draw it by hand. Write a
program that generates one for any seed, and make sure each maze it makes obeys every rule below. The rules are
hard to meet all at once. Plan before you write code.

This file stays in your work folder as `TASK.md`. Read it again whenever you are unsure of the rules, for example
after your conversation has been shortened.

## What to deliver, in this folder

1. **`generate`**, an executable that `./generate SEED OUT.json` runs from this folder.
   - SEED is a decimal integer from 0 to 2147483647. It writes one maze for that seed to OUT.json.
   - The same seed always gives the same file. Different seeds must give different mazes: identical mazes for
     different seeds count once.
   - It must finish within 120 seconds on one CPU core.
   - Use any language installed here: Python 3.12, Node 22, Rust (cargo) or C (gcc). If it needs compiling, build
     it yourself and leave the built program in place.
   - No network and no files outside this folder.
2. **`labyrinth.json`**, your showcase maze, made by your generator, and **`SHOWCASE_SEED`**, a file holding only
   the seed that made it.
   - `./generate $(cat SHOWCASE_SEED) labyrinth.json` must write exactly this file. We check that.
   - Give it a title and name the four checkpoints yourself: these are the names players will see.
   - This is the maze that gets built in Minecraft.
3. **`NOTES.md`**, in a few paragraphs:
   - how your generator works;
   - which seed made the showcase, and why you chose it;
   - the output of `python3 verify.py labyrinth.json`, pasted as it is;
   - how many seeds you tested and how many passed, and the command you ran to test them.

   Report only what you actually ran.

`verify.py` is in this folder: `python3 verify.py labyrinth.json` checks every rule and says what is wrong. Run it
often. We grade with an untouched copy of `verify.py`, and we also run your `generate` on seeds you have not seen.
A generator that only works for the seeds you tried will lose most of the marks.

**Extra credit.** Measured on the unseen seeds, as the worst of them: a route of at least 320 cells, and a route
that changes floor at least 6 times. Meet every rule first.

## The labyrinth

- **The grid.** Three floors, numbered 0 (bottom) to 2 (top). Each floor is 16 by 16 cells:
  - `x` runs 0-15 from west to east;
  - `z` runs 0-15 from north to south.

  Each cell lists its openings as letters:

  | Letter | Opens to                       |
  |--------|--------------------------------|
  | `N`    | `z - 1`                        |
  | `S`    | `z + 1`                        |
  | `E`    | `x + 1`                        |
  | `W`    | `x - 1`                        |
  | `U`    | the same cell on the floor above |
  | `D`    | the same cell on the floor below |

  A missing letter is a wall. Every letter counts as an **opening**, including `U`, `D` and the two doors to the
  outside, so a cell's number of openings is the length of its string.
- **The file.** It looks like this:

  ```json
  {"format": "bakeoff-labyrinth/1",
   "title": "...",
   "cells": [ floor 0, floor 1, floor 2 ],
   "checkpoints": [ {"name": "...", "floor": 0, "x": 3, "z": 7}, ... ],
   "palette": {"0": "stone_bricks", "1": "deepslate_tiles", "2": "quartz_block"}}
  ```

  - Each floor in `cells` is a list of 16 rows (z = 0..15).
  - Each row is a list of 16 strings (x = 0..15), for example `cells[f][z][x] = "NE"`.
  - Each letter may appear at most once in a string.
  - The title is 1-40 characters. Checkpoint names are 1-24 characters.

## The rules (verify.py checks each one; when an early rule fails, it skips the later ones)

1. **Consistent.** Every opening has its partner. If a cell has `E`, the cell east of it has `W`; if a cell has `U`,
   the cell above has `D`. Nothing opens off the grid except:
   - the **entrance**, floor 0, x 0, z 0, which opens `W`;
   - the **exit**, floor 2, x 15, z 15, which opens `E`.
2. **A perfect maze.** All 768 cells can be reached from the entrance, and there is exactly one route between any two cells: no loops,
   no closed-off parts.
3. **Stairs.** A stair is a `U` in one cell matched by a `D` in the cell above.
   - Each pair of neighbouring floors (0-1 and 1-2) has between 3 and 6 stairs.
   - A stair cell, at the top or the bottom, has exactly one other opening (N, E, S or W).
   - A stair cell cannot go both up and down.
   - A stair cell is not on the outer ring of the floor (x or z equal to 0 or 15).
   - A stair cell does not touch another stair cell on the same floor, not even at a corner.
4. **A long way through.** The route from the entrance to the exit is at least 250 cells long, counting both ends.
5. **Up and down.** Along that route, the floor changes at least 4 times. Going straight up 0-1-2 is only 2 changes,
   so the route has to come back down at least once.
6. **Checkpoints.** Exactly four, listed in the order the route meets them.
   - They are on floors 0, 2, 1 and 2, in that order.
   - Each is a cell on the route, none is a stair cell, and each is a junction (at least three openings).
   - They are at least 30 moves apart along the route: if the entrance is move 0, the first checkpoint is at move 30
     or later, each next one at least 30 moves after the one before, and the exit at least 30 moves after the last.
7. **Real decisions.** At least 45 cells on the route are junctions (cells with three or more openings), so the
   walker has to choose often.
8. **Dead ends.** At least 120 cells in the whole maze are dead ends (exactly one opening).
9. **No long corridors.** No straight line of joined cells is longer than 5 cells, east-west or north-south, on any
   floor. The doors to the outside do not join anything.
10. **Materials.** `palette` gives each floor a different wall block from this list:
    - stone_bricks, mossy_stone_bricks, cracked_stone_bricks
    - deepslate_bricks, deepslate_tiles, polished_blackstone_bricks
    - bricks, mud_bricks, sandstone, red_sandstone
    - prismarine_bricks, nether_bricks, end_stone_bricks
    - quartz_block, purpur_block
    - oak_planks, spruce_planks, dark_oak_planks, cherry_planks, bamboo_planks
    - copper_block, tuff_bricks

## How it will be built

In Minecraft, each cell becomes a corridor two blocks wide with walls three blocks high, and each stair becomes a
ladder. A checkpoint becomes a lit spot with its name on a sign. People will walk your showcase, so make it a maze
worth exploring, not just one that passes.
