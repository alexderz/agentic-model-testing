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
| Experts mostly in RAM | 3-26 | Flash-Next 12-14 on llama.cpp 0.6, 19-26 streamed with the expert cache; Ornith-1.5-122B 13.7-16.7; GLM-5.3-Flash on Maya 17; Cyber-Tiel 6-bit with 20 layers in RAM 44 over a test 1 run (50-52 on the short probe) |

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

**Rule.** For Qwen3.8-Flash-Next, the only model tested both ways, keep all experts in
RAM (`-cmoe`) and give the GPU a cache of the hot ones (`--moe-cache-mib N`) in
llama.cpp 0.7.0, with 8-bit KV to make room, instead of splitting by layers
(`-ncmoe`). Ornith and Flint were only run as layer splits, so for them the
cache is untested. Offloaded experts must load eagerly, or the first request stalls.

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
- Ornith, 41 layers on the CPU: `-ub 2048` lifted prefill from 116 to 392 tok/s
  with the same decode (16.1 against 16.0 tok/s, 2026-10-20).
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
  faster than MTP (95 against 93; 47 % of drafts accepted), so the engine
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
- Strata 0.1.44.1 against 0.1.42 (2026-10-15): 0.1.42 decoded 13.1 tok/s cold
  and 23.5 warm; 18.3 is the mean of the two rounds. Against the mean the gain
  looks like 2.5x (44.9), against the warm round it is about 1.9x.
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
  was 21-23. tqLLM's 105.2 / 83.5 / 107.1 tok/s (code / prose / structured, 262k default)
  is the same kind of figure: short replies, thinking off.

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
  faster than llama.cpp on the same GGUF and passed at most 4 of 11 multi-session checks
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

## 12. Two different cards: a 3090 and a V100

Since 2026-11-06 the test box has a Tesla V100 32 GB (sm_70) next to the RTX 3090
24 GB (sm_86, held at 250 W). One llama.cpp build (Clover, commit 4838ffb) serves
both. All rates below are short-benchmark rates: one oracle prompt, a warm-up and
two measured prompts of a few hundred output tokens, not agent runs. Fit rule as
everywhere: at least 1.5 GiB free on each card after the longest prefill.

**DeepSeek-V4.1-Flash 1017 UD-IQ1_S across both cards.** Attention and dense
layers split over the two cards, the routed experts of 40 layers in RAM
(`--n-cpu-moe 40`), and a GPU expert cache (`--moe-cache-mib`).

| Change (one at a time) | Decode tok/s | Prefill tok/s | Free 3090 / V100 GiB |
| --- | --- | --- | --- |
| Start: cache 20 GiB, split 1:1, F16 KV, flash attention off, ubatch 128, 8k | 9.7 | 16.7 (1.1k prompt) | 10.0 / 15.9 |
| Cache 28 GiB | 12.5 | 17.2 | 6.1 / 11.9 |
| Split 2:3 (more layers on the 3090) | 13.3 | 16.5 | 2.6 / 15.3 |
| Threads 12 to 16 | 13.4 | 16.5 | 2.6 / 15.3 |
| Flash attention on | 15.5 | 16.5 | 3.2 / 15.3 |
| Q8 KV with flash attention | 15.2 | 16.7 | 3.2 / 15.3 |
| ubatch 512 without flash attention | 12.9 | 33.0 | **1.2** / 15.3 (fails the fit rule) |
| ubatch 512 with flash attention and Q8 KV | 15.0 | 33.4 | 3.0 / 15.3 |
| Same, split back to 1:1 | 13.9 | 34.1 | 6.4 / 11.9 |
| Same at 96k context: 90,230-token retrieval correct | 14.0 | 31 (90k prompt, 48.5 min to first token) | 5.5 / 11.8 |
| Cache 34 GiB at 96k: 30,250-token retrieval correct | **16.5** | 35 (30k prompt, 14.3 min) | 2.5 / 8.8 |
| Cache 28 GiB, ubatch 1024 at 96k: 30k retrieval correct | 13.9 | 54 (9.3 min) | 4.6 / 11.7 |
| Cache 28 GiB, ubatch 2048 at 96k: 30k retrieval correct | 13.6 | **83** (6.1 min) | 2.7 / 10.3 |
| Cache 34 GiB, ubatch 1024 at 96k: 30k and 90k retrieval correct | 16.4 | 56 (30k, 9.1 min); 49 (90k, 30.5 min) | 1.6 / 8.7 (just inside the fit rule) |
| Same, 16 CPU batch threads instead of 12 | 16.5 | 56 (30k, 9.0 min) | 1.6 / 8.7 |
| Same, split 3:2 (more layers on the V100) | 15.0 | 56 (30k, 9.0 min) | 5.7 / 4.6 |
| Cache 34 GiB, ubatch 2048, split 3:2: 30k and 90k correct | 14.7 | 84 (30k, 6.0 min); 67 (90k, 22.6 min) | 3.9 / 2.8 |
| Cache 30 GiB, ubatch 2048, split 1:1: 30k and 90k correct | 14.5 | 84 (30k, 6.0 min); **69** (90k, 21.7 min) | 1.7 / 9.3 |
| Cache 40 GiB (split 1:1 or 3:4) | does not load: the V100 runs out of memory reserving compute buffers | | |

