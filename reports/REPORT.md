# Titan model bake-off — Home Assistant CLI

> **Status (2026-10-22): round 1, kept as a record.** This is the first round (September 2026): one
> prompt, the Pi agent, a single llama.cpp build, one sample per case, no tests beyond the CLI.
> Models, engines and tests have changed since. Current results and picks are in
> [Conclusions](../docs/model-research/conclusions.md); how the tests work now is in
> [Method](../docs/model-research/method.md).

**Task (identical for every case, no guidance, no SDLC):**
`Write a Python command-line tool for the Home Assistant REST API.`

Agent: Pi 0.87.1 over ACP → llama-swap → llama.cpp b1-4260903 on titan (RTX 3090, 24 GB).
Each model warmed before the run so load time is excluded from the measurement.
No time or turn caps. 17 cases, one model resident at a time.

---

## Results

| case | status | dur | turns | tok/s | LOC | API cov | compiles |
|---|---|---|---|---|---|---|---|
| devstral24-max | ok | 26s | 2 | 94 | 98 | 3/9 | yes |
| nano30-speed | ok | 47s | 2 | 102 | 204 | 2/9 | **NO** |
| coder30-speed | ok | 60s | 19 | 166 | 306 | 5/9 | yes |
| glm47-speed | ok | 82s | 8 | 133 | 287 | 5/9 | yes |
| nano30-max | ok | 85s | 2 | 87 | 295 | 2/9 | yes |
| **qwen35b-speed** | ok | **109s** | 4 | **163** | 857 | 6/9 | yes |
| qwen35b-max | ok | 128s | 6 | 126 | 807 | 4/9 | yes |
| coder30-max | ok | 138s | 11 | 68 | 304 | 6/9 | yes |
| qwen38-27b-nothink | ok | 191s | 10 | 78 | 354 | 6/9 | yes |
| glm47-max | ok | 197s | 11 | 73 | 463 | 6/9 | yes |
| qwen36-27b-max | ok | 238s | 7 | 77 | 563 | 3/9 | yes |
| qwen38-27b-max | **no_files** | 418s | 1 | 78 | 0 | — | — |
| super120-max | ok | 541s | 10 | 16 | 142 | 3/9 | yes |
| qwen38-27b-budget16k | ok | 733s | 18 | 74 | 467 | 4/9 | yes |
| glm45air-max | ok | 1043s | 17 | 16 | 430 | 4/9 | yes |
| **qwen38-27b-budget** | ok | 1253s | 60 | 62 | 1043 | **8/9** | yes |
| qwen235-max | ok | **3045s** | 4 | **3.9** | 81 | 3/9 | yes |

API coverage = distinct Home Assistant REST endpoints touched, of 9
(states, config, services, events, history, logbook, template, error_log, calendars).

---

## Verdict

**Best overall: `qwen3.6-35b-a3b` at speed settings** (`-ncmoe 12 -c 131072`).
857 LOC in 109 seconds at 163 tok/s, 6/9 endpoints, 40 functions, and the only
top finisher that chose a **zero-dependency stdlib design** (urllib, no
`requests`). Best quality-per-second by a wide margin, and it is already the
daily driver — no change needed.

**Best coverage: `qwen3.8-27b` with `--reasoning-budget 4096`.**
8/9 endpoints and the only model that wrote itself a **mock HA server**
(`mock_ha.py`, 355 lines) to test the CLI against. That is real initiative.
Cost: 21 minutes and 60 turns. Worth it when quality matters more than latency.

**Best fast option: `qwen3-coder-30b-a3b`.** 306 LOC in 60 seconds, 5/9.
Consistently competent, never brilliant.

**Avoid for agentic coding:**
- `nemotron3-nano-30b` — 2/9 coverage at both settings, and the speed variant
  emitted Python that does not compile (unterminated string literal, line 193).
  Only case in the entire matrix producing broken syntax.
