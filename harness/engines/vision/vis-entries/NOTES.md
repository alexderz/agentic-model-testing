# Notes: vision entries, 2026-10-15

## Surprises

- **No copy is needed.** Titan's `~/ai/models` is the NAS: NFS4, read-only, from `saturn.lan.example:/srv/store/models`. All 10 heads the entries use are visible on Titan at the expected size. The tool checks them again before it writes.
- **Every -vis entry needs its own spec file.** `entry_spec.validate` requires `model_id == entry`, and run-case-test8.sh stops with `spec_missing` otherwise. The tool writes `~/ai/config/specs/<source>-vis.json` on Titan, before the yaml, with tmp + rename. Copies are in `entry-specs/` here. Nobody has put them into `engines/entry-specs/`: that directory is outside what I may write, so `entry_spec.py --check` without `--titan` reports "no repo copy" for the 13 entries until someone does.
- **Same inode, not tmp + rename, for the yaml.** The house rule (every `tools/add_*.py`) is to edit llama-swap.yaml in place: same inode, validated, backed up, then sleep 20 s. llama-swap runs with `-watch-config`, and a rename swaps the inode under the watcher; it would also drop the file's owner, mode and label. So the tool works like this:
  - writes and fsyncs a temporary copy in the same directory
  - reads it back and validates it
  - copies it into the yaml in place, and asserts the inode and content
  - removes the temporary file
  - sleeps 20 s

  The spec files use a real tmp + rename. The tool refuses if the yaml changed since it read it, or if a model got loaded meanwhile.
- **`--no-mmproj-offload` exists in the native binary (q38-27b-cyber-vis).** The Grok review asked for a check, since the survey had shown the flag only on the 0.6.0 image. `llama-server --help` cannot run without a GPU: the binary needs `libcuda.so.1` even for `--help`. So I read the strings of the statically linked `/usr/local/bin/llama-server` (271 MB, Sep 20) in the llama-swap image `localhost/llama-swap-claims:v263-56-g5b3ce2`, with `podman run --rm --network none`, no GPU. The binary has `--mmproj-offload` and `--no-mmproj-offload` as separate literals, the help text "whether to enable GPU offloading for multimodal projector (default: %s)", and the env name `LLAMA_ARG_MMPROJ_OFFLOAD`. That is upstream's `{"--mmproj-offload", "--no-mmproj-offload"}` arg definition, so the entry keeps the flag. The first smoke will show it live: `vis_load_s` set, and no "invalid argument" in `smoke-<date>/q38-27b-cyber-vis.log`.
- **q38-27b-cyber fills the card.** The tuner measured it at 23800 MiB at its 229376 context (results-wave-b/tune-b.log:83). I had first assumed about 19.5 GB from other logs. Its head goes on the CPU too. Gemma 4 26B is the only setup whose head goes on the GPU (tuned 20520-21068 MiB + 1.4-1.7 GB).
- **The vLLM entries are blind today.** HyperQwen's `VISION` defaults to 0, which passes `--language-model-only`.
  - `VISION=1` allows only 1 image per prompt. A test 8 agent conversation carries several screenshots, so EXTRA_ARGS gets `--limit-mm-per-prompt {"image":{"count":32}}`. The step therefore passes the flag twice, and the second one wins. Checked after the Grok review in the pinned image (`ghcr.io/syv-ai/hyperqwen@sha256:34c2e3a4...`, `podman run --rm --network none`, no GPU):
    - `/app/batch/start_qwen.sh` sets `VISION_ARGS='--limit-mm-per-prompt {"image":{"count":1}} --mm-processor-kwargs {...}'` and its exec line is `vllm serve ... ${VISION_ARGS} ... ${EXTRA_ARGS}`, so ours comes last. The script's own comment: the two VISION=1 flags "can be overridden from EXTRA_ARGS, which is expanded after them".
    - The image's vLLM is 0.30.0. In `vllm/utils/argparse_utils.py` (FlexibleArgumentParser.parse_args), a repeated plain `--flag` only goes into `duplicates` and is logged as `Found duplicate keys ...`. A warning, not an error. The args then go to stdlib argparse.
    - `--limit-mm-per-prompt` is a plain store argument with `type=json.loads` (engine/arg_utils.py, dict fields), not append, so stdlib argparse keeps the last value.
    - `vllm/config/multimodal.py` accepts both `{"image": 16}` (legacy) and `{"image": {"count": 5, ...}}` (configurable). The nested form is the one start_qwen.sh itself uses.
    - `/app/resolve_config.sh` warns about EXTRA_ARGS shadowing only for a fixed list (port, host, max-model-len, ...). `--limit-mm-per-prompt` is not on it, and it never refuses for shadowing.
    - The shell does not mangle the JSON: it sits inside the single-quoted `EXTRA_ARGS`, start_qwen.sh expands it unquoted, and it contains no spaces or glob characters.
  - The smoke still checks this live: `two_image_status` 200 and `two_image_tokens` about twice `image_tokens`. The engine log grep keeps the `Found duplicate keys` line (`mmproj_log`).
