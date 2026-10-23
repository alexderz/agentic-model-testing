# Method

This page describes how models are tested and how to read the numbers.

## The machine

| Part | Value |
| --- | --- |
| GPU | NVIDIA RTX 3090, 24 GB (compute capability 8.6) |
| System RAM | 125 GB |
| CPU | AVX2, no AVX-512 |
| Weights | Read from a NAS over the network; the first load streams at roughly 180-280 MB/s |
| Router | llama-swap: one model loaded at a time, each engine as a separate process or container |
| Agent | OpenCode in a sandboxed container; some runs use the Pi agent |

## The tests

Every test gives the agent one task and no guidance. The agent runs in a
container with no network access except the model server and a read-only
replay of a real Home Assistant installation (434 entities). The result is
graded by running it, not by reading it.

### Test 1: a command-line tool

The task is to write a Python command-line tool for the Home Assistant REST
API. The grader runs the tool in a sandbox and checks five things:

1. It has an entry point and prints help.
2. It reads real data from the API.
3. It handles bad input.
4. It handles a bad token.
5. It doesn't crash.

The grader also runs the model's own tests and counts subcommands.

### Test 2: an MCP server

The task is to build a Model Context Protocol (MCP) server in Rust that
exposes the same Home Assistant API to an agent. The MCP specification is
on disk. The grader builds the server and talks to it as a real MCP
client: `initialize`, `tools/list`, and a real `tools/call` that must return
data from the replay. Every failure is checked by hand and explained in the
model's card.

| Result | Meaning |
| --- | --- |
| pass | Builds, answers `initialize`, lists tools, and a tool call returns real data. |
| partial | Builds and answers a client in part (for example, tools without `initialize`, or tools that return no data). |
| fail | Does not build, or nothing a client can use. |

Test 2 separates models that test 1 cannot: invented API endpoints, broken
handshakes, and networking bugs only show when a client drives the server.

### Struggle: how hard the model fought the compiler

Every run also gets a struggle score, read from the transcript: each build
and every Python run the agent made, with its output.

- **Failed builds:** Rust builds (`cargo build`, `check`, `test`, `run`) that
  failed, out of all builds. Python runs count outputs with a traceback.
- **Errors:** the compiler's own count (`due to N previous errors`, which
  survives when the agent trims the output), classified where visible as
  syntax, unknown names (functions, methods, fields, and imports that don't
  exist), types, borrow checking, or other. Python errors split the same way:
  syntax, unknown names (`NameError`, `AttributeError`, missing modules), and
  types.
- **Errors per 1,000 lines** of the final code, so large and small projects
  compare fairly.

A model that writes clean code from the start scores low; a model that
brute-forces its way past the compiler scores high, even when it ends with a
pass. It is a separate axis from pass or fail.

### Test 2T: trust the docs

Test 2 with a short Home Assistant REST reference added to the workspace,
introduced as written for a slightly older version. Most entries are
correct; three are deliberately wrong (`GET /api/entities`,
`GET /api/entities/<entity_id>`, and `GET /api/services/list`; the real
endpoints are `/api/states`, `/api/states/<entity_id>`, and `/api/services`).
Besides the normal test-2 grade, each run gets a trust verdict from the
replay's access log and the shipped code:

| Verdict | Meaning |
| --- | --- |
| tested | Tried a planted endpoint, got a 404, and shipped code that uses only the real ones. |
| avoided | Never tried a planted endpoint; shipped only the real ones. |
| hedged | Shipped code that tries a planted endpoint and falls back to the real one. |
| trusted | Shipped code that uses a planted endpoint and never the real one. |

This came from an accident: `/api/entities` is not a Home Assistant
endpoint (entities are listed through `/api/states`; the entity registry is
only on the WebSocket API), yet six runs used it with no prompt or document
mentioning it. Some models switched to `/api/states` after the 404; one
built its whole tool on invented paths.

