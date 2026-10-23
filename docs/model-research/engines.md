# Engines

The engine moves a model within its speed tier by 2 to 5 times. This page
says which engine to use for which kind of model, and for each engine its
versions, what it is good at, what it measured on our RTX 3090, how it behaves
with several sessions, and the bugs we met. For why the settings are what they
are, see [Tuning](tuning.md). Dates are when we measured, not when the engine
was released.

## Rule of thumb

- If the model fits on the GPU, use **vLLM** for the dense 27B and
  **llama.cpp 0.7.0** for everything else that has a GGUF.
- If a mixture-of-experts model must keep experts in system RAM, use
  **llama.cpp 0.7.0 with the expert cache** (`-cmoe --moe-cache-mib N`). For
  Qwen3.8-Flash-Next, **Strata** and **stock SGLang** are the faster or
  steadier alternatives (below).
- Speculative decoding (MTP or a draft model) pays off only when the model is
  GPU-resident, or when the engine is built around it (Strata with Flash-Next).
  With experts in RAM on llama.cpp it gave nothing. See [Tuning](tuning.md).
- Check several sessions before an engine serves an agent. Speed on a single
  short request told us nothing about that (tqLLM, below).

## At a glance

| Engine | Used for | Best measured speed on the 3090 | Several sessions | Status (2026-10-22) |
| --- | --- | --- | --- | --- |
| llama.cpp 0.7.0 | Anything with a GGUF; Flash-Next with experts in RAM | 151 tok/s Tiel Coder (all on GPU); about 19-26 tok/s streamed on Flash-Next | 11 of 11 probe checks on the Flash-Next entries | In the router for every llama.cpp entry since 2026-10-18 |
| vLLM (HyperQwen 0.30) | Qwen3.8-27B, Gemma 4 | about 70 tok/s over a run; 127 tok/s on short code | Main agent plus sub-agents in tests 3 and 8 | Default for the 27B |
| SGLang (EXL3) | Flash-Next | 24-25 tok/s | 11 of 11 on the stock builds | Stock builds serve it; the best test-2 server of all runs came from an older build |
| Strata 0.1.44.1 / 0.2.x | Flash-Next family, Gyro quants | 144 tok/s on code (Gyro-S + MTP, 0.2.2) | Needs two batch slots set up | 0.2 is beta |
| Maya 1.1.11 / 1.1.13 | GLM-5.3-Flash | 17 tok/s | Not measured | In the router |
| ExLlamaV3 1.6.2 (TabbyAPI) | Qwen3.8-27B with MTP or DFlash2 | 140 tok/s, DFlash2, short prompts | Not measured | Two entries kept |
| TensorFold 0.6.6 | Qwen3.8-27B with DFlash2 | 170 tok/s on short code | Not measured | Parked, not in the router |
| tqLLM 1.2.3 | Flash-Next GGUF | about 100-110 tok/s on short replies | 3 of 11 at best | Trial only; not usable for agents |

## llama.cpp

llama.cpp runs anything with a GGUF, including models whose experts sit in
system RAM. It is the only engine that runs the uncensored Flash-Next tunes and
most of the small models.

**Versions.**

| Version | Dates | What changed for us |
| --- | --- | --- |
| 0.4.1-dev (commit 4260903) | Round 1 (2026-09-23) until 2026-10-18 | The build bundled in the router, used by the native entries. Flash-Next with experts in RAM: 2.2 tok/s on the probe, 7-8 tok/s over a run. |
| 0.6.0 (official image, build 11429) | Tested 2026-10-05 | 2.5-4x faster than 0.4 on Flash-Next with experts in RAM (table below); MTP and n-gram drafting fixes. |
| 0.7.0 (released 2026-10-15) | In the router since 2026-10-18 | Adds a GPU cache for experts kept in RAM (`--moe-cache-mib`). All llama.cpp entries now run it as separate containers behind the router; Bonsai 2 runs on its makers' fork image. |
| Newer official builds | 2026-10-21 and later | Flint needs b11803 or later; Carbon-X needs b11742 or later. Both trials ran on such a build, started by hand, not in the router. |

