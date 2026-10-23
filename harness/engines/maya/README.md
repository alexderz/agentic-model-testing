# Project Maya on titan (GLM-5.3-Flash)

Operator 2026-10-07: "Another one: https://github.com/mw00/project-maya". Maya runs GLM-5.3-Flash (zai-org, MIT;
321B MoE, about 18B active per token, up to 1M context) on Strata's engine, rewritten for GLM: experts tiered across
VRAM, RAM and SSD.

## What is pinned

- **Maya:** tag `v1.0.4`, commit `70e0746e6f2d02a7cbdb22ac33c1b31ee2ce1213`; its `VERSION` and CHANGELOG say 1.3.0
  (the maintainer renumbered the release tags on 2026-10-07: v1.2.0 seen in the afternoon, v1.0.4 at 23:39). The
  commit is the pin; build.sh refuses a moved tag.
- **llama.cpp** (ggml for the engine, gguf-py for the pack builder): commit `3cf03257f219afbe7334045ff7c6a06ac68c627d`,
  zip sha256 `cbe23c594282ead2937abb3f008e51fcec4609d9256652fff42c7cc1c21ea47b`, the same pin as Strata's build.
- **CUDA images** by digest (13.0.2 devel and runtime, Ubuntu 24.04), as Strata's.
- **Weights:** `peasantsmith/GLM-5.3-Flash-Maya-GGUF` rev `ac8bb6aa11a7cd8bf6c0216e3c51c047b72b2e19`, Maya-S-v2 IQ2_XXS,
  3 shards, 97.6 GB, in `/srv/store/models/llm/glm-5.3-flash-maya/` (download.sh there).

## What its installer does (read in full before building; we do not run it)

`setup.sh` and `maya.sh` only make a `.venv` and run `maya.py`, which imports Strata's `setup.py` unchanged.
Network use, as written:
- `pip install` into `.venv`: numpy, jinja2, regex, pyyaml, tqdm, requests, cmake, ninja, pillow, psutil (unpinned).
- llama.cpp's source zip at the pinned commit (above); `maya.py` hashes nothing itself, so the sha256 is ours.
- The model from Hugging Face (`peasantsmith/...`, revision pinned in its table), shown and asked first, resumable.
- The vision encoder files, unless `--no-vision`; its build also runs `tools/vision/glm5next_patch.py` on the llama.cpp
  tree (patches llama.cpp's mtmd for GLM). Not used here: our image is text only.
- Inherited from Strata's `setup.py`, not used by Maya's flow but present: a **prebuilt engine download** from
  `github.com/Niko1221/Strata/releases/latest` (`PREBUILT_URL`), ROCm wheels from `rocm.nightlies.amd.com`, and on
  Linux without CUDA the **NVIDIA cuda-keyring .deb**. We build from source and never run the installer.

## Risks noted

- **One-day-old repository and weights by a single maintainer** (repo created 2026-10-06; the HF repo 2026-10-07 with
  0 downloads at the time we pinned it). The same day's notes flag backdoored community weights that trigger tool
  calls exfiltrating secrets through a coding agent. Mitigations here: the agent runs in our sandbox (egress allowlist,
  no secrets in /work, capability-less root), the engine container is on an internal podman network with no internet egress, and the
  weights are pinned by revision. Not verified: that Maya-S was quantised from zai-org's FP8 release as claimed.
- **Server-side MCP client** (`serve/mcp.py`): the server can start MCP servers or call MCP URLs listed in its run
  config (`mcp_servers` / `mcpServers`) or `--mcp-config`. Our config has neither, so it stays off; never add one.
- **RAM:** by default the engine pins all free RAM but about 6 GB for its expert tier (`STRATA_GLM_RAM_HEADROOM_GB`).
  Our config caps it with `STRATA_GLM_RAM_GB=95` so llama-swap, the proxy, the OS and page cache keep about 30 GB.
  titan's systemd-oomd is off since 2026-10-07 (it killed Strata's pinning); the kernel OOM killer is the backstop.
- Vendored code: `third_party/ggml/ggml-common.h` (one header from llama.cpp, as Strata).

## Serving facts (from the code)

- OpenAI-compatible `/v1/chat/completions` (stream and not), `/v1/models`, `/health`, Anthropic `/v1/messages`.
- **Tool calls:** returned as OpenAI `tool_calls` (streamed in pieces by index, `finish_reason: tool_calls`), parsed from
  GLM's own template by the server. Test 1 shows whether OpenCode's tool use works end to end.
- **One request at a time:** "One sequence at a time behind a FIFO"; `/v1/status` reports `concurrency.serving: 1`.
  Concurrent requests wait their turn (they do not fail). Test 3 is multi-agent: the main agent waits while its probe
  runs, so a FIFO serves it, but OpenCode's background requests (titles) queue behind long turns.
- Thinking: run config `thinking_budget` (tokens; 0 = none; Maya's default 32768); ours is 24000 like the other engines.
  Default sampling temperature 1.0, top_p 0.95, reasoning effort medium.
- No Host-header guard (Strata needed `allowed_hosts` for llama-swap); only an Origin check on settings/tool endpoints.

## Files

- `Containerfile`, `build.sh`: `localhost/maya:v1.0.4-sm86`, engine (`strata` target, `-DSTRATA_NATIVE_EXPERTS=ON`) and
  server, sm_86, text only, user 10001. Built on Saturn capped:
  `systemd-run --user --scope -p CPUQuota=600% -p MemoryMax=24G nice -n 15 ./build.sh`. Image ID in `image-id.txt`.
- The pack (`tools/iq_pack.py --compat-bf16`): written next to the GGUFs at
  `/srv/store/models/llm/glm-5.3-flash-maya/Maya-S-v2-IQ2_XXS/pack/` (the engine finds the GGUFs at `<pack>/..`).
- `../../tools/add_maya_entry.py IMAGE_ID`: titan entry `maya-glm-5.3-flash` and `~/ai/maya/configs/glm-5.3-flash.json`
  (131072 context, 24k budget, RAM tier 95 GB). Run since; results for Maya 1.0.4, 1.1.11 and 1.1.13 are in
  `docs/model-research/engines.md` and the GLM-5.3-Flash card.
- `../../matrix-maya-a.tsv`, `../../matrix-maya-b.tsv`: test 1 and test 2 rows (since run).

## Build and pack results (Saturn, 2026-10-07)

- Image `localhost/maya:v1.0.4-sm86`, ID `7f0891a37751ab8948933fda709e13066d88604af5e498aa06966e3fc60d6200`, 2.96 GB,
  built in about 3 minutes under the cap (6 CPUs, 24 GB). Runs as uid 10001; pip versions in `/opt/maya/pip-freeze.txt`.
- Pack: 908 MB, 16 s, offline (`--network none`): 1,257 tensors indexed, 317 served natively, 0.88 GiB arena of BF16
  projections, tokenizer and chat template. The packer dropped the 26 MTP (NextN) tensors of layer 45: this runner does
  not use MTP on one GPU (Maya drafts with MTP only on two GPUs).

## Needs titan to verify

Load time and whether 131072 context fits beside the expert cache; the RAM tier actually pinned; decode speed;
tool calling through OpenCode (test 1); that the NFS-mounted GGUFs are fast enough for the SSD tier (titan reads them
over NFS, not from a local NVMe as Maya assumes): with a 95 GB RAM tier, little should come from the "SSD".
