# Research log

Dated findings and decisions, newest first. Results also land in the model
cards; this log keeps the reasoning.

## 2026-10-22

- Expert cache is live. llama.cpp 0.7.0 with all experts in RAM (`-cmoe`), a GPU cache of hot experts (`--moe-cache-mib N`) and 8-bit KV replaced the 38-40 layer split on all 12 Flash-Next entries at 262k. Streamed decode with thinking: Orcarouter about 19 tok/s (was 12-14), Heretic2 about 18, Abliterated s1.5 19-21, Swift 1.5 23-26, unpruned 21-23. Raw decode on short outputs is higher (about 40 on the unpruned GGUF with thinking off). Prefill on fresh loads: 415-427 tok/s against 250 (three reproductions). Cache sizes: 12800 MiB (Orcarouter, Heretic2), 13824 (Abliterated s1.5), 9216 (Swift, unpruned); 13312 ran out of memory for Orcarouter with vision and four slots. Mean KL against the f16-KV config 0.0011, top-1 98.2 %, needles 8 of 8 in both; a second load differs by 0.0002. f16 KV with the new flags does not fit at any cache size. Needles at 100k, 190k and 250k, and 11 of 11 multi-session checks. These entries have not been through tests 1 and 2, so the picks do not change. See [Tuning](tuning.md).
- Strata 0.2.2 against 0.2.0-beta on the Gyro-S + MTP build, same day, one load each: code 121.6 → 144.1 tok/s, prose 106.4 → 123.4, JSON 135.2 → 157.7. Tool call and needles at 16k and 64k pass on both. No agent run on 0.2.2 yet.
- [Flint 40B-A2.5B](models/flint-40b-a2.5b.md) (Apache-2.0, a coding MoE with 2.5B active) fits the card: Q3_K_XL entirely on the GPU at 262k with 8-bit KV decodes 129 tok/s and reads an 11.7k prompt at 5,357 tok/s; Q4_K_XL with 10 to 24 expert layers in RAM decodes 95 to 64. Needs llama.cpp b11803 or newer. Not graded; the one-shots ran at about 100-110 tok/s and are ungraded.
- tqLLM 1.2.3 tried on the Flash-Next IQ3_S GGUF: 101.7 tok/s on code at a 32k window against 40.3 on llama.cpp with the same file, but the first prompt of 256 or more tokens that runs short of VRAM leaves every later request failing until a restart, and the multi-session probe passed 4 of 11 checks at best (llama.cpp 11 of 11). Not usable for agents. See [Engines](engines.md).
- [Carbon-X](models/carbon-x.md) (14.8B DNA language model, Q8_0, 40k context) tried on llama.cpp: 52 tok/s, tool call OK, needle missed at 36.7k, and on the card's sickle-cell DNA example it said "pathogenic" with the wrong reason. One-shots ran and are ungraded. A trial, not a pick.

## 2026-10-21

- Stock SGLang now serves Flash-Next to several sessions. Three stock builds (EXL3 3-bit, 204,800 context, two slots, images) passed 11 of 11 multi-session checks at 24.1, 24.6 and 25.1 tok/s decode. Two of them also passed needles at 100k, 150k and 190k, with prefill about 2,600 tok/s at 190k and a repeated 190k prompt answered in 0.5 s; the third (8-bit KV, 20.8 GB) did not run the needle test. The earlier statement that SGLang serves one session at a time applies to the original fork build only. The phased fork build was dropped.
- Flint and its Unsloth GGUFs were downloaded (Q3_K_XL 18 GB, Q4_K_XL 24 GB).

## 2026-10-20

