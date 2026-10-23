# llama.cpp current (`lcpp7`): official image b11641

Third llama.cpp engine beside Claw's llama-swap build (0.4.1-dev) and `lcpp6` (v0.6.0, b11429).
Needed for two architectures that landed after b11429: MiniCPM-V 4.7 (projector `minicpmv4_7`)
and EmbeddingGemma 2 (`gemma-embedding2`). Prepared 2026-10-15 (Model Master 2).
Status (2026-10-22): superseded. llama.cpp 0.7.0 has been the build behind every llama.cpp entry since
2026-10-18 (see `docs/model-research/engines.md`). The entries below are the original drafts, kept as a record.

    ghcr.io/ggml-org/llama.cpp:server-cuda12-b11641   (same index as server-cuda-b11641 and, today, server-cuda12)
    = ghcr.io/ggml-org/llama.cpp@sha256:9dfa49ca795363f5fff96f501469e3565e757951f04701a8ad8a5dc5e3ee916d   (OCI index)
      linux/amd64 manifest sha256:645d440e86cda7b4ae790057d7749d7ac4492844e94b0229389b0058f0ae5fb3
    image id 7886f808fc80, 4.37 GB, created 2026-10-15 06:31 UTC
    llama-server --version: 0.6.0-dev (build 11641, commit 843e7dcc1)

Pulled on titan by digest as operator (`nice -n 19 ionice -c3 podman pull ...@sha256:9dfa49...`) and tagged
locally `ghcr.io/ggml-org/llama.cpp:server-cuda12-b11641`. `--version` was run with `--network none`
and no GPU device.

## Why this build
- Newest official CUDA server image when checked (release b11641, published 2026-10-15 06:53 UTC;
  releases b11642 to b11647 exist but have no image yet). The image workflow does not build every
  release: server-cuda12 tags after b11429 are b11434, 11459, 11515, 11541, 11552, 11561, 11580,
  11610, 11641. There is no image for b11588 (named in CANDIDATES.md). b11580 and b11610 also contain
  both PRs (compare API: 29 and 59 commits ahead of 69f201a2051e, 0 behind); b11641 is the newest.
- Contains PR 29416 (MiniCPM-V 4.7, merge commit 69f201a2051ea9b9e9b50c3cc56afd9e2ae64414,
  2026-10-10 18:42 UTC) and PR 30054 (EmbeddingGemma 2, 4fbc76dec51d0add466f0210855c0596589b60d4,
  2026-10-06 16:20 UTC). Evidence: GitHub compare API (anonymous) `69f201a2051e...b11641` = ahead 90,
  behind 0; `4fbc76dec...b11641` = ahead 189, behind 0. Inside the image, `/app/libmtmd.so` contains the
  string `minicpmv4_7` and `/app/libllama.so` contains `gemma-embedding2` / `gemma_embedding2`.
- sm86: `.devops/cuda.Dockerfile` at b11641 builds with `CUDA_DOCKER_ARCH=default`, CUDA 12.8.1; the
  default list in `ggml/src/ggml-cuda/CMakeLists.txt` for CUDA 12.x is
  `50-virtual 61-virtual 70-virtual 75-virtual 80-virtual 86-real 89-real 90-virtual` plus Blackwell, so
  the 3090 gets native sm86 code. Same CUDA 12 line as lcpp6 (titan driver 615.71.09).
- Same `.devops` shape as b11429 (binaries in `/app`, entrypoint `/app/llama-server`), so the lcpp6
  command shape carries over unchanged except for the image.
- Risk: 212 commits newer than b11429 (compare API, ahead 212, behind 0); nothing of ours has run on it yet. Keep lcpp6 entries on b11429.

## Models (downloaded 2026-10-15 to Saturn /srv/store/models, titan /home/operator/ai/models)
Each dir has `download.sh` (pinned revision), `download.log`, `SHA256SUMS` (Hub LFS sha256, all `OK`).

