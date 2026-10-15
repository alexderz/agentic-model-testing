# Test 4: how to run, grade and aggregate

Test 4 repeats the same ticket against the same model with the same settings and measures how much the
outcome varies. `DESIGN.md` says why. This file says how, and records what was changed from the design
while building it (2026-10-10).

## What is here

| Path | Contents |
| --- | --- |
| `project/` | The starting tree for every run: the known-good crate from `wb-flashnext-sglang` (`suites/test3/KNOWN-GOOD.md`), without `target/` and `.git`. It builds in `localhost/bakeoff-agent` and its own 155 tests pass (115 in the library, 22 in `tests/tools.rs`, 18 in `tests/protocol.rs`). |
| `baseline-tests.json` | The names of those 155 tests. The grader counts a baseline test that later fails or is gone as a regression. |
| `tickets/<id>/TICKET.md` | The issue text the agent receives. |
| `tickets/<id>/hidden/checks.py` | The acceptance checks the agent never sees. |
| `tickets/<id>/reference/solution.patch` | A reference solution, as a patch against `project/`. |
| `prompt-preamble.txt` | The fixed text placed before every ticket. |
| `grader/` | What runs inside the grading container: `in_container.py` (build, tests, hidden checks), `run_hidden.py` and `t4lib.py` (an MCP client over stdio and a scripted fake Home Assistant). |
| `make-matrix.py` | Prints the matrix rows for one model. |

At the top of the repo: `run-case-test4.sh`, `run-test4.sh`, `grade-test4.sh`, `grade-test4.py`.

## The three tickets

| Ticket | Shape | Hidden checks | Reference patch |
| --- | --- | --- | --- |
| `bugfix-targets` | Small bug fix. `list_services` reports `targets_entities: false` for every service of a current Home Assistant. | 4 | 2 files, 67 lines added, 1 removed |
| `feature-filter` | Medium feature. `list_entities` gains a `device_class` filter and a `count_only` mode. | 11 | 4 files, 72 added, 4 removed |
| `config-timeouts` | Cross-cutting change. Connect timeout, retry count and retry delay become environment settings. | 13 | 5 files, 191 added, 3 removed |

The hidden checks are black box. They start the built `ha-mcp` binary, speak MCP to it over stdio, and
point it at the grading replay (port 8127) or at a scripted fake Home Assistant inside the container.
They do not depend on any name inside the crate. Expected numbers are computed from the replay's own
answers at grading time. `tickets/bugfix-targets/hidden/EXPECTED.md` records the defect as reproduced
and the correct answer for the three lock services (`true` for all three).

## Run one case

One case is one model entry, one ticket and one run number. Case names are
`t4-<ticket>-<model short name>-r<n>`; results go to `results-test4/<case>/`.

Make a matrix for a model (five runs of each ticket, interleaved), then queue it the usual way:

```sh
suites/test4/make-matrix.py qwen38-vllm qwen3.8-27b-vllm - > matrix-test4-qwen38-vllm.tsv
RUN_SCRIPT=run-test4.sh python3 -u tools/tune_and_run.py matrix-test4-qwen38-vllm.tsv
```

The third argument is the entry's flag line, or `-` for an entry used as configured. Take it from the
model's test 3 row. A row has the four tab-separated columns `tools/tune_and_run.py` reads:

```
t4-bugfix-targets-qwen38-vllm-r1	qwen3.8-27b-vllm	-	fixed: ticket=bugfix-targets run=1
```

The note starts with `fixed` so the flags are not re-tuned between runs, and carries `ticket=<id>`,
which `run-case-test4.sh` reads. To run a single case by hand:

```sh
./run-case-test4.sh t4-bugfix-targets-qwen38-vllm-r1 qwen3.8-27b-vllm - bugfix-targets 1
```

What a run does:

