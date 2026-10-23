# Tuning

What we learned about making models fast and reliable on one RTX 3090 (24 GB)
with 125 GB of system RAM. Each point says the rule, then the evidence with
numbers and dates. For the picks see [Conclusions](conclusions.md); for the
engines themselves see [Engines](engines.md); for how the tests work see
[Method](method.md). All speeds are tokens per second on this card. "Streamed"
means measured while a thinking model streams a real reply; "raw" means a short
benchmark with thinking off, which reads higher.

## 1. VRAM tiers: pick the tier first

**Rule.** Speed is set by how much of the model sits in VRAM, far more than by
its size. There are three tiers; choose the tier, then the model.

| Tier | Typical speed | Examples (decode, 2026-10) |
| --- | --- | --- |
| Everything on the GPU | 45-175 tok/s | Tiel Coder 35B IQ4_XS 151 (llama.cpp 0.7.0); Flint 40B Q3_K_XL 129 and 106 at 11.7k depth; LFM2.5-24B 125-176; Carbon-X 14.8B Q8_0 52; dense Qwen3.8-27B 42-45 plain, 70-170 with drafting |
| Most on the GPU, a few expert layers in RAM | 60-95 | Flint Q4_K_XL: 95 tok/s with 10 layers in RAM at a 150k window, 81 with 15, 73 with 19, 64 with 24 (262k); Tiel Coder Q4_K_XL with 6 layers in RAM 77-81 |
| Experts mostly in RAM | 3-26 | Flash-Next 12-14 on llama.cpp 0.6, 19-26 streamed with the expert cache; Ornith-1.5-122B 13.7-16.7; GLM-5.3-Flash on Maya 17; Cyber-Tiel 6-bit with 20 layers in RAM 43-44 |

**Evidence.**

- Flint Q4_K_XL, one model, one flag changed (the number of expert layers in RAM),
  2026-10-21 and 22: 81.4 → 73.1 → 64.2 tok/s at 15, 19 and 24 layers, and
  prefill of an 11.7k prompt fell from 2,208 to 1,624 tok/s. Every layer moved
  to RAM costs about 1.9 tok/s.
- Ornith-1.5-122B UD-Q4_K_XL (2026-10-20): 42 expert layers on the CPU gave
  13.7 tok/s, 41 gave 16.0 and 40 gave 16.3. Loads with 39, 36 and 34 layers
  failed on the compute buffer, so 40 was the edge.
- The numbers in rule 1 of [Conclusions](conclusions.md) (25-150 against 3-25)
  still hold; the expert cache (section 2) moved the bottom tier up, not out.

## 2. Expert placement: `-ncmoe` against `-cmoe` plus the expert cache

**Rule.** For a mixture-of-experts model that does not fit, keep all experts in
RAM (`-cmoe`) and give the GPU a cache of the hot ones (`--moe-cache-mib N`) in
llama.cpp 0.7.0, with 8-bit KV to make room. Do not split by layers (`-ncmoe`)
any more. Offloaded experts must load eagerly, or the first request stalls.

**Evidence.**

- 2026-10-22, Flash-Next, five GGUFs, 262k context: the cache beat the old
  layer split on every one, after a sweep of cache sizes (nine runs). Live on
  all 12 Flash-Next entries since that afternoon.

  | GGUF | Before: `-ncmoe`, f16 KV | Now: cache (MiB) | Streamed decode before → now |
  | --- | --- | --- | --- |
  | Orcarouter IQ4_XS | 40 | 12800 | 12-14 → about 19 |
  | Heretic2 IQ4XS-NGQ4 | 40 | 12800 | 11-14 → about 18 |
  | Abliterated s1.5 IQ4_XS | 39 | 13824 | 11.5-14.6 → 19-21 |
  | Swift 1.5 IQ3_XXS | 38 | 9216 | 13-17 → 23-26 |
  | Unpruned IQ3_S | 39 | 9216 | 12.5-15 → 21-23 |

- Prefill on fresh loads: about 250 → 415-427 tok/s at 16k and 48k, three
  reproductions. `--no-host` was worse (180).
- The cache size is bounded by what else lives in VRAM. For Orcarouter 13312
  MiB ran out of memory with the vision head and four slots; 12800 fit. Swift
  did not fit at 13312 or more. Peak VRAM
  on the live entries is 20.2-24.0 GB.