- `qwen3-235b-a22b` — 3.9 tok/s, 51 minutes for 81 LOC. 142 GB of weights
  against 125 GB RAM and a 24 GB card; only 9.4 GB stayed resident. Unusable.
- `nemotron3-super-120b` — 16 tok/s, 142 LOC, 3/9. Slow and thin.

---

## The qwen3.8-27b reasoning ladder

The baseline failure was a **setting, not the model**. With thinking
unrestricted it consumed its entire 32,768-token output budget inside a
`<think>` block, hit `stop: length`, and emitted no content and no tool call
in 418 seconds. Pi declares no `maxTokens` for it, so it inherited the 32k
default.

| reasoning setting | LOC | coverage | turns | verdict |
|---|---|---|---|---|
| unrestricted | 0 | — | 1 | fails outright |
| `--reasoning off` | 354 | 6/9 | 10 | works |
| `--reasoning-budget 4096` | **1043** | **8/9** | 60 | **best result in the matrix** |
| `--reasoning-budget 16384` | 467 | 4/9 | 18 | works, worse than 4096 |

**Any cap rescues it** — so it was looping, not starved for room. More budget
was actively worse: 16384 produced less than half the code of 4096. The model
is strong when its deliberation is bounded.

For reference, a productive turn for most models here is 1,000–3,500 output
tokens; the largest legitimate turn in the matrix was 8,142 (qwen3.6-35b).
4,096 is generous against that baseline.

---

## Excluded

**`MiMo-V2.6-Distill-Qwen-9B` — stack incompatibility, not a capability result.**
Its chat template emits fully concatenated tool calls
(`<tool_call><function=x><parameter=y>` with no newlines). No parser in
llama.cpp b1-4260903 terminates on that form, so every turn runs to the output
token limit and is rejected. Reproduced in a single curl outside Pi entirely.
Patching the template did not help — the model was *trained* to emit that form,
and a template cannot change what the model emits. Needs a llama.cpp build with
a matching parser or a client-side shim.

---

## Methodology notes and caveats

Three conditions were run; results above are the third. All are archived.

1. `results/contaminated-agents-md/` — Pi loaded `~/src/AGENTS.md` and
   `~/src/<agent workspace>/AGENTS.md`, injecting your SDLC into a test that was
   supposed to be unguided. Effect was **uneven**: qwen3-coder ignored it and
   built the tool; qwen3.6-35b obeyed it and asked permission, writing no code.
   Scored naively that reads as incompetence when it is actually compliance.
2. `results/prev-nc-flag-only/` — context files disabled via `-nc`, but still
   running inside the repo tree.
3. `results/` — models work in `/work/tmp/bakeoff/<case>/`, whose ancestry is
   verified free of `AGENTS.md`/`CLAUDE.md`, so nothing ambient is reachable and
   they cannot wander up into the repo while exploring. Output is copied back.

Clean-tree results were consistently better: qwen3.6-35b went 585 → 857 LOC and
qwen3-coder stopped emitting duplicate files.

**Gates built after early runs produced misleading data:**
- `preflight.sh` — proves a structured tool call round-trips before a model gets
  hours of wall time. Caught MiMo. 10/11 passed.
- `probe-variants.sh` — proves every matrix variant *loads*. Caught
  `coder30-max` OOMing at `-ncmoe 24 -c 262144`; `-ncmoe 36 -c 262144` fits.

**Known caveats:**
- `nemotron3-super-120b` and `qwen3-235b-a22b` are not declared in
  `~/.pi/agent/models.json`; both ran via custom-model-id passthrough. Pi
  budgets against an assumed 128K for every model while actual contexts here
  ranged 40,960 → 1,048,576. No overflow errors occurred in any run, so results
  stand, but the declarations should be added.
- Pi reports `reasoning: 0` in usage, so thinking tokens cannot be separated
  from content tokens for models that produced both. For qwen3.8's baseline
  failure it is unambiguous — content was empty and the message type was
  `thinking`.
- Single sample per case. No repeats, so run-to-run variance is unmeasured.
