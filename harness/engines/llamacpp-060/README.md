# llama.cpp v0.6.0 as a second llama.cpp engine

Claw's llama-swap image on titan carries llama.cpp 0.4.1-dev (commit 4260903).
v0.6.0 (2026-10-05) runs beside it from the official image, untouched by and
not touching Claw's setup:

    ghcr.io/ggml-org/llama.cpp:server-cuda12-b11429
    = ghcr.io/ggml-org/llama.cpp@sha256:a863a2d1dc2cbc5326c995ae380eec9c57f37a7e1cac944f0c6f43e4e9afff23
    llama-server --version: 0.6.0-dev (build 11429, commit d81235049), 4.4 GB, pulled 2026-10-05

Pulled with `nice -n 19 ionice -c3 podman pull` while a Strata case ran. CUDA 12
build; titan's driver is 615.71.09.

## Why (what the release changes for us)
- Speculative decoding: probabilistic acceptance for simple and MTP drafts
  (#27694); n-gram drafts no longer rejected at temp > 0 (#29924); CUDA graphs
  for MTP drafting (0.5.0, #28549). Our agent runs sample at temp 1.0.
- CUDA MoE: MMVQ shared-expert fusion (ggml 0.26.0).
- KV restore fixes (#28498, #27530): related to the parent-cache eviction seen
  in the OrcaSAQ verifier run.
- Risks: the batch API rewrite (`llama_batch_ext`) moved server and speculative
  decoding; stricter GGUF size validation may refuse odd quants. The new FP4
  (NVFP4/MXFP4) path needs Blackwell: no gain on the 3090.

## Prep (queue step, `tools/llamacpp060_prep.py`, log `results-wave-b/llamacpp060.log`)
A/B at 49k, thinking off, same flags, old build (podman exec in llama-swap) vs
v0.6.0 (throwaway container, `--network none`), plus v0.6.0-only variants:

| model | same flags | v0.6.0 extras |
|---|---|---|
| orcasaq2-cyber-27b | DFlash2 n4 | DFlash2 n8; DFlash2 n4 + ngram-mod |
| q38-27b-cyber | no spec | MTP n3 (heads are in the GGUF, never used) |
| cyber-tiel-coder-35b | -ncmoe 20 | (MoE fusion only) |
| orcarouter-fn-uncensored | -ncmoe 40 | MTP draft n3 (shipped draft GGUF, never used) |
| qwen3.8-flash-next-unpruned | -ncmoe 39 | orcarouter's MTP draft n3 (same base model); unsloth MTP head shared-Q8_0 n1 and n3; unsloth MTP head Q8_0 n3 |

"Qwen4Exp" in llama.cpp is Qwen3.8-Flash-Next: v0.6.0 adds its MTP (#29761: 1.55x decode,
0.64 acceptance, iq4_xs on DGX Spark), halves indexer score memory (#29825) and prefetches
PLE rows (#29599). None of our Flash-Next GGUFs carry nextn layers (checked 2026-10-05);
orcarouter ships them as a separate 3.9 GB draft GGUF.

Winner per model (best mean of decode and quote, prefill within 10% of best) is
load-checked at the entry's full context (10% less per failure), then added as
`lcpp6-<model>`: container `llamacpp6`, llama network, port 8096, no -p,
cap-drop ALL, models :ro, thinking on, budget baked in (container entries run
as written). Results JSON: `results-wave-b/results-llamacpp060.json`.

## Flash-Next MTP heads (downloaded 2026-10-05)
`unsloth/Qwen3.8-Flash-Next-GGUF` rev 38bb39ee97821de2c9009abb7e93950eec396e66, `MTP/` only,
on Saturn at `/srv/store/models/llm/qwen3.8-flash-next-mtp/` (script `download.sh` there):
`mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf` (2.6 GB, borrows the main model's embedding and
output projection) and `mtp-Qwen3.8-Flash-Next-Q8_0.gguf` (3.9 GB, self-contained). unsloth's
README (written before v0.6.0) says mainline cannot use them and points at a fork; v0.6.0
merged Flash-Next MTP (#29761), but whether it can borrow tensors across models for the
"shared" head is unknown, hence both. kingjones777 measured MTP on Flash-Next: draft n1 never
lost, n4 lost 10-14% on code and long documents, and warned about MTP above 32k context on
their ROCm fork. Our probe runs at 49k; the full-context check loads at 262k.

## Decision models (classifiers for `/v1/systemone`), downloaded 2026-10-05
Operator asked for all of them on the NAS. Saturn `/srv/store/models/classify/ggml-org-decision/`
(titan: `/models/classify/ggml-org-decision/`), script and log beside them. Q8_0 + Q4_K_M + mmproj
(BF16 skipped, ~150 GB; Laya and Julia-1 whole since they are tiny). The existing `classify/laya*`
folders belong to someone else and are untouched.

| dir | repo @ rev | Q8_0 | notes |
|---|---|---|---|
| julia-1 | ggml-org/Julia-1-GGUF @ 16fee1794920 | 0.16 GB | |
| laya | ggml-org/Laya-GGUF @ 222650077002 | 0.42 GB | |
| kev-4b | ggml-org/Kev-4B-GGUF @ d924f2e2c387 | 4.2 GB | |
| lev | ggml-org/lev-GGUF @ 3e9286a79ae8 | 4.2 GB | |
| nimble-9b-v3 | ggml-org/Bespoke-Nimble-9B-v3-GGUF @ a72bdbadb355 | 8.9 GB | |
| clef-flash | ggml-org/Clef-Flash-GGUF @ 4a192915ef97 | 9.0 GB | vision |
| clef | ggml-org/Clef-GGUF @ 63840a1a68cb | 26.8 GB | vision |
| openjev | ggml-org/OpenJev-GGUF @ 10840f375658 | 26.6 GB | vision |

They answer structured questions about an input (choice / yes-no "noul" / score) and need
llama.cpp v0.6.0 (`lcpp6` image). No llama-swap entries yet.