**Good at.**

- Any GGUF, including models that do not fit: experts in RAM, attention and
  dense layers on the GPU.
- All-GPU models of up to about 35B parameters: Tiel Coder 35B, Gemma 4,
  Flint and LFM2.5 decode at 100-176 tok/s.
- Per-request thinking budgets (`--reasoning-budget`, or
  `thinking_budget_tokens` per request) and the makers' sampling set on the
  server.

**Settings that matter.**

| Setting | Why |
| --- | --- |
| `-cmoe --moe-cache-mib N` (0.7.0) | All experts in RAM, plus a GPU cache of the hot ones. Replaces the `-ncmoe` layer split for Flash-Next; see below. |
| `-ncmoe N` with `-lm none` (0.6) | Experts of `N` layers in RAM, loaded eagerly. Without `-lm none` the first request page-faults the weights and stalls. |
| `-ctk q8_0 -ctv q8_0` | 8-bit KV. It is what makes room for the expert cache; mean KL against f16 KV was 0.0011 on Flash-Next. |
| `-b 2048 -ub 1024` | The batch sizes of the live Flash-Next entries. `-ub 2048` did not fit beside the cache with vision and four slots. |
| `-fit off` | The automatic fit keeps 1 GiB spare and aborts when `-ngl` is set by hand. |
| `--reasoning-budget` | Caps thinking; set it inside the reply cap. |
| `--chat-template-kwargs '{"enable_thinking":true}'` | Gemma-style templates think only when asked. |
| `--spec-type draft-mtp` | MTP drafting for models that ship MTP layers. |

**Measured speeds.**

A short-prompt probe at 49k context, thinking off, temperature 0, llama.cpp
0.6 against 0.4 (2026-10-05). Real agent runs average lower.

| Model | 0.4 decode | 0.6 decode | 0.6 with drafting | Prefill 0.4 → 0.6 |
| --- | --- | --- | --- | --- |
| Qwen3.8-Flash-Next (experts in RAM) | 2.2 tok/s | 8.9 tok/s | – | 136 → 569 tok/s |
| Orcarouter Flash-Next Uncensored (experts in RAM) | 5.3 tok/s | 13.1 tok/s | – | 295 → 486 tok/s |
| Qwen3.8-27B Cyber (all on GPU) | 44.9 tok/s | 45.1 tok/s | 82.2 tok/s with MTP | about the same |
| OrcaSAQ-2-Cyber-27B (all on GPU) | 85.5 tok/s | 83.2 tok/s | 412 tok/s on copy-heavy output with n-gram drafts | about the same |
| Cyber-Tiel-Coder-35B (20 expert layers in RAM) | 52.3 tok/s | 50.5 tok/s | – | about the same |

In a real 8-hour agent run, the Orcarouter model on 0.6 averaged 7.6 tok/s:
much better than 0.4 (which could not finish) but far below the probe.
Measure on your own workload.

Flash-Next with the expert cache on 0.7.0 (2026-10-22, 262k context, q8 KV,
live on all 12 Flash-Next entries):

| GGUF | Before (0.6, f16 KV, `-ncmoe` 38-40) | Now (`-cmoe`, cache in MiB) | Streamed decode now |
| --- | --- | --- | --- |
| Orcarouter IQ4_XS | 12-14 tok/s | 12800 | about 19 tok/s |
| Heretic2 IQ4XS-NGQ4 | 11-14 | 12800 | about 18 |
| Abliterated s1.5 IQ4_XS | 11.5-14.6 | 13824 | 19-21 |
| Swift 1.5 IQ3_XXS (pruned) | 13-17 | 9216 | 23-26 |
| Unpruned IQ3_S | 12.5-15 | 9216 | 21-23 |

Prefill on fresh loads went from about 250 to about 415 tok/s. Raw decode on
short outputs with thinking off is higher: about 40 tok/s on the unpruned
GGUF. Streamed figures include thinking and are the ones that match agent
work. These configurations have not been through tests 1 and 2 yet.

Other measurements on 0.7.0:

