# Speech-to-text on titan: CrispASR (whisper, parakeet, canary-qwen)

Prepared 2026-10-15 by Claw (engine-prep helper). DRAFT: nothing here is in `llama-swap.yaml`, and
nothing was run on the GPU. Still pending: an independent review by a non-Claude model, and spec JSONs (the
`ENTRY-SPEC.md` engine enum has no STT engine yet).

## Choice: CrispASR, one OpenAI-compatible server for all three model families

- **CrispStrobe/CrispASR** (MIT). It is a whisper.cpp/ggml fork with about 119 backends.
  `crispasr --server` serves:
  - `POST /v1/audio/transcriptions` (OpenAI-compatible, multipart);
  - `POST /inference` (whisper.cpp style);
  - `GET /health`, which returns `{"status": "ok", "backend": ...}`, or 503 `{"status": "loading"}` while loading;
  - `GET /v1/models`, `/backends`, `/progress`;
  - `POST /load`.
- It runs whisper GGML `.bin` files as they are. It also runs `parakeet-tdt-0.6b-v2` (backend `parakeet`) and
  `canary-qwen-2.5b` (backend `canary-qwen`) from GGUF, with no NeMo, Riva or Python.
- Maintenance: very active (v0.8.43 on 2026-10-12, commits on 2026-10-15). However, it is effectively a
  **single-maintainer project with a very fast release pace**, so it is a risk (see below).