1. Copies `project/` to a fresh `results-test4/<case>/work`, mounted as `/work`.
2. Writes the prompt: `prompt-preamble.txt` followed by the ticket.
3. Loads the model and writes the same OpenCode configuration as `run-case-sandboxed.sh`.
4. In the container, builds the project once before the clock starts (`t4/prebuild.log`), so the cap
   measures the agent's work and not the first compile.
5. Starts OpenCode under `timeout` with a 45-minute cap (`T4_CAP_S`, default 2700 seconds). The cap is
   applied inside the container. `CASE_TIMEOUT` in `run-test4.sh` is only the outer guard of
   `run-matrix.sh`; it also covers loading the model, so it is set an hour above the cap.
6. Writes `meta.json` with the usual fields plus `test`, `ticket`, `run`, `cap_s`, `agent_rc`,
   `timed_out`, `prebuild` and `container_wall_s`. `duration_s` is the agent's own time.

The agent can reach the Home Assistant replay on port 8126 (`$HA_URL`, `$HA_TOKEN`), as in the other
tests. The bug-fix ticket needs it: the project's own fixtures do not show the defect.

## Grade

```sh
python3 grade-test4.py --header > results-test4/grades.tsv
for d in results-test4/t4-*/; do python3 grade-test4.py "$d" >> results-test4/grades.tsv; done
```

`grade-test4.py CASE_DIR [TICKET]` prints one TSV row. The ticket defaults to the one in `meta.json`,
then to the one in the case name. `--detail OUT.json` also writes every test and check result, the
changed files and the agent's last message. The docstring of `grade-test4.py` describes each column.

The script calls `grade-test4.sh`, which makes a private snapshot of the work tree (without `target/`
and `.git`), hands it to evalbox and runs `grader/in_container.py` in `localhost/bakeoff-agent`:
`cargo build --release`, `cargo test --release --no-fail-fast`, then the hidden checks. Nothing the
model wrote is executed on the host. The container uses the grading replay on port 8127, never 8126.
A lock file (`tmp/test4-grade.lock`) lets only one grading build run at a time. One case takes about
half a minute.

A run **passed** when the tree builds, every hidden check passes and no baseline test regressed.

`claimed_done` is read from the last assistant text of the main session in `oc-data/opencode.db`. The
preamble asks the agent to end with `STATUS: DONE` or `STATUS: NOT DONE`; when that line is there it
decides. Otherwise phrases decide ("all 156 tests pass", "is fixed", "could not finish"), and a
statement of failure outweighs a statement of success. The column carries the phrase that decided
(`yes:STATUS: DONE`, `no:3 tests failed`), so a reader can audit it. The phrase matching is a
heuristic: check the `false_done` rows by eye before quoting the number, using `--detail`.