What we take from it:

- The expert cache is the decode lever (20 to 34 GiB: 9.7 to 16.5 tok/s); 40 GiB
  does not fit beside the V100's compute buffers.
- Flash attention is worth about 2 tok/s and saves about 0.5 GiB on the 3090; Q8
  KV costs nothing measurable and makes 96k context cheap (about 0.8 GiB over 8k).
- ubatch is the prefill lever, as on one card (section 4): 128 to 512 doubles
  prefill, 512 to 2048 more than doubles it again on a 30k prompt. Without flash
  attention, ubatch 512 broke the fit rule on the 3090.
- More threads did nothing, for decode or for prefill (CPU batch threads 12 to 16); prefill with experts in RAM stays the weak spot, so
  a long first prompt takes minutes.
- The cache and ubatch compete for the 3090. A 34 GiB cache with ubatch 1024 keeps
  the best decode (16.4 tok/s) but leaves 1.6 GiB free, just inside the rule. A
  30 GiB cache with ubatch 2048 gives the fastest long prompts (a 90k prompt reaches
  its first token in 22 minutes, down from 48.5) at 14.5 tok/s decode.
- Moving layers to the V100 (split 3:2) frees the 3090 but costs about 1.4 tok/s of
  decode, so split 1:1 stays the better trade.

**Qwopus3.8-27B-Coder-Flash Q6_K on the V100 alone**, 96k context, Q8 KV: decode
27.0 tok/s, first token 0.8 s on short prompts; 30,125-token retrieval correct
with a 43 s first token (700 tok/s prefill) and 90,105 tokens correct in 193 s
(470 tok/s). 8.0 GiB stayed free. No agent tests on this setup yet.

**Arete-27B Q6_K** (a Nous Research fine-tune of Qwen3.8-27B) in the same setup:
decode 26.1 tok/s; 30,125 tokens correct in 43 s (709 tok/s) and 90,105 tokens in
191 s (476 tok/s); 6.5 GiB free. On the 3090 alone it does not load: 22 GiB of
weights plus the 96k Q8 KV cache is more than 24 GiB.

**Largest contexts on the V100 alone** (2026-11-12, Q8 KV, short-benchmark
rates; the V100 drives no display, so its floor is 512 MiB free after the longest
prefill):

- Arete-27B Q6_K: 240k fits with 1.0 GiB free (26.2 tok/s decode; 235k tokens
  correct, first token 899 s at 262 tok/s). 256k also retrieves 250k tokens
  correctly (1,003 s) but leaves 440 MiB, 72 MiB under the floor.
- Arete-27B Q8_0: 128k fits with 0.9 GiB free (23.1 tok/s; 120k tokens correct
  in 287 s, 420 tok/s).
- Tiel-Coder-35B-A3B UD-Q6_K_XL, thinking off: 64k fits with 1.5 GiB free at
  92 tok/s (60k tokens correct in 98 s), so it no longer needs the 3090.
- Flash-Next UD-Q2_0 on Strata 0.2.13 built for the V100, experts streamed from
  RAM: two 256k slots with all K/V on the card fit with 3.1 GiB free and hold
  two ~240k prompts at once (both correct). Prefill runs one session at a time
  (first tokens 305 s and 761 s), and a session decoding beside a prefill gets no
  drafts (12.5 tok/s); alone with drafts it runs 31.7 tok/s.

**Qwopus 27B Q4_K_M, 3090 against V100**, 96k, Q8 KV: decode is the same on both
cards (33.0 tok/s), but the V100 prefills at about 60% of the 3090's rate (662
against 1,095 tok/s at 30k; 90k first token 200 s against 110 s). The 3090 rerun
is about 20% below the 2026-11-02 run of the same setup (41.6 tok/s) after a
driver change; the earlier power limit is not checked yet, so the cause is open.

## 13. Flash-Next toward 150 tok/s on one 3090

Goal set 2026-11-08: 150 tok/s decode and more than 1,000 tok/s prefill on a larger
Unsloth Dynamic v3.1 quant of Qwen3.8 Flash-Next, with about 128k context and int8
KV. Strata 0.2.12 with MTP drafting (spec 4, min-p 0.5) on the RTX 3090; the Tesla
V100 joins only as a helper expert cache. All rates are short-benchmark rates (one
oracle prompt, a warm-up and two measured prompts of 384 output tokens), not agent
runs. Every passing config answered both retrievals (30,037 and 120,007 tokens)
correctly and kept at least 1.5 GiB free on each card.

