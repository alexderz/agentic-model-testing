#!/usr/bin/env python3
"""Write the OpenCode config for a test 3 case (suites/test3/DESIGN.md).

  test3_config.py --model ID --base-url URL --context N --output N [--options JSON] --out FILE

Isolation, all in the config OpenCode resolves (checked by tests/test_test3_isolation.sh):
- The MCP server `ha` runs through /opt/t3/shim.py (mcp-restart-shim.py) on whatever binary the agent
  last built in /work/mcp-src/target/release; its tools appear to OpenCode as `ha_<tool>`.
- `mcp-probe` (subagent) has every built-in tool off and `*` denied, then `ha_*` allowed: it can call
  the MCP tools and nothing else (no shell, files, web, or further subagents).
- Every other agent has `ha_*` off: the main agent (build), the other primaries, and the built-in
  subagents general and explore, so the only route to the MCP server is the task tool -> mcp-probe.
"""
import argparse, json

PROBE_PROMPT = ("You are mcp-probe, a subagent. Your only tools are those of a Home Assistant MCP server "
                "(their names start with ha_). Do the task you are given using only those tools. Report what "
                "the tools returned, and say plainly when a tool fails, errors or returns nothing.")
OTHER_AGENTS = ["build", "plan", "general", "explore", "compaction", "summary", "title"]

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--base-url", required=True)
ap.add_argument("--context", type=int, required=True)
ap.add_argument("--output", type=int, required=True)
ap.add_argument("--options", default="{}", help="model options JSON, e.g. thinking_token_budget")
ap.add_argument("--ha-url", default="http://host.containers.internal:8126")
ap.add_argument("--ha-token", default="bakeoff-placeholder-token")
ap.add_argument("--shim-log", default="/t3/shim.jsonl")
ap.add_argument("--out", required=True)
a = ap.parse_args()

model = {"name": a.model, "limit": {"context": a.context, "output": a.output}}
opts = json.loads(a.options)
if opts: model["options"] = opts
cfg = {
    "$schema": "https://opencode.ai/config.json",
    "share": "disabled", "autoupdate": False, "instructions": [], "skills": [], "plugin": [],
    "snapshot": False, "logLevel": "INFO", "enabled_providers": ["titan"],
    "model": f"titan/{a.model}", "small_model": f"titan/{a.model}",
    "provider": {"titan": {"npm": "@ai-sdk/openai-compatible",
                           "options": {"baseURL": a.base_url, "requestTimeout": 5400000, "timeout": 5400000},
                           "models": {a.model: model}}},
    "mcp": {"ha": {"type": "local", "enabled": True,
                   "command": ["python3", "/opt/t3/shim.py", "--args-from-help",
                               "--find", "/work/mcp-src/target/release"],
                   "environment": {"HA_URL": a.ha_url, "HA_BASE_URL": a.ha_url, "HA_TOKEN": a.ha_token,
                                   "SHIM_LOG": a.shim_log}}},
    "tools": {"bash": True, "edit": True, "write": True, "read": True, "grep": True, "glob": True,
              "lsp": True, "apply_patch": True, "todowrite": True, "task": True,
              "webfetch": True, "websearch": True, "question": False},
    "permission": {"bash": "allow", "edit": "allow", "webfetch": "allow", "doom_loop": "deny"},
    "agent": {name: {"tools": {"ha_*": False}} for name in OTHER_AGENTS},
}
cfg["agent"]["mcp-probe"] = {
    "mode": "subagent",
    "description": "Reads the Home Assistant installation through the ha MCP server. Its only tools are that "
                   "server's; give it a complete, self-contained task.",
    "prompt": PROBE_PROMPT,
    "tools": {"*": False, "ha_*": True},
}
json.dump(cfg, open(a.out, "w"), indent=1)
