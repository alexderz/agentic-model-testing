# bitnet.cpp (`localhost/bitnet-cpp:0b341e5-relu2`): CPU engine for BitNet b1.58

Prepared 2026-10-15 (Model Master 2). No llama-swap entry exists yet: the entries below
are DRAFTS for the parent to add in a queue step. Nothing here touches the GPU.

    localhost/bitnet-cpp:0b341e5-relu2   (titan, operator's podman; local build, not pushed)
    image id 35e83874e85615b8e20096347b8c8a0f966f31eb63dfe68d38d50b9c8f27cac9, 125,779,656 B,
    created 2026-10-15 12:51:19 UTC
    llama-server --version: 9918 (390c30775), Clang 18.1.3, x86_64
    binaries in /app: llama-server (entrypoint), llama-cli, llama-embedding, llama-bench, VERSION

Do NOT use `localhost/bitnet-cpp:0b341e5` (image id 1831940fd60c..., the first build, same pins
without the patch): its 2B output is wrong (see "Activation bug"). It is still on titan; delete it
when convenient (`podman rmi localhost/bitnet-cpp:0b341e5`).

## Pins
- microsoft/BitNet `0b341e582afbf9e1011f24744b554c96a3477eb5` (2026-07-27, main HEAD on 2026-10-15)
- submodule 3rdparty/llama.cpp = isHuangXin/llama.cpp `390c307752ab78fd8189f359d6954c9ba1be74af`
  (branch release-bitnet-embedding-0.6b-270m; modern llama.cpp with tools/server and the I2_S CPU
  kernels). The build checks the submodule HEAD and fails on a mismatch.
- base `docker.io/library/ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55`
  (build and runtime stage); clang 18.1.3, cmake and make from Ubuntu 24.04 apt (not pinned further).
- Local patch, one line, in the Containerfile (see below).

## CPU, not GPU
I2_S is a CPU format (x86 AVX2 / ARM NEON kernels). The repo's `gpu/` directory is a PyTorch W2A8
GEMV kernel plus a `generate.py` demo for the bf16 2B checkpoint: no server, no GGUF, no embeddings.
So the image is CPU-only and the entries have no `--device`. Titan's Ryzen 9 5950X has AVX2, FMA,
F16C and BMI2 and no AVX-512, so the build sets those flags explicitly (`GGML_NATIVE=OFF`), TL2 off
(as `setup_env.py` does on x86), no OpenMP, static binaries, no web UI, no OpenSSL.

## Activation bug and the patch
At these pins the 2B runs its FFN with SiLU; BitNet-b1.58-2B-4T uses squared ReLU (`hidden_act:
relu2`). Upstream: microsoft/BitNet#588 and #602 (open), fix PR #605 (open, not merged on 2026-10-15).
Reported perplexity on the official GGUF: about 100 to 113 unpatched against 17 to 19 patched and in
HF transformers. Our first smoke run showed exactly the reported symptom ("The capital of France is a
small city, and the capital of France is a small city, ..."). The Containerfile now changes
`LLM_FFN_SILU` to `LLM_FFN_RELU_SQR` in `src/models/bitnet.cpp` only when the arch is `bitnet-b1.58`
and the model has 30 layers (the 2B4T); 1bitLLM `bitnet_b1_58` models share that arch and use SiLU,
so they are unchanged. The RUN step fails the build if the source line is not found exactly once.
Retire the patch when a pinned BitNet release carries #605 (then add
`--override-kv bitnet-b1.58.hidden_activation=str:relu2` instead, per #588).

Two more model-side fixes are in the draft entry, both from smoke evidence:
- The 2B GGUF has no `tokenizer.ggml.pre`; the loader falls back to the default pre-tokenizer and warns
  "GENERATION QUALITY WILL BE DEGRADED". `--override-kv tokenizer.ggml.pre=str:llama-bpe` fixes it
  (Llama 3 tokenizer; prompt of the chat test went from 32 to 29 tokens). Also reported in #588.
- The GGUF's embedded chat template is `Human: ...\n\nBITNETAssistant: ` followed by `eos_token`, so the
  generation prompt ends in an end-of-text token. The reference template from
  `microsoft/bitnet-b1.58-2B-4T` @ 04c3b9ad9361b824064a1f25ea60a8be9599b127 (`tokenizer_config.json`,
  sha256 d27b6986...) is `Role: content<|eot_id|>` per message and `Assistant: ` as the generation
  prompt. It is saved as `/srv/store/models/llm/bitnet-b1.58-2b4t/chat_template.jinja` (provenance in
  `chat_template.SOURCE` beside it) and passed with `--jinja --chat-template-file`.
  Reference sampling (generation_config.json): temperature 0.6, top-p 0.9; eos 128001 and 128009.

Known but not hit here: #601 (I2_S crash at n_ubatch >= 32, only with a BLAS backend; this build has
none), #608 (claims zeroed tensors in the current HF files; the same file sha 4221b252... scores 18.87
perplexity with the ReLU2 fix in #588, and our patched smoke output is coherent, so it does not apply
to this GGUF in practice).