| Change (one at a time, UD-IQ3_XXS unless noted) | Decode tok/s | 120k prefill tok/s (first token) | Decode right after 120k |
| --- | --- | --- | --- |
| Start: 3090 alone, 250 W | 98.8 | 2,419 (49.7 s) | 68 |
| UD-Q2_K_XL / UD-Q3_K_XL at 250 W | 100.1 / 96.8 | 2,452 / 2,346 | 65 / 59 |
| MTP spec 6 | 95.1 | 2,426 | 48 |
| Prefill chunks up to 32k | 99.0 | 2,397 | 61 |
| Power 300 W | 108.1 | 2,701 (44.5 s) | 67 |
| Power 350 W (the card's maximum) | 112.2 | 2,824 (42.6 s) | 67 |
| 350 W: MTP spec 3 / min-p 0.3 | 110.4 / 104.6 | 2,808 / 2,825 | 68 / 67 |
| 350 W: huge pages / async tier / shared-memory expert kernel | 110.8 / 110.7 / 108.2 | 2,806 / 2,862 / 2,820 | 58 / 62 / 72 |
| 350 W: **adaptive overlap on** | **116.9** | 2,831 (42.5 s) | 65 |
| Overlap, min-p 0.7 | 114.6 | 2,834 | 70 |
| Overlap, UD-Q3_K_XL | 101.6 | 2,742 | 64 |
| 350 W + V100 helper cache (remote expert optimisation on) | 108.4 | 2,623 (45.8 s) | **113** |
| Same, remote expert optimisation off | 104.5 | 2,634 | 77 |
| Same, adaptive overlap on (needs the optimisation off) | 108.3 | 2,666 | 77 |
| Two 128k slots: 3090 alone at 250 W / with the V100 at 350 W | 80.5 / 100.2 | 2,335 / 2,622 | 59 / 101 |
| Four 128k slots with the V100 | 93.7 | 2,609 | 80 |
| Overlap + split decode attention / coupled drafting | 115.1 / 114.3 | 2,865 / 2,838 | 65 / 69 |
| Overlap + router prior 1.5 (**lossy**, changes the output) | 117.7 | 2,823 | 135 |
| Overlap + English and code draft vocabulary | **118.8** | 2,847 (42.2 s) | 64 |
| Same + fused hyper-connection up projection / int8 hyper-connection projections | 118.0 / 114.8 | 2,905 / 2,934 | 69 / 77 |
| Adaptive fetch 2 instead of overlap | 113.5 | 2,823 | 102 |
| Fetch + draft vocabulary | 117.2 | 2,838 | 101 |
| Fetch + draft vocabulary + int8 hyper-connection projections | 113.3 | **2,965 (40.6 s)** | 100 |
| Fetch + draft vocabulary, fetch margin 0 | 118.5 | 2,845 | 115 |
| Same, PCIe share 0.55 | 116.8 | 2,879 (41.8 s) | **125** |
| Fetch + draft vocabulary, two 128k slots, 3090 alone | 84.0 | 2,754 | 50 |
| V100 helper cache + draft vocabulary | 109.2 | 2,636 | 105 |
| V100 peer tier (the V100 computes its cached experts) + draft vocabulary, one / two slots | 107.1 / 96.7 | 1,546 / 1,517 (77.7 s) | 118 / 101; misses our fit rule (1,492 MiB free on the V100) |
| Drafting off | not supported: native IQ packs require MTP drafting | | |
| V100 peer tier, peer reserve 2,560 MiB (fit fixed) | 98.6 | 1,550 (77.5 s) | 114 |
| Same, prompt rows kept on the 3090 | 102.8 | 2,628 (45.7 s) | 116 |
| Same, peer reserve 2,048 MiB | 107.5 | 2,674 (45.0 s) | 116 |
| Peer tier, prompt rows on the 3090, two / four 128k slots | 94.8 / 90.8 | 2,626 / 2,614 | 97 / 95 |
| Same + 20k tokens of K/V resident in VRAM (rest from host memory), one / two / four slots | 103.3 / 99.0 / 97.5 | 2,631 / 2,603 / 2,619 | 104 / 101 / 100 |
| Fetch, margin 0, PCIe share 0.80 | 113.6 | 2,833 | 116 |
| Fetch, PCIe share 0.55, prompt-lookup chain 4 | 113.8 | 2,845 | 124 |
| Fetch, PCIe share 0.55, K/V cache that grows with the context | 118.2 | 2,986 (40.3 s) | 118 |
| Same + per-token (stream) draft-head norm | 122.95 | **2,987 (40.2 s)** | **127** |
| Same, 4-bit draft head and projections instead of the stream norm | 115.6 | 2,960 | 125 |
| Stream norm, draft window 5 | 122.85 | 2,986 | 106 |
| Stream norm, draft min-p 0.6 | **128.6** | 2,956 (40.7 s) | 124 |
| The 122.95 setup measured through the llama-swap proxy | 120.5 | 2,973 | 112 |
| Peer tier + stream norm, one / two / four slots (two and four with resident K/V) | 106.6 / 104.8 / 109.3 | 2,649 / 2,599 / 2,607 | 103 / 117 / 122 |
| Peer tier, one slot, stream norm + growing K/V | 107.0 | 2,641 (45.5 s) | **128** (119 after 30k) |
| 3090 alone, stream norm, two 128k slots with resident K/V | 105.6 | 2,805 | 53 |
| Stream norm, min-p 0.7 / min-p 0.6 with draft window 5 | 126.0 / 123.85 | 2,972 / 2,954 | 123 / 114 |
| 128.6 setup, 4,096-token prompt chunks instead of automatic | 127.6 | 2,272 (52.9 s) | 125 |
| 128.6 setup, helper threads off the pool cores / 8 pool workers / gain threshold 1.0 | 123.55 / 119.85 / 123.3 | about 2,940 | 112 / 124 / 112 |
| 128.6 setup, host thread on a hyper-thread sibling / 96 pool tasks / high-priority graph stream | 119.75 / 127.7 / 126.45 | 2,943 / 2,981 / 2,950 | 124 / 114 / 123 |
| 128.6 setup with a DFlash2 draft model instead of the MTP head, confidence 0.5 / 0.65 | 118.9 / 116.9 | 2,946 / 2,950 | 125 / 119 |
| Prefill head alias (with or without short reads off) | not supported on this build | | |
| 128.6 setup on UD-Q2_K_XL / UD-Q3_K_XL | 123.05 / 111.95 | 2,935 / 2,764 | 122 / 108 (79 / 60 after 30k) |
| Peer tier, one slot, growing K/V + min-p 0.6, on UD-IQ3_XXS / UD-Q2_K_XL / UD-Q3_K_XL | 107.1 / 106.95 / 100.65 | 2,642 / 2,644 / 2,384 | 127 / 108 / 101 (122 / 121 / 90 after 30k) |
| Peer tier, four slots with resident K/V, min-p 0.6 | 105.3 | 2,589 | 123 |
| Memory lock on (PLE table pinned in RAM): 128.6 setup / peer tier one, two, four slots | 122.5 / 109.95 / 104.1 / 110.2 | 2,981 / 2,663 / 2,591 / 2,595 | 108 / 106 / 116 / 122 |
| Strata 0.2.13 (engine only): 128.6 setup / peer tier one slot | 126.05 / 109.4 | 2,984 / 2,647 | 117 / 133 (73 / 124 after 30k) |
| Strata 0.2.13, 128.6 setup on UD-Q2_K_XL / UD-Q3_K_XL | 128.1 / 118.45 | 2,889 / 2,769 | 122 / 104 (78 / 83 after 30k) |
| 256k context, UD-IQ3_XXS: default reserve / reserve 3,072 MiB; UD-Q2_K_XL reserve 3,072 MiB | 124.25 / 120.5 / 122.0 | 2,718 / 2,734 / 2,677 at 248k (about 91-93 s) | misses our fit rule: 0.8 / 1.3 / 1.4 GiB free |
| 256k context, UD-Q2_K_XL, reserve 4,096 MiB | 124.5 | 2,628 at 248k (94.7 s) | 115 (73 after 30k); 2.2 GiB free, fits |

What we take from it:

- The 3090 is power-bound on this engine: 250 to 350 W is +13% decode and +17%
  prefill. Start there before tuning anything else.
- Adaptive overlap is the only engine knob that moved short-benchmark decode
  (+4%). Draft window, min-p, huge pages, the async tier and the shared-memory
  kernel did not.
- Prefill is far past the goal: a 120k prompt reaches its first token in about
  42 s.
- On the 3090 alone, decode right after a long prompt falls to about 65 tok/s
  because the long prompt evicts the expert cache. A V100 helper cache keeps it at
  101 to 113 tok/s. That matters more for agent work than the short benchmark,
  where the helper costs about 4 tok/s.
- Extra slots fit: two 128k slots cost one stream about 8% with the helper card
  (20% on the 3090 alone), four cost about 14%. Total throughput across streams is
  not measured yet.
- The quant matters little: UD-Q2_K_XL and UD-IQ3_XXS are within 2%, UD-Q3_K_XL
  is about 10% slower.
- llamAmpere 0.6.3.2 on the same files: 85.6 tok/s decode with the author's
  Swift Q2S-B draft model and 1,865 tok/s prefill at 100k (54 s to first token) at
  350 W; without a draft model, 59 to 62 tok/s, and the default expert-cache
  reserve left only 1.1 GiB free (a 1,536 MiB reserve fixes it).
- The English and code draft vocabulary is a small exact gain (+2%) and frees about
  110 MiB for experts.
- Adaptive fetch fixes decode after long prompts on the 3090 alone: with margin 0 and
  a 0.55 PCIe share it holds 125 tok/s right after a 120k prompt (overlap: about 65)
  at almost the same short-benchmark rate. That is the best setup for agent turns.
- A decode profile (overlap, first measured prompt) shows why short-benchmark decode
  has stopped near 119: each draft window tries 3.0 tokens and keeps 2.2, and takes
  19.5 ms, of which GPU work alone is about 12.9 ms and expert-cache misses about
  2.1 ms. Removing every miss would give at most about 128 tok/s; 150 needs more
  accepted tokens per window, which means a better draft head.
- The router prior that prefers cached experts reaches 135 tok/s after long prompts,
  but it changes the model's output and is not adopted without a quality check.
- The V100 peer tier gives 118 tok/s after a 120k prompt but halves prefill (about
  1,550 tok/s) and left 44 MiB too little free on the V100 for our fit rule.
- The peer tier's prefill penalty came from splitting prompt rows across the two
  cards. With prompt rows kept on the 3090 it prefills at about 2,630 tok/s, and a
  2,048 MiB peer reserve then fits our rule (2.1 GiB free on the V100).
- The per-token (stream) draft-head norm is the first change past the profile's
  ceiling: draft acceptance rises from about 55% to 60-68%. With draft min-p 0.6 it
  reaches 128.6 tok/s. It helps the per-slot drafters most: four peer-tier slots go
  from 97.5 to 109.3 tok/s per stream.
- A K/V cache that grows with the context gives the best prefill, about 2,990 tok/s
  at both 30k and 120k, because the prompt borrows expert slots while the context is
  short.
- Right after a 120k prompt the 3090 alone holds 124-127 tok/s, but right after a
  30k prompt it drops to 65-80. The peer tier holds 119 after 30k and 128 after
  120k, so it is the steadier setup for agent turns.
- With 20k tokens of K/V resident, two and four slots on the peer tier keep 99-109
  tok/s per stream and 100+ after long prompts. Two slots on the 3090 alone still
  starve the expert cache after long prompts (53 tok/s).
- Measuring through the llama-swap proxy costs about 2%, within noise.
- Twenty more single-change runs on the 128.6 setup did not beat it. CPU pool
  size, thread placement, pool tasks, the adaptive gain threshold and a
  high-priority graph stream all tie or lose; smaller prompt chunks cut prefill by
  23% without helping decode after the prompt.
- A DFlash2 draft model accepts about as many tokens as the stream-norm MTP head
  but drafts more of them, and is 7.5% slower on our prose prompts. Strata reports
  it wins on greedy code and JSON, which this benchmark does not cover.
- The same setup gives 123.0 tok/s on UD-Q2_K_XL and 112.0 on UD-Q3_K_XL (101.6 on
  the old stack). On the peer tier the quant barely matters: Q2_K_XL ties IQ3_XXS
  at about 107 tok/s and holds 121 tok/s right after a 30k prompt.
- Locking Strata's PLE table in RAM is neutral on every setup (-5% to +3%, inside
  noise); it only makes loads faster (about 51 s instead of 81 to 122 s for the
  multi-slot setups).