| dir | repo @ revision | files | bytes |
|---|---|---|---|
| vision/minicpm-v4.7-35b-a3b | openbmb/MiniCPM-V-4.7-35B-A3B-gguf @ b3b8cd80c0900c7ca461fdc3b87cbe5780a6b6ff | MiniCPM-V-4_7-35B-A3B-Q4_K_M.gguf (sha256 bf3d1c67f784...) | 21,166,255,008 (19.71 GiB) |
| | | mmproj-model-f16.gguf (bff3b688e14c...) | 1,119,575,840 (1.04 GiB) |
| vision/minicpm-v4.7-1b | openbmb/MiniCPM-V-4.7-1B-gguf @ 7989f440e950c1c8adcd8134a7fe57a086208f46 | MiniCPM-V-4_7-1B-Q8_0.gguf (2b83d8dfcd66...) | 1,081,517,920 (1.01 GiB) |
| | | mmproj-model-f16.gguf (fb9cc047a3cd...) | 1,110,117,984 (1.03 GiB) |
| embed/embeddinggemma-2 | ggml-org/embeddinggemma-2-GGUF @ bfcd298762cc34d0357ece5ebdd31791a3a374d8 (converted from google/embeddinggemma-2 @ 914f7f89142e) | embeddinggemma-2-Q8_0.gguf (2188ac1deca4...) | 309,855,456 (0.29 GiB) |
| | | mmproj-embeddinggemma-2-Q8_0.gguf (c4a8a52691ec...) | 554,821,024 (0.52 GiB) |

Revisions: CANDIDATES.md pinned the MiniCPM GGUF repos at 1e04eae556a0 / 6c2f4cb8bde5 (2026-10-13). Both repos
moved since (README edits and a new `dspark-*-F16.gguf` speculative draft), but the Q4_K_M, Q8_0 and mmproj
blobs are byte-identical (same LFS sha256 at both revisions), so the downloads are pinned to the current
heads. The DSpark draft (35B: `dspark-MiniCPM-V-4_7-35B-A3B-F16.gguf`, 0.74 GiB) was not downloaded:
whether llama.cpp b11641 can use it as a draft is unchecked. EmbeddingGemma 2: the ggml-org conversion
is the one PR 30054 links; the 310 MB / 555 MB sizes match CANDIDATES.md.

## Draft llama-swap entries (do not add outside a queue step)
Container `llamacpp7`, port 8102 (unused in llama-swap.yaml today; 8096-8101 are taken), same flags as
the lcpp6 entries. `--label bakeoff.spec=...` follows the lcpp6 pattern; the spec JSONs do not exist yet.

### MiniCPM-V 4.7 35B-A3B Q4_K_M + mmproj f16
Text model is qwen35moe: 40 layers, only 10 full-attention (2 KV heads x 256), the rest gated-delta.
KV = 10 x 2 x 2 x 256 = 10 240 values per token: 20 KiB/token f16, about 10.6 KiB q8_0.
At `-c 32768` with q8_0 KV that is about 0.33 GiB (f16 would be 0.63 GiB). Weights plus projector are
20.75 GiB, leaving about 1.2 to 1.5 GiB on the 3090 (desktop takes about 1 GB) for KV, recurrent state,
CUDA context and compute buffers. If the load fails, drop to `-c 16384`, then try `--no-mmproj-offload`
(projector on CPU, frees 1.04 GiB of VRAM, slower image encode). Sampling is the card's instruct-mode set
(temp 0.7, top-p 0.95, top-k 100, min-p 0, presence 0, repetition 1.03); the card's examples use
`enable_thinking=False`.

```yaml
  lcpp7-minicpm-v47-35b-a3b:
    name: "MiniCPM-V 4.7 35B-A3B Q4_K_M + mmproj f16 on llama.cpp b11641"
    description: "Official llama.cpp b11641 image (server-cuda12), digest-pinned: first build with the minicpmv4_7 projector (PR 29416). Vision-language MoE, 35B / 3B active. Short context so weights + projector + KV fit 24 GB. Card instruct sampling. Model Master 2."
    proxy: "http://llamacpp7:8102"
    checkEndpoint: /health
    cmd: |
      podman run --name llamacpp7 --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/lcpp7-minicpm-v47-35b-a3b.json
      -e LLAMA_SERVER_SLOTS_DEBUG=1
      --network llama
      --device nvidia.com/gpu=all
      --security-opt label=disable
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      ghcr.io/ggml-org/llama.cpp@sha256:9dfa49ca795363f5fff96f501469e3565e757951f04701a8ad8a5dc5e3ee916d
      --host 0.0.0.0 --port 8102 -fa on --metrics
      -m /models/vision/minicpm-v4.7-35b-a3b/MiniCPM-V-4_7-35B-A3B-Q4_K_M.gguf
      -mm /models/vision/minicpm-v4.7-35b-a3b/mmproj-model-f16.gguf
      --jinja
      --temp 0.7 --top-p 0.95 --top-k 100 --min-p 0 --presence-penalty 0 --repeat-penalty 1.03
      -ngl 999 -c 32768 -ctk q8_0 -ctv q8_0 -fit off
    cmdStop: /bin/sh -c "podman stop -t 30 llamacpp7 || podman rm -f llamacpp7"
```

