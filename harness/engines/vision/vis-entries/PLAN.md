# Vision entries for the test 8 setups

**Operator decision, 2026-10-15:** test 8 tests the models' vision feedback, so its 15 setups get vision. This is done with `<entry>-vis` copies of the llama-swap entries. The blind entries stay untouched, so one-shot results stay comparable.

Prepared by a Model Master 2 helper on 2026-10-15. Nothing has been applied. Everything here waits for:
- a review
- the renames below
- the new-work slot

## Files

| file | purpose |
|---|---|
| `tools/add_vis_entries.py.new` | Runs on Titan. Adds the 13 entries and their 13 spec files. |
| `queue-new.d/20-vision-entries.sh.new` | Queue step: add, mirror, smoke. |
| `engines/vision/vis-entries/vis_smoke.py` | The step's helper: load an entry, the vision probe (yes / no / unclear plus the raw answer), count the tokens of one screenshot. Stdlib plus tools/t8_tools.py's probe image. |
| `dry-run.txt` | Output of the tool's `--dry-run` on Titan (read-only: GET `/running` and file reads), regenerated after the Grok review; its first lines give the time, the yaml's sha256 and entry count. |
| `entry-specs/*.json` | The 13 spec files the dry run would write to `~/ai/config/specs/` on Titan. They are for review, and are the repo copies for `engines/entry-specs/`. |

Install order:
1. `mv tools/add_vis_entries.py.new tools/add_vis_entries.py`
2. `mv queue-new.d/20-vision-entries.sh.new queue-new.d/20-vision-entries.sh`

The step refuses to run if the tool has not been renamed into place.

## Method

Each new entry is a verbatim copy of its source entry, with these changes:
- the key gets `-vis`
- `name` gets ` + vision`
- `description` starts with "Vision variant of `<source>` (test 8)..."
- the spec reference points to `<source>-vis.json`
- the vision flags below are added

The tool checks each copy with `yaml.safe_load`:
- the key set grew by exactly the 13 new keys
- every existing entry is unchanged
- each new entry has the same fields as its source
- removing the added lines from the new cmd gives back the source cmd exactly

On llama.cpp, `--mmproj` goes on a new line right after the `-m` line. It never goes on the `-ngl` line, because lib.sh `set_variant` rewrites that line.