- llamAmpere 0.6.3.8 ties 0.6.3.2 on Linux: 85.1 tok/s decode and 1,873 tok/s
  prefill at 100k (53.8 s to first token).
- Strata 0.2.13 ties 0.2.12: 126.05 tok/s on the 3090 alone and 109.4 on the peer
  tier, with the same prefill. The 0.2.12 packs load unchanged.
- A 256k slot fits on the 3090 alone with a 4,096 MiB VRAM reserve on UD-Q2_K_XL: the
  248k-token retrieval is correct, the first token arrives in 94.7 s (2,628 tok/s),
  and 2.2 GiB stays free.
- Best on prose so far is 128.6 tok/s, about 86% of the 150 tok/s goal; replicates gave
  127.6 and 127.7. Run-to-run noise is about 4 tok/s, so single-digit differences
  between rows are not real.

### Code and JSON output, and several streams at once (2026-11-09)

The short benchmark now also runs code and JSON prompts, and a quality check of
three tasks with checkable answers (a Python task run in a network-free sandbox, a
JSON extraction, a word problem). Strata 0.2.13, the 128.6 setup, short-benchmark
rates.

| Setup | Prose | Code (accepted) | JSON (accepted) | Quality |
| --- | --- | --- | --- | --- |
| UD-IQ3_XXS, MTP head | 123.2 | 147.0 (82%) | 178.85 (95%) | 3/3 |
| UD-IQ3_XXS, DFlash2 draft model | 120.55 | 156.8 (76%) | 198.25 (93%) | 3/3 |
| UD-Q2_K_XL, MTP head | 121.55 | 150.65 (83%) | 179.2 (96%) | 3/3 |
| UD-Q2_K_XL, DFlash2 draft model | 120.4 | **162.25** (77%) | **203.1** (92%) | 3/3 |
| UD-IQ3_XXS, both drafters, automatic choice | 100.95 | 132.85 | 184.55 | 3/3 |
| UD-IQ3_XXS, DFlash2 flags written out, window 8 or confidence 0.3 | 87.2 | 85.9 | 137.2 | 3/3 |
| V100 peer tier, one slot, MTP head | 107.8 | 133.95 (81%) | 147.25 (95%) | 3/3 |
| UD-Q2_K_XL, DFlash2, window 8 | 121.4 | 162.15 (72%) | **206.95** (88%) | 3/3 |
| UD-Q2_K_XL, DFlash2, window 8, with 30k and 120k retrievals (2.2 GiB free after 120k) | 120.25 | **167.55** (75%) | 206.05 (89%) | retrievals correct |
| UD-Q2_K_XL, DFlash2, confidence 0.3 / window 8 and confidence 0.3 | 114.25 / 112.95 | 157.1 / 149.4 | 198.45 / 195.2 | 3/3 |
| UD-Q2_K_XL, memory clock locked at 9,751 MHz: DFlash2 window 8 / MTP head | 117.35 / 125.25 | 162.95 / 151.6 | 201.85 / 177.45 | retrievals correct |
| UD-Q2_K_XL, sampled like an agent: MTP head / MTP coupled / DFlash2 window 8 | 122.95 / 124.7 / 118.4 | 157.55 / 157.05 / 150.5 | 183.65 / 179.1 / 197.6 | retrievals correct |
| 256k context, UD-Q2_K_XL, MTP head, reserve 4,096 MiB | 123.55 | 144.9 | 172.9 | 248k correct, 94.75 s |
| 256k context, UD-Q2_K_XL, DFlash2, reserve 4,096 MiB: Strata's choice / confidence 0.5 | 116.5 / 120.2 | 152.85 / 154.65 | 193.7 / 191.45 | 248k correct, 93.1 / 93.3 s, 2.6 GiB free |
| 256k context, UD-Q2_K_XL, DFlash2, reserve 3,584 MiB: Strata's choice / confidence 0.5 | 116.1 / 117.6 | 157.95 / 157.45 | 192.6 / 197.35 | 248k correct, 93.7 s, 2.2 GiB free |
| UD-Q2_K_XL, thinking on, Qwen's thinking sampling: DFlash2 window 8 / MTP head | 116.45 / **124.9** | **150.2** / 139.3 | **186.9** / 166.8 | 30k correct; one of two JSON outputs invalid in each |