### MiniCPM-V 4.7 1B Q8_0 + mmproj f16
qwen35 dense, 24 layers, 6 full-attention (2 KV x 256): about 6.4 KiB/token at q8_0, so 131k context is
about 0.8 GiB. Everything fits on the GPU with room to spare (about 3 GiB total).

```yaml
  lcpp7-minicpm-v47-1b:
    name: "MiniCPM-V 4.7 1B Q8_0 + mmproj f16 on llama.cpp b11641"
    description: "Official llama.cpp b11641 image (server-cuda12), digest-pinned (minicpmv4_7 projector, PR 29416). Small vision-language model, vision smoke test only. Card instruct sampling. Model Master 2."
    proxy: "http://llamacpp7:8102"
    checkEndpoint: /health
    cmd: |
      podman run --name llamacpp7 --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/lcpp7-minicpm-v47-1b.json
      -e LLAMA_SERVER_SLOTS_DEBUG=1
      --network llama
      --device nvidia.com/gpu=all
      --security-opt label=disable
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      ghcr.io/ggml-org/llama.cpp@sha256:9dfa49ca795363f5fff96f501469e3565e757951f04701a8ad8a5dc5e3ee916d
      --host 0.0.0.0 --port 8102 -fa on --metrics
      -m /models/vision/minicpm-v4.7-1b/MiniCPM-V-4_7-1B-Q8_0.gguf
      -mm /models/vision/minicpm-v4.7-1b/mmproj-model-f16.gguf
      --jinja
      --temp 0.7 --top-p 0.95 --top-k 100 --min-p 0 --presence-penalty 0 --repeat-penalty 1.03
      -ngl 999 -c 131072 -ctk q8_0 -ctv q8_0 -fit off
    cmdStop: /bin/sh -c "podman stop -t 30 llamacpp7 || podman rm -f llamacpp7"
```

### EmbeddingGemma 2 Q8_0 (text embeddings)
740M total (270M text model), 768-dim output (Matryoshka 512/256/128), mean pooling, 8192-token context.
Embedding requests must fit one physical batch, hence `-b`/`-ub` = `-c`. No KV quantization (tiny model;
the CANDIDATES note asks for bf16/f32 activations). Queries need the card's task prefixes, e.g.
`task: search result | query: ...` and `title: none | text: ...` for documents. The image/audio projector
(`mmproj-embeddinggemma-2-Q8_0.gguf`) is on the NAS; whether llama-server b11641 serves multimodal
embeddings through `/v1/embeddings` is unchecked, so the draft is text-only (add
`-mm /models/embed/embeddinggemma-2/mmproj-embeddinggemma-2-Q8_0.gguf` to try).

```yaml
  lcpp7-embeddinggemma2:
    name: "EmbeddingGemma 2 Q8_0 embeddings on llama.cpp b11641"
    description: "Official llama.cpp b11641 image (server-cuda12), digest-pinned: first build with gemma-embedding2 (PR 30054). 768-dim text embeddings, mean pooling, 8k context, /v1/embeddings. Model Master 2."
    proxy: "http://llamacpp7:8102"
    checkEndpoint: /health
    cmd: |
      podman run --name llamacpp7 --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/lcpp7-embeddinggemma2.json
      --network llama
      --device nvidia.com/gpu=all
      --security-opt label=disable
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      ghcr.io/ggml-org/llama.cpp@sha256:9dfa49ca795363f5fff96f501469e3565e757951f04701a8ad8a5dc5e3ee916d
      --host 0.0.0.0 --port 8102 -fa on --metrics
      -m /models/embed/embeddinggemma-2/embeddinggemma-2-Q8_0.gguf
      --embedding --pooling mean
      -ngl 999 -c 8192 -b 8192 -ub 8192 -fit off
    cmdStop: /bin/sh -c "podman stop -t 30 llamacpp7 || podman rm -f llamacpp7"
```

## Not done
- No GPU load, no smoke test, no llama-swap edit (parent runs these in a queue step).
- Spec JSONs under `~/ai/config/specs/` for the three entries do not exist.
- DSpark drafts not downloaded or evaluated.
