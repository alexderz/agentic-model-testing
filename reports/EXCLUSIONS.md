# Excluded models

A model is excluded only on evidence from a completed run, never on size or
reputation. The failing result stays in `results-r2/` as the record.

Re-qualify any of these by deleting its row and running the gates plus one
case; a new release under the same name is a different model.

| model | reason | evidence |
|---|---|---|
| `mimo-v2.6-9b` | stack incompatibility, not capability | Emits fully concatenated `<tool_call><function=x><parameter=y>` XML. No parser in llama.cpp b1-4260903 terminates on it, so every turn runs to the output-token limit and is rejected. Reproduced outside the agent in one request. A template patch cannot fix it — the model was trained to emit that form. |
| `smollm3-3b` | cannot do agentic work | `smollm3-3b-max`: 1 turn, 43.8s, zero files written. |
| `qwen3-4b-instruct` | known broken output | `qwen3-4b-max`: 509 lines across 2 files, **none of which compile** (`py_syntax_ok` 0/2). Produces confident, non-functional Python. |
| `jan-nano-128k` | cannot do agentic work | **wave A (2026-09-30), test 1, gated config 131072/q8_0, 14,876 MiB.** 41 tool calls, **zero files written**, empty work tree, stopped naturally (`reason: stop`) so nothing killed it. Tool mix was `webfetch` 15, `task` 16, `bash` 10, `write`/`edit` **0**. Its bash calls were `opencode pair` (x4) and `curl -fsSL https://opencode.ai/v2/install \| bash` — it spent the case trying to install and run the agent harness it was already running inside, rather than attempting the task. Consistent with test 1 (`jan-nano-max`: 1/5 checks, 27 lines, 624 turns). Previously listed as borderline; this settles it. || `qwen3vl-8b` | source does not import | **wave A, test 1.** 0/5 checks. `homeassistant-cli.py:10` runs `last_request_time = time.time()` with no `import time`; `httpx`, `argparse`, `json`, `Dict`, `Any` used and never imported; `HA_TOKEN` referenced and never defined. `ruff --select F821` reports 16 undefined names. 191 lines, one file, no tests. The runner recorded it `ok` because `ok` only means it wrote a file and stopped. |
| `bonsai2-27b` | does not implement the API it claims | **wave A, test 1.** 2/5 checks. `grep -rl 'api/states'` over its source returns nothing: `/api/states`, the central endpoint, is absent. 16 of its 20 subcommands target paths that do not exist (`/api/entities`, `/api/system/health`, `/api/webhooks`, `/api/stats/<date>/summary`). Its 68 passing tests validate a fabricated surface. No README; ships one failing test. The HTTP client itself is the best in the cohort, which is what makes this a confabulation finding rather than an incompetence one. |

## Deliberately NOT excluded

| model | why it stays |
|---|---|
| `nanbeige4.2-3b` | 3B, but produced 1284 lines across 9 files that all compile, in 104 turns — more working output than several models 10-70x its size. Size is not the predictor. |
| `nemotron3-nano-30b` | Weak API coverage (2/9) and it never queried the live endpoint, but it reliably produces compiling code. That is a quality finding, not grounds for exclusion. |
| `qwen3-235b-a22b` | Slow (2221s for 146 lines) and a poor fit for a 24 GB card, but functional. Its problem was configuration: it ran on 9 GB of 24 until the fill retune. |

## Cannot be run on this rig (not a capability judgement)

These are not exclusions in the sense above. Nothing was measured about the
model's ability, because no configuration of this hardware can load it. The
row records what was checked, so the question does not get re-opened from
memory.

| model | checked | finding |
|---|---|---|
| `NaiveAI/Naive-N0.5-Flash` | 2026-09-28 | 309B MoE, 15.5B active, published 2026-09-27. **No GGUF exists in any repo** (upstream, FP8, FP8-Draft, or the third-party NVFP4), and llama.cpp cannot produce one: the architecture is `naive_n05_flash` with `custom_code`, a hybrid of sliding-window and DeepSeek Sparse Attention (39 SWA + 9 DSA layers). DSA itself only exists in llama.cpp draft branches for DeepSeek V3.2/V4; this arch is not implemented anywhere. Sizes: BF16 617.8 GB, FP8 315.1 GB, NVFP4 182.6 GB. Titan has 125 GB RAM (111 available) + 24 GB VRAM = ~135 GB addressable, so even the smallest variant is 1.35x over before any KV cache, against a model whose selling point is a 1M-token context. FP8 and NVFP4 also need Ada/Hopper/Blackwell tensor cores; the 3090 is Ampere. Reported local runs of this class of model use dual 96 GB Blackwell cards. Three independent blockers, none of them tunable. |

Re-check when a GGUF appears **and** llama.cpp gains the architecture. Both
are required; either alone is not enough.

## qwen3-235b-a22b (2026-10-02)

Does not fit Titan. Q4_K_M weights are 132 GiB against 125 GB of RAM. An
offloaded model must load with `-lm none` (see `lib.sh` set_variant), so the
experts have to fit in RAM. Gating at `-ncmoe 82` failed five times with
"upstream command exited prematurely", about 2.5 minutes each. A smaller quant
(Q2/IQ3 under ~95 GiB) would be needed to test it.

## nemotron3-nano-30b (2026-10-03)

Failed test 1 twice: 2/5 at 131k (wave A), 2/5 again at 425,984 context with
the GPU filled (batch 2). Both times it quit within minutes with 2-3
subcommands, no working reads and a failing test. Fast (91 tok/s) but does not
finish the task.

## nanbeige4.2-3b (2026-10-03)

Failed test 1 twice: 2/5 (wave A), then 1/5 at 204,800 context (batch 2), where
it crashed on input and made no working reads. A 3B model is out of its depth
on this task.

## qwen3.6-35b-a3b and qwen3.6-27b (2026-10-03)

Dropped from further testing by the operator. Both passed test 1 (5/5) but
failed test 2's MCP handshake in wave B: the 35B-A3B wrapped initialize and
tools/list in a tool-result shape and replied to a notification; the 27B has no
initialize method at all. The two queued 35B-A3B repeat runs were removed.
qwen3.8-27b supersedes both.

## Operator cut, 2026-10-03 (wave B onward)

Dropped from further testing: `flashnext` (SGLang/EXL3 fork, crashed under
multi-session use), `flashnext-heretic2` and `flashnext-abliterated-s15`
(`orcarouter-fn-uncensored` kept as the best uncensored Flash-Next: 54 tests
and 13 subcommands on test 1 vs 25-26), `qwen3-coder-30b-a3b` (Qwen3 family),
`bonsai2-27b-pq2`, `devstral-small-2-24b`, `nemotron3-super-120b`.
Kept: Qwen3.8 27B (+cyber), Flash-Next unpruned / swift15 / coder / orcarouter,
Tiel (until the quant comparison is in), GLM (not cut), Gemma 4 26B-A4B and 31B.

## glm-4.7-flash and glm-4.5-air (2026-10-04)

Dropped from further testing by the operator: "just not cutting it". Both built
a test-2 server that no MCP client can connect to: 4.7-Flash rejects numeric
JSON-RPC ids, 4.5-Air has no initialize method. 4.7-Flash had also split 2/5
and 5/5 on test 1; 4.5-Air ran at 3-6 tok/s with experts in RAM.