Several streams at once: total decode while every stream is writing, about
1,600-token replies.

| Setup | 1 / 2 / 4 streams, tok/s | First tokens with four ~30k prompts |
| --- | --- | --- |
| Strata, 3090 alone, four 128k slots, short prompts | 97.3 / 114.9 / 126.2 | 0.7-3.8 s |
| Strata, 3090 alone, four 128k slots, ~30k prompts | 95.1 / 105.1 / 122.7 | 11.9 / 28.3 / 44.7 / 61.1 s |
| Strata, peer tier, four 128k slots, ~30k prompts | 99.1 / 116.8 / 124.1 | 11.7 / 27.8 / 43.9 / 60.2 s |
| llama.cpp, Tiel-Coder 35B Q6 in VRAM on both cards, four 128k slots | 96.55 / 133.2 / 164.5 | 19.8 / 38.3 / 55.7 / 72.2 s |
| Strata, 3090 alone, four 128k slots, DFlash2 on each slot, sampled | 93.5 / 108.9 / 126.9 | 11.1 to 55.8 s; 0.6 GiB free, misses our fit rule |
| llamAmpere 0.6.3.2, UD-IQ3_XXS, four 32k slots | 71.5 / 82.6 / 45.7 | 129 s for one prompt, 505 s with four |
| Strata, 3090 alone, four 128k slots, DFlash2, reserve 3,072 MiB, sampled | 94.5 / 101.2 / 122.7 | 10.6 to 54.4 s; 1.6 GiB free, fits |
| Strata, 3090 alone, four 128k slots, MTP head, reserve 3,072 MiB, sampled | 95.1 / 107.2 / 122.7 | 10.9 to 55.0 s; 3.0 GiB free, fits |
| Strata, 3090 alone, two 128k slots, MTP head, reserve 3,072 MiB, ~100k prompts, sampled | 95.0 / 103.1 / - | 35.4 s alone; 35.8 and 88.5 s with two; 3.2 GiB free, fits |