## Build (titan, fenced)
`build.sh` beside this file: `podman build --pull=missing --memory 12g --cpu-period 100000
--cpu-quota 600000 --build-arg JOBS=6 -t localhost/bitnet-cpp:0b341e5-relu2`, started as
`systemd-run --user --unit=build-bitnet-cpp2 --collect -p MemoryMax=12G -p CPUQuota=600% nice -n 19 sh
~/build/bitnet-cpp/build.sh`. Fence caveat: the unit's cgroup holds only the podman client (8 s CPU,
618 MB peak over 2 min 10 s); the compile ran in podman's own build container cgroup, so the
effective limits were podman's `--memory 12g` and 6-CPU quota, plus the inherited nice 19. The first
(unpatched) build: unit build-bitnet-cpp, 3 min 53 s wall, 2.1 GB peak. Logs on titan:
`~/build/bitnet-cpp/build.log` (patched), `build-unpatched.log`, `image-id.txt`, `image-id-unpatched.txt`,
`Containerfile.unpatched`.

## Models (downloaded 2026-10-15 to Saturn /srv/store/models = titan /home/operator/ai/models)
Each dir has `download.sh` (pinned revision, `hf download --revision`), `download.log` (rc=0,
sha256 OK) and `SHA256SUMS` (Hub LFS sha256).

| dir | repo @ revision | file | bytes | sha256 |
|---|---|---|---|---|
| llm/bitnet-b1.58-2b4t | microsoft/bitnet-b1.58-2B-4T-gguf @ a1f2f1c765812aa8af3f6eda4a313707064bba15 | ggml-model-i2_s.gguf | 1,187,801,280 | 4221b252fdd5fd25e15847adfeb5ee88886506ba50b8a34548374492884c2162 |
| embed/bitnet-embedding-0.6b | microsoft/bitnet-embedding-0.6b @ 16176d108561b62e3d6f2b558587afe1140b413f | bitnet-embeddings-0.6b-bf16-i2_s.gguf | 427,935,008 | c89c64f05a2d3f83565250a6762640197fc624df866d4a1bd5853f811219af17 |
| embed/bitnet-embedding-270m | microsoft/bitnet-embedding-270m @ 5f1c2fd19f37ca653a3d719c8ee6cc1895f4b64f | bitnet-embeddings-270m-bf16-i2_s.gguf | 367,487,040 | 8ee5ae971b103cd55758934be54e5c9f7cc2b58b15890615acce8e649988c751 |

The embedding dirs also hold the card README and `mteb_v2_eval_prompts.json` (one-sentence task
instructions per MTEB task).