- Image: **`ghcr.io/crispstrobe/crispasr@sha256:7e053e4c5210ae9198fd6f2df3723b3953638b21f0a6f990774b34cf1857f955`**
  - Tag `main-cuda-eb633d908120cc5f44b8af8cd4aeb1191f16bfd8`, which is v0.8.43, git `eb633d90`, built
    2026-10-12T03:14Z.
  - CUDA 13.0 (`NVIDIA_REQUIRE_CUDA=cuda>=13.0`; titan's driver 615.78.08 is fine). Built for archs
    75/80/86/89/90/120.
  - **Pulled on titan:** image ID `82b90237650063477e209a75443f426071ca3a45695fe96e5c4f37d8e501602f`, 3.92 GB.
  - Entrypoint `tini -- bash /app/.devops/run-server.sh`, user `crispasr` (uid 1000).
  - Config comes from environment variables: `CRISPASR_MODEL`, `CRISPASR_BACKEND`, `CRISPASR_LANGUAGE`,
    `CRISPASR_PORT` (default 8080), `CRISPASR_AUTO_DOWNLOAD` (default 0), `CRISPASR_CACHE_DIR=/cache` (must be
    writable), `CRISPASR_EXTRA_ARGS`, and `CRISPASR_API_KEYS`.
  - The script logs `nvidia-smi` and the ldconfig resolution at start.
- Other digests, for the record (not pulled):
  - `main-cuda-12-eb633d90…`: `sha256:b5c724c91a3c15b408f568cba01a8ec5abbab1c6ea26dee29e9b021e76eaf4cc`
  - `main` (CPU): `sha256:9652e3552f2a2ee9a31fc30737db550da1cada27bff04f8e2a72f830750a57a1`
  - v0.8.42 `main-cuda`: `sha256:a3618ddee7ae04d77221825a0af5d37f607166cc9b15eccd99c6218c83f15c6d`

Alternatives considered:

| Option | Why not (now) |
| --- | --- |
| whisper.cpp v1.9.5 (`d1be6fde`), `ghcr.io/ggml-org/whisper.cpp@sha256:24f8c99e826de7b1f4fa76406fed87626a8322c880ea4cd15bd339a3c0d42c3a` (main-cuda, CUDA 13) | The most mature and best-maintained, but its server is whisper only (`/inference`, `/load`). Parakeet exists only as `parakeet-cli`; parakeet-server is PR #3904 (open). **This is the fallback for whisper if CrispASR misbehaves.** Not pulled. |
| speaches (v0.9.0-rc.3, last commit 2026-04-18) | Whisper needs CTranslate2 models and parakeet needs onnx-asr ONNX models. It would use none of the NAS files, and it is stale. |
| onnx-asr | Library; covers Parakeet and Canary 1B, but not canary-qwen. |
| transcribe.cpp (handy-computer, v0.4.0) | Library and CLI only, with no server. |
| NeMo / Riva | Excluded by the brief. canary-qwen otherwise needs NeMo. |

## Model paths (NAS `/srv/store/models/stt/`, titan `/home/operator/ai/models/stt/`)

| File | Bytes | Source |
| --- | --- | --- |
| `whisper/ggml-large-v3.bin` | 3,095,033,483 | existing (2026-09-21) |
| `whisper/ggml-large-v3-turbo.bin` | 1,624,555,275 | existing |
| `parakeet-tdt-0.6b-v2-gguf/parakeet-tdt-0.6b-v2.gguf` (F16) | 1,236,861,248 | **new**, `cstr/parakeet-tdt-0.6b-v2-GGUF` @ `8878172f3c45ba231fac8cfd4aff2542b13bc875`, CC-BY-4.0 |
| `parakeet-tdt-0.6b-v2-gguf/parakeet-tdt-0.6b-v2-q8_0.gguf` | 664,466,368 | new, same repo |
| `canary-qwen-2.5b-gguf/canary-qwen-2.5b-f16.gguf` | 5,697,820,960 | **new**, `cstr/canary-qwen-2.5b-GGUF` @ `633d32e7415bb281ea159c60e20dd3ec61fb8ddf`, CC-BY-4.0 |
| `canary-qwen-2.5b-gguf/canary-qwen-2.5b-q8_0.gguf` | 4,376,615,264 | new, same repo |

- The new dirs are siblings of the existing `parakeet-tdt/` (`.nemo`) and `canary-qwen-2.5b/` (NeMo
  safetensors). Those existing dirs were not touched; CrispASR cannot read `.nemo` directly.
- Each new dir has its pinned `download.sh`, `download.log` and the converter's `README.md`.
- The GGUFs were converted by the CrispASR author (cstr) from the NVIDIA releases. They are data, and no code
  from them is run.
- Not covered: `stt/audio8-asr-infinite` and `stt/nemotron-3-diarization` (not in this brief).

## Expected VRAM (estimates; measure in the smoke test)

- whisper large-v3 F16: ~4 GB
- whisper large-v3-turbo: ~2.5 GB
- parakeet-tdt-0.6b-v2 F16: ~2 GB
- canary-qwen-2.5b F16: ~7 GB (Q8_0: ~5.5 GB)

All of these fit easily. canary-qwen takes **English only, about 40 s of audio per request at most**; longer
audio needs chunking on the client or CrispASR's VAD options.

## DRAFT llama-swap entries

One entry per model, all sharing the container name `crispasr` (llama-swap runs one at a time). No `ttl`.

```yaml
  stt-whisper-large-v3-turbo:
    name: "Whisper large-v3-turbo on CrispASR v0.8.43 (OpenAI /v1/audio/transcriptions)"
    description: "ggml-large-v3-turbo.bin (NAS stt/whisper) on CrispASR eb633d90 main-cuda. Multilingual, auto language."
    proxy: "http://crispasr:8080"
    checkEndpoint: /health
    cmd: |
      podman run --name crispasr --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/stt-whisper-large-v3-turbo.json
      --network llama-internal
      --device nvidia.com/gpu=all
      --security-opt label=disable
      --cap-drop ALL
      --security-opt no-new-privileges
      --read-only
      --tmpfs /cache:rw,size=256m,mode=1777
      --tmpfs /tmp:rw,size=1g,mode=1777
      -e CRISPASR_AUTO_DOWNLOAD=0
      -e CRISPASR_BACKEND=whisper
      -e CRISPASR_LANGUAGE=auto
      -e CRISPASR_MODEL=/models/stt/whisper/ggml-large-v3-turbo.bin
      -v /home/operator/ai/models:/models:ro
      ghcr.io/crispstrobe/crispasr@sha256:7e053e4c5210ae9198fd6f2df3723b3953638b21f0a6f990774b34cf1857f955
    cmdStop: /bin/sh -c "podman stop -t 30 crispasr || podman rm -f crispasr"
```

The other entries have the same `cmd`, with the id, label and these values changed:

| Entry id | `CRISPASR_BACKEND` | `CRISPASR_LANGUAGE` | `CRISPASR_MODEL` |
| --- | --- | --- | --- |
| `stt-whisper-large-v3` | `whisper` | `auto` | `/models/stt/whisper/ggml-large-v3.bin` |
| `stt-parakeet-tdt-0.6b-v2` | `parakeet` | `en` | `/models/stt/parakeet-tdt-0.6b-v2-gguf/parakeet-tdt-0.6b-v2.gguf` |
| `stt-canary-qwen-2.5b` | `canary-qwen` | `en` | `/models/stt/canary-qwen-2.5b-gguf/canary-qwen-2.5b-f16.gguf` |

Untested details, to settle in the smoke test:

- With `--read-only`, the server may need another writable path (it decodes uploads, possibly through temp
  files). If so, widen the tmpfs mounts rather than dropping `--read-only`.
- Rootless podman maps uid 1000 to a subuid. The NAS files are world-readable (0644/0755), so the `:ro` mount
  should read fine without `--userns=keep-id`.

## Smoke test

Run this in the queue step only, since it loads the model. Use a short public-domain WAV, e.g. whisper.cpp's
`samples/jfk.wav` (11 s, 16 kHz mono):

```sh
curl -s http://127.0.0.1:8081/upstream/stt-whisper-large-v3-turbo/v1/audio/transcriptions \
  -F file=@jfk.wav -F model=whisper-large-v3-turbo -F response_format=json
# expect {"text":" And so my fellow Americans, ask not what your country can do for you, ..."}
curl -s http://127.0.0.1:8081/upstream/stt-parakeet-tdt-0.6b-v2/v1/audio/transcriptions \
  -F file=@jfk.wav -F model=parakeet -F response_format=json
curl -s http://127.0.0.1:8081/upstream/stt-canary-qwen-2.5b/v1/audio/transcriptions \
  -F file=@jfk.wav -F model=canary-qwen -F response_format=json
```

Also check `GET /health` → `{"status": "ok", "backend": "<name>"}`, then `nvidia-smi` for VRAM, and one clip
longer than 40 s on canary-qwen to see how it fails or chunks.

## Risks

- **Single-maintainer, fast-moving fork.** The image is pinned by digest, so nothing moves under us, but
  upgrades need a re-test. whisper.cpp is the conservative fallback for whisper.
- **`POST /load` swaps the model at runtime** to any path the container can read (all of `/models`, read-only).
  llama-swap would not know about the swap. The route is reachable through `/upstream/<id>/load` by anyone who
  can reach llama-swap.
  - Mitigations: the container has no internet (`llama-internal`, `CRISPASR_AUTO_DOWNLOAD=0`). Optionally set
    `CRISPASR_API_KEYS`, which gates every route except `/health`; clients would then need the key.
  - `/load` is disabled only when `CRISPASR_SERVER_WORKERS>1`, which costs VRAM.
- The server also exposes TTS, voice upload (`/v1/voices`, needs `--voice-dir`, which is not set), translation
  and `/v1/chat/completions` routes. With an ASR backend loaded, these return 400. They add attack surface
  but no capability.

## VibeVoice-ASR-BitNet (VibeASR.cpp)

- `microsoft/VibeASR.cpp` (MIT, last commit 2026-09-15) is **CPU-only**. It is built with a Python
  `setup_env.py` (BitNet-style codegen plus cmake).
- Microsoft reports an RTF of about 0.27 on 8 threads of an AVX2 EPYC. That is practical on titan's AVX2 CPU,
  but it is not a GPU llama-swap fit, and it would compete for the CPU and RAM that the MoE models use.
- **Not built.** CrispASR already has a `vibevoice-bitnet` backend that runs `cstr/vibevoice-asr-bitnet-GGUF`
  (TQ2_0, 1.55 GB, MIT, sha `f5fdbff294893acfe7f54890bc86478c7418e9ec`, not gated) with no extra build.
  It could be one more entry in the table above (backend `vibevoice-bitnet`) if wanted; that GGUF was **not
  downloaded**.