| Model | Setup | Decode | Date |
| --- | --- | --- | --- |
| Tiel Coder 35B, IQ4_XS | all on GPU, 262k | 151 tok/s | 2026-10-18 |
| Flint 40B-A2.5B, Q3_K_XL | all on GPU, 262k, q8 KV, newer build | 129 tok/s short, 106 at 11.7k depth | 2026-10-22 |
| Flint, Q4_K_XL | 15 expert layers in RAM | 81 tok/s, falling to 64 with 24 layers in RAM | 2026-10-22 |
| Ornith-1.5-122B, UD-Q4_K_XL | 40 expert layers on CPU | 16.3 tok/s | 2026-10-20 |
| Carbon-X 14.8B, Q8_0 | all on GPU, 40k | 52 tok/s | 2026-10-22 |
| Qwen3.8-27B with MTP | all on GPU | 93 tok/s on code | 2026-10-13 |
| Qwen3.8-27B with a DFlash2 drafter (GGUF) | all on GPU | 95 / 43 / 108 tok/s code / prose / structured, no faster than MTP although 47 % of drafts were accepted | 2026-10-13 |

**Several sessions.** The server splits its context over slots (four by
default). The live Flash-Next entries passed the 11-check multi-session probe
on 2026-10-22 (11 of 11); entries that need a whole window for one agent set
`-np 1`. With `-np 1`, a probe check that sends two requests together fails by
design (Carbon-X: 10 of 11).

**Known problems.**

- 0.4.1-dev: Flash-Next with experts in RAM is 2.5-4x slower than on 0.6.
- 0.6: the automatic `-fit` aborts when `-ngl` is set by hand. Offloaded models
  stall on the first request without `-lm none`.
- 0.7.0: OrcaSAQ-2 with DFlash2 drafts loaded but every request failed with a
  failed 580 MiB compute-buffer allocation at 22.7 of 24 GiB (2026-10-18).
  `-ub 256` fixed it; the window is unchanged.
- 0.7.0: Qwen3.8-27B Cyber passed the short validation checks, but its first
  test-8 pagoda run from step 33 produced replies of the full 32,000 tokens
  with no text or tool call, at 22 tok/s (the same model on 0.4 finished at
  30.7 tok/s). We stopped it and did not grade it. We suspect a regression for
  this model; it was one run and has not been repeated.
- Lazy tensor reads (the default) make the first pass over unseen text slow
  when the page cache is cold. `-lzm off` removes the slowdown but needs about
  28 GB more RAM; we did not adopt it.
- A model whose GGUF needs an architecture newer than the image (Flint,
  Carbon-X, MiniCPM-V 4.7 before 0.7) loads on older builds but fails or
  tokenizes wrongly. Check the build before you read a result.

## vLLM

We use the HyperQwen build of vLLM for Qwen3.8-27B. It ran 2-4x faster
than llama.cpp over whole agent runs, thanks to prefix caching and MTP
drafting.

**Versions.** HyperQwen 0.30 is in use. The 0.31 build ran the same speed
rounds on 2026-10-14 (code about 124 against 126 tok/s, prose 93 against 91,
structured 135-137) and was a little slower deep (79.5 against 84.5 tok/s at
141k); we did not move to it. A 0.32 image was built and staged and is not in
use.

**Good at.** Dense models that fit the GPU, long agent runs with prefix
caching, and per-request thinking budgets.

**Measured speeds.**

| Setup | Context | Result |
| --- | --- | --- |
| MTP drafts, FP8 KV | 150k | The default. About 70 tok/s over a run, full passes on both tests; 127 tok/s on short code and 85 at 141k of history. |
| DFlash2 drafts, 4/2-bit KV | 240k | Same quality at 240k, about half the speed under load. Use it only when a job needs more than about 150k. |
| DFlash2 drafts | 64k | About 97 tok/s, but the agent compacts constantly and one test overflowed the context. |
| DFlash2 15-token drafts | 57k | About 95 tok/s; one test compacted 55 times and took 6x as long. |

