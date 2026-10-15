# Vision heads for the catalog models

Survey date: 2026-10-15. This covers every record under `engines/model-meta/` (48 records). The table is `heads.tsv`, one row per record. Nothing here is configured in llama-swap. No llama-swap entry, queue, matrix or tracked file was changed.

## How the survey was done

1. **Catalog.** Each record's `base_model`, `source`, `license`, `vision` block and `used_by` entries were read.
2. **Vision tower.** The base model's HF `config.json` was fetched anonymously and checked for `vision_config` or a `*ForConditionalGeneration` architecture. For native checkpoints (vLLM, SGLang, exllamav3), the local safetensors index was also checked, and visual tensors were counted.
3. **Head candidates.** For each GGUF record, these repos were listed with the anonymous HF API (`?blobs=true`):
   - the model's own GGUF repo
   - the base model's GGUF repos (unsloth, ggml-org, mradermacher, bartowski)

   For every `*mmproj*` file, the survey took the current commit sha, the size and the lfs sha256. F16/BF16 was preferred, then Q8_0. A gated repo was never opened (`gated=auto` means not taken), and no login was used.
4. **Compatibility, read from the GGUF headers and not run on a GPU.**
   - `clip.projector_type` had to be one that the engine's libmtmd knows. llama.cpp 0.6.0 / b11429 (`/app/libmtmd.so.0.6.0`) knows: gemma3, gemma4v, glm4v, glm5v, kimivl, lfm2, pixtral, qwen2vl_merger, qwen3vl_merger.
   - The head's output width had to equal the text GGUF's `embedding_length`. That width is `clip.vision.projection_dim`, or the `mm.2` tensor for pixtral. Every head in `heads.tsv` matches its record's text GGUF.
5. **Fine-tunes.** Where the fine-tune's own repo has no free head, the base model's head was taken. Those rows are marked `base-head-unverified`: the text weights moved during tuning, and nobody has checked that image understanding survived.
6. **Engines.** The llama-swap config was read (read-only copy) to see which entries already pass `--mmproj`, and which engine each entry runs.
7. **Hashes of heads already on disk.** Every `*mmproj*.gguf` already on the NAS was hashed (sha256). All match the current HF lfs sha256 of the file named in `heads.tsv`.

## What was downloaded

The survey downloaded 17 files, **15,777,989,504 bytes (14.69 GiB)**. Each went into a new `vision-head/` subdir of the model's NAS dir. All model dirs are owned by operator, so no sibling dirs were needed. Each `vision-head/` dir holds:

- `download.sh`, pinned to the repo commit sha
- `download.log`
- `SHA256SUMS`
- the hf client's `.cache/`

Every file was checked twice: the byte count against HF, and the sha256 against the HF lfs sha256 (`sha256sum -c`). All 17 passed. There were never more than two downloads running at once. Free space on the NAS went from 4,186,575,224,832 to 4,169,942,790,144 bytes.

| record | file | bytes |
|---|---|---|
| bonsai2-27b | Ternary-Bonsai-2-27B-mmproj-BF16.gguf | 931,145,856 |
| bonsai2-27b-ada-surgery | Ternary-Bonsai-2-27B-mmproj-BF16.gguf | 931,145,856 |
| devstral-small-2-24b | mmproj-F16.gguf | 878,054,048 |
| flashnext-abliterated-s15 | Qwen3.8-Flash-Next-Abliterated-s1.5-mmproj-BF16.gguf | 907,543,008 |
| glm-5.3-flash-huihui-abliterated | mmproj-model-bf16.gguf | 1,164,010,176 |
| glm-5.3-flash-orcarouter-uncensored | mmproj-F16.gguf (unsloth base) | 1,128,047,296 |
| mimo-v2.6-9b | MiMo-V2.6-Distill-Qwen-9B.mmproj-f16.gguf | 918,166,080 |
| orcarouter-flash-next-uncensored | mmproj-F16.gguf (unsloth base) | 904,004,000 |
| orcasaq2-cyber-27b | mmproj-F16.gguf (unsloth base) | 927,607,488 |
| q38-27b-coder390-et | GGUF/mmproj-Qwen3.8-27B-Q8_0.gguf | 629,247,008 |
| q38-27b-cyber-agentic | mmproj-Qwen3.8-27B-Uncensored-Cyber-BF16.gguf | 931,146,272 |
| q38-27b-cyber-q5 | same file | 931,146,272 |
| q38-27b-cyber-q6q8 | same file | 931,146,272 |
| qwen3.6-27b | mmproj-F16.gguf | 927,607,360 |
| qwen3.8-27b | mmproj-F16.gguf | 927,607,488 |
| qwen3.8-flash-next-unpruned | mmproj-Qwen3.8-Flash-Next-BF16.gguf | 907,543,008 |
| tiel-coder-35b-mtp | mmproj-BF16.gguf | 902,822,016 |

