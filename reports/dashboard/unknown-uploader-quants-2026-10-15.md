# Quants from unknown uploaders, setup check of 2026-10-15

The operator asked about the items the 2026-10-15 setup check called "a quant from an unknown uploader". These are the
HF model trees (quantized, finetune and adapter) of our hot watchlist model rows, plus the drafter searches, created
since 2026-10-08. All of those rows come from models the operator bookmarked.

- **Source.** 184 repos. Sizes, dates, shas, downloads and likes come from `api/models/<id>?blobs=true`, read on
  2026-10-15. Engine needs and methods come from the model cards. Those cards are untrusted: the claims below are the
  uploaders' own and are not measured by us.
- **Mirrors.** "Mirror" means every GGUF blob has the same LFS sha256 as the named original repo.
- **Fit.** Fit is judged for titan: one RTX 3090 (24 GB) and 125 GB RAM for MoE offload.
- **Triage only.** The test / watch / skip calls are recommendations, not download proposals. Before any download,
  write a proposal under DAILY-SETUP-CHECK.md hard rule 1: full revision sha from the API, include globs, exact
  selected bytes, target directory and free space.
- **Nothing here is on disk** (hard rule 4 checked: no hit in `engines/model-meta`, `engines/entry-specs`,
  `CANDIDATES.md` or `TAKEOVER.md`).

## Worth a look