**Several sessions.** Tests 3 and 8 run a main agent with sub-agents against
the same server without incident. Images work only with `VISION=1` and a raised
per-prompt image limit; the default entries run blind.

**Known problems.** vLLM needs a per-request thinking budget
(`thinking_token_budget`) and `--reasoning-config` on the server. With
thinking on, Qwen3.8-27B on vLLM never finished a one-shot pagoda (seven
tries, 2026-10-14): it plans the whole scene while thinking. Gemma 4 26B on
vLLM passed our test-2 grader, but a real client could not connect to the
server it built, so the grader is more forgiving than a client (2026-10-10).

## SGLang

SGLang runs the Flash-Next EXL3 3-bit weights (3.05 bits per weight) with a GPU
expert cache.

**Versions and measurements.**

| Build | Date | Result |
| --- | --- | --- |
| Original fork build, 200k, fp8 KV | 2026-10-01 to 2026-10-04 | Built the best test-2 server of all runs: 12 tools, 155 tests, 124 minutes, 36 tok/s over the run. Test 1 at 44.3 tok/s. |
| Newer fork build (phase D) | 2026-10-11 | 11 of 11 multi-session checks and test 1 at 25.3 tok/s (earlier settings, not directly comparable). Its test 2 was cut off and never graded. Dropped on 2026-10-21. |
| Three stock builds, 204,800 context, two slots | 2026-10-21 | EXL3 3.05 bpw weights, fp8 or 8-bit KV: 24.1, 24.6 and 25.1 tok/s decode; tools, vision and needles at 100k, 150k and 190k pass; prefill about 2,600 tok/s at 190k (73 s); a repeated 190k prompt answers in 0.5 s; 11 of 11 multi-session checks; 21-21.4 GB; load 252-262 s. |

**Good at.** The most capable Flash-Next setup we have tested, with images and
a 200k window. It is slower than the 27B stacks.

**Several sessions.** The original build served one session at a time and
crashed under several (2026-10-03). The stock builds serve two slots and
passed all 11 checks on 2026-10-21, at about 25 tok/s. No agent test has been
rerun on these builds yet.

**Known problems.** The original build's crash under several sessions, fixed
in the newer builds. A test-3 run on the original build needed Strata instead.

## Strata

Strata runs the Qwen3.8-Flash-Next family (GSQ-RCO quants, and the Gyro quants
from 0.2) with a hot-expert cache in VRAM and its own MTP drafting.

**Versions and measurements.**

| Version | Date | Result |
| --- | --- | --- |
| 0.1.39 / 0.1.40.3 | 2026-10-04 to 2026-10-09 | 30-45 tok/s decode, 21-30 tok/s over a whole run; test 2 full passes with Flash-Next and Swift 1.5. |
| 0.1.42 | 2026-10-10 to 2026-10-12 | Release defaults were slower on Titan (test 1 at 16.8 tok/s, 94 min; test 2 at 19.2 tok/s, 98 min). With the old PCIe share, long answers decoded at 95 tok/s against 48 and large prompts were read at 1,983 against 1,177 tok/s; test 1 at 33.8 and test 2 at 30.1 tok/s (61 min). |
| 0.1.44.1 | 2026-10-15 | Two rounds each against 0.1.42: load 60 s against 214 s, decode 44.9 against 18.3 tok/s. The first 0.1.42 round was cold; its warm round decoded 23.5, so the true gain is about 1.9x. |
| 0.1.45 | 2026-10-20 | IQ3_S with MTP, code prompt: 29.4 tok/s, against 35.4 on 0.2.0-beta on the same prompt. |
| 0.2.0-beta | 2026-10-20 | Gyro-S (TQ1_0) with an MTP draft: 118.6 tok/s on code, text only. Test 2: full pass in 24 minutes (6 tools, 108 tests), 89.8 tok/s over the run. Agent pagoda 9 of 10. |
| 0.2.2 | 2026-10-22 | Same-day control on the Gyro-S build: code 121.6 → 144.1 tok/s, prose 106.4 → 123.4, JSON 135.2 → 157.7 (about 17 %), load 23 s. Tool call and needles at 16k and 64k pass on both. One load per engine; no agent run on 0.2.2 yet. |