- The 150 tok/s goal is met for code and JSON: the DFlash2 draft model gives 162
  tok/s on code and 203 on JSON on UD-Q2_K_XL. Prose stays at 120-128.
- Letting Strata choose the drafter is slower than either fixed choice.
- Writing the DFlash2 flags out by hand nearly stopped drafting (31 tokens drafted on
  prose), so a wider window and a lower confidence threshold are not yet tested.
- Four 128k slots fit on the 3090 alone (2.0 GiB free with four 30k prompts live),
  but Strata prefills prompts one at a time and drafts almost nothing once two
  streams decode together, so four streams sum to only about 125 tok/s. A batch-4
  server also makes a lone request slower. llama.cpp batches the streams and goes
  from 97 to 165 tok/s.
- With a draft window of 8, the DFlash2 draft model reaches 167.55 tok/s on code and
  206 on JSON, and the same setup keeps 2.2 GiB free after a 120k-token prompt
  (first token 42.2 s). A 256k slot with DFlash2 fits and stays above 150 on code.
- A lower draft confidence (0.3) is slower; coupled draft sampling and a memory clock
  lock change nothing (under CUDA the driver keeps the memory clock at 9,501 MHz).
- Sampled like an agent (temperature 0.7, top-p 0.8, top-k 20), the MTP head keeps its
  greedy rates; DFlash2 loses about 10% on code (150.5 tok/s) and 4% on JSON.