Each new spec is the source spec (Titan's copy) with these fields changed:
- `model_id`
- `cmd_sha256`, recomputed with entry_spec's `cmd_hash`
- `generated`
- the report label/note

A new spec is needed because `entry_spec.validate` requires `model_id == entry`; otherwise run-case-test8.sh records `spec_missing`.

All 13 specs validate with the repo's own `entry_spec.validate` and `cmd_hash` (tools: `<scratch>/vis/visent/check_dry.py`).

## The 15 setups

VRAM is nvidia-smi `memory.used` for the whole card: 24576 MiB, of which about 1 GB goes to the desktop. "Tuned" means the tuner's own measurement at the served context (results-wave-a/b `tune-*.log`, `next.log`). The extra-VRAM figures for heads come from engines/vision/README.md and are estimates:
- qwen3vl BF16/F16 head: 1.4-2.7 GB (0.9-1.2 GB weights plus buffers)
- qwen3vl Q8_0 head: 1.1-2.1 GB
- gemma4v head: 1.4-1.7 GB

Tokens per 1280x720 image are estimates too: about 920 for qwen3vl, about 400 for gemma4v. The smoke step measures them.

### Already see images (2): no -vis entry

**cyber-tiel-coder-35b**
- Engine: native llama-server in the llama-swap image (Sep 20 build).
- Head: `/models/llm/cyber-tiel-coder-35b/mmproj-BF16.gguf` (902822016 B).
- Projector: qwen3vl_merger. Supported: yes. The entry already passes `-mm` and loads; it was tuned to 23600 MiB with the head on the GPU.
- Plan: no change. The smoke probes it as it is.

**flashnext-phased**
- Engine: SGLang EXL3 (ghcr.io/0xsero/sglang-exl3-flashnext@sha256:a21efea6...).
- Head: the vision tower is inside the EXL3 checkpoint.
- Supported: yes.
  - plugin.py: `SGLANG_EXL3_VISION` defaults to "1" and calls `vision_exl3.install()`. The entry sets `SGLANG_EXL3_VISION=1`.
  - serve_flashnext_3090.sh: "Vision (images 256^2 .. 4096^2): EXL3 ViT decoded to bf16 at load".
- Already serves images; untested. 21102 MiB measured.
- Plan: no -vis entry, since it would be identical. The smoke probes it as it is.

### New -vis entries (13)

| source entry | engine / image | head (as the server sees it; Titan host path is `~/ai/models/...`, the NAS) | projector | engine supports it (evidence) | new entry | flags added | served ctx and VRAM now | est. extra VRAM |
|---|---|---|---|---|---|---|---|---|
| exl3-qwen3.8-27b-dflash2 | TabbyAPI a3fed43e + exllamav3 1.6.1 (image 8eb86a95ffca) | vision tower inside turboderp/Qwen3.8-27B-exl3 4.00bpw | exllamav3 Qwen3.8 VL tower | yes: server log "The provided model has vision capabilities, vision is disabled in config"; `/app/common/config_models.py` has `vision`, `vision_offload`; TABBY_* env overrides the file (engines/exllamav3/README) | exl3-qwen3.8-27b-dflash2-vis | `-e TABBY_MODEL_VISION=true -e TABBY_MODEL_VISION_OFFLOAD=true` | 98304, 8-bit cache; 22.3-22.6 GB | ~0 resident (ViT ~0.9 GB kept in pinned host RAM), per-image activations only; offload because the entry has ~1.5 GB left |
| gemma-4-26b-a4b | native llama-server (llama-swap image), draft-mtp | `/models/llm/gemma-4-26b-a4b/gemma-4-26B-it-mmproj.gguf` (1194828160 B, Google) | gemma4v, proj 2816 = n_embd | yes: native binary has `gemma4v` (4 hits) and the mmproj flags. Unknown: draft-mtp together with mmproj in this build | gemma-4-26b-a4b-vis | `--mmproj ...` (projector on GPU) | 262144 f16; tuned 20520-21068 MiB | +1.4-1.7 GB, so about 22.5-22.8 GB: fits |
| lcpp6-flashnext-abliterated-s15 | llama.cpp 0.6.0 (ghcr.io/ggml-org/llama.cpp@sha256:a863a2d1...) | `/models/llm/flashnext-abliterated-s15/vision-head/Qwen3.8-Flash-Next-Abliterated-s1.5-mmproj-BF16.gguf` (907543008 B, author's) | qwen3vl_merger, proj 2560 = n_embd | yes: `/app/libmtmd.so.0.6.0` has qwen3vl_merger; libllama-common has `--mmproj`, `--no-mmproj-offload` | lcpp6-flashnext-abliterated-s15-vis | `--mmproj ... --no-mmproj-offload` | 262144 f16, -ncmoe 39; tuned 23830 MiB | ~0 GPU (head and its compute in host RAM, ~0.9 GB + buffers); no room on the GPU |
| lcpp6-flashnext-heretic2 | llama.cpp 0.6.0 | `/models/llm/flashnext-heretic2/mmproj-Heretic2-BF16.gguf` (907542880 B, author's; the 0.4 entry flashnext-heretic2 loads it) | qwen3vl_merger, 2560 | yes (as above) | lcpp6-flashnext-heretic2-vis | `--mmproj ... --no-mmproj-offload` | 262144, -ncmoe 40; tuned 23568 MiB | ~0 GPU; no room |
| lcpp6-orcarouter-fn-uncensored | llama.cpp 0.6.0 | `/models/llm/orcarouter-flash-next-uncensored/vision-head-own/mmproj-Qwen3.8-Flash-Next-Uncensored-F16.gguf` (907543296 B, orcarouter's own head; gated repo, operator accepted 2026-10-15) | qwen3vl_merger, 2560 | yes | lcpp6-orcarouter-fn-uncensored-vis | `--mmproj ... --no-mmproj-offload` | 262144, -ncmoe 40; 23336-23344 MiB | ~0 GPU; no room |
| lcpp6-orcasaq2-cyber-27b | llama.cpp 0.6.0, dflash + ngram-mod | `/models/llm/orcasaq2-cyber-27b/vision-head/mmproj-F16.gguf` (927607488 B, **base** unsloth Qwen3.8-27B head) | qwen3vl_merger, 5120 | yes; 0.6.0 also has spec-decode + multimodal code ("drafts after multimodal input will be poor" when widths differ). **EXPERIMENTAL** (base head; OrcaSAQ-2 may be a text-only tune) | lcpp6-orcasaq2-cyber-27b-vis | `--mmproj ... --no-mmproj-offload` | 94208 q8_0; tuned 23328-23352 MiB | ~0 GPU; no room |
| lcpp6-q38-27b-cyber-q5 | llama.cpp 0.6.0 | `/models/llm/q38-27b-cyber-q5/vision-head/mmproj-Qwen3.8-27B-Uncensored-Cyber-BF16.gguf` (931146272 B, author's) | qwen3vl_merger, 5120 | yes | lcpp6-q38-27b-cyber-q5-vis | `--mmproj ... --no-mmproj-offload` | 81920 q8_0; not measured: 21.27 GB weights + about 3 GiB KV (38 KiB/token, measured on q38-27b-cyber) is about 24 GB | ~0 GPU; no room |
| lcpp6-q38-coder390 | llama.cpp 0.6.0, draft-mtp, -np 2 | `/models/llm/q38-27b-coder390-et/vision-head/GGUF/mmproj-Qwen3.8-27B-Q8_0.gguf` (629247008 B, author's) | qwen3vl_merger Q8_0, 5120 | yes | lcpp6-q38-coder390-vis | `--mmproj ... --no-mmproj-offload` | 81920 q8_0 x2 slots; 23686-23828 MiB | ~0 GPU; no room (would need 1.1-2.1 GB) |
| lcpp6-thinkingcap-27b-heretic | llama.cpp 0.6.0 | `/models/llm/thinkingcap-27b-heretic/ThinkingCap-Qwen3.8-27B-Uncensored-Heretic.mmproj-Q8_0.gguf` (629247616 B, mradermacher) | qwen3vl_merger Q8_0, 5120 | yes | lcpp6-thinkingcap-27b-heretic-vis | `--mmproj ... --no-mmproj-offload` | 196608 q8_0; tuned 23636 MiB | ~0 GPU; no room |
| lcpp6-tiel-coder-35b-t06 | llama.cpp 0.6.0 | `/models/llm/tiel-coder-35b/mmproj-BF16.gguf` (902822016 B, author's; the 0.4 entry tiel-coder-35b loads it) | qwen3vl_merger, 2048 | yes; the pilot (results-test8/t8-*-tiel-p1) got 500 "image input is not supported ... provide the mmproj", vision 0 | lcpp6-tiel-coder-35b-t06-vis | `--mmproj ... --no-mmproj-offload` | 262144 f16, all on GPU; 22480-22484 MiB (pilot) | +1.4-2.7 GB on GPU would give 23.9-25.2 GB, so the head goes on the CPU: ~0 GPU |
| q38-27b-cyber | native llama-server | `/models/llm/q38-27b-cyber-agentic/vision-head/mmproj-Qwen3.8-27B-Uncensored-Cyber-BF16.gguf` (931146272 B, author's) | qwen3vl_merger, 5120 | yes: native binary has qwen3vl_merger; the native entries tiel-coder-35b, qwen3vl-* load `-mm`; `--no-mmproj-offload` is in this binary too (checked after the Grok review, NOTES.md) | q38-27b-cyber-vis | `--mmproj ... --no-mmproj-offload` | 229376 q8_0; tuned 23800 MiB | ~0 GPU; no room |
| qwen3.8-27b-uncensored-vllm | HyperQwen vLLM 0.30 (ghcr.io/syv-ai/hyperqwen@sha256:34c2e3a4...) | vision tower inside the checkpoint (Qwen3_5ForConditionalGeneration, vision_config, processor_config.json) | Qwen3.8 VL tower (patch 16, merge 2) | yes, but **the existing entry is blind**: start_qwen.sh `VISION` defaults to 0, which passes `--language-model-only` | qwen3.8-27b-uncensored-vllm-vis | `-e VISION=1 -e VISION_OFFLOAD=1`; EXTRA_ARGS += `--limit-mm-per-prompt {"image":{"count":32}}` (VISION=1 alone allows 1 image per prompt; the duplicate flag only warns and the last one wins in this vLLM 0.30.0, checked, NOTES.md) | 150k fp8; 23342-23642 MiB | tower 0.858 GiB in pinned host RAM, ~9 MiB resident (HyperQwen README); the encoder profile may shrink the KV pool |
| qwen3.8-27b-vllm | HyperQwen vLLM 0.30 | as above (Qwen3.8-27B-W4A16-AutoRound; has processor_config.json but **no preprocessor_config.json**) | as above | as above; existing entry blind | qwen3.8-27b-vllm-vis | as above | 150k fp8; 23350 MiB | as above |

What a -vis variant changes on the three non-llama.cpp engines:
- **exl3:** turns on TabbyAPI's vision, which is off in tabby-qwen38.yml, with the ViT kept in host RAM.
- **vLLM:** replaces `--language-model-only` with the tower, keeps the tower in host RAM (VLLM_VISION_CPU_OFFLOAD_GB=1, the script's default with VISION=1), and lifts the 1-image cap to 32.
- **SGLang:** nothing; vision is already on.

Alternative for the MoE entries (abliterated-s15, heretic2, orcarouter): raise `-ncmoe` by 2-3 to free the head's 1.4-2.7 GB and keep the projector on the GPU. That changes the speed, so it is only noted here and not proposed.

## Smoke step (queue-new.d/20-vision-entries.sh.new)

The step runs in run-next-new.sh's slot. It does the following:

1. Unloads, using run-next-new.sh's own method (bounded: at least 3 tries, then only until the entry or step end plus 300 s; if it gives up, the step stops and run-next-new.sh unloads with its own 30 tries).
2. Pipes the tool to Titan. The tool refuses unless `/running` is empty and never unloads.
3. Runs `tools/entry_spec.py --mirror`. If it fails, the smoke still runs (it reads the specs from Titan), and the step exits 1 at the end.
4. For each of the 13 pairs:
   - unload
   - load the blind source with a tiny text request, capped at 900 s, and only if 2700 s of the entry budget stay free for the -vis load and probe; record load s, GPU memory and the container's host memory (cgroup `anon`, and the VmRSS sum of its processes)
   - unload
   - load the -vis entry (cap 1800 s); record the same
   - the vision probe, `vis_smoke.py probe`: test 8's image and question, max_tokens 1024, thinking off in the request (cap 600 s). GPU memory is sampled every 0.5 s from here to the end of the image requests.
   - if the probe got no answer (timeout), unload and load the -vis entry again, so a request the server is still working on does not hold the GPU during the image requests
   - send one 1280x720 PNG and the same prompt without it (prompt_tokens difference), max_tokens 1, 600 s per request
   - send two different PNGs (the second has red and blue swapped), for the vLLM cap
   - record GPU memory and host memory after the images, and the GPU peak
   - save engine log lines (mmproj estimate, KV pool, duplicate or unknown flags, errors), also when the -vis load failed
5. Probes cyber-tiel-coder-35b and flashnext-phased as they are.

Output goes to `engines/vision/vis-entries/smoke-<date>.tsv` (33 columns, every row full width), with raw files in `smoke-<date>/`. NOTES.md "Reading the smoke TSV" says what each number means and what it does not.

Time limits: each entry has 5700 s (`VIS_PER_ENTRY_S`; blind 900 + -vis load 1800 + probe 600 + 3 x 600 for the image requests + 600 for unloads and logs). The step has 36000 s (`VIS_TOTAL_S`, 10 h) and starts no entry with less than 1200 s of that left. A typical entry should take 10-25 min, so the 15 entries need about 3-6 h. An entry that does not get its -vis probe for lack of time gets a SKIPPED_TIME row (vision and probe_status `SKIPPED_TIME`), and the step then exits 1, so it lands in queue-new.d/failed/ instead of passing silently. A failing entry is recorded and the step goes on. A model that will not unload stops it (exit 1, as in run-next-new.sh).

Checked with `bash -n`, and run end to end against a mock server and a fake ssh, including the time limits, a failing entry and a probe that times out.
