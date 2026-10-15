#!/bin/bash
# How much context TensorFold admits for Qwen3.8-27B + DFlash2 on titan's 24 GiB card: ask for the native
# window and read the startup refusal, which names the largest fitting one. No weights are loaded by a refusal.
IMAGE=${IMAGE:-localhost/tensorfold:v0.6.6-sm86-p4}
probe() { label=$1; shift; out=$(podman run --rm --device nvidia.com/gpu=all --security-opt label=disable --cap-drop ALL \
  --security-opt no-new-privileges "$@" -v /home/operator/ai/models:/models:ro -v tensorfold-cache:/cache \
  "$IMAGE" serve TensorFold/Qwen3.8-27B-MLX-4bit --name bench --context 262144 --no-thinking $EXTRA 2>&1 | tail -1)
  echo "$label: $(echo "$out" | grep -o 'window: [0-9]* tokens' || echo "$out")"; }
EXTRA="" probe "kv bf16, reserve 4 GiB (default)"
EXTRA="" probe "kv bf16, reserve 2 GiB" -e TENSORFOLD_MEMORY_RESERVE_GIB=2
EXTRA="--kv-dtype int8" probe "kv int8, reserve 4 GiB"
EXTRA="--kv-dtype int8" probe "kv int8, reserve 2 GiB" -e TENSORFOLD_MEMORY_RESERVE_GIB=2
EXTRA="--kv-dtype int4" probe "kv int4, reserve 4 GiB"
EXTRA="--kv-dtype int4" probe "kv int4, reserve 2 GiB" -e TENSORFOLD_MEMORY_RESERVE_GIB=2
EXTRA="--no-drafts" probe "no drafter, kv bf16, reserve 4 GiB"