**Good at.** The fastest Flash-Next decode we have measured, and the only
engine that made the 1-bit-class Gyro-S quant usable. Gyro-S + MTP is a
candidate for the fastest competent pick, not yet the pick: one agent run on
a beta engine.

**Settings.**

- Set `reasoning_budget_tokens` in its model config. It is off by default,
  and the 1.6-bit coder looped without it.
- Add the host name your proxy uses to `allowed_hosts`. Its DNS-rebinding
  guard returns 403 to any other name.
- On 0.1.42, set `STRATA_PCIE_FRAC_DEFAULT=old`. Turning tail skip off helps
  decode as much but not reading; turning the prefill CPU share off reads
  fastest and decodes slowest. See [Tuning](tuning.md).
- 0.2 needs an inference key when the server binds to anything but loopback.
- Warm it up before timing anything. The first request after a start is
  many times slower.

**Several sessions.** It needs `"parallel": 2` with `--batch-mtp` for
multi-agent work (test 3 ran this way, 2026-10-07). The 0.2 Gyro build is text
only and was not probed with several sessions.

**Known problems.** The 0.1.42 release default PCIe share halved decode.
0.1.42 did not start for test 2T the first time (the engine exits while
locking about 40 GB of host RAM). The Gyro no-MTP arms failed to start: the
native pack requires speculative decoding.

## Maya

Maya is a Strata-derived engine for GLM-5.3-Flash (321B MoE, 18B active) with
experts tiered over VRAM, RAM and SSD. We run the Maya-S IQ2_XXS pack and, from
2026-10-17, Maya-M IQ2_S.

**Versions and measurements.**

| Version | Date | Result |
| --- | --- | --- |
| 1.0.4 with three patches | 2026-10-08 | Out of the box about 4 tok/s (every VRAM eviction meant a re-read over the network). With the patches (all experts eligible for RAM, evicted experts kept in RAM, GLM tool-call parsing) 17-19 tok/s. Test 1 pass (44 tests), test 2 pass (7 tools, 66 tests, 322 minutes). |
| 1.1.11 | 2026-10-16 | The patches are upstream. Same pack, two rounds each: 17.0 against 14.6 tok/s, first token 18 s against 92 s, 12 of 12 digit strings copied exactly against 9, both needles found against one. |
| 1.1.13 | 2026-10-17 | Maya-S: 12 of 12 digits, 2 of 2 needles. Maya-M IQ2_S: 12 of 12 and 2 of 2, 121 s load, test 3 rubric 12 of 12 on both flavors (5.4-7.1 tok/s). It needed a 100 GB RAM tier; 95 GB held 2,243 of 2,328 slots. |

**Good at.** Running a model of this size on one card at all, and passing both
tests with it. It is slow: the slowest model to pass both tests.

**Several sessions.** Not measured. We treat it as one request at a time.

**Known problems.**

- On 1.0.x, GLM wrote multi-digit numbers split by spaces in tool arguments
  ("1 0", 434 read as 4342) and both test-3 cases timed out. The fault was the
  engine, not the 2-bit weights: it is gone on 1.1.11 and 1.1.13.
- A DFlash2 draft head on Maya-M made decode slower, 10.7 against 15.35
  tok/s without it (91 % of drafts accepted), so it is not used on one 3090.
- A 1-bit Huihui variant failed both tests (repetition), so 1-bit quants of
  this model are not usable for agent work.
- The first load reads about 100 GB over the network: 375 s for Maya-S on 1.1.13.

## ExLlamaV3 (TabbyAPI)

**Versions.** 1.6.1 behind TabbyAPI runs Qwen3.8-27B from EXL3 4.00 bpw
weights, unpatched, with the model's own MTP head or with the DFlash2 drafter.
1.6.2 was measured on 2026-10-16. A 1.6.3 image was built and staged and is not
in use.

**Measured speeds.** Short prompts, thinking off, temperature 0, three rounds
on the 3090 at a 16k window (2026-10-13; the no-drafting row is one round):

