# Test 3: using an MCP server through a delegated subagent

Operator, 2026-10-07. Test 1 asks whether a model can write a working client, test 2 whether it can
build a working MCP server. Test 3 asks whether it can *use* one well: get reliable data through an
MCP server, judge whether that server can be trusted, fix it when it cannot, and manage a subagent
to do the extraction.

## Two flavors per model

- **3G (known good):** the agent is given the best MCP server the bake-off has produced, checked
  beforehand: every tool hits only real Home Assistant endpoints and returns data that matches the
  fixture (see KNOWN-GOOD.md).
- **3O (own):** the agent is given the server it built itself in test 2, taken from the archive as
  it was graded, even if it does not build, calls invented endpoints or returns wrong data.

The prompt is the same for both. It does not say which flavor it is, and it does not say the server
may be broken.

## What the agent gets

- The server's source, writable, in `/work/mcp-src`, with cargo. It may fix and rebuild it.
- The server connected to OpenCode as an MCP server, through `mcp-restart-shim.py`: when the binary
  changes, the shim starts the new build on the next request, replays the handshake and tells the
  client the tool list changed. A fix the agent makes therefore reaches the subagent.
- A subagent named `mcp-probe` whose only tools are the server's tools: no shell, no files, no web.
- No MCP tools for the main agent, so the only way to use the server is to delegate to the probe with
  OpenCode's `task` tool and write its instructions.
- Direct access to the Home Assistant REST API (curl), so it can check what the probe reports against
  the source of truth.

## The task

Extract a fixed set of facts about the installation through the probe, check them against the REST
API, decide whether the MCP server can be trusted, fix it if not and re-test through the probe, and
write `REPORT.md` with each fact, where it came from and the assessment of the server.

## Grading

Automatic (`grade-test3.py`, one TSV row per case): facts correct out of the total, the number of
probe sessions, MCP tool calls made through the probe (shim log), whether the main agent ever called
an MCP tool directly (it cannot; a yes means the isolation failed), whether it called the REST API
itself, whether it changed the server, and whether a changed server still passes test 2's grader.

Judged (`RUBRIC.md`, scored by Model Master from the transcript, each item 0-2 with a quoted line as
evidence): how well the agent briefs the probe, whether it asks for structured output, whether it
verifies what the probe returns, how it handles a failing probe, and whether its trust-or-fix decision
fits the evidence.

## First runs

The current picks, both flavors: qwen3.8-27b-vllm, flashnext (SGLang), lcpp6-orcarouter-fn-uncensored,
lcpp6-thinkingcap-27b-heretic. `matrix-test3.tsv`, not queued yet.
