#!/bin/bash
# One-off HyperQwen model preparation on Titan: CPU only, 4 cores, low priority.
# Writes ~/ai/hyperqwen/models (requantized heads, fast variant, chat template)
# and ~/ai/hyperqwen/cache (HF cache for the 1 GB fast-variant fetch).
set -euo pipefail
H=$HOME/ai/hyperqwen
exec nice -n 15 podman run --rm --name hyperqwen-prepare \
  --cpus 4 --userns=keep-id --cap-drop ALL --security-opt no-new-privileges \
  --security-opt label=disable \
  -v $H/models:/app/models -v $H/cache:/cache \
  -e HOME=/cache -e VLLM_NO_USAGE_STATS=1 -e DO_NOT_TRACK=1 \
  ghcr.io/syv-ai/hyperqwen@sha256:34c2e3a408e2a6ec94d3c6434ff14550b4525301f1ad6c06e40e409db1eefd55 \
  prepare