- **exl3 vision is off in the config file** (`vision: false` in tabby-qwen38.yml). The server log says the model has vision.
- **Pre-existing drift, not mine.** For lcpp6-flashnext-abliterated-s15, Titan's spec has `thinking.server_budget` 24000, which matches the yaml's `--reasoning-budget 24000`. The repo copy engines/entry-specs/lcpp6-flashnext-abliterated-s15.json says 26000. The -vis copy follows Titan's.
- **Compatibility with existing scripts.**
  - The run-case scripts match `*-vllm|*-vllm-*`, so `qwen3.8-27b-vllm-vis` still gets its thinking_token_budget.
  - The SLOTS_DEBUG regex and the `-ngl` regex in set_variant keep working, since `--mmproj` sits on its own line after `-m`.
  - `tools/build_report.py` CTX_FIXED/KV_FIXED and `tools/apply_vllm_budget.py` ENTRIES are keyed by exact id, so they do not know the -vis entries. apply_vllm_budget is not needed: `--reasoning-config` is copied verbatim.

## Reading the smoke TSV (after the Grok review)

Do not copy these numbers into the model report without these caveats.
- **`gpu_delta_excl_offloaded_mib`** is GPU 0's whole-card `memory.used` after a text `hi` on the -vis entry, minus the same for the blind source. It excludes everything that lives in host RAM. In 11 of the 13 entries the head is there (`head_where` cpu or pinned), so expect about 0. Only gemma-4-26b-a4b-vis (`gpu`) shows its head here, so the column does not compare Gemma with the others.
- **`*_host_anon_mib`, `*_host_rss_mib`**: the container's cgroup on Titan (native entries: the llama-swap container, which also holds llama-swap itself). `anon` is from `memory.stat` and counts malloc'd memory, so it includes a head on the CPU and its buffers. `rss` is the VmRSS sum of the container's processes, and also counts mmapped GGUF pages. `host_anon_delta_mib` is -vis minus blind. CUDA pinned host memory (`pinned`: exl3 VISION_OFFLOAD, vLLM VLLM_VISION_CPU_OFFLOAD_GB) is allocated by the driver and may show in neither. I did not verify that.
- **`gpu_peak_mib`**: the highest GPU 0 sample (nvidia-smi `-lms 500`) from the probe to the end of the image requests. Raw samples are in `smoke-<date>/<id>-gpu.txt`. The step records no host-memory peak: the cgroup's `memory.peak` counts page cache from loading the model, and for native entries it covers the llama-swap container's whole life.
- **`vision`** is `yes` / `no` / `unclear`, from test 8's own rule since 2026-10-15: `tools/t8_tools.py` `vision_verdict` (1 / 0 / None), the one function both use (Grok review 3).
  - `yes`: the answer names red as the LEFT half's colour: the single word "red", red tied to "left" ("Red on the left, blue on the right", "the left is red", "Left: red"), or, with no colour tied to "left", red as the only colour that is neither negated nor tied to "right" ("Not blue, it is red"). No refusal came before it. Blue is allowed, since the right half is blue.
  - `no`: a refusal first ("I can't see images", "no image attached", "text-only"; "I don't see a problem" is not one), a left-half colour other than red, an HTTP error body saying the server takes no images (llama.cpp without `--mmproj` answers 500 "image input is not supported"), or any HTTP 4xx.
  - `unclear`: no HTTP answer, a 5xx that is not about images (a crash, a 502, a loading upstream), an empty answer, no colour ("Crimson"), or red plus another colour for the left ("red or blue").
  - Always read **`probe_answer`** (the raw answer); the full message, with a reasoning excerpt, finish_reason and usage, is in `smoke-<date>/<id>-vision.json`. **`t8_old_rule`** (was `t8_rule`) is what test 8's rule before 2026-10-15 said (red and no blue anywhere; it called "Red on the left, blue on the right" blind). The tiel pilot cases (`-p1`, `-p2`) ran under that rule.