- Gyro-S + MTP on Strata 0.2.0-beta: Flash-Next in a 1-bit-class quant (see [the card](models/gyro-s-flash-next.md)) decoded 118.6 tok/s on code against 35.4 for the IQ3_S quant with MTP on the same engine (29.4 on Strata 0.1.45). It passed test 2 in full in 24 minutes (6 tools, 108 tests, none failing, 89.8 tok/s over the run) and scored 9 of 10 as an agent pagoda in 16 minutes. The tool call and needles at 16k and 64k passed. Without an MTP draft the Gyro build does not start. One run on a beta engine, so it is a candidate for the fastest competent pick, not the pick.
- [Ornith-1.5-122B](models/ornith-1.5-122b.md) (a 122B Qwen3.5 mixture) tuned on llama.cpp 0.7.0 at 262k: 13.7 tok/s with 42 expert layers on the CPU, 16.0 with 41, 16.3 with 40; MTP with two drafts at 44 layers 16.7; larger batches lifted prefill from 116 to 392 tok/s at 41 layers. Not graded; one-shots ran at about 15 tok/s.

## 2026-10-18

- llama.cpp 0.7.0 replaced 0.4 and 0.6 for every llama.cpp entry in the router. Checks on representative entries passed (Tiel Coder 151 tok/s decode, Gemma 4 26B with its MTP draft, Qwen3.8-27B Cyber, Orcarouter). OrcaSAQ-2 with DFlash2 drafts loaded but failed every request on a 580 MiB compute buffer at 22.7 of 24 GiB; `-ub 256` fixed it. The first Qwen3.8-27B Cyber test-8 pagoda run on 0.7.0 produced 32,000-token replies with no text or tool call from step 33; we stopped it, did not grade it and suspect a regression for that model (one run).
- TensorFold's upstream 1.1.0 reports native support for RTX 30 cards, with receipts of its own for a 3090. We have not built or run it.
- Newer builds of Strata (0.1.45), Maya (1.1.15), exllamav3 (1.6.3) and vLLM (0.32) were built and staged; none is in use.

## 2026-10-17

- First graded test 8 batches. Six models whose one-shot pagoda was blank scored 7 to 10 as agents: Coder 390 10, ThinkingCap 9, Orcarouter 9, Abliterated s1.5 8, Cyber 7, Cyber Q5 7 (mean 8.3, against 0 one-shot). Other pagodas: Qwen3.8-27B Uncensored 10, OrcaSAQ-2 9, Cyber-Tiel 8, Heretic2 7, Tiel Coder 6. Orreries are mixed: Qwen3.8-27B Uncensored and Orcarouter 10, OrcaSAQ-2 and ThinkingCap 8, Cyber-Tiel 8, Heretic2 7, Coder 390 5, Abliterated s1.5 3, Cyber Q5 0 (stopped at the cap with an empty file). One agent run per model. Files, frames and grades are in the repository (`oneshots/`).
- The larger Maya-M IQ2_S pack of GLM-5.3-Flash on Maya 1.1.13: 12 of 12 digit strings and both needles; test 3 rubric 12 of 12 on both flavors. The split-digit fault was the engine, not the weights. A PCIe share of 0.25 against the default 0.36 gave about 12 % more decode (a candidate, not applied); a DFlash2 draft head made decode slower (10.7 against 15.35 tok/s).

## 2026-10-16

- Maya 1.1.11 against 1.0.4 on the same GLM-5.3-Flash pack, two rounds each: decode 17.0 against 14.6 tok/s, first token 18 s against 92 s, 12 of 12 digit strings copied exactly against 9, both needles found against one. Maya-S and Maya-M on 1.1.13 also scored 12 of 12.
- exllamav3 1.6.2 against 1.6.1, DFlash2 build of Qwen3.8-27B: 140.1 against 138.6 tok/s, within noise; the needle 48213-KESTREL found at 128k, 112k and 94k windows.
- TensorFold 1.0.12 still has no RTX 30 path upstream; the Python 0.6.6 line stays parked.

## 2026-10-15