Some of these files have the same bytes as each other:

- the two bonsai heads
- the three cyber heads
- orcasaq2 and qwen3.8-27b
- qwen3.8-flash-next-unpruned and the head already in qwen3.8-flash-next-coder
- tiel-coder-35b-mtp and the tiel heads already on disk

They were kept as separate copies, one per model dir, with no hard links.

**Already on disk, not downloaded again (13 records):**

- cyber-tiel-coder-35b, tiel-coder-35b, tiel-coder-35b-q6
- flashnext-heretic2
- gemma-4-26b-a4b, gemma-4-31b
- glm-5.3-flash-maya (in `vision/`)
- qwen3.6-35b-a3b
- qwen3.8-flash-next-coder
- swift15-flash-next
- thinkingcap-27b-heretic (Q8_0)
- qwen3vl-8b, qwen3vl-32b

## What was not downloaded, and why

- **orcarouter's own heads** (update 2026-10-15): both repos are `gated=auto`. The operator accepted both gates on 2026-10-15, and the heads were then downloaded with his token, pinned and sha256-verified, into `vision-head-own/` next to the base heads (which stay in `vision-head/`). Both rows are now `head`.
  - `orcarouter/GLM-5.3-Flash-Uncensored-GGUF` @8bd0d5368a: mmproj-GLM-5.3-Flash-Uncensored-F16.gguf, 1,164,010,080 bytes, sha256 e951b3b1... No engine we have loads this text model with a vision projector, so no entry uses it yet.
  - `orcarouter/Qwen3.8-Flash-Next-Uncensored-GGUF` @d27c0a1544: mmproj-Qwen3.8-Flash-Next-Uncensored-F16.gguf, 907,543,296 bytes, sha256 f0f352a9... The entry `lcpp6-orcarouter-fn-uncensored-vis` uses it.

  `orcarouter/OrcaSAQ-2-Cyber-27B-Uncensored-GGUF` (also gated) lists no mmproj at all, so orcasaq2-cyber-27b stays on the base head (`base-head-unverified`).
- **ThinkingCap f16 head.** It is 927,607,552 bytes in the same mradermacher repo. It was skipped because the record already has the Q8_0 head on disk.
- **Native checkpoints (5 records).** Nothing to download: the vision weights are inside the served checkpoint. Those records are:
  - the turboderp Qwen3.8-27B exl3
  - the turboderp Flash-Next exl3
  - the vLLM gemma-4 AWQ
  - the two HyperQwen W4A16 checkpoints
- **Text-only models (13 records).** Their configs have no vision tower, so no head exists:
  - glm-4.5-air, glm-4.7-flash
  - jan-nano-128k, kolibri-1, lfm2.5-24b-a2b, nanbeige4.2-3b
  - the three nemotron records
  - qwen3-235b-a22b, qwen3-4b-instruct, qwen3-coder-30b-a3b
  - smollm3-3b
- **Two NAS heads outside the catalog.** These belong to no catalog record, so they are not in the table:
  - `vision/minicpm-v4.7-35b-a3b/mmproj-model-f16.gguf` (1,119,575,840 bytes)
  - `vision/minicpm-v4.7-1b/mmproj-model-f16.gguf` (1,110,117,984 bytes)

  `llm/winnow-e4b/gguf/mmproj-Winnow-E4B.gguf` is in the same situation.

## Engine caveats

- **Strata and Maya images are text-only builds** with no vision encoder. Entries named strata-* or maya-* cannot use a head, even where one is on disk.
- **GLM-5.3-Flash has two head formats.**
  - Mainline (0.6.0) knows `glm5v` and loads text GGUFs of arch `glm5-next`. That covers huihui and the unsloth base.
  - The glm5next fork (`engines/llamacpp-glm5next`) loads text GGUFs of arch `glm5next` (orcarouter, Maya) and knows projector `glm5next`, not `glm5v`.
  - So the unsloth glm5v head downloaded for orcarouter GLM pairs with no engine that can load the orcarouter text. In the fork, the Maya head (`glm5next`) is the likely partner, but this is untested.