- **A hung image request.** `vis_smoke.py tokens` stops at the first request that gets no HTTP answer and sends no more (`not_sent` in `<id>-tokens.json`). The step then unloads the server before anything else, since it may still be prefilling that image. `gpu_after_images_mib` and `host_anon_after_images_mib` stay `-` for that entry, and `errors` says `tokens rc=3`. The probe already worked this way.
- **`SKIPPED_UNLOAD` rows.** If a model will not unload (at least 3 tries, then until the entry or step end + 300 s), the step stops. The entry it was on keeps a row with what it had measured, and `errors` starts with `STOPPED`. Every later entry gets a full-width `SKIPPED_UNLOAD` row. The step exits 1. Its last unload then runs with the step's time, not the entry's, and run-next-new.sh's own 30 tries come after that.
- **The GPU sampler** (`nvidia-smi -lms 500` on Titan) writes its pid to `/tmp/vis-gpu-watch-<host>-<pid>-<random>.pid` on Titan and runs under `timeout` for the entry's remaining time. Stopping it kills that pid on Titan, and only while it is still `timeout`, which passes the TERM on to nvidia-smi. Killing the local ssh alone left the remote sampler running until its own timeout.
- **The probe** uses test 8's image and question, but max_tokens 1024 (test 8: 4000), `chat_template_kwargs.enable_thinking=false`, and `thinking_token_budget` 256 on vLLM. A cmd that forces thinking on can still think. Then `probe_finish` is `length` and `vision` is `unclear`, which is not a no.
- **`blind_load_s`, `vis_load_s`** are wall time from the first request to the first answer. They include the 30 s sleeps between retries while llama-swap answers 5xx; the `errors` column says how many retries there were. They are cold loads; the -vis load may profit from the page cache the blind load just warmed.
- **`image_tokens`** is prompt_tokens(text + image) minus prompt_tokens(text). It is the cost of one 1280x720 screenshot in each engine's own counting, including image marker tokens, and is not comparable across Gemma, the Qwen GGUF heads and vLLM. **`prompt_tokens_details`** is the image request's raw `usage.prompt_tokens_details` (vLLM: `--enable-prompt-tokens-details`). If `image_tokens` is 0 there, look at it first.
- **`two_image_*`** sends two different screenshots (the second has red and blue swapped), so no cache or dedupe can answer for the second one. `two_image_status` 200 shows that the per-prompt cap allows two. `two_image_tokens` should be about twice `image_tokens`.
- **`image_req_s`** is the time of the one-image request with max_tokens 1: encode + prefill + one decoded token. One token caps any forced thinking too.

## Risks the smoke step is built to show

- **Native llama-server with draft-mtp plus mmproj (gemma-4-26b-a4b-vis).** The Sep 20 native build has gemma4v and the mmproj flags. I found no string that shows speculative decoding working together with multimodal input, as 0.6.0 has. The build may disable the drafter, refuse, or crash.
- **Speculative decoding plus images on 0.6.0** (orcasaq2 dflash, coder390 draft-mtp). The build warns "drafts after multimodal input will be poor" when the widths differ. Test 8 speed may drop after the first screenshot. 0.6.0 also disables context shift and cache reuse with multimodal; none of these entries sets them.
- **The projector on the CPU** (9 entries). The screenshot encode time is unknown; see `image_req_s` in the TSV. With test 8's 7200 s cap, slow encodes cost the agent time. Each one also adds about 0.6-0.9 GB of weights plus buffers to Titan RAM; 59 GB was free while orcarouter was loaded.
- **The base head is unverified** for orcasaq2-cyber-27b (unsloth base Qwen3.8-27B head). The projection width matches n_embd, so it should load. Whether the fine-tuned text model reads its embeddings well is unknown; OrcaSAQ-2 may have been tuned text-only. It is marked EXPERIMENTAL in the description and the spec note. orcarouter-fn-uncensored uses orcarouter's own head since 2026-10-15 (gated repo; the operator accepted the gate); its base head stays in `vision-head/` for comparison.
- **vLLM.**
  - The encoder profile at start may shrink the KV pool below what the 150k context needs (watch "KV cache" in `smoke-<date>/<id>.log`).
  - The AutoRound checkpoint (qwen3.8-27b-vllm) has `processor_config.json` but no `preprocessor_config.json`.