### Test 3: use an MCP server through a subagent

The agent gets an MCP server's source and a subagent whose only tools are that
server's. It must get 14 facts about the recorded installation through the
subagent, check them against the REST API, decide whether the server can be
trusted, fix it if not, and write a report. *3G* uses a known-good server; *3O*
uses the model's own server from test 2, even when it is broken. Besides the
automatic grade (facts right, probe sessions, whether the server changed and
still passes test 2), a 12-point rubric scores the transcript: how the agent
briefs and sizes the probe's jobs, whether it asks for structured output, whether it checks the
answers, how it handles a failing probe and whether its trust-or-fix decision
fits the evidence. Since 2026-10-11 the task is also given as a file, because
compaction lost the required answer layout, and a right value written in
another layout is credited; runs from before then are not strictly comparable.

### Test 4: ticket fixes in a known-good Rust crate

Tests 1 and 2 never touch existing code. Test 4 gives the agent a Rust MCP
server that builds and passes its 155 own tests, and one ticket at a time:

| Ticket | Shape | Hidden checks |
| --- | --- | --- |
| `bugfix-targets` | A small bug fix: `list_services` reports `targets_entities: false` for every service. | 4 |
| `feature-filter` | A medium feature: a `device_class` filter and a `count_only` mode on `list_entities`. | 11 |
| `config-timeouts` | A cross-cutting change: connect timeout, retry count and retry delay become environment settings. | 13 |

The grader builds the server and runs black-box checks the agent never sees,
against the replay or a scripted fake Home Assistant, and counts any baseline
test that now fails or is gone as a regression and any claim of "done" that
fails the checks. The cap is 45 minutes per run; the design repeats each ticket
five times to measure variation. So far only Tiel Coder has run it (three runs
per ticket).

### Test 5: a one-shot animated SVG

A single request, no agent and no tools: one SVG of a brass orrery, eight planets
on their real periods, meshing gears and a night side on each planet. The reply
cap is 32,000 tokens. The file is rendered offline in a container with no
network and graded from three frames, 0 to 2 points each for: does it draw, does
it move, orbit speeds, gears, and day and night (10 in all). A reference answer
written with tools sets the top of the scale; it is not a pass mark.

### Long-horizon runs

Slow models get an 8-hour cap and the sampling Qwen uses for its own
long-horizon coding evaluation: temperature 1.0, top-p 0.95, top-k 20,
min-p 0, and a 26k-token thinking budget.

### Test 6: a one-shot voxel scene

A single request, no agent and no tools: write one HTML page with three.js that shows a voxel Japanese
pagoda (five storeys, upturned eaves, a spire) on a stone platform with cherry trees, a pond and a torii,
an orbiting camera, falling petals and shadows. The reply cap is 32,000 tokens and counts thinking. The
page is rendered offline (Chromium without network, three.js served from a pinned local copy) and graded
from three frames, the console and the file, 0 to 2 points each for: does it draw, voxels, the pagoda,
the setting, and life. A blank page or a reply cut off by the cap scores 0. It measures quick creative
code, not agent work; two to five samples per setup.

### Test 7: the labyrinth

The agent writes a seeded generator for a three-floor labyrinth of 16 x 16 cells
per floor that meets ten rules at once: a perfect maze, spaced stairs, a route of
at least 250 cells that changes floor at least four times, four ordered
checkpoints that are junctions at least 30 moves apart, at least 45 junctions on
the route, at least 120 dead ends, no straight corridor over 5 cells and three
wall blocks. It has a verifier to check against and a 3-hour cap. Three marks are
automatic: the showcase maze passes and reproduces from its seed; ten unseen
seeds, each in its own container with no network, give ten different passing
mazes; and an extra-credit route of at least 320 cells with at least 6 floor
changes. Two marks are judged by hand: whether the maze is worth walking, and
whether the agent's notes are honest. Only two Tiel Coder pilot runs have been
graded (2026-10-15; not scored): the first left no generator at the cap, the
second passed both the showcase and the ten unseen seeds. The full matrix has not
produced graded results yet.

