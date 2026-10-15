# Model settings audit, 2026-10-03

Operator asked for every stack and model still in the running to be checked.
Method: dump each llama-swap entry; read each GGUF's embedded sampling and chat
template; capture what OpenCode actually sends (a logging stub server, one run
per model id); confirm on a live model what llama.cpp applies (`/props`, and a
real tool-call request).

## What the client sends

OpenCode 1.18.32 sends **no sampling parameters** for any of our models: no
temperature, top_p, top_k, min_p, and no `chat_template_kwargs`. Only
`max_tokens` (32000, or our configured output limit), `tool_choice: auto` and
streaming. So the **server defaults decide everything**.

## llama.cpp

llama.cpp applies a GGUF's `general.sampling.*` keys as its defaults (verified
on tiel-coder-35b-q6: temp 1.0, top_k 20, top_p 0.95 from the GGUF). Anything
the GGUF does not set falls back to llama.cpp's own defaults: temp 0.8, top_k 40,
top_p 0.95, **min_p 0.05**.

| model | sampling in effect | model's own guidance | thinking | finding |
|---|---|---|---|---|
| qwen3.8-27b, q38-27b-cyber | 1.0 / 20 / 0.95, min_p **0.05** | min_p 0 | on (template default) | min_p differs |
| tiel-coder-35b, -q6 | 1.0 / 20 / 0.95, min_p **0.05** | min_p 0 | on | min_p differs |
| cyber-tiel-coder-35b | 0.6 / 20 / 0.95, min_p 0 | (abliterator's choice) | on | ok |
| Flash-Next unpruned / swift15 / coder / orcarouter | 1.0 / 20 / 0.95, min_p **0.05** | min_p 0 | on | min_p differs |
| glm-4.7-flash | 1.0 / **40** / 0.95, min_p **0.05** | temp 1.0, top_p 0.95 | on | top_k/min_p from llama.cpp |
| glm-4.5-air | **0.8 / 40 / 0.95, min_p 0.05** (nothing embedded) | not stated in its config | on | runs entirely on llama.cpp defaults |
| gemma-4-26b-a4b, gemma-4-31b | 1.0 / 64 / 0.95, min_p **0.05** | 1.0 / 64 / 0.95 (Google) | **OFF** (`enable_thinking` defaults to false) | **thinking never enabled** |

Other llama.cpp findings:

- **Tool calls and reasoning are parsed per request** (`/props` shows
  `Content-only` / `reasoning_format: none` only as idle defaults; a real
  tool-call request returned a structured `tool_calls` and separate
  `reasoning_content`).
- **Unused vision encoders**: tiel x3 and swift15 load an mmproj (about 0.9 GB
  BF16 each). The tests are text-only, so that VRAM could hold context or
  experts instead.
- **No speculative decoding on any Qwen3.8 GGUF.** Several ship MTP layers
  (`q38-27b-cyber` "plus-mtp", orcarouter "ships an MTP draft"); this llama.cpp
  build supports `--spec-type draft-mtp`. Untested here; potentially a large
  speed-up for the slow Flash-Next tier, and lossless.
- Reasoning budget unlimited everywhere (no `--reasoning-budget`). OK.
- Context and KV type are set per case by `tools/fill_vram.py`; OpenCode gets
  the matching limit (`run-case-sandboxed.sh`). OK.

## vLLM (HyperQwen)

- Sampling from the model's `generation_config.json`: temp 1.0, top_k 20,
  top_p 0.95; vLLM's min_p default is 0. Matches Qwen guidance.
- Thinking on (qwen3 reasoning parser), tool parser `qwen3_coder`. OK.
- KV cache: FP8 (150k profile), KVarN 4/2-bit (240k). Noted, by design.
- So qwen3.8-27b on vLLM ran with min_p 0 while the same model on llama.cpp ran
  with min_p 0.05. A small difference in favour of neither, but a difference.

## Changes (applied from the Gemma rerun onward, untested models only)

1. Gemma 4: `--chat-template-kwargs '{"enable_thinking":true}'` and
   `--min-p 0`. Rerun all six Gemma cases; the no-thinking runs stay as a
   baseline.
2. `--min-p 0` on every remaining llama.cpp model (Flash-Next x4, GLM x2), to
   match model guidance and vLLM. Already-graded runs keep their min_p 0.05,
   recorded here.
3. GLM (both): the GLM-4.7-Flash card gives agentic-coding settings
   (SWE-bench / Terminal Bench): **temperature 0.7, top_p 1.0**; general
   default is 1.0 / 0.95. GLM-4.5-Air's card and config state none, so it was
   running on llama.cpp's generic 0.8 / 40 / 0.95 / 0.05. Use the family's
   coding settings for both: `--temp 0.7 --top-p 1.0 --top-k 0 --min-p 0`.
   The card also recommends "preserved thinking" for multi-turn agent work;
   that needs the client to send prior reasoning back, which OpenCode does not
   appear to do -- not something a server flag can fix.
4. Drop the unused mmproj from swift15 for the test (more VRAM for experts).
5. Probe MTP speculative decoding on the Flash-Next GGUFs; enable it where it
   loads and is accepted.
