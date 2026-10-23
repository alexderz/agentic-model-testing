# Conclusions

This page gives the current picks and the rules that decide them. It
changes as results come in; for dated changes, see the
[Research log](log.md). The reasoning and evidence behind the settings is in
[Tuning](tuning.md); the engines are in [Engines](engines.md).

"Competent" means the model passed test 2: it built an MCP server that a
real client could connect to and call. "Smartest" weighs how much working
server and how many passing tests it produced. For how the tests work, see
[Method](method.md).

## Picks

| Role | Model and setup | Why |
| --- | --- | --- |
| Smartest | [Qwen3.8-Flash-Next](models/qwen3.8-flash-next.md) on SGLang, EXL3 3-bit, GPU expert cache | The best test-2 server of all runs: 12 tools, 155 tests, 124 minutes at 36 tok/s. That run used the older SGLang build, which served one session at a time. The stock builds serve 11 of 11 multi-session checks at about 25 tok/s (2026-10-21); no agent test has been rerun on them. |
| Fastest competent | [Qwen3.8-27B](models/qwen3.8-27b.md) on vLLM, MTP drafts, 150k context | Full passes on both tests at about 70 tok/s; test 2 in 39 minutes. The default agent model. |
| Smartest, uncensored | [Orcarouter Flash-Next Uncensored](models/orcarouter-flash-next-uncensored.md) on llama.cpp, experts in RAM, 262k context | Test-2 full pass with long-horizon settings: 8 tools, 54 tests, and the fewest compiler errors of the big uncensored runs, but slow (191 minutes, 7.6 tok/s on llama.cpp 0.6). Since 2026-10-22 it runs on 0.7.0 with the expert cache at about 19 tok/s streamed (was 12-14); that configuration has not been through tests 1 and 2. [Flash-Next Heretic2](models/flash-next-heretic2.md) was twice as fast on 0.6 with a thinner result (7 tools, 33 tests in 120 minutes) and now streams about 18 tok/s. |
| Fastest competent, uncensored | [Qwen3.8-27B Uncensored](models/qwen3.8-27b-uncensored-aggressive.md) on vLLM, MTP drafts, 150k context | Two test-2 full passes and 5/5 on test 1 at 61-68 tok/s. Run it with the thinking budget. |

[OrcaSAQ-2-Cyber-27B](models/orcasaq-2-cyber-27b.md) is faster than the
uncensored pick (77-86 tok/s with a draft model) but less consistent: one of
its two test-2 runs shipped a broken HTTP client.
[ThinkingCap-27B Heretic](models/thinkingcap-27b-heretic.md) built the most
complete uncensored 27B server so far (8 tools, 56 tests, 52 minutes) at
25-31 tok/s on llama.cpp: pick it when completeness matters more than speed.

[Tiel Coder 35B](models/tiel-coder-35b.md) at Q4_K_XL is a candidate for
fastest competent: with the author's coding sampling (temperature 0.6) it
passed test 1 in 24 minutes and test 2 in 27 minutes (5 tools, 22 tests) at
77-79 tok/s. That is one run each, with fewer tests than Qwen3.8-27B wrote,
so it has not replaced the pick.

**Candidate, not a pick:** [Gyro-S + MTP](models/gyro-s-flash-next.md) on Strata 0.2.0-beta
(Flash-Next in a 1-bit-class quant) decodes 119 tok/s on code, passed test 2 in
full in 24 minutes (6 tools, 108 tests) and scored 9 of 10 as an agent pagoda.
Strata 0.2.2 raised decode to 144 tok/s on code in a same-day control. It is one
run on a beta engine, so Qwen3.8-27B on vLLM stays the fastest competent pick
until a repeat and a test 1 run support it.

The picks above rest on graded test 1 and 2 runs. The new llama.cpp 0.7.0
configurations and the Strata 0.2.2 build have not been through them; their
speeds are in the tradeoff text and in [Engines](engines.md), not in the picks.

**Test 8 (agent pagoda and orrery).** Six models whose one-shot pagoda was blank
scored 7 to 10 as agents with a sealed browser (mean 8.3 of 10, 2026-10-17):
Coder 390 10, ThinkingCap 9, Orcarouter 9, Abliterated s1.5 8, Cyber 7, Cyber
Q5 7. Orrery results are mixed, 0 to 10; Qwen3.8-27B Uncensored and Orcarouter
scored 10. See [Method](method.md) and the model cards.

## By family

