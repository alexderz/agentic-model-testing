# Test 8: the pagoda and the orrery as agent tasks (sub-agents, a sealed browser)

**Operator, 2026-10-14 (Model Master 2):** asked whether the pagoda standard is a one-shot (it is: tests 5
and 6 send the prompt as the only message, with no tools), then: "1, yes. Add that as another test. Allow it
sub-agents (engines where this doesn't with will fail as intended). Give it a browser that is locked down (and it's
settings are read only)".

## The task

The same two prompts as the one-shots, `suites/prompt-test6-pagoda.txt` (a voxel pagoda in three.js, one HTML file)
and `suites/prompt-test5-orrery.txt` (an animated brass orrery, one SVG file). Each is a separate case. The model
works in an OpenCode session instead of one reply. It can write and check its file in a browser, and hand parts to
sub-agents with the task tool. Only the file it leaves (`/work/page.html` or `/work/orrery.svg`) is graded, rendered
by the same grader as the one-shot. So test 8 against tests 5 and 6 shows what the agent loop and a browser add for
the same model.

The prompt (`tools/t8_tools.py prompt`): `preamble.txt`, with the task's `view-*.txt` and `eyes-on.txt` or
`eyes-off.txt` filled in, then the one-shot prompt, then one line saying that the file is the answer. The prompt also
stays in /work as `TASK.md`, because a compaction drops the first message.

## Setup

- Runner: `run-case-test8.sh` (one case), `run-test8.sh` (the matrix), `run-next-test8.sh` (unit `bakeoff-queue-test8`).
  Matrix `matrix-test8.tsv`: the five test 7 setups, both tasks, five runs, round-robin by run. A setup's two tasks
  run back to back, so the model loads once.
- Cap: 2 hours per case (`T8_CAP_S=7200`), then the session is stopped and the file is graded as it stands.
  Compaction is on, with the OpenCode limits from the entry spec, as in test 7.
- **The agent container** (`localhost/bakeoff-agent`, OpenCode 1.18.32) is the test 7 sandbox with no public
  Internet. `net-policy.sh` runs with `NET_PUBLIC=0`: llama-swap on Titan only, and no DNS. So the agent cannot fetch
  someone else's pagoda. `webfetch` and `websearch` are off. `task` is on, with sub-agent depth 1. A setup whose engine
  cannot serve the sub-agent's parallel requests fails as it fails (operator: "will fail as intended").
- **The browser container** (`localhost/bakeoff-browser`, `Containerfile.browser`): Playwright MCP 0.0.83 on the
  grader's own Chromium 154 (the build fails if the Chromium version changes). It runs with `--network=none`, a
  read-only root, no capabilities, no-new-privileges, 3 GB and 512 processes.
  - Its settings (`sandbox/t8/playwright-mcp.json`, the entry script and the preview server) are mounted read-only.
  - Playwright's opt-in tool groups that change settings at run time (config, network, storage and the like) are not
    turned on.
  - `browser_run_code_unsafe`, which runs Node code in the browser's container, and `browser_file_upload` are off in
    OpenCode.
  - Navigation is allowed only to the preview server, `http://127.0.0.1:8000`.
  - The agent reaches the browser only through the MCP socket in a shared folder (`sandbox/t8/mcp-bridge.py`).
    Sub-agents share the browser.
- **The preview server** (`sandbox/t8/preview.py`) shows the agent's /work, read-only, the way the grader renders it:
  - `.html` with the three.js URLs rewritten to the local three 0.186.1, by `tools/three_rewrite.py`, which is the
    same code `tools/render_html.sh` now calls;
  - `.svg` itself, and `/view/<name>.svg` as the grader's `<img>` wrapper;
  - nothing else (404), since the grader gets only the one file.
- **Pagoda viewport.** The page area is 1280 x 657, the grader's page area while the page runs: headless Chromium's
  `--window-size=1280,800` gives 657, and the window grows to 800 just before each shot. The prompt says so.
- **Images.** Screenshots come back as images only when the served model takes images. At the start of each case,
  `t8_tools.py vision` sends one red and blue PNG. If the answer says red, the browser sends images
  (`PLAYWRIGHT_MCP_IMAGE_RESPONSES=allow`), the OpenCode model entry declares image input, and the prompt says so.
  Otherwise images are omitted and the prompt points to the console, `browser_evaluate` and the snapshot.
  The probe answer is kept in `t8-vision.json`; `T8_VISION=0|1` overrides it.
- Rendering after the case: `tools/render_html.sh` (frames at 1.5, 5 and 10 s) or `tools/render_svg.sh` (0.1, 2 and
  6 s) into `frames/`, as in tests 6 and 5.

## Grading

By hand, with the test 6 rubric for the pagoda (`suites/test6/README.md`, five points A to E, 10 in all) and the test 5
rubric for the orrery (`suites/test5/README.md`), including the rules settled while grading those. As there, grade
from the frames and the file, not from what the model says it did.

Also recorded, not scored (`meta.json`, `t8-stats.json`):

- time used and whether the cap stopped it;
- vision on or off;
- tool calls by tool;
- browser calls and screenshots;
- task (sub-agent) calls;
- compactions;
- which files the preview served.

## Checks

`tests/test_test8.sh` runs two offline cases (no Titan, no GPU) with a scripted fake model
(`tests/fake_llm_t8.py`), once with images and once without. It checks the following:

- The agent is offered the browser and `task`, and none of: web tools, `run_code_unsafe`, `file_upload`, or
  settings tools.
- The agent container has no Internet, DNS or LAN.
- The page loads the local three.js.
- A screenshot reaches the model as an image only with vision on.
- Other files get 404, and the browser cannot open example.com.
- A sub-agent started with `task` gets the browser, and its call works.
- The file is kept and rendered by the grader.
- The stats count the calls.