- The 0.6 evidence for eager loading: before `-lm none` (2026-09-30), offloaded
  models produced no output at all, because the experts were memory-mapped and
  page-faulted off the network during the first request.
- Lazy tensor reads, the default, make the first pass over unseen text slow when
  the page cache is cold. `-lzm off` removes it but costs about 28 GB more RAM,
  and Orcarouter did not finish loading with it in 25 minutes. Not adopted.
- Not yet checked: these configurations have not been through tests 1 and 2.

## 3. KV precision

**Rule.** Use 8-bit KV when it buys context, expert cache or a larger batch.
Use f16 only when nothing else needs the VRAM.

**Evidence.**

- Flash-Next on llama.cpp, Orcarouter GGUF, greedy, top-20 log-probabilities
  over cuts from 2k to 100k tokens plus chat (2026-10-22): the old f16-KV
  config against the new 8-bit-KV-plus-cache config has mean KL 0.0011, top-1
  agreement 98.2 %, and 8 of 8 needles found in both. Two loads of the new
  config differ by KL 0.0002 and 99.6 %, so that is the noise floor.
- f16 KV with the new flags does not fit at any cache size (12288, 11776,
  11264), so KV type and cache could not be separated on 24 GB. Flint at 262k:
  f16 KV failed with an out-of-memory error (2026-10-21).
- ExLlamaV3 with an 8-bit cache: 98k window with the DFlash2 drafter, 196k with
  MTP (2026-10-13). TensorFold keeps a bf16 cache only: 42k window by default,
  73k at the edge. vLLM runs 150k with FP8 KV; the 4/2-bit KV variant reached
  240k at about half the speed under load.
- Earlier cards say "f16 costs VRAM, not speed"; the Flash-Next result is the
  case where VRAM turned into speed.

## 4. Batch and ubatch

**Rule.** A larger physical batch (`-ub`) speeds prefill and costs compute-buffer
VRAM. Take the largest that still loads with everything else in place.

**Evidence.**

- Flint (all on GPU, 2026-10-22): `-ub 2048` read an 11.7k prompt at 5,357 tok/s.
- Ornith, 41 layers on the CPU: `-ub 2048` lifted prefill from 118 to 392 tok/s
  with the same 16.1 tok/s decode (2026-10-20).
- Flash-Next live entries use `-b 2048 -ub 1024`: `-ub 2048` with a 12288 MiB
  cache did not fit beside the vision head and four slots (2026-10-22).
- The opposite failure: OrcaSAQ-2 with DFlash2 drafts loaded on llama.cpp 0.7.0
  but every request failed on a 580 MiB compute buffer at 22.7 of 24 GiB.
  `-ub 256` fixed it at an unchanged window (2026-10-18).

## 5. Context margin and thinking budget

**Rule.** Tell the agent a context smaller than the server's, and cap thinking
inside the reply cap. Without both, runs die on overflow or on one endless think.

**Evidence.**

- Margin of `max(10%, 16k)` (2026-10-04). A 240k vLLM case died at 213,761
  tokens of prompt plus a 32,000-token reply against a 245,760 window; on small
  windows 10 % was not enough, hence the 16k floor.
- Compaction point (2026-10-14): the limit had counted the 32k reply twice, so
  a 150k server compacted at 71,000 tokens (47 %). It now compacts at 89,328
  (60 %). Runs before that date, all of test 2 included, used the old window.
- Small windows cost more than they save: the 57-64k vLLM setups decoded 35-40 %
  faster than 150k but each failed a test, and one compacted 55 times and took
  six times as long (2026-10-06). With the Pi agent the 57k setup compacted 8
  times.
- Thinking budget is `min(24000, reply cap − 6000)`. When the cap fell to 23,961
  below a flat 24,000 budget, one 87,000-character think used the whole reply
  and no files were written (OrcaSAQ-2, 2026-10-04). Unbounded, Qwen3.8-27B
  spent its whole 32,768-token output on thinking in round 1 (2026-09-23) and in the
  story test (20,000 tokens, 2026-10-08).
- Any cap rescued round 1: `--reasoning off` 6 of 9 endpoints, budget 4096 8 of 9,
  budget 16384 4 of 9. More budget was not better.
- A budget stops runaway thinking, not output loops (Qwen3.8-27B Cyber looped
  by varying its calls slightly).