| Family | Smartest | Fastest competent | Notes |
| --- | --- | --- | --- |
| Qwen3.8 27B | vLLM, MTP drafts, 150k | the same | llama.cpp on the same weights scored the same and ran 2-4x slower. |
| Qwen3.8 Flash-Next | SGLang, EXL3 3-bit | Swift 1.5 (pruned) on Strata; Gyro-S + MTP on Strata 0.2 is a candidate | Uncensored: Orcarouter on llama.cpp, or Heretic2 for more speed. Only llama.cpp runs the uncensored variants; 0.6 is 2.5-4x faster than 0.4 on them, and 0.7.0 with the expert cache adds about 1.5x (streamed 18-26 tok/s on the five live GGUFs). Strata 0.1.42 passes both tests; see [Engines](engines.md) for the setting it needs. |
| Tiel Coder 35B | Cyber-Tiel-Coder 6-bit | Tiel-Coder Q4_K_XL, 6 expert layers in RAM (77-79 tok/s on both tests) | Run it at temperature 0.6. At that setting both 4-bit builds pass test 2; an earlier 4-bit run with other sampling called an invented endpoint. All on GPU, the IQ4_XS build reaches 99-101 tok/s on test 1. |
| Gemma 4 | 31B | 26B-A4B on vLLM | Fast but thin: 3 tools on test 2. |
| Qwen3.6 | 27B | none passed test 2 | Superseded by Qwen3.8. |
| Kolibri | Kolibri-1 | none passed test 2 | Thin on both tests. |
| GLM, Nemotron, others | none | none | GLM-5.3-Flash passes both tests on Maya, at about 14 tok/s over a run (17 in a short probe on Maya 1.1.11). LFM2.5-24B decodes at 125-176 tok/s but passed test 1 in three of five quants and no test 2 (the handshake fails in all five). Underdog Saluki, a 2-bit Qwen3.8-27B tune (7.9 GB), passed test 1 (72 tests, 25.3 tok/s) and part-passed test 2 (47 tests, 166 minutes). GLM-4.7-Flash, Devstral Small 2 and Qwen3.6-35B fail the test-2 handshake even with their makers' sampling. See their cards. |

## Rules we learned

1. **Speed is set by how much of the model sits in VRAM.** Models that fit
   the GPU ran at 25-150 tok/s; models with experts in system RAM ran at
   3-25 tok/s, whatever their size. Pick a tier first, then a model.
2. **The engine matters as much as the model.** The same weights ran 2-5x
   faster on a better-suited engine. See [Engines](engines.md). A fast engine
   is not an agent engine until it passes a multi-session probe: tqLLM decodes
   about 2.5x faster than llama.cpp on the same Flash-Next GGUF and passed 3 of
   11 checks.
3. **Offloaded experts must load eagerly** (`-lm none` on 0.6), or the first
   request stalls on page faults.
4. **Speculative decoding pays only when the model is GPU-resident.**
5. **Give the agent a context margin and a thinking budget.** Without them,
   runs die on context overflow or on a single think that uses the whole
   reply.
6. **Small context windows cost more than they save.** At 57-64k the agent
   compacts constantly; 150k with OpenCode is the working minimum. The Pi
   agent copes better with a small window.
7. **Runs vary a lot.** The same model and settings can pass and fail on
   different runs. Treat one result as a sample. Speed varies too: a cold
   first request read a prompt at 44 tok/s that the warm engine read at
   1,269, so warm up and measure twice before ranking settings.
8. **Serve the maker's recommended sampling.** Tiel Coder's test-2 server
   stopped calling an invented endpoint at its author's temperature 0.6
   (its test-1 tools still invent a few), and Ternary Bonsai
   degenerated into repeated tokens without its card's settings. Coding
   agents often send no sampling at all, so set it on the server. It is not
   a cure-all: three models still failed the test-2 handshake with it.
9. **Tell the agent the context the server really serves.** Gemma on vLLM
   was given a 262k limit for a server with 73k and quit within minutes;
   those earlier results were our error, and with the right limit it passes.
10. **Turn on the agent's loop guard, and do not rely on it alone.**
    OpenCode asks before repeating an identical call, and a headless run
    approves that silently; set `doom_loop` to deny. Qwen3.8-27B Cyber still
    looped by varying its calls slightly. A thinking budget stops runaway
    thinking, not output loops.
11. **Keep all experts in RAM and give the GPU a cache of the hot ones.** On
    llama.cpp 0.7.0, `-cmoe --moe-cache-mib N` with 8-bit KV beat the old
    layer split (`-ncmoe 38-40`, f16 KV) on every Flash-Next GGUF at 262k
    context (2026-10-22): streamed decode went from 12-14 to about 19 for
    Orcarouter, from 11-14 to about 18 for Heretic2 and from 13-17 to 23-26 for
    Swift 1.5, and prefill on fresh loads rose from about 250 to about 415
    tok/s. Mean KL against the f16 config was 0.0011 and all needles were found.
    Size the cache to what is left in VRAM after the vision head and the slots
    (12800 MiB for Orcarouter and Heretic2, 13824 Abliterated s1.5, 9216 for
    Swift and the unpruned GGUF). Not yet through tests 1 and 2. See
    [Tuning](tuning.md).
12. **A blank one-shot page does not predict the agent.** Six models that drew
    blank pagodas in one shot scored 7 to 10 once they could write, run and look
    at the page (test 8). Judge design work with the agent test.
13. **Measure the speed you will use.** A raw benchmark of short outputs with
    thinking off reads high (about 40 tok/s on the unpruned Flash-Next GGUF
    against 21-23 streamed). Report the streamed figure, and run the
    multi-session probe before you call an engine fast.