- [LFM2.5-24B-A2B](models/lfm2.5-24b-a2b.md) test 2 on five quants (Q4_K_M, Q6_K and the unsloth UD-Q4_K_XL, UD-Q5_K_XL, UD-Q6_K_XL): none passed. The servers answered `initialize` with -32601, read all of stdin before replying, or glued the next request to the last; 0 to 3 tools. Test 1 passed on the three UD quants (12, 18 and 6 tests at 125-150 tok/s). Status changed to Dropped.
- [Underdog Saluki 27B](models/saluki-27b.md), a 2-bit Qwen3.8-27B tune (7.9 GB): test 1 5/5 with 72 tests in 63 minutes at 25.3 tok/s; test 2 partial (17 tools, 47 tests passing, 166 minutes at 22.0 tok/s, `list_entities` called the invented `/api/entities`).
- Strata 0.1.44.1 against 0.1.42 on Flash-Next, two rounds each: load 60 s against 214 s and decode 44.9 against 18.3 tok/s (means of two rounds each). The first 0.1.42 round was cold at 13.1 tok/s and the second warm at 23.5, so against the warm round the gain is about 1.9x.
- Vision: 15 of 15 vision setups answered the red-and-blue test image, so the cards now list them as configured.
- Shell commands in tests 1 to 4 now time out after 9 minutes instead of 30 (tests 7 and 8 already did), because a tool call whose shell had died stalled the agent until the timeout and the case looked hung. A cargo build longer than 9 minutes is cut unless the agent asks for a longer timeout on that call.

## 2026-10-14

- [LFM2.5-24B-A2B](models/lfm2.5-24b-a2b.md) was already on disk (Q4_K_M 13.53 GiB and Q6_K 18.34 GiB; both fit a 24 GB card). Test 1 on llama.cpp 0.6 is partial, 4 of 5, at 157.6 tok/s for Q4_K_M, and a fail, 2 of 5, at 176.2 tok/s for Q6_K. Test 2 followed on 2026-10-15 (below).
- [ScaleDown constrained decoding models](models/scaledown-cdm.md) are a hosted API. No public weights and no release date, so nothing was downloaded.
- DigUp is a macOS app that runs EmbeddingGemma 2. That model still needs a llama.cpp newer than v0.6.0, so nothing new was downloaded.

- Test 6 added: a one-shot voxel pagoda in three.js, no agent, graded from offline renders (see method). It
  separates the fast long-context setups that all passed the speed bar: Tiel-Coder-35B-A3B wrote the best scenes
  (three pages at 10 of 10 and one at 8 in eight samples) but fails all-or-nothing (four zeros); Gemma-4-26B-A4B answers in about 27 seconds with plainer
  pages (7 and 9, one script error).
- Qwen3.8-27B on vLLM with thinking on has not finished a page in seven tries (one at the 32k cap, one with a 64k cap, five with a
  24,000-token thinking budget): it plans the whole scene while thinking. On ExLlamaV3, whose setups cap thinking, the same model drew four pages of six (7, 9, 9, 10). With
  DFlash2 drafting it drew all three, one of them at 10 of 10. Both ExLlamaV3 setups stay: MTP at 196k, DFlash2 at 98k.
- Tiel-Coder-35B-A3B (llama.cpp 0.6, 262k) and Gemma-4-26B-A4B (on trial) joined the daily drivers.
- TensorFold: the Python engine (0.6.x) is frozen upstream and the native engine does not yet run Qwen3.8-27B on
  the RTX 30 series. Parked; TensorFold was 7-17 % faster than the ExLlamaV3 DFlash2 setup
  side by side on this card.

