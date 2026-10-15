# Model checklist: lessons that became checks

Every configuration lesson we learn gets an entry here, an automatic check in `tools/preflight.py`, and a failure
signature in `tools/audit_runs.py`. The rule (the bake-off's operating rule 10):

1. Add the entry below, with the rule in one sentence and the case that taught it.
2. Add the check to `tools/preflight.py` (it reads the config spec and the model record, `engines/ENTRY-SPEC.md`).
3. Add the signature to `tools/audit_runs.py` and run it over every case: live, archived, superseded, and the models
   we rejected. A rejected model may have failed because of us.
4. Rerun or mark each case the audit flags, and record the outcome in the entry's audit line.
5. No queue starts without a passing preflight (`python3 -u tools/preflight.py --skip-done MATRIX...` as the queue
   script's first step), and the hourly check runs it on the live queue and the daily-driver configs.

Check ids are what preflight prints. Audit status uses the run of 2026-10-09 (`tmp/audit-2026-10-09.tsv`, 156 cases).

## C1. Every entry has a valid, current spec

- **Rule:** an entry is only tested through its config spec and model record; a spec whose `cmd_sha256` no longer
  matches the entry's command is stale.
- **Learned from:** every limit miss below came from a second copy of a fact (hand-kept maps in the runners).
- **Check:** preflight C1 (missing, invalid or stale spec). `entry_spec.py --titan --check` for all entries.
- **Audit:** not applicable (specs start on 2026-10-09).

## C2. OpenCode's context never exceeds what the server serves

- **Rule:** OpenCode's `limit.context` comes from the spec's `served_context` minus the margin (C3), never from a
  hand-kept value.
- **Learned from:** Gemma 26B on vLLM (2026-10-09): the runners said 262,144, the server serves 73,728; vLLM refused
  every request past ~41.7k tokens and the agent quit within minutes (wb-, wt- and the first test 3 cases).
- **Check:** preflight C2 (also warns when `served_context` exceeds the model's `native_context`). Runners take limits
  from `entry_spec.py --limits`.
- **Signature:** `ContextOverflowError`, "maximum context length", "exceeds the available context size"; saved
  `oc/opencode.json` context above the served context.
- **Audit 2026-10-09:** SUSPECT: wt-gemma-4-26b-a4b-vllm, the superseded Gemma test 3 cases, wb-qwen3.8-27b-vllm-64k,
  wa-qwen3.8-27b-vllm-64k-pi-tb, wa-qwen3vl-8b, wa-bonsai2-27b-pq2, wa-flashnext. AFFECTED-PASS (overflowed, recovered):
  wa-/wb-qwen3.8-27b-vllm, wa-qwen3.8-27b-vllm-quote, wb-gemma-4-26b-a4b-vllm, wb-qwen3.8-27b-uncensored-vllm-tb,
  wb-qwen3.8-27b-vllm-240k. Outcome: the Gemma redo (2026-10-09) replaces the Gemma cases; the others wait for the
  operator.

## C3. The margin covers a full reply plus one large tool result

- **Rule:** `served - context >= min(max(reply, 16384) + served/10, max(28672, served/10))` (since 2026-10-14; before, `max(reply, 16384) + served/10`; engines/ENTRY-SPEC.md).
- **Learned from:** wb-qwen3.8-27b-vllm-64k (margin 6,554 under a 14,745 reply) and wa-qwen3.8-27b-vllm-quote (5,735
  under 12,902) overflowed after one large tool result, with the old 10% margin. The daily-driver configs on Saturn
  still use it.
- **Check:** preflight C3; `preflight.py --harness` for the OpenCode and Pi daily-driver configs.
- **Signature:** as C2, plus a saved margin below the saved reply limit (INFO when nothing overflowed).

## C4. The thinking budget stays below the reply limit

- **Rule:** the per-request thinking cap and any server-side `--reasoning-budget` must leave room to answer inside the
  reply limit (`thinking = min(24000, reply - 6000)`).
- **Learned from:** uncapped Qwen3.8 spent all 20,000 tokens thinking and wrote nothing (story test, 2026-10-08);
  32k thinking loops in early vLLM runs (2026-10-03).
- **Check:** preflight C4.
- **Signature:** steps that stop on `length` (INFO), a Pi session that ends on `length`.

## C5. A case carries the settings its reference case passed with

- **Rule:** `-pp` (presence penalty 1.5), `-tb` (thinking budget) and `-nothink` change the run; a case built on a
  passing reference (a test-2 source, a rerun) carries the same suffix, or says `ignore=C5` with a reason.
- **Learned from:** test 3 wave 2 (2026-10-09) queued the uncensored Qwen vLLM without `-pp`, the only setting it
  passed with (test 1 failed without it).
- **Check:** preflight C5 (FAIL).
- **Signature:** a failed case of a model whose `-pp` sibling passed (INFO): wa-qwen3.8-27b-uncensored-vllm.

## C6. Test 3 needs an engine that serves several sessions at once

- **Rule:** test 3 runs a main agent and probe subagents concurrently; the entry must be `multi_agent_ok`.
- **Learned from:** the SGLang EXL3 build is single-session and crashed under several (2026-10-07); Strata needs a
  two-slot entry (`-p2`).
- **Check:** preflight C6.

## C7. The model's required template switches are on

- **Rule:** whatever the model record lists under `requires.chat_template_kwargs` must be in the entry's
  `templates.chat_template_kwargs`.
- **Learned from:** Gemma 4 without `enable_thinking` answers short and quits agent tasks early (2026-10).
- **Check:** preflight C7.

## C8. Experts on the CPU load eagerly

- **Rule:** any `-ncmoe` entry carries `-lm none` (TAKEOVER rule 3).
- **Learned from:** lazy mmap page-faulted ~90 GiB off NFS on the first request; the agent's 300 s stream timeout
  looped forever (wave A).
- **Check:** preflight C8 (`set_variant` also adds it to flagged rows).

## C9. KrakenViz gets its data from every engine

- **Rule:** llama.cpp entries run with `--metrics` and `LLAMA_SERVER_SLOTS_DEBUG=1`; vLLM entries with
  `--enable-prompt-tokens-details --enable-force-include-usage`. Strata, Maya and SGLang: to be established with
  KrakenViz (WARN until then).
- **Learned from:** KrakenViz's CACHED column read 0 on vLLM while the prefix cache hit 79% (2026-10-09).
- **Check:** preflight C9.

## C10. The weights are where the spec says

- **Rule:** `model_file` exists on titan; SSD copies follow rule 8a (stage, then delete or symlink).
- **Check:** preflight C10.

## C11. A test-3 own-server case has its source

- **Rule:** a t3o row's `mcp=<case>` exists in the live area or the archive (WARN when an earlier step of the same
  queue makes it).
- **Check:** preflight C11.

## C12. Container entries follow titan's entry checklist

- **Rule:** TAKEOVER rule 1: a fixed `--name`, cap-drop ALL, no-new-privileges, no `-p`, read-only model mounts, no
  `--env-file`, an image pinned by digest or ID.
- **Check:** preflight C12 (a lint of the command; limits never come from it).

## C13. The entry serves the model's recommended sampling

- **Rule:** an entry's `sampling` (plus what the client adds per request) matches the model record's
  `recommended_sampling`; on llama.cpp every recommended key is an explicit flag. Deviations need `ignore=C13` and a
  reason in the matrix note; `presence_penalty` (the `-pp` cases) only WARNs, since Qwen's card allows 0 to 2 against
  endless repetition.
- **Learned from:** bonsai2-27b-ada (2026-10-09) first ran without the model card's and the repo launcher's
  `--temp 1.0 --top-p 0.95 --top-k 20` and degenerated into "'entities', 'entities', ...". Operator: "we should follow
  the recommendations". Caveat: both llama.cpp builds on Saturn carry the GGUF `general.sampling.*` keys, so an entry
  without flags may already have run on the GGUF's defaults; not verified for llama.cpp 0.4 (native), prism or kolibri.
  A `/props` read of a loaded llama.cpp entry (`default_generation_settings`) would settle it.
- **Check:** preflight C13 (`entry_spec.sampling_check`).
- **Signature:** a case whose saved `entry-spec.json` (or, for older cases, today's spec with the case's flags) misses
  or contradicts the recommendation.
- **Audit 2026-10-09** (`tmp/audit-sampling-2026-10-09.tsv`, 172 cases): from saved specs: SUSPECT t3g-orcasaq2-cyber-27b
  (fail: facts-file shape after compactions; unlikely sampling-caused) and the superseded wa-bonsai2-27b-ada-nosampling
  run; AFFECTED-PASS t3g/t3o-cyber-tiel-coder-35b, t3g/t3o-qwen3.8-27b, t3g/t3o-tiel-coder-35b-q6, t3o-orcasaq2-cyber-27b.
  From today's spec (weaker, INFO): 72 rows; the only explicit conflict is glm-4.7-flash (`top_p` 1.0 against 0.95;
  OpenCode sends temperature 1.0 for that id, so its 0.7 never applied); the rest are unset keys on llama.cpp
  (Gemma, Bonsai, Nemotron, Nanbeige, Qwen3.6, Tiel, Swift15, OrcaSAQ, orcarouter, q38 MTP). Entries to change:
  `tmp/sampling-entry-changes-2026-10-09.tsv` (flags per entry), corrected spec copies in `engines/entry-specs/pending/`
  (moved into place only together with the yaml change).

## C14. OpenCode's loop guard is on in the harness

- **Rule:** the harness generators set OpenCode's `"doom_loop": "deny"`: three identical tool calls in a row are
  refused, which breaks a loop instead of burning the case. Headless `opencode run` approved the default `"ask"`.
- **Learned from:** t3g-q38-27b-cyber (2026-10-09): a probe subagent repeated `ha_list_entities {"limit":30}` 32 times
  ("Let me actually pass 300") until stopped by hand.
- **Check:** preflight C14 (both generators, `run-case-sandboxed.sh` and `tools/test3_config.py`); `--harness` shows
  the operator's own OpenCode setting and WARNs only on `allow` (interactively, `ask` is right).
- **Signature:** runs of 3+ identical consecutive tool calls (same tool, same input) per session, from
  `oc-data/opencode.db` (main and subagent sessions) or `events.jsonl`.
- **Audit 2026-10-09:** SUSPECT t3g-q38-27b-cyber (13 runs, longest 52), wb-q38-27b-cyber-mtp-default (18, longest 159:
  the same `read` of lib.rs), wb-q38-27b-cyber-mtp-long-loop (11, longest 69: the `Bobaerer` curl), wa-qwen3vl-8b
  (2, longest 47: the same `write`); AFFECTED-PASS wa-q38-27b-cyber (3, longest 718: `python3 /tmp/hammer.py`); INFO
  wa-jan-nano-128k (5, longest 8). Every looping case but two is Q38 Cyber (IQ4_XS); the guard applies from
  2026-10-09 on.

- **Limit found 2026-10-09 22:55:** the guard almost never fires in our runs. OpenCode (1.18.x, session processor)
  asks `doom_loop` only when the last three parts *of the current assistant message* are all identical tool calls,
  i.e. three identical calls inside one model turn. A loop of one call per turn (each turn adds step-start and
  reasoning parts) never trips it: wb-q38-27b-cyber-q5 ran the same sed-and-cargo command 100 times in a row, every
  call `completed`, with `doom_loop: deny` in its config. Keep the setting (it is harmless), but do not count on it.

## C15. A dense model stays on the GPU

- **Rule:** on llama.cpp, a dense model's weights (no `expert_count` in the model record, no `-ncmoe`) leave at least
  3 GiB of the 24 GiB RTX 3090 for the KV cache and buffers. Otherwise llama.cpp (`-ngl auto`, `--fit on`) quietly puts
  layers in RAM. Pick the largest quant that fits and size the context by a load test; state `-ngl 999 -fit off` so a
  miss fails loudly. MoE models are exempt (their experts are meant to go to RAM, C8).
- **Learned from:** lcpp6-q38-27b-cyber-q6 (2026-10-09): the author's Q6_K (23.7 GB) ran test 1 at 4.5 tok/s against
  35 for its Q5_K_M; the operator aborted it ("That's too slow"), and the Q8_0 (28.6 GB) was dropped unrun.
- **Check:** preflight C15 (`entry_spec.gpu_fit_check`, from the model record's weight sizes).
- **Signature:** the same rule on a case's saved `entry-spec.json` (or today's spec with the case's flags).
- **Audit 2026-10-09** (`tmp/audit-2026-10-09.tsv`, 175 cases): SUSPECT only the aborted
  wa-q38-27b-cyber-q6-spilled-aborted; no earlier result is affected.

## C16. The agent image carries the tools OpenCode shells out to

- **Rule:** `rg` (ripgrep) is on the PATH of `localhost/bakeoff-agent`, so the glob and grep tools of OpenCode work in a case. Without it OpenCode unpacks its own ripgrep with tar, and tar fails inside the case container (root in the user namespace, no CAP_CHOWN): the tool returns tar errors instead of results.
- **Learned from:** wb-retry-devstral-q5 and wb-retry-qwen36-q6 (2026-10-11): every glob and grep call returned "tar: ... Cannot change ownership to uid 1001, gid 1001: Operation not permitted"; Devstral listed it as a blocker in its compaction summary.
- **Fixed 2026-10-11:** Containerfile.agent installs ripgrep in a late layer; image 75048c44a8a8, the earlier image kept as `localhost/bakeoff-agent:pre-rg-20261011`. Operator: add it from now on, rerun nothing. First wave on it: the Tiel Coder focus wave.
- **Check:** NOT ADDED YET. Planned: preflight (harness part) runs `command -v rg` in the agent image as the case runs it.
- **Signature:** NOT ADDED YET to tools/audit_runs.py. In a finished case: a `glob` or `grep` tool_use in events.jsonl whose error text contains "Cannot change ownership to uid".
- **Audit 2026-10-11 (by grep, not audit_runs.py):** 57 of 181 cases in results-wave-a, results-wave-b and results-test3 carry the signature, from 2026-10-01 on, the reference runs included. Not scanned: older result sets and superseded folders. Not decided: rerun or mark (report/open-decisions.tsv). The image is unchanged; change it only between waves.

## Daily-driver configs

`preflight.py --harness` checks the operator's OpenCode (`~/.config/opencode/opencode.json`) and Pi
(`~/.pi/agent/models.json`) configs against the same specs and prints corrected values. It never edits them.