### Test 8: the pagoda and the orrery as agent tasks

The same two prompts as tests 5 and 6, solved by an agent in OpenCode instead of
one reply. The agent has no Internet, may use sub-agents, and has a sealed
browser (no network, read-only settings, navigation only to a preview of its own
`/work` folder) to look at its page. Only the file it leaves is graded, rendered
by the same grader, on the same rubric, with a two-hour cap. Screenshots reach
the model only when it takes images (a red-and-blue probe decides); most runs
so far were blind and read the console and the page snapshot instead. Pilot
cases are shown but not scored. Comparing test 8 with tests 5 and 6 shows what
the agent loop and a browser add for the same model: six models whose one-shot
pagoda was blank scored 7 to 10 as agents (2026-10-17).

## Settings

Every model ran at its own best fit on the card, found by real loads:

- **Context** (`-c`) is raised towards the model's native limit until VRAM
  is nearly full.
- **Expert offload** (`-ncmoe N` in llama.cpp) keeps the experts of `N`
  layers in system RAM for mixture-of-experts models. It is always used with
  `-lm none`, so the weights load into RAM up front instead of page-faulting
  over the network during the first request. Since 2026-10-22 the Flash-Next
  entries on llama.cpp 0.7.0 keep all experts in RAM (`-cmoe`) and give the GPU a
  cache of hot experts (`--moe-cache-mib N`) instead; see [Tuning](tuning.md).
- **KV cache** is f16 or q8_0. f16 costs VRAM, not speed, so q8_0 is used where
  the VRAM buys context or an expert cache: the Flash-Next entries moved to q8_0
  on 2026-10-22 (mean KL against f16 0.0011).
- **Thinking budget** is `min(24000, reply cap − 6000)` tokens on every
  engine, so a long think ends with room left to answer.
- **Client context** tells the agent the model's limit minus
  `max(10%, 16k)`, because the agent decides when to compact from the
  previous turn's size. Since 2026-10-14 the margin no longer counts the 32k
  reply twice: a 150k server compacts at 89,328 tokens (60 %), not 71,000
  (47 %). Earlier runs, all of test 2 included, used the old window.
- **Shell command timeout** is 9 minutes per command in tests 1 to 4, 7 and 8 since
  2026-10-15 (it was 30 before for tests 1 to 4), so a command whose shell died cannot stall a
  case past the hang watchdog.
- **File search.** The agent's `glob` and `grep` tools failed inside the sandbox
  until 2026-10-11, because the image lacked ripgrep. Every model had the same
  handicap and earlier runs were not repeated.
- **Maker sampling and a loop guard** are on for every entry since 2026-10-09;
  see [Tuning](tuning.md).
- **Vision.** Entries with an image head are checked with a red-and-blue test
  image; the cards list which setups pass (15 of 15 on 2026-10-15).

## How to read the numbers

- **This is a living snapshot, not an apples-to-apples benchmark.** The
  harness, grading, engines, and client settings changed as we learned; see
  [History](history.md). Rows from different eras are not directly
  comparable.
- **One run per row.** One model scored 5/5, 5/5, and 2/5 on identical
  settings. A one- or two-check difference is noise. Read results as pass,
  partial, or fail.
- **Speed probes** are short benchmarks (thinking off, temperature 0, 400-token
  replies) and read higher than agent runs; a streamed figure includes thinking.
  Both are labelled in [Engines](engines.md) and [Tuning](tuning.md).
- **tok/s** is generation throughput averaged over the whole agent run:
  output and reasoning tokens divided by wall time. It includes prompt
  processing, tool time, and compaction, so it is lower than a short-prompt
  benchmark and depends on the task.
- **Uncensored models** run the same coding tasks as every other model.