- Test 7 added: each model writes a seeded generator for a three-floor labyrinth that must pass a ten-rule checker on seeds it has not seen. Test 8 added: the pagoda and the orrery as agent tasks with a sealed browser and sub-agents (see [Method](method.md)).
- Agent window margin changed. The limit had counted the 32k reply twice, so a 150k server compacted at 71,000 tokens (47 %); it now compacts at 89,328 (60 %), and a 262k server at 201k instead of 172k. Runs from now on use the new window; earlier runs, test 2 included, used the old one.
- Night search for speed at 141k of history, code prompts: Gemma-4-26B-A4B with an MTP draft 266.9 tok/s short and 123.1 deep, Tiel Coder IQ4_XS 148.8 and 98.0, Qwen3.8-27B on vLLM 126.9 and 85.0, Qwen3.8-27B on exllamav3 with MTP 115.2 and 71.7. All four found the needle at 141k. Prefill at that depth: 2,094, 2,046, 739 and about 650 tok/s.
- HyperQwen vLLM 0.31 matched 0.30 on short tasks (code about 124 against 126 tok/s, prose 93 against 91) and was a little slower deep (79.5 against 84.5). The 141k needle passed on both.

## 2026-10-13

- MiniCPM-V 4.7 (OpenBMB, Apache-2.0), released 2026-10-12: a 1.55B dense vision-language model and a 35.3B MoE (8 of 256 experts). Official GGUF is public and not gated. The 1B Q8_0 file is 1.01 GiB plus a 1.03 GiB projector and fits a 24 GB card. The 35B Q4_K_M file is 19.71 GiB plus a 1.04 GiB projector (20.8 GiB), so only a short context fits on the card; Q8_0 is 34.37 GiB and fits with experts in RAM.
- Not downloaded. The language files are qwen35 and qwen35moe, which llama.cpp 0.6 already loads, but vision projector type minicpmv4_7 was added on 2026-10-10 (PR 29416), after the v0.6.0 image (build 11429, 2026-10-05). Current llama.cpp master has it; today's release tag is b11588.

- Engine shoot-out on Qwen3.8-27B, short prompts, thinking off, temperature 0 (code tok/s): plain llama.cpp 42; llama.cpp with MTP 93; ExLlamaV3 1.6.1 with MTP 116 and with a DFlash2 drafter 158; TensorFold 0.6.6 with DFlash2 170. The same DFlash2 drafter in llama.cpp was no faster than MTP (95 against 95, 47 % of drafts accepted). The windows that fit: 98k with an 8-bit cache (exllamav3 DFlash2), 131k to 196k (MTP), 42,724 tokens with TensorFold's bf16 cache (73k at the memory edge). At temperature 0 drafting changed 7 of 15 exllamav3 DFlash2 replies, 10 of 15 with MTP, 4 of 15 on llama.cpp and none on TensorFold. See [Engines](engines.md).

## 2026-10-12

- Looked at four models that fit a 24 GB card but need an engine we do not run. None downloaded.
  [PersonaPlex-7B](models/personaplex-7b.md) is a gated 16 GB full-duplex speech model; its 4-bit GGUF loads only in moshi.cpp.
  [BitNet b1.58 2B4T](models/bitnet-b1.58-2b-4t.md) is a 1.1 GB ternary chat model for bitnet.cpp.
  [BitNet embeddings](models/bitnet-embeddings.md) (0.6B and 270M) use those same kernels.
  [VibeVoice-ASR-BitNet](models/vibevoice-asr-bitnet.md) is a 1.6 GB speech recognizer for VibeASR.cpp, aimed at AVX2 CPUs.
- Rechecked the abliterated DeepSeek V4.1 Flash. Still nothing near 135 GB; the smallest build seen today is about 190 GB.
- A third-party GLM-5.3-Flash IQ2_XXS is 81 GB. Not pulled: the author points at an unmerged llama.cpp change, and the Maya quant of the same model is already tested.

## 2026-10-11

- Looked at three new items, none downloaded. [Decision 3.0](models/decision-3.0.md) loads through its own
  Transformers code and has no requants yet. The [DFlash2 draft for ExLlamaV3](models/qwen3.8-27b-dflash2-exl3.md)
  is a serving path for Qwen3.8-27B that needs an ExLlamaV3 server. [Qwen 4](models/qwen4.md) is a rumour without
  weights.