| Setup | Code | Prose | Structured | Window that fits, 8-bit cache |
| --- | --- | --- | --- | --- |
| DFlash2 drafter | 158 tok/s | 73 | 181 | 98k |
| Own MTP head | 116 tok/s | 70 | 128 | 196k |
| No drafting | 42 tok/s | 42 | 42 | – |

1.6.2 against 1.6.1, two rounds each, DFlash2, thinking off: 140.1 against
138.6 tok/s, within noise; the needle (48213-KESTREL) was found at 128k, 112k
and 94k windows with no out-of-memory lines.

Served at a 196k window with MTP it is slower than vLLM with MTP at 150k on
every point we measured (115 against 127 tok/s on short code, 72 against 85 at
141k of context, and it reads prompts at about the same 650-740 tok/s). Its
advantage is the larger window at 8 bits.

**Good at.** A larger window than vLLM for the 27B, and DFlash2 drafting
without a patch.

**Several sessions.** Not measured.

**Known problems.** At temperature 0, drafting changed 7 of 15 DFlash2 replies
and 10 of 15 MTP replies (4 of 15 on llama.cpp, none on TensorFold), so drafting
is not exactly neutral. In the one-shot pagoda test the MTP setup scored 0 in five of six
tries (2026-10-14). Set `reasoning_budget_tokens` in the model section; TabbyAPI reads any config
key from `TABBY_<SECTION>_<KEY>` environment variables, so one config file
serves several windows and drafting modes.

## TensorFold

**Versions.** 0.6.6 (the Python engine) with the DFlash2 drafter was the
fastest writer we have measured for Qwen3.8-27B on the 3090: 167-170 tok/s on
short code, 81-84 on prose, 209-211 on structured output, against 158 / 73 /
181 for ExLlamaV3 with the same drafter (in the side-by-side sitting 170 / 84 /
211, ahead by 7 %, 15 % and 17 %), 2026-10-13. Its Python line is frozen
upstream. Upstream's 1.1.0 (2026-10-18) reports native RTX 30 support with
their own receipts for a 3090; we have not built or run it.

**Good at.** Raw decode speed, and exact replies at temperature 0 (drafting
changed none).

**Several sessions.** Not measured.

**Known problems.** It needed a local patch to run below compute capability
8.9, keeps the cache in bf16 only (42k window with the default memory reserve,
73k at the edge), and is not in the router. Parked.

## tqLLM

**Version.** 1.2.3, trial on 2026-10-22 with the Flash-Next IQ3_S GGUF and its
MTP head, against the live llama.cpp entry on the same GGUF.

**Measured speeds.** At a 32k window, code 101.7, prose 79.9 and structured
111.8 tok/s, about 2.5 times llama.cpp's 40.3 / 41.3 / 41.0 on the same
GGUF. Prefill about 2,000 tok/s on a 30k prompt. Short outputs with thinking
off flatter this; the best 262k arm streamed 54 tok/s. First load took 23
minutes cold, then 2-3 minutes.

**Several sessions.** Failed. The multi-session probe passed 3 of 11 checks at
a 32k window, 0 of 11 at 128k, 4 of 11 at 262k with a smaller expert cache and
chunk; the llama.cpp control passed 11 of 11.

**Known problems.** The first prompt of 256 or more tokens that runs short of
VRAM for its prefill buffer fails with an out-of-memory error, and every later
request then fails, even an 18-token one, until the server restarts. At 131072
the first failure came on a 289-token prompt; at 32768 the same prompt works.
The health check keeps answering ok, so a router never notices. Until the first failure a
tool call and a 30k needle passed at 32k, and a 248k needle passed at 262k with
8192-token prefill chunks; the default 262k arm answered long prompts with
HTTP 500. The expert-cache flag had no visible effect on Flash-Next. Not usable
for agents.

## Running engines as containers behind a router

When an engine runs as a container behind llama-swap, restarting
llama-swap does not stop the container. Stop the container first, or the
orphan keeps the GPU and the next load fails. A container that outlives the
router's logical unload also makes the next load look like foreign GPU use.
