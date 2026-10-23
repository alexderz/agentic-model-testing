# Agentic model testing

Which open-weight models can do real agent work on one local GPU, how fast, and with what
settings. This repository holds the test harness, the written reports and the one-shot
creative tests of a long-running model bake-off on a single machine: **Titan**, one NVIDIA
RTX 3090 (24 GB) with 125 GB of system RAM, serving one model at a time through llama-swap.

The work started in the `agentic-toolbox` repository from the same owner, under
`docs/model-research/`. Those notes now live in
[`docs/model-research/`](docs/model-research/README.md). The toolbox keeps only a
pointer, and new work lands here.

## What is here

| Path | What |
| --- | --- |
| [`reports/`](reports/) | Written reports and method documents: test results, candidate and exclusion lists, and the bake-off dashboard (`reports/dashboard/`: a static HTML page and its `data.json`). |
| [`oneshots/`](oneshots/README.md) | Test 5 (brass orrery, SVG) and test 6 (voxel pagoda, three.js) one-shot replies: the model-written source, rendered frames and grades. Unedited model output; the site plays it in a sandboxed frame (see the README). |
| [`harness/`](harness/) | The harness: case runners (`run-case*.sh`, `run-matrix.sh`), graders and rubric (`grade-*.py`, `rubric.py`, `score-*.py`), the Home Assistant replay server and read-only proxy (`ha-replay.py`, `ha-readonly-proxy.py`, `ha-record.py`), the sandboxed eval box (`sandbox/`), test suites and prompts (`suites/`), entry and spec tooling (`tools/`, `engines/ENTRY-SPEC.md`, `engines/entry-specs/`), engine build and setup notes (`engines/`), and the harness's own tests (`tests/`). |
| [`site/`](site/data/README.md) | The project site: a data-driven page that renders `site/data/bakeoff.json` (built by `site/tools/build_data.py`) and plays the one-shots in a sandboxed frame. Published to GitHub Pages from `main`. |
| [`docs/model-research/`](docs/model-research/README.md) | Method, conclusions, per-model cards and the story test. Moved here from `agentic-toolbox`, which keeps only a pointer. |

## The tests in one paragraph each

- **Test 1**: a Python command-line tool for the Home Assistant REST API, run and checked by a grader
  in a locked-down container (`harness/sandbox/`). Agents can reach only the model server and a
  replay of a recorded Home Assistant fixture (`harness/ha-replay.py`), never a live house.
- **Test 2**: an MCP server built from a spec, with the same container and replay. **Test 2T** is
  test 2 with a reference document in the workspace that has three deliberately wrong endpoints.
- **Test 3**: use an MCP server through a subagent that has only that server's tools. The agent
  gets 14 facts about the recorded installation, checks them, decides whether to trust the server
  and fixes it if not (3G: a known-good server; 3O: the model's own server from test 2). A
  12-point rubric scores how the agent works with the subagent.
- **Test 4**: ticket-sized fixes (a bug, a feature, a cross-cutting change) in a Rust MCP server that
  already passes its 155 tests, graded with hidden checks and a regression count.
- **Test 5 (orrery) and test 6 (pagoda)**: one reply, no tools, to a single creative-coding prompt
  (`harness/suites/prompt-test5-orrery.txt`, `harness/suites/prompt-test6-pagoda.txt`), rendered
  offline and graded on a five-part rubric (`harness/suites/test5/README.md`,
  `harness/suites/test6/README.md`). Frames and grades: `oneshots/orrery/` and `oneshots/pagoda/`.
- **Test 7**: a seeded generator for a three-floor labyrinth, checked on unseen seeds. Only pilot
  runs are graded so far.
- **Test 8**: the same two prompts as tests 5 and 6, given to an agent with a locked-down browser
  that can see its own page and a 2 hour cap. The agent's final page, its rendered frames and the
  grades are in `oneshots/agent-pagoda/` and `oneshots/agent-orrery/`; the transcripts and work
  directories are not published (see below). A model whose one-shot pagoda was blank scored 7 to 10
  as an agent, so the one-shot score does not predict the agent score.

Method, results and settings are written up in [`docs/model-research/`](docs/model-research/README.md):
[Method](docs/model-research/method.md), [Conclusions](docs/model-research/conclusions.md),
[Engines](docs/model-research/engines.md) and [Tuning](docs/model-research/tuning.md).

## Not here yet

Phase 1 publishes code, reports and the one-shot outputs only. These stay private until a further
scrub review:

- the test evidence: transcripts, work directories and per-case result sets, test 8 included;
- the Home Assistant fixture, including its pseudonymized public version, and the test 3
  known-good exercise derived from it.

Some harness entry points therefore refer to files that are not in this repository
(`fixtures/ha-fixture.json`, result directories).

A few other files wait for a manual review because the publication gate flagged them or
they describe the host setup rather than the tests: some engine service notes and patches, a
review log, two dashboard helpers, three orrery cases (see `oneshots/README.md`) and twelve
story-test drafts under `docs/model-research/story-test/results/`. The copies of those notes in
`agentic-toolbox` are unchanged.

## Site-specific values

Every file here went through an automated publication gate (identifiers, credentials, personal
data) and a manual read before it was committed. The gate itself is not published yet.

The harness ran on a home network. Before publication, host addresses were replaced by RFC 5737
documentation addresses (`192.0.2.0/24`; `192.0.2.62` is the GPU host), internal host names by
`*.lan.example` and `*.vpn.example`, the account and home directory by `operator` and
`/home/operator`, and names from the recorded Home Assistant install by consistent fakes.
Placeholder tokens and passwords in the test 4 project and the sandbox demo were renamed to
obvious placeholders or moved to environment variables (`DEMO_DB_PASSWORD`, `DATABASE_URL`,
`PASTA_ADDR`). Edit `harness/lib.sh`, `harness/evals.env` and the entry specs for your own setup.

## License

MIT, see [LICENSE](LICENSE). Model-written files under `oneshots/` are model output kept as test
evidence.