- Retry wave: nine models that had failed earlier, rerun on llama.cpp 0.6 with researched sampling and less compressed weights.
  [Tiel Coder 35B](models/tiel-coder-35b.md) turned out to be a sampling problem: at temperature 0.6 the 4-bit file
  that had called an invented endpoint passes both tests, and the Q4_K_XL build passes test 2 in 27 minutes at
  78.6 tok/s with real endpoints only. [Devstral Small 2](models/devstral-small-2-24b.md),
  [Qwen3.6-35B-A3B](models/qwen3.6-35b-a3b.md) and [GLM-4.7-Flash](models/glm-4.7-flash.md) now pass test 1 and
  still fail test 2 on the MCP handshake: all three wrote `initialize` with snake_case fields. None of them sent a
  request to Home Assistant during its run, but that alone does not explain it: three passing runs sent none
  either. Nemotron 3 Nano, Nemotron 3.5 Lightning, Nanbeige 4.2, Qwen3-VL 8B and MiMo v2.6 did not pass test 1.
- Strata 0.1.42 runs [Qwen3.8-Flash-Next](models/qwen3.8-flash-next.md) through both tests (test 1 5/5 twice; test
  2 a full pass with 9 tools and 72 tests in 98 minutes), but slower over the run than 0.1.39 (19.2 against 24.4
  tok/s). A settings probe, repeated with a warm-up and in both orders, found one setting that matters: going back
  to the older PCIe share about doubled decode speed on long answers (95 against 48 tok/s) and read large prompts
  1.7 times faster. The first probe could not rank the settings because its opening run was a cold start: the same
  prompt was read at 44 tok/s cold and 1,269 warm.
- A newer SGLang build for Flash-Next handles several sessions at once (11 of 11 checks in a multi-session probe;
  the older build crashed under several) and passed test 1 5/5 at 25.3 tok/s. Its test 2 was interrupted and never graded; that build was dropped on 2026-10-21 (see that day).
- Test 3 now also gives the task as a file in the work folder, because models that compacted their conversation
  lost the required answer layout, and the grader credits a right value written in another layout. Four earlier
  runs gained; the cards show both counts.
- Harness finding: the coding agent's file search tools (glob and grep) have failed inside our test sandbox since
  the first runs, because the agent image lacks ripgrep. 57 of 181 runs asked for them and got an error, and the
  models fell back to shell commands. Every model had the same handicap, so the rankings hold, but turn counts are
  inflated. Fixed on 2026-10-11 by adding ripgrep to the image; earlier runs were not repeated.

- Test 4 result: Tiel Coder (Q4_K_XL, llama.cpp 0.6) fixed 9 of 9 tickets, three tickets three runs each, on a crate with 155 passing tests. All 84 hidden checks passed, nothing regressed and no run claimed "done" falsely; the slowest run took 42 minutes, the fastest 2. One model only.
- Test 5 added: one reply, no tools, an animated SVG brass orrery, graded from offline renders. Of 15 models, eight replied with an SVG that parses.
- Strata 0.1.42 with the old PCIe share passed test 1 at 33.8 tok/s (51 minutes) and test 2 at 30.1 tok/s (9 tools, 77 tests, 61 minutes), against 16.8 and 19.2 on the release default (94 and 98 minutes).

## 2026-10-10