- Thinking models can fail one-shot work for the same reason: Qwen3.8-27B on
  vLLM with thinking on finished no pagoda in seven tries (2026-10-14).

## 6. Maker sampling

**Rule.** Serve the maker's recommended sampling on the server. Coding agents
usually send none.

**Evidence.**

- Adopted for every entry on 2026-10-09, after loops had ruined several runs;
  the agents also deny repeated identical tool calls.
- Tiel Coder 35B at the author's temperature 0.6: the 4-bit build that had
  called an invented endpoint passed both tests, and the Q4_K_XL build passed
  test 2 in 27 minutes at 78.6 tok/s with real endpoints only (2026-10-11).
- Ternary Bonsai 2 degenerated into repeated tokens without its card's
  settings; with the makers' agent settings test 1 rose from 2/5 to 5/5
  (2026-10-07), though its invented endpoints remained.
- It is not a cure-all: Devstral Small 2, Qwen3.6-35B and GLM-4.7-Flash still
  failed the test-2 handshake with the makers' sampling.
- Long-horizon sampling (temperature 1.0, top-p 0.95, top-k 20, min-p 0) with an
  8-hour cap let the slow uncensored Flash-Next tunes finish test 2 for the
  first time (2026-10-05).

## 7. Speculative decoding: when it pays

**Rule.** It pays when the whole model is on the GPU, or when the engine is built
around it. With experts in RAM it gave nothing. Check that drafting does not
change the answers you need.

**Evidence.**

- Qwen3.8-27B code decode, 4-bit, one card (2026-10-13): 42 tok/s plain, 93
  llama.cpp with MTP, 116 ExLlamaV3 with MTP, 158 ExLlamaV3 with a DFlash2
  drafter, 170 TensorFold with DFlash2. The same drafter in llama.cpp was no
  faster than MTP (95 against 95; 47 % of drafts accepted), so the engine
  matters as much as the draft.
- Gemma 4 26B-A4B with its MTP drafter: 267 tok/s on short code, 123 at 141k
  of history, the fastest stack at that depth (2026-10-14).
- Qwen3.8-27B Cyber with its own MTP heads on llama.cpp 0.6: about 72 tok/s,
  against 30-45 before (2026-10-06).
- OrcaSAQ-2 with n-gram drafts: 412 tok/s on copy-heavy output; plain 83.
- Ornith-1.5-122B, experts in RAM (2026-10-20): MTP with two drafts at 44 layers
  on the CPU reached 16.7 tok/s, no better than 40 layers without a draft
  (16.3); three drafts gave 16.1, and a DFlash drafter slowed it to 11.5.
- Maya-M IQ2_S with a DFlash2 draft: 10.7 against 15.35 tok/s without, with
  91 % of drafts accepted (2026-10-17).
- Strata with its MTP head is the exception for Flash-Next: Gyro-S + MTP decodes
  119-144 tok/s, because the engine was built for it. The IQ3_S quant with MTP on
  the same engine is 35 (2026-10-20).
- Neutrality: at temperature 0, drafting changed 7 of 15 ExLlamaV3 DFlash2
  replies, 10 of 15 with MTP, 4 of 15 on llama.cpp, none on TensorFold.
- Tiel Coder's MTP head was not clearly faster than the plain build on test 1
  (67-82 tok/s), and one of three test-2 runs built a usable server; the
  failures were the server's, not a broken tool-call format (2026-10-12).

## 8. Cold against warm page cache, and measuring twice

**Rule.** Warm up before timing. Never rank settings on one run, and run each
setting twice in opposite orders.

**Evidence.**

- The same prompt was read at 44 tok/s on a cold start and 1,269 tok/s warm
  (Strata 0.1.42, 2026-10-11). The first settings probe could not rank anything
  because its opening run was cold.
- Strata 0.1.44.1 against 0.1.42: the first 0.1.42 round decoded 18.3 tok/s cold
  and 23.5 warm, so the true gain is about 1.9x, not 2.5x (2026-10-15).
- In the repeated probe everything ran faster in the second round, so
  differences smaller than that were treated as noise (2026-10-11).
- Maya first token: 92 s on 1.0.4 and 18 s on 1.1.11; its first load reads
  about 100 GB from the network (375 s).
- A fresh llama.cpp load showed prefill of 415 tok/s three times, while two runs
  inside the quality script read 85-100 tok/s and could not be reproduced
  (2026-10-22). We report only what reproduced.