- llamAmpere does not scale Flash-Next across slots: a 30k prompt prefills at 234
  tok/s and four streams total only 46 tok/s.
- Keeping the K/V cache in host RAM (llama.cpp, Tiel-Coder on both cards) cuts
  decode from 118 to 24 tok/s and prefill by about 40% to free only 1.2-1.4 GiB per card.
- A 3,072 MiB VRAM reserve makes four 128k slots fit the 1.5 GiB rule (3.0 GiB free with
  the MTP head, 1.6 GiB with DFlash2); the total stays at about 123 tok/s. Two slots
  with ~100k prompts also fit (3.2 GiB free, 103 tok/s total, second first token 88.5 s).
- With thinking on and Qwen's thinking sampling, the MTP head wins on prose (124.9
  tok/s) and DFlash2 on code and JSON (150.2 and 186.9).

### Session switches and two 256k agent slots (2026-11-09)

UD-Q2_K_XL, Strata 0.2.13, MTP draft head, 8-bit K/V, the 3090 at 300 W,
short-benchmark rates.

Session switches: sessions of about 93k prompt tokens served one request at a time in
rotation, so each turn returns to a session another one displaced.

| Setup | First token on a switch (median) | Prompt reused | Free VRAM |
| --- | --- | --- | --- |
| Session cache in host RAM, 12 GiB, 2 or 4 sessions | **0.93 s** | 99.9% | 2.2 GiB |
| No session cache | 34.8 s | 0% | 2.2 GiB |
| Four batch slots, no session cache | 35.9 s | 0% | 3.2 GiB |

Two 256k slots, two ~240k prompts at once, Qwen thinking sampling, both streams recall
early and late markers correctly.

| Setup | First tokens | Total decode, tok/s (per stream) | Free VRAM |
| --- | --- | --- | --- |
| Whole K/V in 3090 VRAM | 137.6 / 344.7 s | 51.5 (19.3 / 25.1) | 3.2 GiB |
| 20,480 K/V cells in VRAM, rest in pinned host RAM | 94.8 / 234.9 s | 90.2 (52.0 / 29.9) | 3.2 GiB |
| 65,536 K/V cells in VRAM | 96.5 / 239.9 s | 83.8 (33.2 / 41.2) | 3.2 GiB |
| Whole K/V in 3090 VRAM, V100 peer tier | 137.8 / 344.1 s | 101.2 (32.5 / 59.3) | 3.2 / 2.2 GiB |
| 20,480 cells in VRAM, V100 peer tier | 105.6 / 264.5 s | 93.7 (34.6 / 47.4) | 3.2 / 2.1 GiB |
| Layers split 24/24 with the V100, whole K/V in VRAM | 121.4 / 369.5 s | 96.6 (25.9 / 56.6) | 3.3 / 3.2 GiB |

- A session cache in host RAM is what makes several long sessions cheap: 37 times faster
  switches for 2-2.8 GiB of host RAM per parked session and no VRAM. Batch slots do not
  hold a finished conversation.
- Keeping the whole K/V of two 256k slots in 3090 VRAM costs about 80% of the expert
  cache. With 20,480 cells per layer resident, 99.7% of K/V reads already hit VRAM, so a
  larger window only takes expert-cache room.