GGUF metadata (read with a data-only parser): 2B4T arch `bitnet-b1.58`, 30 layers, ctx 4096, gpt2
tokenizer without `pre`, bos 128000, eos 128001. embedding-0.6b arch `qwen3`, ctx 32768, pre `qwen2`,
add_eos true, pooling_type 1 (MEAN). embedding-270m arch `gemma3`, ctx 32768, add_eos true,
pooling_type 1 (MEAN).

Pooling conflict: the card and `docs/bitnet-embeddings-i2s-guide.md` say last-token (EOS) pooling then
L2 normalization; both GGUFs declare MEAN (converter default when no sentence-transformers pooling
config is found). Upstream issue microsoft/BitNet#640 (open) reports that `--pooling last` roughly
doubled rank-1 retrieval accuracy on one set. The drafts use `--pooling last`. Queries need a
one-sentence task instruction (card FAQ; documents need none); the card's own example is
`query: What is BitNet?`, and it does not state the exact wrapper (Qwen3-Embedding's
`Instruct: <task>\nQuery: <text>` is a plausible guess, unverified).

## CPU smoke tests (2B only, titan)
`smoke.sh` beside this file, run as `timeout 120 nice -n 19 bash smoke.sh <tag> <extra server args>`:
container `--memory 8g --cpus 8 --cap-drop ALL --security-opt no-new-privileges`, server under
`nice -n 19`, `-t 8 -c 4096 -ngl 0`, published on 127.0.0.1:18103 only, no GPU device, temperature 0.
Requests: chat (system + "Explain in three sentences why ternary weights make CPU inference cheaper.",
max 200), raw completion "The capital of France is" (128 tokens, ignore_eos), raw `/completion` with the
GGUF's `Human: ...\n\nBITNETAssistant:` format (200). Titan was busy with bake-off queues (load about 10).

| run | image / extra args | chat gen tok/s | completion gen tok/s | raw gen tok/s | prompt tok/s | output |
|---|---|---|---|---|---|---|
| 1 | unpatched | 23.6 (200 tok) | 26.0 | - | 118 to 222 | wrong, repetitive ("a small city, and ...") |
| 2 | unpatched + pre override | 24.4 | 22.0 | 24.6 | 110 to 184 | still wrong ("ternary weights make CPU inference more expensive") |
| 3 | relu2 + pre override | 27.3 | 23.0 | 27.8 | 118 to 282 | completion correct ("Paris. Paris is a city ..."), raw prompt coherent; chat via the GGUF template rambles |
| 4 | relu2 + pre override + reference template | **28.0** (61 tok, stopped on its own) | 25.9 | 18.9 | 110 to 184 | all coherent; chat answer correct and concise |

Container memory about 412 to 425 MB; health after 1 to 2 s (19 s on the first, cold NFS read).
Single-stream generation is about 23 to 28 tok/s on 8 threads of the 5950X (spread is load from the
running queues). Smoke outputs and server logs: titan `~/build/bitnet-cpp/smoke{,-pre,-relu2,-relu2-tpl}/`.
No embedding smoke test was run (only the 2B was allowed).