| repo (sha) | base | quant, size | created | dl / likes | what is unusual | fits 3090 | call |
|---|---|---|---|---|---|---|---|
| lapadatbogdan/GLM-5.3-Flash-REAP144-Coder-GGUF (2b279393) | GLM-5.3-Flash | Q4_K_M 97.6 GB, Q3_K 71.4 GB, IQ2_S 54.8 GB, IQ2_XXS 45.3 GB; MTP block 2.6 GB | 10-13 | 10933 / 11 | REAP expert pruning: 144 of 288 experts per layer, chosen on agentic coding sessions, with an imatrix from the same sessions (161B-A17B). Card: Q4_K_M 48/48 on its own 48 Python-repo attempts, IQ2_XXS loops; runs on Maya | with RAM offload only (all four are 45-98 GB). Q4_K_M is the same footprint as our Maya-S IQ2_XXS (96.5 GB) | **test**: Q4_K_M (or IQ2_S) on Maya against maya-glm-5.3-flash |
| sam33339999/HuiHui-Qwen3.8-27B-Coder390-abliterated-MTP-Exl3-3.5bpw (acb70916) | huihui Coder390-EfficientThink abliterated (Qwen3.8-27B) | EXL3 3.5 bpw, 15.4 GB, MTP head in the same files | 10-13 | 34 / 0 | an abliterated Coder390 (we run nerkyor's Coder390 GGUF), exllamav3 1.4.2, made for a 3090; no eval of the quant | yes, ~8 GB for context | **test** in TabbyAPI exl3 for the uncensored round |
| parth-thakre/Qwen3.8-27B-DFlash2-EXL3-3.0bpw (3d915b12) | incoai/Qwen3.8-27B-DFlash2 (drafter) | EXL3 3.0 bpw, 0.9 GB | 10-13 | 44 / 1 | a DFlash2 drafter for ExLlamaV3. Our `exl3-qwen3.8-27b-dflash2` uses z-lab's bf16 drafter | yes with the exl3 27B target (3.5 bpw ~15 GB); saves VRAM against the bf16 drafter | **test** (cheap) as the drafter of the exl3 27B entry |
| Pragmatism0220/Huihui-v2-Qwen3.8-Flash-Next-GSQ-RCO-Strata-abliterated-direction-GGUF (77407f6f) | Flash-Next (ISTA GSQ-RCO GGUF) | control vector, 0.5 MB | 10-15 | 0 / 1 | huihui's refusal direction as a llama.cpp control vector, made for the ISTA GSQ-RCO GGUFs we already have (flash-next unpruned IQ3_S) | as the base entry: the GSQ-RCO IQ3_S already runs on titan, the vector adds no weight | **test** (cheap) on the GSQ-RCO IQ3_S entry, for the uncensored round |
| Derpyhue/Qwen3.8-27B-abliterated-2.55bpw-SC-SH (e10036cb) and -2.60bpw-SC-SH (9f3435ef) | huihui Qwen3.8-27B abliterated | EXL3 2.55 / 2.60 bpw, 11.8 / 12.0 GB | 10-14 | 17 / 0, 6 / 0 | per-tensor bit allocation (sc_optimize, scaled Hessian), KLD table on the card | yes, both (~12 GB), room for long context | **watch**: 2.6 bpw on a dense 27B is low; take it only if we want a small uncensored exl3 27B |
| Muyuxiao/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF (c76c0aa5) | trohrbaugh Qwen3.8-27B heretic-ara | 105 GGUFs, IQ1_S to BF16, each with and without MTP, plus "multilingual" imatrix variants (Q4-class ~16-17 GB) | 10-14 | 8981 / 0 | Heretic ARA abliteration plus two more refinement passes ("RVN"), imatrix; roleplay-tagged | Q4-class (~16-17 GB): plausible GPU fit with bounded context. Larger variants need their own RAM-offload sizing; BF16 (~54 GB) does not fit in VRAM. Not all 105 fit | **watch**: an uncensored-round alternative to huihui; roleplay focus |
| JRamirez-UAB/Ornith-1.5-35B-A3B-EXL3-4.00bpw-24GB (4a5abcdc) | Ornith-1.5-35B-A3B | EXL3 4.00 bpw, 19 GB (4.50 and 5.00 on branches) | 10-09 | 170 / 0 | SC bit allocation, 6-bit head, 4-bit MTP. Card: 262k context with vision on one 3090, 24/30 agent tasks, 114 tok/s, but only through vLLM 0.31 + exllamav3 1.5.1 + two third-party plugins | 4.00 bpw: yes per the card (19 GB plus context); the 4.50 / 5.00 branches were not sized | **watch**: never install its plugins; if anything, try the weights in our TabbyAPI exl3 |
| CCSSNE/HauhauCS-Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-MTP (a5610e1c) and the 31B one (c247bac0) | Gemma 4 26B-A4B / 31B QAT | Q4_K_M 16.8 / 18.7 GB, MTP head 0.3 GB, mmproj | 10-11 | 571 / 0, 444 / 0 | HauhauCS uncensoring from the QAT weights, with MTP; CCSSNE is a re-uploader, so the original was not checked | yes at Q4_K_M, the 31B with less room for context | **watch**: for an uncensored Gemma, find and pin HauhauCS's own repo first |
| JThomas-CoE/coe-tiel-coder-python-n1-55-19b-a3b-q4_k_xl (9e67495c) | Ornith-1.5-35B-A3B (Tiel coder) | Q4_K_XL 12.5 GB | 10-14 | 42 / 0 | expert surgery: 256 → 128 experts per layer for Python (19B-A3B); needs an empty-think assistant prefill | yes | **watch**: a narrow Python specialist, and the prefill fights our harnesses |
| vvsotnikov/Qwen3.8-27B-test-DFlash2-v0.3-GGUF (b511d529) | a community DFlash2 drafter (step 500) | BF16 GGUF 3.9 GB | 10-14 | 269 / 0 | for llama.cpp `--spec-type draft-dflash`; "test" in its own name | yes beside a 27B target | **watch**: we have z-lab's DFlash2 |
| Launch80/Qwen3.8-27B-DFlash2-Int4-baked-drafter (984a35c6) | z-lab DFlash2 | GPTQ Int4 1.5 GB | 10-13 | 25 / 0 | vLLM dflash drafter; card: 80.5 → 96.7 tok/s against MTP k=6 (Intel XPU) | the drafter yes; the vLLM target was not sized | **watch** for HyperQwen (slot 1) |
| MorinoNushi/GLM-5.3-Flash-Heretic-Abliterated-LoRA-V3-GGUF (c5623df0) | GLM-5.3-Flash | rank-1 LoRA, 0.1 GB | 10-13 | 61 / 1 | a Heretic abliteration as a LoRA for mainline llama.cpp; card: 14/140 refusals, KL 0.238 | the LoRA is tiny, but it needs a llama.cpp GLM-5.3-Flash GGUF (RAM offload, 45-98 GB class); Maya takes no LoRA | **watch** |
| Wladastic/Qwen3.8-Flash-Next-Ombro-v13b-GGUF (4b20669b) | Flash-Next | custom mix (experts Q5_1 / Q8_0), 118.9 GB | 10-15 | 0 / 0 | imatrix, its own per-tensor recipe, llama.cpp-compatible | very tight: 119 GB on 24 + 125 GB, with titan already using RAM | **watch** |
| msuiche/gemma-4-26B-A4B-it-abliterated-GLP-27-L3-29-a0.5 (07ce5ad4) | Gemma 4 26B-A4B | control vector, 301 KB (gated) | 10-11 | 2 / 0 | a projective refusal control vector | as its Gemma 4 26B-A4B base model (~17 GB at Q4); the vector adds no weight | **watch** |

## Skip

| repo | why |
|---|---|
| Petyx123/ and robertbschuette/Huihui-GLM-5.3-Flash-abliterated-GGUF | mirrors of huihui-ai c43a9946 (47 of 47 blobs), which the watchlist already tracks |
| Weirdo333/Huihui-Qwen3.8-27B-abliterated-GGUF, josecjr23232/gen-llm-qwen38 | mirrors of huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF 1c69098e. If wanted, take the original, which has GSQ-RCO IQ3_S with MTP at 12.1 GB |
| UnitGrief/gemma-4-31B-it-GGUF | a mirror of lmstudio-community 67a72ce4 |
| axteam/gemma-4-31B-it-GGUF | plain Q4_K_M; we run Google's QAT q4_0 |
| CanadaApollo6/Ornith-1.5-35B-A3B-M3TiS-3090 | 16 GB, made for a 3090, and the card claims ~545 tok/s. But it ships a prebuilt `bin/tensorfold-native` binary and a run script from an unknown uploader, and links a different TensorFold org (machinegenieorg) from the one we track (ashhart). Never run its binary; TensorFold stays parked |
| robertbschuette/Qwen3.8-27B-TURBO-Fable-Cold-Fusion-…-MTP-GGUF, Solstice-AI/Qwen3.8-27B-Turbo-Brilliance-50X-…-UltraOptimised | DavidAU merges with marketing claims ("exceeds … in ALL … benchmarks"), not quants of what we run |
| Baekpica/GLM-5.3-Flash-VQ-GGUF, fly9i/GLM-5.3-Flash-SPX1-V1.1, nibor1896/GLM-5.3-Flash-MUL1K3 | each needs its own engine (a VQ reader, 2× DGX Spark, crow-nest on a 32 GB card with NVFP4) |
| meldlabs Meld-Turbo, glyd hummingbird, satellitedown heretic-fngine, SiliconSpecies EXL3-Sushi | Flash-Next packs for their own engines (Apple, a custom runtime, FP8 on an RTX 5090) or empty |
| gorbatjovy Swift1.5 Flash-Next EXL3 4.05 bpw (108 GB), mikechambers84 GLM / Flash-Next W4A16 (192 / 186 GB), SuperPUPS Flash-Next INT8 | too big for one 24 GB GPU in engines that keep the experts in VRAM |
| yyrgzn Qwen3.8-27B FP8 (30 GB), zhubaohi NInfer NVFP4, Xananthium REDCELL W6A8, Cyronius ternary NPU drafter | FP8 / NVFP4 / NPU formats or over 24 GB |
| the remaining tree entries: 56 MLX or oQ, 9 NVFP4 / MXFP, 21 LoRAs, 38 full-precision finetunes, 1 gated (401) | not runnable on a 3090 as quants, or not quants |
