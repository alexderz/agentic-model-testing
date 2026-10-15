#!/bin/bash
# Start llama.cpp by hand on titan for the DFlash2 arm of the engine comparison. The image is the one our
# lcpp6 llama-swap entries run (llama.cpp 0.6.0, build 11429), by digest; nothing is built or patched.
#   lcpp-dflash2/run.sh [dflash2|dflash2-q4|nodraft|mtp]
# dflash2      Qwen3.8-27B UD-Q4_K_M with the DFlash2 drafter (BF16 GGUF), 7 tokens a step
# dflash2-q4   the same with the drafter's Q4_K_M GGUF
# nodraft      Qwen3.8-27B UD-Q4_K_M alone
# mtp          the weights and drafting of our entry lcpp6-q38-27b-cyber-mtp (Cyber fine-tune, IQ4_XS, MTP head)
# Serves on 127.0.0.1:18082. CTX sets the window (default 16384), EXTRA adds llama-server flags (e.g. "-np 1" or "-ctk q8_0 -ctv q8_0").
# Needs the GPU lease and nothing loaded in llama-swap. Stop with: podman rm -f -t 10 lcpp-dflash2
set -euo pipefail
IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:a863a2d1dc2cbc5326c995ae380eec9c57f37a7e1cac944f0c6f43e4e9afff23
BASE=/models/llm/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf
CYBER=/models/llm/q38-27b-cyber-agentic/Qwen3.8-27B-Uncensored-Cyber-IQ4_XS-imatrix-fromq8-plus-mtp.gguf
DRAFT=/models/llm/tensorfold-hf/hub/models--z-lab--Qwen3.8-27B-DFlash2-GGUF/snapshots/2d9571f8ce46e151f61c6499c99dee6079e1d610
case "${1:-dflash2}" in
  dflash2)    args=(-m "$BASE" --spec-type draft-dflash --spec-draft-n-max 7 -md "$DRAFT/Qwen3.8-27B-DFlash2-BF16.gguf" -ngld 999);;
  dflash2-q4) args=(-m "$BASE" --spec-type draft-dflash --spec-draft-n-max 7 -md "$DRAFT/Qwen3.8-27B-DFlash2-Q4_K_M.gguf" -ngld 999);;
  nodraft)    args=(-m "$BASE");;
  mtp)        args=(-m "$CYBER" --spec-type draft-mtp --spec-draft-n-max 3);;
  *) echo "usage: $0 [dflash2|dflash2-q4|nodraft|mtp]" >&2; exit 2;;
esac
# shellcheck disable=SC2086
exec podman run -d --name lcpp-dflash2 \
  --device nvidia.com/gpu=all --security-opt label=disable \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  -v /home/operator/ai/models:/models:ro \
  -p 127.0.0.1:18082:8096 \
  "$IMAGE" --host 0.0.0.0 --port 8096 -fa on --metrics \
  "${args[@]}" -ngl 999 -c "${CTX:-16384}" -fit off ${EXTRA:-}
