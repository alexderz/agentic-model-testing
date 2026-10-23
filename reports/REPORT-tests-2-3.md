# Tests 2, 3A and 3B — building an MCP server, and using one

> Status (2026-10-22): a record of the first runs of 2026-09-27 and 2026-09-28. Test 3 was reworked afterwards
> (a subagent with only the server's tools, 14 facts, a 12-point rubric); see
> [Method](../docs/model-research/method.md).

Three tests on one RTX 3090, run 2026-09-27 to 2026-09-28 against a recorded
fixture of a real Home Assistant installation (434 entities, 22 domains, 124
unavailable, 126 unknown). Every agent ran in a container. Agent: Open Code
1.18.32 over llama-swap.

- **Test 2** — build a Rust MCP server for the Home Assistant API, with the
  official protocol specification supplied on disk.
- **Test 3A** — describe the installation using *the server you built*.
- **Test 3B** — describe it using *a server someone else built*.

3A and 3B exist to separate two skills that a single test conflates: can a
model **build** a working tool, and can it **use** one.

---

## Read this before any table

Ordering here is not a ranking. An earlier cohort on the same harness ran
three cases three times each at identical settings: duration varied 11-25%,
turns 16-32%, lines of code 12-22%, and one model swung 5/5, 5/5, 2/5 on
execution checks. Everything below is n=1. A one- or two-check difference
between two models is noise.

Two specific limits on the numbers in this report:

**The fact score saturates.** Eleven facts are checked; eight of them are
per-domain entity counts, which the best server returns in a single call. A
model that calls one tool and transcribes the table scores 8/11. The
`depth` column counts the two checks that a domain dump does *not* give you
— the `unavailable` and `unknown` totals, which are different states and
have to be computed. In test 3B, **no model got either of them**. Read
`depth`, not the ratio.

**Report size is descriptive, not a quality measure**, and neither is lines
of code. They are included because they separate a 967-character domain dump
from a 13 KB report, not because longer is better.

---

## Test 2 — build an MCP server

Ten models, each given the official specification (92 KB, curated, plus the
JSON schema). Graded by building the result and speaking MCP to it over
stdio.

| model | builds | tools | its own tests | conforms |
|---|---|---|---|---|
| qwen3.8-27b | yes | 7 | 36 pass | **yes** |
| bonsai2-27b | yes | 6 | 34 pass | **yes** |
| devstral-small-2-24b | yes | 4 | 5 pass | no — id not echoed |
| qwen3.6-35b-a3b | yes | 6 | 18 pass | no — no protocolVersion |
| qwen3.6-27b | yes | 0 | 26 pass | no — no initialize response |
| glm-4.7-flash | yes | 0 | 13 pass | no — no initialize response |
| qwen3-coder-30b | yes | 0 | 5 pass | no — no initialize response |
| nanbeige4.2-3b | no | — | — | no Cargo.toml written |
| nemotron3-nano-30b | no | — | — | malformed Cargo.toml |
| jan-nano-128k | no | — | — | no binary |

**Two of ten produced a server a client can talk to.** That is the headline.

### Passing tests is not evidence the thing works

qwen3.6-27b wrote **26 passing tests** for a server that never answers
`initialize`. glm-4.7-flash wrote 13, qwen3-coder-30b wrote 5, with the same
outcome. The tests exercised internal helpers; nothing drove the protocol.

This is the most transferable result in the set, and it is not about local
models: a model writing its own tests will tend to test what it already
believes, and a green suite says nothing about whether the artifact performs
its function. Only running the protocol against the binary found this.

### The grader was more lenient than a real client

Our first grader accepted any response *containing* `serverInfo` as a
successful handshake, and recorded devstral-small-2-24b as working. A real
client refuses that server: its initialize result carries `"id": null`, so
no response can be correlated to a request, and Open Code closes the
connection. Tightening the grader to require the id echo took conforming
servers from four to two.

If you write your own conformance grader, it will drift toward leniency,
because you build it from the same assumptions as the thing you are
grading. Drive it through a real client where one exists.

### One working server was not reproducible

qwen3.8-27b's server is the best artifact in the cohort. Its repeat run at
identical settings **failed to compile** (`E0308`). One success is a
ceiling, not a capability.

### A model invented a protocol version

bonsai2-27b's server advertises protocol version `2025-11-05`. No such
release exists — the real ones are 2025-03-26, 2025-06-18, 2025-11-25 and
2026-07-28. It conforms structurally while naming a version it made up.

---

## Test 3A — use the server you built

Only four models had a server worth trying. Two of the four had theirs
refused by the client, which is the test working as intended.

| model | client accepted its server | MCP calls | HTTP reqs | facts | wrong | depth | outcome |
|---|---|---|---|---|---|---|---|
| qwen3.8-27b | yes | 16 | 16 | 11/11 | 0 | **2/2** | ok |
| bonsai2-27b | yes | 16 | 22 | 10/11 | 1 | 1/2 | ok |
| qwen3.6-35b-a3b | **no** | 0 | **146** | 9/11 | 2 | 0/2 | worked around it |
| devstral-small-2-24b | **no** | 0 | **0** | 0/11 | **4** | 0/2 | **fabricated** |

### Identical failure, opposite response

The bottom two rows are the most useful result of the whole exercise. Both
models' own servers were refused by the client. Then:

- **qwen3.6-35b-a3b noticed**, fell back to `curl` from bash, made 146
  direct HTTP requests, and produced a 9/11 report.
- **devstral-small-2-24b made zero queries of any kind** and wrote a
  confident report containing four wrong numbers and ten invented per-domain
  counts.

Both wrote a plausible-looking report. Only the request log separates
querying from claiming. Any evaluation that reads the output without
recording what the model actually did would score these two similarly.

For autonomous or multi-agent work this is a disqualifying difference, not a
scoring one: an agent that fabricates when its tools break poisons every
downstream consumer of its output.

---

## Test 3B — use a server someone else built

Every model was given `qwen38-mcp2` (7 tools, the best in the cohort),
except its author, which was given the second-best, `bonsai2-mcp2`.

| model | server given | MCP calls | facts | wrong | depth | report | duration |
|---|---|---|---|---|---|---|---|
| glm-4.7-flash | qwen38 | 13 | 9/11 | 1 | 0/2 | 10.2 KB | 72 s |
| nanbeige4.2-3b | qwen38 | 28 | 9/11 | 2 | 0/2 | 8.9 KB | 272 s |
| qwen3.8-27b | **bonsai2** | **668** | 8/11 | 1 | 0/2 | 13.0 KB | 2520 s |
| bonsai2-27b | qwen38 | 80 | 8/11 | 3 | 0/2 | 12.8 KB | 1539 s |
| nemotron3-nano-30b | qwen38 | 3 | 8/11 | 1 | 0/2 | 1.7 KB | 54 s |
| devstral-small-2-24b | qwen38 | 3 | 8/11 | 1 | 0/2 | 7.7 KB | 78 s |
| jan-nano-128k | qwen38 | 4 | 8/11 | 1 | 0/2 | **1.0 KB** | **14 s** |
| qwen3.6-35b-a3b | qwen38 | 55 | 7/11 | 3 | 0/2 | 11.4 KB | 135 s |

### A good tool collapses the task

Handed a well-designed server, **every model succeeded**, including three
that could not build one at all and one that fabricated in 3A. The spread is
7-9 of 11 — inside the noise floor.

That is not because the models are equivalent. It is because the task became
"call `list_domains`, transcribe the table". jan-nano-128k scored 8/11 with
four calls, fourteen seconds and a 967-character report; in test 1 the same
model spent 624 turns to produce 27 lines. The server did the work.

The `depth` column shows the cost of that collapse: **not one model in 3B
reported the unavailable and unknown counts correctly**, the only two facts
that require computing something rather than copying it. In 3A, using its
own server, qwen3.8-27b got both.

If you are choosing a model by how well it drives a good tool, this test says
you cannot — they all look the same. The differences live in building the
tool, and in what happens when it breaks.

### The shape of a server's tools dominates its consumer's effort

qwen3.8-27b, same model, same prompt, same fixture, same day:

| server given | tools | MCP calls | facts | duration |
|---|---|---|---|---|
| its own | 7 | **16** | 11/11 | 1070 s |
| bonsai2's | 6 | **668** | 8/11 | 2520 s |

**42x the calls and a worse report**, from changing nothing but the server.

This is not thrashing: 64 steps, a natural stop (no length or turn cap), and
near-all distinct arguments — the most repeated call shape occurs twice. The
model is enumerating entity by entity because that server paginates and
offers no bulk listing, where its own answered the whole-inventory question
in one call.

Both servers pass conformance. Both "work". One costs its consumer 42x more
to use. Conformance is a floor, not a design review — and an MCP author's
tool granularity is a performance decision that lands entirely on someone
else.

---

## Method and caveats

**Sandboxing.** Every agent ran in a rootless container: work directory
mounted, unprivileged user, capabilities dropped, no route to host-local
services. Generated code is executed only in a container.

**Reproducibility.** All three tests ran against a recorded fixture served by
a replay server, not the live house. No rate limit, no load on a real system,
identical data for every case. The replay is verified before each run to
serve reads and refuse writes, from both the host and inside a container.

**The 96k context floor.** All variants run at 98304 tokens or above. Cases
below that are retired, their results kept on record. The target is
long-running agentic sessions, and a 48k window spends its budget compacting
rather than working — qwen3.8-27b at 49152 burned its entire context
transcribing entities by hand and never wrote its report.

**A protocol version gap we created.** Models were given the 2026-07-28
specification; Open Code 1.18.32 requests 2025-11-25. None implement it, so
each correctly answers with its own latest, and the client correctly refuses.
Both sides conform and nothing connects. A shim bridges only the negotiated
version and logs what was really advertised. It never supplies a field a
server omitted — that would convert a genuine protocol violation into a pass.

**A permission-layer confound, fixed mid-test.** Headless Open Code
auto-rejects every permission request. A model that reached for `/tmp`
stalled while one that happened to pick the work directory succeeded — that
measures which scratch path a model guessed, not tool use. The container is
the isolation boundary, so the prompt layer was disabled inside it and 3A was
re-run. bonsai2-27b went from "no report" to 10/11 purely from lifting this.
The earlier cohort is kept at `results-r4-strictperm`; **do not compare
across the two**.

**Grading bugs found and fixed**, all of which produced plausible *negative*
results rather than errors:

- `unavailable` was scored against `unavailable + unknown`. Those are
  different states; a model reported the correct narrower figure and was
  marked wrong for being more precise than the grader.
- Claim patterns took the first textual match, so a stray "16 button" in
  prose overrode `| button | 21 |` in the inventory table.
- Harness faults were recorded as model failures: a login shell replaced the
  container's PATH so cargo vanished and working servers "did not build";
  `| tail` masked the failure; a sourced `set -euo pipefail` killed runs on a
  grep that found nothing, which was the *result*, not an error.

After tuning the grader, a negative control was run: corrupting three figures
in a known-good report is still caught, and nothing else flips.

**One dirty number.** A conformance probe hit the live replay while
`qwen38-other` was running and may have added a line or two to its 668
requests. Immaterial at that magnitude, but the number is not clean. The
checker now points at the discard port so this cannot recur.

**Cohorts, not baselines.** These numbers describe these models, this
harness, this day. They do not travel. What travels is the method and the
qualitative findings.
