# Test 4: consistency (repeated runs of in-project coding work)

Operator, 2026-10-10: tests 1 to 3 are single samples. Once a model is judged good, how far can it be trusted?
Its job here is heavy coding inside an existing project, in an agent harness, so that expensive hosted tokens are
kept for other work. Test 4 repeats the same prompt against the same model with the same settings and measures how
much the outcome varies.

Status: DRAFT by Model Master. Not built yet. The choices below are recommendations; the operator may change them.

## What it measures

For each model and task, over N identical runs:

- **Pass rate**: runs whose result passes the hidden acceptance tests, as k of N.
- **Regressions**: runs that break tests which passed before the agent started.
- **False "done"**: runs where the agent says the work is finished and tested while the hidden tests fail. This is
  the trust number: a model that fails and says so is usable; one that fails and reports success is not.
- **Spread of effort**: minimum, median and maximum of wall time, output tokens, turns and tool calls, and of the
  size of the change (files touched, lines added and removed).
- **Process faults**: loops, runaway thinking steps, compactions, hitting the time cap.
- **Sameness of the solution**: whether the runs converge on the same approach (which files they touch), reported
  as a short note, not scored.

## Tasks: tickets against one existing codebase

Tests 1 and 2 are greenfield. Test 4 works inside a project that already exists, which is the use case.

The project is the known-good Rust MCP server from test 3 (`suites/test3/KNOWN-GOOD.md`: crate `ha-mcp`, 12 tools,
155 tests, builds in the agent image, talks to the Home Assistant replay). We know it well and it has one real
defect. Each ticket is a short issue text, the way a developer would file it. Three tickets of different shape:

1. **Bug fix (small).** The real defect: `list_services` reports `targets_entities: false` for services that do
   target entities. The ticket describes the symptom, not the cause.
2. **Feature (medium).** Add one capability with a written specification, for example a `name_contains` filter and a
   `count_only` mode on `list_entities`, with tests.
3. **Cross-cutting change (medium).** A change that touches several modules and must keep everything green, for
   example making the HTTP timeout and retry count configurable by environment variables, documented, with the
   defaults unchanged.

Each ticket has hidden acceptance tests the agent never sees (run by the grader against its final tree), and the
project's own tests must still pass. Before the suite is used, the grader must show: the untouched project FAILS
each ticket's hidden tests, and a reference solution PASSES them.

## Runs

- N = 5 per model and ticket to start (15 runs per model). Five runs separate "always", "usually" and "sometimes";
  they do not give tight percentages, and the report says so. Raise N for the models we shortlist.
- Same entry, same flags, same prompt, a fresh work tree and a fresh OpenCode session each time. The server's seed
  stays random (the default), and the seed is recorded when the engine reports it.
- Cap: 45 minutes per run. One slot, the usual OpenCode limits from the entry spec.
- Case names: `t4-<ticket>-<model>-r<n>`; results in `results-test4/`.

## Models

Eligibility (operator 2026-10-10): a model must have passed tests 1 and 2 and generate at least 20 tokens per second
in those runs. Slower models are not repeated: five runs each would take days.

Eligible today, in running order (speeds are test 1 / test 2):

1. Qwen3.8-27B on vLLM, 150k (70 / 70 tok/s), the default.
2. Qwen3.8-27B Coder390 EfficientThink on llama.cpp 0.6 (50 / 50).
3. Qwen3.8-27B Uncensored Aggressive on vLLM (64 to 68 / 60 to 64).
4. Tiel-Coder-35B 6-bit (43 / 39).
5. Cyber-Tiel-Coder-35B (44 / 25).
6. ThinkingCap Qwen3.8-27B Heretic on llama.cpp 0.6 (31 / 25, one test-2 run at 19).
7. OrcaSAQ-2-Cyber-27B on llama.cpp 0.6 (54 / 53), known to vary: a good subject.
8. Gemma 4 31B (31 to 53 / 39 to 50), thin but fast.
9. Qwen3.8-Flash-Next on its fastest engine: SGLang (36 to 45 on test 2, 44 on test 1). The operator wants
   Flash-Next as the smart daily driver, so this one matters most. Strata (24 to 30) is the fallback if SGLang
   misbehaves; test 4 and test 1B are single-agent, so SGLang's single session is enough.

Included below the floor by the operator's choice (2026-10-10):

10. Flash-Next Heretic2 on llama.cpp 0.6 (9 / 15), the fastest of the uncensored and abliterated Flash-Next builds
    (Abliterated S15 runs 10, Orcarouter 8).
11. GLM-5.3-Flash on Maya (14 / 14): "I want to see if GLM Flash is consistent or not."

Not eligible on speed: Flash-Next unpruned and Abliterated S15 on llama.cpp (7 to 10 tok/s), Orcarouter Flash-Next
(8), Swift 1.5 on llama.cpp (7). Any retry-wave model that passes both tests at 20 tok/s or more joins the list.
The slow three (9 to 11 above) run last, so the fast models' results are in first.

## Test 1B: test 1 repeated

Operator 2026-10-10: rerun test 1 four more times for each eligible model, unchanged (same prompt, entry, flags,
harness and time cap as its graded test-1 case), and grade each run with the test-1 grader. With the original run that
gives five samples. Case names `wa-<original case>-r2` to `-r5`; results in `results-wave-a/` like any test-1 case.
The report shows, per model, k of 5 at 5/5, the range of passing tests and subcommands, and the min / median / max of
time and tokens. Every model gets the same time cap: no time-boxing by model.

## Report

A consistency table per model: for each ticket k of N passed, false-done count, regressions, and the min / median /
max of time and tokens; then one overall line per model ("passed 13 of 15, never claimed a pass it did not have").
The model card gains a "consistency" paragraph.

## Decided (operator 2026-10-10)

- Speed floor of 20 tok/s for eligibility.
- Test 1 is repeated four more times as test 1B.
- The same time cap for every model within a test.

## Open choices (recommendations in brackets)

- Language of the project [Rust, because the known-good server exists and test 2 showed Rust separates models
  better than Python; a Python ticket set can follow].
- N for the tickets [5, then 10 for the shortlist].