## Draft llama-swap entries (do not add outside a queue step)
Container `bitnet`, port 8103 (unused in llama-swap.yaml today). CPU only: no `--device`, no
`label=disable` (the smoke tests read /models without it), `--cpus 8` so the bake-off's own CPU work
keeps the rest. `--label bakeoff.spec=...` follows the lcpp6 pattern; the spec JSONs do not exist yet.
`LLAMA_SERVER_SLOTS_DEBUG` is kept from the lcpp6 shape (the fork's server reads it).

```yaml
  bitnet-b158-2b4t:
    name: "BitNet b1.58 2B4T I2_S on bitnet.cpp (CPU)"
    description: "microsoft/BitNet 0b341e5 + fork 390c307 with the relu2 FFN fix (BitNet#588), CPU-only I2_S, 8 threads. Llama-3 pre-tokenizer override and the HF reference chat template (the GGUF lacks the first and ships a broken second). 4k context. Model Master 2."
    proxy: "http://bitnet:8103"
    checkEndpoint: /health
    cmd: |
      podman run --name bitnet --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/bitnet-b158-2b4t.json
      -e LLAMA_SERVER_SLOTS_DEBUG=1
      --network llama
      --memory 4g --cpus 8
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      localhost/bitnet-cpp:0b341e5-relu2
      --host 0.0.0.0 --port 8103 --metrics
      -m /models/llm/bitnet-b1.58-2b4t/ggml-model-i2_s.gguf
      --override-kv tokenizer.ggml.pre=str:llama-bpe
      --jinja --chat-template-file /models/llm/bitnet-b1.58-2b4t/chat_template.jinja
      --temp 0.6 --top-p 0.9
      -t 8 -c 4096 -ngl 0
    cmdStop: /bin/sh -c "podman stop -t 30 bitnet || podman rm -f bitnet"
```

Embedding entries: untested. `--pooling last` per the card (the GGUF says MEAN, see above);
`/v1/embeddings` returns L2-normalized vectors. Context capped at 8192 (the models allow 32768) and
`-b`/`-ub` = `-c` so a request fits one batch; the 8 GB memory cap is a guess for the CPU compute
buffer at ub 8192, lower `-c`/`-ub` if it is hit.

```yaml
  bitnet-embedding-0.6b:
    name: "BitNet embedding 0.6B I2_S on bitnet.cpp (CPU)"
    description: "microsoft/bitnet-embedding-0.6b (Qwen3-based, 1024-dim) I2_S on bitnet.cpp 0b341e5, CPU-only, 8 threads. Last-token pooling per the model card (the GGUF wrongly declares mean, BitNet#640). Queries need a one-sentence task instruction. Model Master 2."
    proxy: "http://bitnet:8103"
    checkEndpoint: /health
    cmd: |
      podman run --name bitnet --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/bitnet-embedding-0.6b.json
      --network llama
      --memory 8g --cpus 8
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      localhost/bitnet-cpp:0b341e5-relu2
      --host 0.0.0.0 --port 8103 --metrics
      -m /models/embed/bitnet-embedding-0.6b/bitnet-embeddings-0.6b-bf16-i2_s.gguf
      --embedding --pooling last
      -t 8 -c 8192 -b 8192 -ub 8192 -ngl 0
    cmdStop: /bin/sh -c "podman stop -t 30 bitnet || podman rm -f bitnet"

  bitnet-embedding-270m:
    name: "BitNet embedding 270M I2_S on bitnet.cpp (CPU)"
    description: "microsoft/bitnet-embedding-270m (Gemma3-based) I2_S on bitnet.cpp 0b341e5, CPU-only, 8 threads. Last-token pooling per the model card (the GGUF wrongly declares mean, BitNet#640). Queries need a one-sentence task instruction. Model Master 2."
    proxy: "http://bitnet:8103"
    checkEndpoint: /health
    cmd: |
      podman run --name bitnet --rm
      --label bakeoff.spec=/home/operator/ai/config/specs/bitnet-embedding-270m.json
      --network llama
      --memory 8g --cpus 8
      --cap-drop ALL
      --security-opt no-new-privileges
      -v /home/operator/ai/models:/models:ro
      localhost/bitnet-cpp:0b341e5-relu2
      --host 0.0.0.0 --port 8103 --metrics
      -m /models/embed/bitnet-embedding-270m/bitnet-embeddings-270m-bf16-i2_s.gguf
      --embedding --pooling last
      -t 8 -c 8192 -b 8192 -ub 8192 -ngl 0
    cmdStop: /bin/sh -c "podman stop -t 30 bitnet || podman rm -f bitnet"
```

## Not done
- No llama-swap edit, no spec JSONs, no GPU use.
- No embedding smoke test; pooling (last vs mean) and the query-instruction format are unverified here.
- No perplexity or quality eval of the patched 2B beyond the smoke prompts.
- The patch is local; nothing was posted upstream.