Two columns were added after the ones the task listed: `timed_out` and `note` (the build error, or the
run's status when it is not `ok`).

## Aggregate

```sh
python3 grade-test4.py --summary results-test4/grades.tsv
```

This needs no other tool. It prints, per model and ticket, k of N passed, the false-done count, the
number of runs with regressions, and minimum / median / maximum of duration and output tokens; then one
line per model. A case graded twice counts once (its last row). With five runs the pass rate separates
"always", "usually" and "sometimes" and nothing finer.

## Validation (2026-10-10)

For each ticket two fake case folders were graded: the untouched project, and the project with the
reference patch (`tmp/test4-validate/`, rows in `tmp/test4-validate/grades.tsv`).

| Ticket | Untouched project: hidden checks | Reference: hidden checks | Reference: own tests | Regressions |
| --- | --- | --- | --- | --- |
| `bugfix-targets` | 1 pass, 3 fail | 4 pass, 0 fail | 156 pass, 0 fail | 0 |
| `feature-filter` | 0 pass, 11 fail | 11 pass, 0 fail | 156 pass, 0 fail | 0 |
| `config-timeouts` | 4 pass, 9 fail | 13 pass, 0 fail | 159 pass, 0 fail | 0 |

The untouched project fails every ticket and each reference passes with all 155 baseline tests green.
The checks that pass on the untouched project are the ones that guard existing behaviour (services
without a target stay `false`; without the new variables a request is tried once).

Further checks made the same day:

- A naive bug fix that swaps `target.entity_id` for `target.entity` scores 3 of 4 hidden checks and
  one regression, so it does not pass. A tree that does not compile scores `builds=no`, 155
  regressions and every hidden check failed.
- A fake case holding the archived `wb-flashnext-sglang` transcript exercised the transcript columns:
  2 compactions, 215 turns, 222 tool calls, `claimed_done=yes:155 pass`, and `false_done=yes` when the
  same transcript was paired with the untouched tree.
- The generated `agent-cmd.sh` ran in the real sandbox (container root, network policy) with a stub in
  place of OpenCode: the prebuild succeeded, the cap ended the stub with exit status 124, and the
  start, end and exit-status files were written.

To apply a reference patch to a copy of the project (the host has no `patch` command):

```sh
cp -r suites/test4/project /some/scratch/tree && cd /some/scratch/tree
git apply -p1 /srv/bakeoff/model-bakeoff/suites/test4/tickets/<id>/reference/solution.patch
```

## Changes from DESIGN.md

- **`config-timeouts`.** The design sketched "HTTP timeout and retry count configurable by environment
  variables". The request timeout already is (`HA_MCP_TIMEOUT_SECS`), and the server has no retries at
  all. The ticket therefore asks for what is missing: `HA_MCP_CONNECT_TIMEOUT_SECS` (the connect
  timeout is hard-coded to 5 seconds today), `HA_MCP_RETRIES` (default 0, so the default behaviour is
  unchanged) and `HA_MCP_RETRY_DELAY_MS`. The connect timeout itself is checked only for validation and
  documentation: a connection that hangs cannot be produced reliably inside the container.
- **`feature-filter`.** The design suggested a `name_contains` filter. `list_entities` already has
  `query`, which matches entity id and friendly name, so that filter would duplicate it. The ticket
  asks for `device_class` instead, an exact-match filter in the style of the existing `domain` and
  `state` arguments, and keeps `count_only`.
- **`bugfix-targets`.** Four services of the recorded installation declare an empty target
  (`"target": {}`). Both answers are defensible for them, so the hidden checks do not test them. The
  ticket also requires the older catalogue shape to keep working, because an existing test asserts it.
- **Time cap.** The cap is applied to the agent inside the container, not to the whole case, so model
  loading does not eat into the 45 minutes. The project is built before the clock starts.
- **Preamble.** It asks for a final `STATUS: DONE` or `STATUS: NOT DONE` line, which makes
  `claimed_done` much less dependent on phrase matching.

## Not verified without a model

These parts could not be exercised without access to a model. They were checked with `bash -n` and by
reading them against the test 3 scripts.

- `run-case-test4.sh` end to end: `set_variant`, `warm`, the limits from `tools/entry_spec.py`, the
  real `opencode run` under `timeout`, and `distil-meta.py` on a test 4 `events.jsonl`.
- `run-test4.sh` under `tools/tune_and_run.py` and `run-matrix.sh`: the replay guards, the skip of
  finished cases, and whether an hour above the cap is enough for the outer `CASE_TIMEOUT` when a
  model loads cold.
- What OpenCode leaves behind when `timeout` stops it at the cap: whether the session database is
  complete, and whether the last assistant text is then a usable basis for `claimed_done`.
- Whether real models follow the `STATUS:` line, and how often the phrase fallback misreads a final
  message.
- Whether 45 minutes and the three tickets separate the first-round models at all. If every model
  passes or fails every run, the tickets need to be harder or easier.
- The transcript columns on a session with subagents (the archived transcript has none).
- Recording the server's seed (DESIGN.md, "Runs") is not implemented: nothing here reads it.