- tqLLM's first load took 23 minutes cold and 2-3 minutes after.
- A raw benchmark of short outputs with thinking off overstates agent speed: on
  the unpruned Flash-Next GGUF it read about 40 tok/s while the streamed figure
  was 21-23. tqLLM's 100-110 tok/s on short replies fell to 54 on its best long
  arm.

## 9. PCIe share and other engine-internal knobs

**Rule.** When an engine splits transfers between the GPU and the CPU, measure
its share setting on your own card. A release default can be wrong for it.

**Evidence.**

- Strata 0.1.42 on Flash-Next (2026-10-11): returning to the older PCIe share
  doubled long-answer decode (48 → 95 tok/s) and read big prompts 1.7x faster
  (1,177 → 1,983 tok/s). Test 1 went from 94 to 51 minutes and test 2 from 98
  to 61 minutes with more tests passing (72 → 77).
- Other switches, each measured twice in opposite orders: turning tail skip off
  matched the decode gain but not the reading; turning the prefill CPU share off
  read fastest and decoded slowest.
- Maya-M (2026-10-17): a PCIe share of 0.25 against the engine default 0.36 gave
  about 17.9 against 16.0 tok/s (+12 %); 16 CPU threads stayed (18.7 against
  18.5 at 8). It is a measured candidate and was not applied.

## 10. Engine choice

**Rule.** The same weights run 2-5x faster on a suitable engine. Choose the
engine for the model class, then tune.

**Evidence.**

- Flash-Next with experts in RAM, same hardware: llama.cpp 0.4 2.2 tok/s, 0.6
  8.9 (2026-10-05), Strata 30-45 (2026-10-04), 0.7.0 with the cache about 19-26
  streamed, Strata 0.2.2 with the Gyro-S quant 144 on code (2026-10-22).
- Qwen3.8-27B: llama.cpp scored the same as vLLM and ran 2-4x slower over whole
  runs; ExLlamaV3 and TensorFold are faster on short code and hold a smaller
  window (section 7).
- Speed on one short request is not agent readiness. tqLLM decoded about 2.5x
  faster than llama.cpp on the same GGUF and failed 8 of 11 multi-session checks
  (section 11); stock SGLang at 25 tok/s passed 11 of 11.
- The engine table is in [Engines](engines.md).

## 11. The quality checks we use

We check a setup before we trust its speed. All of these run on every new
engine or settings change that matters.

| Check | What it does | Evidence |
| --- | --- | --- |
| KL and top-1 | Greedy logprobs (top 20) over cuts of 2k to 100k tokens and a chat, old config against new, same GGUF. A second load gives the noise floor. | Expert cache, 2026-10-22: KL 0.0011, top-1 98.2 %; noise 0.0002 and 99.6 % |
| Needle in a haystack | A planted code in filler text at 16k to 250k tokens, with room left for thinking. | Flash-Next live entries 211k; stock SGLang 100k, 150k and 190k; exllamav3 48213-KESTREL at 128k, 112k and 94k; Gemma, Tiel, Qwen and exllamav3 at 141k; Carbon-X missed at 36.7k (2026-10-22) |
| Digit-copy probe | Copies digit strings in long prompts and finds two needles; catches engines that corrupt numbers. | Maya 1.0.4 split one string and found one needle; 1.1.11 and 1.1.13 12 of 12 and both needles |
| Tool-call probe | One function call with arguments, parsed. | Passed on every engine above until tqLLM's first failure |
| Multi-session probe | 11 checks: three requests each get their own answer, two decode together, two agents call a tool with their own name, a long document and a short request together, five concurrent requests. | llama.cpp live 11 of 11; stock SGLang 11 of 11; tqLLM 3, 0 and 4 of 11; Carbon-X 10 of 11 at one slot (the two-together check fails by design) |
| Real agent tests | Tests 1 to 8 ([Method](method.md)). The only check that sees what an agent does with a setup. | Gyro-S + MTP test 2: full pass in 24 minutes |
| Grader audits | Regrade old runs when a grader changes. | 125 runs regraded on 2026-10-10, four verdicts changed; test counts for 21 of 46 test-2 runs were too low until the grader summed every cargo target |

A speed result without the probe next to it is a lead, not a pick. The picks
only change when a graded test 1 or 2 run supports them.
