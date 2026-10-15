# Test 5: one-shot animated SVG (the orrery)

Operator, 2026-10-11, after Claw (Claude Opus 5.5, the bake-off conversation) answered this prompt itself:
"Did you think I wanted the smartest model we have to do this? Save that as the perfect case. Then have our models try it."

- Prompt: `suites/prompt-test5-orrery.txt`, the operator's words unchanged, sent as the only user message. No system
  prompt, no tools, no agent, no second turn.
- Perfect case: `reference/brass-orrery.svg` (77 KB, SMIL only, no script), written by `reference/make_orrery.py`.
  It is the top of the scale, not a pass mark, and it was made with tools the local models do not get here: a
  generator script, a headless browser to look at frames, and one round of fixes.
- Runner: `tools/run_oneshot.py`, queue `run-next-orrery.sh` (unit `bakeoff-queue-orrery`), results in `results-test5/<case>/`:
  `reply.txt`, `reasoning.txt`, `orrery.svg` (when one can be cut out of the reply), `meta.json`.
- Settings: each entry as configured in llama-swap (its own sampling and thinking defaults), reply cap 32,000 tokens.

## What the reference does (the things to look for)

1. One self-contained SVG that parses and animates without script.
2. Eight planets on their real sidereal periods in true proportion (one Earth year = 12 s).
3. A wheel per planet (20 to 83 teeth) meshing with a 12-tooth pinion; pitch radius is proportional to tooth count and
   the two turn in opposite directions at speeds in the inverse ratio of their teeth, so the teeth stay interleaved.
4. A night half on each planet that always faces away from the sun while the surface turns under it.
5. Extras: Saturn's shadow on its rings, the Moon, real spin directions.
Its known shortcut: every pinion turns on its own arbor; no single drive shaft links the eight.

## Grading (Claw decides, operator: "you own this"; 0 to 2 points each, 10 in all)

| point | 0 | 1 | 2 |
|---|---|---|---|
| A. Is it an SVG that draws | no SVG, or it does not parse or render | renders with visible defects | renders cleanly |
| B. Does it move | static | something moves | orbits, gears and planets all move |
| C. Orbit speeds | equal or arbitrary | ordered right, ratios off | ratios within 5% of the real periods |
| D. Gears | none, or plain circles | toothed and turning, but not in mesh (wrong ratio, direction or spacing) | meshing pairs that obey the gear law and plausibly drive the orbits |
| E. Day and night | none | a fixed shaded half, or a shadow that turns the wrong way | the dark side stays away from the sun and sweeps the surface |

Also recorded, not scored: length stop, time, tokens per second, reply size, whether the reply is only the SVG or
carries prose, and whether it uses script. Grade from the file and from rendered frames, not from the model's own
description. Never open a model-written SVG in a browser on a host: the hosts have Internet access (operator, 2026-10-11). Render only with `tools/render_svg.sh`, which runs Chromium in a container with no network (`localhost/bakeoff-render`).