- **exl3:** vision together with the DFlash2 drafter has not been tested anywhere.
- **The token counts** include the 2 or so image marker tokens. The smoke's PNG is screenshot-like but synthetic; the Qwen heads' token count depends only on the size.

## The yaml write (after the Grok review)

- `.bak-vis-<stamp>` is fsynced, with its directory, and read back before the yaml is touched.
- The in-place write is one `pwrite` of the whole text at offset 0, then `ftruncate` and `fsync`, through one fd. The new text is longer than the old, so a reader never sees a short file. During that one syscall it can still see a mix of old and new bytes.
- The backup's path is printed before the yaml is touched, with the recovery command (`cat <bak> > llama-swap.yaml`, in place).
- If anything fails after the write starts (an exception, the content does not read back, the path now points at another inode), the tool reads the inode back. It writes the original bytes back through the same fd only if the file still holds this tool's text, the original, or a torn mix of the two (a prefix of the new text over the rest of the old: what an interrupted pwrite from offset 0 leaves). It then exits non-zero and says so. A third version means someone else wrote the inode. That is left alone, and the tool exits non-zero with a loud `THIRD version ... NOT restored` message that names the backup. If the yaml changed just before the write, the tool writes nothing and leaves the other writer's text alone.
- **A kill -9 (or a dropped ssh) during the write can leave the yaml torn, and nothing restores it.** The window is one pwrite syscall. The manual recovery is the printed `.bak-vis-<stamp>`, copied back in place.
- A `-vis` key that already exists is checked. If its cmd is the source cmd plus exactly this tool's lines and only its spec is bad, the spec is repaired:
  - the spec already has the -vis `model_id` and only `cmd_sha256` is stale: only the hash is patched. A hand-tuned note or budget in it survives.
  - the spec is missing, unreadable, or still has the source's `model_id`: it is rewritten from the source spec. If the source spec's own `cmd_sha256` is stale, it warns, as for a new entry.
  - any other `model_id`: it refuses, with nothing changed.

  The dry run only prints the repair. Anything else about the entry aborts with nothing changed.
- These paths were tested offline on a read-only copy of Titan's yaml and specs taken 2026-10-15 09:27 (sha256 d776ca8e..., 78 entries; 19 checks).

## What I did not do

- I did not edit Titan's llama-swap.yaml or write any spec on Titan, and did not run the tool for real. The tool ran only as `--dry-run` (`dry-run.txt`). Its write path was tested on a local copy of the yaml (same inode, 78 to 91 entries, a second run adds nothing, it refuses while a model is loaded).
- I did not run the smoke step and used no GPU. I did not take the lease. The only llama-swap route I called was GET `/running`, inside the dry runs. The step itself does call `/unload`, run-next-new.sh's way, inside the lease.
- For the Grok review I also ran, on Titan: read-only file reads; `podman run --rm --network none` (no GPU) of the llama-swap image and the HyperQwen image, to read the binary's strings and the scripts; and the cgroup memory read the step uses, on the running llamacpp6 container.
- Test 8's vision rule changed on 2026-10-15, on the operator's instruction after Grok review 3: `tools/t8_tools.py` `vision_verdict`, shared with vis_smoke.py (see "Reading the smoke TSV"). It applies to test 8 cases started after that commit only. The pilot `-p1`/`-p2` cases ran under the old rule; their probes all got the llama.cpp 500 "image input is not supported", which is 0 under both rules. An unclear probe is no longer turned into blind: run-case-test8.sh retries it once, then stops the case as a `harness_failure` before the agent starts, and tools/tune_and_run.py leaves that row runnable. A one-word guess of "red" from a blind model still counts as sighted; telling those apart needs a second probe, which this change does not add.
- I did not run `entry_spec.py --mirror`; the step does.
- I did not commit, did not rename the `.new` files into place, and did not write into `engines/entry-specs/`, matrices, the report or the model catalog.
- I added no test 8 matrix rows for the -vis entries; that is the operator's decision.
- I did not try the `-ncmoe` alternative or any other context change for the MoE entries; all source flags are copied verbatim.
