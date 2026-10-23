# History

The tests changed as we learned. Most changes came from a failure that
turned out to be the harness, not the model. This page lists each change
and the reason for it.

| Date | Change | Why |
| --- | --- | --- |
| 2026-09-23 | **Round 1.** One prompt (a Python CLI for the Home Assistant API), the Pi agent, llama.cpp only, 17 setups. Scored by API endpoints touched and whether the code compiled. | A first look at which local models write working code at all. |
| 2026-09-27 | **Tests 2, 3A, and 3B.** OpenCode in a container against a recorded Home Assistant. Test 2 builds a Rust MCP server; test 3A and 3B describe the house through your own server or someone else's. | Separate building a tool from using one. |
| 2026-09-29 | **Uncensored cohort.** Three uncensored Flash-Next variants and the stock model through the MCP test. | Security testing of our own software needs models that don't refuse. |
| 2026-09-30 | **Harness fixes.** Experts offloaded to RAM were memory-mapped and page-faulted off the network during the first request, so offloaded models produced no output. Fixed with eager loading (`-lm none`); also a 3-hour case cap, longer client timeouts, and guaranteed result records. | Several early failures were the harness. |
| 2026-10-01 | **Wave A.** Test 1 graded by running the tool (five checks plus the model's own tests). Context and offload tuned per model with real loads. | Counting endpoints in the source credited help text and invented APIs. |
| 2026-10-03 | **Wave B.** Test 2 graded by driving the server as a real MCP client; every failure verified by hand. | Test 1 no longer separated the models. |
| 2026-10-04 | **Client settings.** Context margin of `max(10%, 16k)` and a thinking budget on every engine. | Runs died on context overflow, and on single thinks that used the whole reply. |
| 2026-10-04 | **New engines.** vLLM for the dense 27B; SGLang and Strata for Flash-Next. | The same weights ran 2-5x faster on a better-suited engine. |
| 2026-10-05 | **llama.cpp 0.6, long-horizon runs, small-window setups.** An A/B of llama.cpp 0.6 against 0.4; 8-hour runs with Qwen's long-horizon sampling; 57-64k vLLM setups with OpenCode and Pi. | llama.cpp 0.6 is 2.5-4x faster on Flash-Next; the uncensored Flash-Next finished test 2 for the first time. |
| 2026-10-06 | **Uncensored round.** A new uncensored 27B, and 8-hour test-2 runs for the slower uncensored Flash-Next variants. | Find the smartest uncensored model, not only the fastest. |
| 2026-10-07 | **Test 3.** The agent uses an MCP server through a subagent, checks 14 facts against the REST API and fixes the server if it is wrong. | Tests 1 and 2 cannot see how well a model briefs and checks a subagent. |
| 2026-10-08 | **GLM-5.3-Flash on Maya.** Three engine patches lifted decode from 4 to 17-19 tok/s; tests 1 and 2 passed. | Can a 320B model work on one card? |
| 2026-10-09 | **Maker sampling and a loop guard.** Every entry serves its maker's sampling and the agent denies repeated identical calls. | Loops had ruined several runs. |
| 2026-10-10 | **Grader audit.** All 125 archived test-1 and test-2 runs were regraded after grader fixes; four test-1 verdicts changed. | Old and new scores must compare. |
| 2026-10-11 | **Test 4, test 5 and Strata's PCIe share.** Tiel Coder fixed 9 of 9 tickets; the one-shot orrery test was added; the old PCIe share doubled Flash-Next decode on Strata 0.1.42. File search tools were fixed in the sandbox. | Tests 1 and 2 never touch existing code; a default had halved speed. |
| 2026-10-13 | **Engine shoot-out on Qwen3.8-27B.** TensorFold, ExLlamaV3 and llama.cpp compared with and without drafting. | Pick the fastest stack for the daily model. |
| 2026-10-14 | **Tests 6, 7 and 8.** One-shot voxel pagoda, a seeded labyrinth generator, and the pagoda and orrery as agent tasks. The agent window margin changed: a 150k server now compacts at 89,328 tokens instead of 71,000. | Measure design work, not only code; fewer compactions. |
| 2026-10-15 | **LFM2.5 and Saluki tested; shell timeout 9 minutes.** Five LFM2.5-24B quants and a 2-bit Qwen3.8-27B tune went through tests 1 and 2. Every test gives a shell command 9 minutes instead of 30. | Check small and very low-bit models; a dead shell stalled cases. |
| 2026-10-16 | **Engine re-measures.** Strata 0.1.44.1 (decode 44.9 against 18.3, means of two rounds each), Maya 1.1.11 (17.0 against 14.6, split digits fixed) and exllamav3 1.6.2 (140.1 against 138.6). | Re-measure each engine before changing defaults. |
| 2026-10-17 | **First graded test 8 batches.** Six models that drew blank one-shot pagodas scored 7 to 10 as agents. | Show what tools and a browser add. |
| 2026-10-18 | **llama.cpp 0.7.0** replaced 0.4 and 0.6 for every llama.cpp entry; 0.7.0 adds a GPU cache for experts. | Big mixture models need that cache. |
| 2026-10-20 | **Gyro-S on Strata 0.2.** A 1-bit-class Flash-Next quant with an MTP draft decoded 119 tok/s and passed test 2 in 24 minutes; Ornith-1.5-122B tuned to 16 tok/s. | Long agent runs at 20 tok/s are too slow. |
| 2026-10-21 | **Stock SGLang for Flash-Next.** Three stock builds served 11 of 11 multi-session checks at about 25 tok/s. | Flash-Next without a custom fork. |
| 2026-10-22 | **Expert cache live; Strata 0.2.2; tqLLM and Carbon-X tried.** All 12 Flash-Next llama.cpp entries moved to `-cmoe` plus a GPU expert cache with 8-bit KV (streamed decode 12-14 → 18-26). Strata 0.2.2 is about 17 % faster than 0.2.0. Flint fits the card (129 tok/s). tqLLM decodes fast but fails several sessions. | Make the 125B model usable on one card. |
