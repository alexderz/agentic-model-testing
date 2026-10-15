# Qwen3.8-27B: vLLM (HyperQwen) against llama.cpp

Same model, same tasks, one RTX 3090. Test 1: Python Home Assistant CLI.
Test 2: Rust MCP server for Home Assistant. One run each unless noted; a
one-check difference is noise.

| engine / profile | context | test 1 | test 2 | speed over the run | wall |
|---|---|---|---|---|---|
| llama.cpp (UD-Q4_K_M, q8_0 KV) | 131k / 213k | 5/5, 55 tests, 8 subcmds | full pass, 8 tools, 59 tests | 33 / 17.5 tok/s | 25 / 82 min |
| **vLLM profile D** (MTP, FP8 KV) | 150k | **5/5, 89 tests, 13 subcmds** | **full pass, 5 tools, 67 tests** | **70.5 / 69.5 tok/s** | 27 / **39 min** |
| vLLM profile E (DFlash2, KVarN 4/2-bit KV) | 240k | 5/5, 80 tests, 8 subcmds | full pass, 6 tools, 44 tests | 56.5 / 30 tok/s | 23 / 75 min |

Uncensored checkpoint on profile D (philbert440 AWQ, prepared by HyperQwen's
own pipeline): test 2 full pass, 7 tools, 41 tests, 61 tok/s, 60 min. Its
test 1 ran away (a 32k-token think, no files) before the thinking budget.

## Readings

- **Profile D is the setup to use.** As correct as llama.cpp, 2-4x faster over
  whole agent runs, and the second question over a 124k-token prompt starts in
  2.5 s instead of 160 s (prefix cache). MTP drafting accepts ~3 tokens/step.
- **Profile E keeps quality at 240k** (no failed check across two tests) but
  is slower under load: 30 tok/s on test 2 against 70 for D. Use it only when
  a job truly needs more than ~150k.
- **Context overflow is a client problem, not vLLM's.** OpenCode compacts from
  the previous turn's usage; two of three E attempts died at the same
  213,761-token prompt + 32k reply > 245,760. The harness now tells OpenCode
  10% less than the real window.
- **Thinking budget:** `--reasoning-config` + `thinking_token_budget` is live on
  all vLLM entries since 2026-10-04 13:26 (24k inside a 32k reply cap); the
  64-token smoke test was enforced on all four entries.

## Settings that matter (all set in the llama-swap entries)

- D: `SPEC=mtp CTX=long PREFIX_CACHE=1`; E: `SPEC=dflash2 CTX=huge`.
- `--reasoning-config` with `<think>` / `</think>` via `EXTRA_ARGS`
  (whitespace-free JSON: the launcher word-splits it).
- Sampling from the model's generation_config (1.0 / 20 / 0.95, min_p 0).
- Cold start ~240 s, warm ~40 s with the compile cache in `~/ai/hyperqwen/cache`.

## Small, fast profiles B and C (2026-10-05/06)

Same checkpoint, DFlash2 drafting and FP8 KV, but a small window to fit faster drafts.
Below the 100k floor on purpose: does the speed survive the agent compacting more often?

| profile | context | test 1 (OpenCode) | test 2 (OpenCode) | test 1 (Pi agent) |
|---|---|---|---|---|
| D (reference) | 150k | 5/5, 89 tests, 13 subcmds, 70.5 tok/s, 27 min | full pass, 5 tools, 67 tests, 69.5 tok/s, 39 min | — |
| **B** (`-64k`, DFlash2 fast) | 65,536 | 5/5, 78 tests, 11 subcmds, **97 tok/s, 15 min**, 3 compactions | **failed**: context overflow 11 min in (50,792 + 14,745 > 65,536), no project | harness failures: first a think filled the reply cap (no budget sent), then an overflow (53,249 + 12,288 > 65,536) |
| **C** (`-quote`, 15-token drafts) | 57,344 | 5/5 but 1 test, 10 subcmds, **166 min, 55 compactions** | **full pass, 6 tools, 39 tests, 95 tok/s, 59 min, 17 compactions** | **4/5, 84 tests, 7 subcmds, 49 min, 8 compactions** |

Readings (n=1 each):

- **Decode is 35-40% faster than D**, but OpenCode at ~57-64k spends it on compacting: each
  compaction rewrites and re-reads the conversation (47-84 s each on B). C's test 1 compacted 55
  times and took 6x as long as D.
- **Each profile failed one OpenCode test, in different ways** (B: overflow; C: a compaction loop
  that produced almost no tests). Not a setup for long agent work.
- **Pi copes better with a small window**: on C it compacted 8 times instead of 55 and finished in
  49 min with 84 passing tests. Two harness fixes were needed first: Pi sends no thinking budget
  unless the model is marked `reasoning` with `supportsThinkingTokenBudget` and run at
  `--thinking high`, and Pi must be told the margined window, not the full one.
- Verdict: **D stays the default**. B/C are for short, bounded jobs, preferably with Pi.
