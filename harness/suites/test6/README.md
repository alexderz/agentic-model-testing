# Test 6: one-shot voxel Japanese pagoda (three.js)

Operator, 2026-10-13, about the night search for fast long-context coding setups: "Maybe we ask each
to do the voxel Japanese pagoda test?" The idea is the operator's. The wording of the prompt is Claw's (Model Master
2), written to ask for the usual parts of the community voxel pagoda scene and to pin three.js to one URL, so the page
can be rendered offline. `reference/voxel-pagoda.html` is Claw's own page for the same prompt (written by hand by the
grader, not by a model under test), with its frames in `reference/frames/`: it shows that the prompt can be met in one
file and how a full-marks scene looks in this renderer.

- Prompt: `suites/prompt-test6-pagoda.txt`, sent as the only user message. No system prompt, no tools, no agent, no
  second turn.
- Runner: `tools/run_oneshot.py` with `ONESHOT_ARTIFACT=html`; results in `results-test6/<case>/`: `reply.txt`,
  `reasoning.txt`, `page.html` (when one can be cut out of the reply), `meta.json`, and the rendered `frames/`.
- Settings: each entry as configured (its own sampling and thinking defaults), reply cap 32,000 tokens
  (`ONESHOT_MAX_TOKENS`; thinking counts against it). A later sitting with a larger cap is reported as its own row.
- Rendering: `tools/render_html.sh`, Chromium in a container with no network, software WebGL. Every three.js URL in
  the page is rewritten to a local copy of three 0.186.1 (npm tarball, sha512 in the script); `rewrites.txt` lists
  what was rewritten and which other URLs the page tried. Frames at 1.5, 5 and 10 s of virtual time;
  `console-<ms>.txt` holds the page's console lines and uncaught errors. Never open a model-written page in a browser
  on a host (operator, 2026-10-11).

## Grading (Claw decides; 0 to 2 points each, 10 in all)

| point | 0 | 1 | 2 |
|---|---|---|---|
| A. Does the page draw | no page, blank, or a script error stops it | draws with visible defects | draws cleanly |
| B. Voxels | not built from cubes | partly cubes, partly other shapes | consistently cubes |
| C. The pagoda | none recognisable | a tower, but the storeys, the eaves or the spire are wrong | five storeys with upturned eaves and a spire |
| D. The setting (stone platform, cherry trees, pond, torii) | one or none | two or three | all four |
| E. Life (orbiting camera, falling petals, shadows) | none | one or two | all three |

Also recorded, not scored: length stop, time, tokens per second, page size, InstancedMesh or not, and a short note on
the look (composition, colour, whether it reads as Japanese). Grade from the rendered frames and the file, not from the
model's own description.

Rules settled while grading the first sitting (2026-10-14):

- A page that draws nothing (no page, or a blank frame) scores 0 on every point: B to E are judged on what is drawn.
  The reason goes in the notes (`console-*.txt`).
- A part that is in the code but not visible in any frame (hidden inside another block, or not drawn because of a
  bug) does not count for C or D.
- The camera orbit is graded from the code: headless Chromium runs few animation frames per second of virtual time,
  so an orbit that advances per frame (OrbitControls `autoRotate` without a delta, or `time += k` per frame) barely
  moves between the frames. Petals and shadows must be visible in the frames.
- A: console warnings that do not stop the page (a deprecated three.js call, for example) are not defects; an
  uncaught error counts when it leaves the scene visibly incomplete.
- B: boxes of any proportion count as cubes (a flat petal or a long beam is a box), rotated or not; spheres,
  cylinders, cones, planes carrying the scene, or smooth custom geometry do not.
- C: eaves count as upturned when their corners visibly rise above the eave line, by stepped voxels, raised corner
  blocks or tilted boxes. All five storeys and the spire must be visible in at least one frame.
- When a page fails on one obvious line, a diagnostic render with the smallest fix may be added under
  `<case>/diag/` with the fix stated. It is never scored; it only shows how near the miss was.