- One sample each, so 84-101 tok/s is one band. We picked the 3090 alone with 20,480
  resident cells for agent serving: fastest second prompt and the V100 stays free.
- Pinning about 9 GiB of host RAM for the streamed K/V can stall the load for minutes when
  the page cache is full; dropping the page cache cleared it at once.

The picked profile with a 28 GiB session cache in host RAM (2026-11-10), short-benchmark
rates, thinking on:

| Test | First tokens | Decode, tok/s | Free VRAM |
| --- | --- | --- | --- |
| 4 then 6 sessions of ~155k in rotation, cold turns | 60.0 s median | - | 3.3 GiB |
| Same, switch back to a parked session | **1.25 s** median (2.5 s max) | 85.3 median | 3.3 GiB |
| Four 256k slots, two ~120k prompts at once | 45.8 / 113.7 s | 91.4 (47.5 / 37.3) | 3.1 GiB |
| Four 256k slots, four ~120k prompts at once | 48.0 / 116.4 / 184.8 / 253.1 s | 95.8 (27.2 / 20.5 / 19.0 / 19.4) | 3.1 GiB |
| Four slots plus the V100 peer tier, two ~120k prompts | 49.4 / 123.6 s | 101.1 (42.3 / 53.2) | 3.1 / 2.2 GiB |
| Four slots plus the V100 peer tier, four ~120k prompts | 51.7 / 126.3 / 200.6 / 275.5 s | 109.6 (30.0 / 22.0 / 25.7 / 23.2) | 3.1 / 2.2 GiB |

- All 30 switch recalls and all 6 concurrent streams were right. Each parked 155k session
  holds about 3 GiB of host RAM; at 6 sessions the host's free memory fell from 40 to
  13.6 GiB.
- Four slots cost nothing in fit and keep the total rate; each stream gets a quarter. The
  profile stays at two slots for two large sessions.
- Agent run on the profile: OpenCode ran test 1 and test 2 at the same time on one load.
  Test 2 passed in full (8 tools, 113 of its own tests, 70 minutes) at 39.2 tok/s agent-run
  decode per session, about 77 summed, first token median 1.36 s with prompts up to 217k
  tokens; sessions were parked and restored from host RAM inside the run. The test 1
  session was cut by our own thermal check and is not graded.
- With four slots the V100 peer tier is worth about 11-14% of total decode (101.1 against
  91.4 with two prompts, 109.6 against 95.8 with four); with two slots it was inside the
  noise. The profile stays on the 3090 alone so the V100 stays free; four slots plus the
  peer tier is the setup for four parallel agents. One sample each; three of the four
  120k streams hit the 12,000-token reply limit.

The smaller UD-Q2_0 quant (65.7 GiB against 74.1 GiB for UD-Q2_K_XL) on the daily-driver
setup at 300 W (2026-11-10, short-benchmark rates, greedy): decode 122.4 tok/s against
120.7, short-prompt first tokens 0.30-0.97 s against 0.35-1.15 s, 30k and 120k retrievals
right in 10.6 / 42.7 s against 11.7 / 43.8 s, 2.2 GiB free on both. Speed is a tie, so its
agent tests decide between the two.

UD-Q2_0 on the agent serving profile shape (2026-11-10, two 256k slots, 20,480 resident
K/V cells, two ~240k prompts at once, Qwen thinking sampling, short-benchmark rates): first
tokens 93.7 / 230.5 s, total decode **104.3 tok/s** (62.1 / 32.2) against 90.2 for
UD-Q2_K_XL, 3.1 GiB free. Both streams right. The agent-run edge (about 13%) holds here too.

UD-Q2_0 with many long sessions across both cards (2026-11-12, Strata 0.2.13, MTP draft
head, int8 K/V, Qwen thinking sampling, ~240k prompts all at once, short-benchmark rates):

| Setup | Sessions | First tokens | Total decode, tok/s (per session) | Free VRAM |
| --- | --- | --- | --- | --- |
| 3090 + V100 peer tier, 20,480 K/V cells on the cards, rest in pinned host RAM | 8 | 108 s to 1,212 s, one after another | 89.4 (9.0-14.9) | 2.5 / 3.8 GiB |
| Layers split 24/24, all K/V in VRAM | 4 | 121 / 366 / 610 / 855 s | **111.4** (11.6-35.5) | 3.3 / 3.2 GiB |

- Every needle was right: 8 of 8 and 4 of 4, about 1.9M and 960k tokens live.
- Prefill runs one session at a time (about 1,520 tok/s each with the 3090 primary, about
  980 with the split), and drafting is mostly off for a session decoding beside a prefill.
  More sessions cost waiting time, not fit.
- Holding all K/V in VRAM gives more total decode at four sessions; the host-RAM tier holds
  twice as many sessions with similar free VRAM. One sample each.