- Qwen-Image-2.1-Turbo (the 8-step checkpoint of Qwen-Image 2.1): downloaded, official folder plus a Q8 GGUF of the transformer. Same architecture as Qwen-Image 2.1, so the same image setups apply. Not run yet.
- Mirai S (Qwen3.8-27B compressed to about 8 GB with a speculator): needs its own engine (Mirai's vLLM build or a llama.cpp fork). Not downloaded.
- Samsung LittleBit (sub-1-bit compression): code only, no checkpoints, non-commercial licence. On the watch list.
- TensorFold "Living Weights" (a served model that writes learned facts into its own weights) and Helix Foundry (a local data workspace): tools, not models. Nothing to test.

- Grader audit: the test-1 and test-2 graders were repaired and all 125 archived runs regraded. Four test-1 verdicts changed (Bonsai on the ada stack fail to pass, one Flash-Next row and one Qwen3.8 row partial to pass, the second Devstral run pass to partial); some test counts were corrected and some rows lost a no-crash tick.
- Strata 0.1.42 built beside 0.1.40.3. It skips rarely used experts by default (claimed 13 to 16 % faster decode, answers change slightly).
- The server Gemma 4 26B built on vLLM passed our test-2 grader, but a real client could not connect to it: the grader's client is more forgiving than a real one.

## 2026-10-09

- Step 5 Preview (StepFun, about 600B total / 27B active): does not fit. Official weights are announced for about 15 October; the earlier Hugging Face copies are third-party uploads and were not downloaded.
- Unsloth decision-model training noted as a way to build a local classifier; not a model, nothing downloaded.

- Two rules adopted after the Cyber loops: every entry serves its maker's recommended sampling, and every agent denies repeated identical tool calls.

## 2026-10-08

- New [story test](story-test/README.md): each model writes a Neuromancer-style short story from a fixed
  brief, then edits its own draft. OrcaSAQ-2 Cyber 27B, Qwen3.8 27B and the Orcarouter Flash-Next fine-tune ran it.
  Orcarouter wrote the best story (the longest and the best fight, at about 15-19 tok/s); none reached 5,000 words, and
  none really revised its own draft (they inserted passages or, in Qwen's case, reprinted the draft). Thinking needs a
  cap: uncapped, Qwen spent all 20,000 tokens planning.
- Huihui's abliterated GLM-5.3-Flash at 1 bit (UD-IQ1_S) failed both tests on
  Maya: it fell into repetition ("-0-0-0..." until the token limit) and never
  wrote a working program. Maya-S at 2 bits on the same engine passed both, so
  1-bit quants of this model are not usable for agent work. The Orcarouter
  uncensored Q2_K is next.
- GLM-5.3-Flash now runs on titan through Project Maya (a Strata-derived
  engine). Out of the box it decoded about 4 tok/s: the RAM tier only held
  experts that were not already in VRAM, so every VRAM eviction meant a
  re-read over NFS. Three small patches (all experts eligible for RAM, keep
  evicted experts in RAM, parse GLM's own tool-call format) plus a local SSD
  copy of the weights brought it to about 17-19 tok/s with no disk reads in
  steady state. Test 1 then passed 5/5 with 44 tests in 71 minutes.
- GLM-5.3-Flash on Maya also passed test 2 (7 tools, 66 tests) but needed 322
  of its 360 minutes at about 14 tok/s over the run: the slowest model to pass
  both tests. Next up is the Huihui abliterated build (UD-IQ1_S) on the same
  engine; a second GPU, which turns on Maya's MTP drafting, is what would make
  GLM-5.3-Flash practical here.
- Grader fix: test 1's read check could not walk into an argparse command
  group whose subcommands hide behind a custom label (`ACTION ...`) or carry
  aliases (`list (ls)`). Regrading the 14 runs that had no read credit moved
  Devstral Small 2 from 2/5 to 5/5; no other run changed.


## 2026-10-07

- Test 3 is in: the model gets an MCP server's source and a probe subagent
  whose only tools are that server's, must get 14 facts through the probe,
  check them against the REST API, and fix the server if it is wrong (3G: a
  known-good server; 3O: the model's own from test 2). Eight runs across
  Qwen3.8-27B (vLLM), Flash-Next (Strata with two batch slots), Orcarouter
  Flash-Next and ThinkingCap Heretic: every run got all 14 facts and scored
  12/12 on the transcript rubric, so the test does not yet separate these
  models. Speed does (9 to 46 minutes), and so does how deep each one looked.
- Every 3O run found and fixed a real defect in its own server: a missing
  services tool, "unknown" counted as "unavailable", arrays in
  `structuredContent` (the MCP schema types it as an object, and strict
  clients reject the whole reply), and facts that only lived in
  `structuredContent`, which OpenCode does not pass to the model.
- One 3G run (Flash-Next) found a defect in the known-good server too: it
  read only `target.entity_id`, while current Home Assistant publishes
  `target.entity`.
- Strata needs `"parallel": 2` with `--batch-mtp` for multi-agent work;
  SGLang's EXL3 build serves one session at a time and was not used.

- The bake-off moved to a new host. Its first run there, Qwen3.8-27B on vLLM,
  passed test 1 (5/5, 123 tests, 22 subcommands, 64 tok/s). About 6 of the 22
  subcommands call Home Assistant endpoints that do not exist, and test 1's
  checks do not catch that, so invented API surface is not only a Bonsai
  problem. A test 1 check that runs every subcommand and counts 404s is on
  the list.
- EmbeddingGemma 2 (Google, 740M, Apache 2.0) fits easily, but its
  `gemma-embedding2` architecture landed in llama.cpp the day after our
  v0.6.0 build (PR 30054) and in vLLM after 0.31.0. Not downloaded; revisit
  with the next llama.cpp release. New status label: "Needs an engine
  update".
- Bonsai 2 27B rerun with the makers' agent settings (current PrismML
  build, reasoning effort `medium`, 24k thinking budget): test 1 went from
  2/5 to 5/5 with 94 tests, but 7 of its 11 commands still call Home
  Assistant endpoints that do not exist. The settings fixed reliability,
  not the invented API. Test 2 was a partial pass: it builds, lists 3
  tools and passes 32 tests, but its `tools/call` expects an invented
  `toolName` field instead of the spec's `name`, so no standard client can
  call a tool, and two of its tools call the nonexistent `/api/entities`.
- Test 2T, last result: Gemma 4 26B-A4B on vLLM trusted the planted docs.
  Its code calls `/api/entities`; it never called the API, quit after three
  minutes and left code that does not build.
- Regraded every test-2 run after the grader fix: 21 of 46 test counts were
  too low (Flash-Next on SGLang 115 -> 155, Orcarouter 13 -> 54, Heretic2
  18 -> 33). With the corrected counts the Orcarouter fine-tune is the
  smartest uncensored setup; Heretic2 stays as the faster one.
- Strata did not start for test 2T (the engine exits while locking about
  40 GB of host RAM). Its 2T result is still open.
- Test 2T: Qwen3.8-Flash-Next on SGLang tested and gave the best 2T run
  so far: 10 tools, 94 tests, 47 min, 6 compiler errors per 1,000 lines.
  It hit planted paths, got 404s, and shipped only real endpoints.

## 2026-10-06

- Test 2T: ThinkingCap tested. It hit planted paths, got 404s, and shipped
  only `/api/states` and `/api/services` (8 tools, 8 tests, 90 min).
- Test 2T: OrcaSAQ hedged the other way round. It ships the real
  `/api/states` first and keeps the planted `/api/entities` as a fallback
  "for a newer Home Assistant", with tests for that fallback (9 tools, 59 tests).
- Grader fix: the test-2 grader read only the first `test result` line of
  `cargo test`, so a crate whose lib target has no tests scored 0. It now
  sums every target; older runs are being regraded.
- Struggle score fix: rerunning a failed build with no edit in between
  (only a different `tail` or `grep`) now counts once.
- Test 2T: Qwen3.8-27B Uncensored hedged. It hit the planted endpoints,
  then shipped code that calls the planted `services/list` as a "modern"
  path and falls back to the real `/api/services`. It passed with 68 tests.
- Test 2T, first result: Qwen3.8-27B on vLLM checked the planted
  `/api/entities`, got a 404, and switched to `/api/states` seven seconds
  later. It shipped only real endpoints and passed (7 tools, 36 tests).
- Added a struggle score to every run: failed builds and compiler errors
  per 1,000 lines of final code, by kind (syntax, unknown names, types,
  borrow checking). Early spread on test 2: ThinkingCap 6, SGLang Flash-Next 9,
  Qwen3.8-27B on vLLM 19, Swift 1.5 27, Heretic2 46, the stuck Qwen3.8-27B
  Cyber MTP run 89 (58 syntax errors), Kolibri 186.
- Qwen3.8-27B Cyber with its own MTP heads on llama.cpp 0.6 decodes about
  72 tok/s (was 30-45), but both test-2 runs with it got stuck: a loop on a
  mistyped call to an invented endpoint under long-horizon sampling, then 23
  identical failed builds on a bracket it could not find under default
  sampling. Its earlier passes were on llama.cpp 0.4 without drafting.
- Found that six runs called `/api/entities`, which is not a Home Assistant
  endpoint and appears in none of our prompts or documents. Models brought it
  from training; some recovered after a 404, Ternary Bonsai 2 did not. Added
  test 2T, which plants three wrong endpoints in an "older version" API
  reference to measure whether a model trusts documents or checks the live
  system. See [Method](method.md).
- Reviewed our Ternary Bonsai 2 27B runs after positive reports. Tool calls
  parsed normally and sampling matched the model card, so the invented API
  endpoints were the model's own (it ignored 404s from its own probes). Two
  settings were not the makers' recommendation: default `xhigh` reasoning
  effort instead of `medium`, and no thinking budget. A rerun on a current
  PrismML build with both is cheap and would settle it.
- Flash-Next Abliterated s1.5 passed the 8-hour long-horizon test 2 on
  llama.cpp 0.6: 6 tools, 19 tests, 120 minutes, 10.4 tok/s. All three
  uncensored Flash-Next variants now pass test 2 on 0.6; Heretic2 stays the
  pick (one more tool, 40% faster).
- Flash-Next Heretic2 passed the 8-hour long-horizon test 2 on llama.cpp 0.6:
  7 tools, 18 tests, 120 minutes, 14.6 tok/s. Twice as fast as the
  Orcarouter fine-tune for a similar result: new smartest uncensored pick.
- ThinkingCap-27B Heretic passed test 2: 8 tools, 30 tests, 52 minutes,
  25 tok/s, fully on the GPU on llama.cpp 0.6. The most tools of any
  uncensored 27B so far. Marked recommended.
- Mistral Large 4 (1.05T total, 49B active) does not fit: about 260 GB even
  at roughly 2 bits per weight. Card added so it isn't researched again.
- Started an uncensored round: ThinkingCap-27B Heretic (new), and 8-hour
  long-horizon test-2 runs for Flash-Next Heretic2, Flash-Next Abliterated
  s1.5, and Qwen3.8-27B Cyber. ThinkingCap test 1: 5/5, 54 tests, 31 tok/s,
  on par with stock Qwen3.8-27B on llama.cpp.
- The small-window vLLM setups (57-64k) finished: about 35-40% faster
  decode than the 150k setup, but each failed one test. With the Pi agent,
  the 57k setup compacted 8 times instead of 55.

## 2026-10-05

- llama.cpp 0.6 is 2.5-4x faster than 0.4 on Qwen3.8-Flash-Next with
  experts in RAM. On it, the Orcarouter uncensored Flash-Next passed test 2
  for the first time (8-hour cap, long-horizon sampling).
- Strata passes test 2 with Flash-Next and Swift 1.5. The 1.6-bit coder
  failed twice.
- Kolibri-1 (patched llama.cpp) is not competitive on these tests.
- An independent verifier subagent did not change OrcaSAQ's result: the
  run that passed never wrote the bug that sank the earlier run.

## 2026-10-04

- vLLM with MTP drafts at 150k became the default for Qwen3.8-27B.
- SGLang Flash-Next built the best server of all runs.
- Added the context margin and thinking budget to every engine.
- Dropped GLM-4.7-Flash and GLM-4.5-Air.
