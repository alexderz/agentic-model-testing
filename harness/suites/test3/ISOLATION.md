# Test 3: how the probe isolation is enforced, and how it is tested

The config comes from `tools/test3_config.py`; OpenCode 1.18.32 enforces it.

- **The MCP server** is OpenCode's `ha` server: `python3 /opt/t3/shim.py --args-from-help --find
  /work/mcp-src/target/release`. Its tools appear as `ha_<tool>`. The shim restarts a rebuilt server
  and logs every message to `/t3/shim.jsonl`.
- **`mcp-probe`** (subagent) has every built-in tool off (`"*": false`) and only `ha_*` on. OpenCode
  then offers it the MCP tools and nothing else: no bash, read, edit, write, glob, grep, webfetch or task.
- **Every other agent** (build, plan, general, explore, compaction, summary, title) has `ha_*` off. The
  main agent therefore cannot call the server, and cannot reach it through the built-in `general`
  subagent either; its only route is the task tool with `mcp-probe`.

`tests/test_test3_isolation.sh` checks this end to end without a GPU: a real OpenCode session in the
agent image, run as evalbox and as container root like a real case, with a fake MCP server behind the
shim and a scripted fake model (`tests/fake_llm.py`). Result on 2026-10-07: ALL PASS.

- The main agent is offered bash, edit, glob, grep, read, skill, task, todowrite, webfetch and write,
  and no `ha_` tool. Its direct `ha_get_config` call is rejected as an unavailable tool.
- The task tool starts `mcp-probe`, which is offered `ha_get_config` only. Its `bash` call is rejected
  ("unavailable tool"); its `ha_get_config` call returns the server's answer, which reaches the main agent.
- The shim log has exactly one `tools/call`, the probe's.

Not covered offline: whether a real model briefs the probe well (that is what the test measures),
and the main agent delegating to `general` (configured off for `ha_*`, not exercised by the script).