- **The exl3 Qwen3.8-27B entries set `vision: false`.**
- **The flashnext SGLang entries set `SGLANG_EXL3_VISION=1`.**
- **The gemma vLLM entry** leaves images on (vLLM default).
- **HyperQwen:** whether its launcher passes images is not verified.
- **Bonsai:** the Prism fork's libmtmd has `qwen3vl_merger`. The `llamacpp-bonsai-ada` source tree has it too. Neither has been loaded with a head.

## VRAM per head (ESTIMATE, not measured)

Estimate = mmproj weights + the CLIP compute buffer. llama.cpp sizes the compute buffer at the warmup image:

- qwen3vl_merger and glm5v: 46x46 = 2116 output tokens
- pixtral and gemma4v: 256 output tokens

**Assumptions.** The buffer ranges below are rough guesses, assuming flash attention in the vision tower. Expect more without flash attention, or when `--image-max-tokens` is raised. The image tokens also take space in the text model's KV cache and its prompt batch.

**How to measure.** Load a head once and read `clip ... compute buffer size` from the llama-server log.

| projector | heads here | weights | compute buffer (est.) | total (est.) |
|---|---|---|---|---|
| qwen3vl_merger, BF16/F16 | Qwen3.6/3.8, Flash-Next, Tiel, Bonsai, MiMo, Qwen3-VL | 0.90-1.20 GB | 0.5-1.5 GB | 1.4-2.7 GB |
| qwen3vl_merger, Q8_0 | coder390, ThinkingCap | 0.63 GB | 0.5-1.5 GB | 1.1-2.1 GB |
| glm5v (BF16/F16) and glm5next (F16) | GLM-5.3-Flash | 1.13-1.16 GB | 0.5-1.5 GB | 1.6-2.7 GB |
| gemma4v | Gemma 4 26B / 31B | 1.19-1.20 GB | 0.2-0.5 GB | 1.4-1.7 GB |
| pixtral F16 | Devstral Small 2 | 0.88 GB | 0.2-0.5 GB | 1.1-1.4 GB |

## Tokens per image

These figures come from the GGUF hparams and the mtmd preprocessing rules. The rules were read from llama.cpp `tools/mtmd/clip.cpp` in a recent mainline checkout on Saturn (`~/build/llamacpp-kolibri`), not from the 0.6.0 image's own source. The token counts are approximate.

| projector | px per output token | token limits (default) | 1280x720 screenshot |
|---|---|---|---|
| qwen3vl_merger | 32 (patch 16, merge 2) | 8-4096 | about 40 x 23 = **~920 tokens** |
| glm5v | 28 (patch 14, merge 2), ceil-aligned | 16-8000 (min/max pixels 12,544-6,272,000) | about 46 x 26 = **~1,200 tokens** |
| glm5next (Maya head) | 28 (patch 14, merge 2) | 16-8000 | **~1,200 tokens** |
| pixtral (Devstral) | 28 (patch 14, merge 2) | 8-1024 | 46 x 26 = 1,196 is over the cap, so the image is scaled down: **~1,000 tokens** |
| gemma4v | 48 (patch 16, pooling 3) | 70-1120 | about 27 x 15 = **~400 tokens** |

Qwen-VL heads print a warning that grounding (boxes, coordinates) needs at least 1024 image tokens (`--image-min-tokens 1024`).

## Not verified

- **No image has been run through any head on any engine.** The GPU was not used.
- **Fine-tunes may have lost image ability.** Every `base-head-unverified` row, and every fine-tune whose author ships a head that is really the base head (for example coder390: its general.name is "Qwen3.8-27B"), may have lost image understanding during text tuning.
- **Fork engines have not loaded a head.** That covers the Prism fork, bonsai-ada and the glm5next fork.
- **HyperQwen image serving.** The weights carry the vision tower, but it is unknown whether the launcher passes images.
- **VRAM figures are estimates.**
- **One source repo now refuses the anonymous API.** `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF` answered 401 on a recheck. The coder head's hash had matched earlier the same day, and an identical file is public in `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`.
