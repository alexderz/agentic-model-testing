#!/bin/bash
# Start TensorFold on titan by hand (outside llama-swap): ./run.sh [serve arguments after the model...]
# Take the GPU lease first and make sure llama-swap has nothing loaded. Listens on 127.0.0.1:18080 on titan.
# The volume tensorfold-cache keeps the kernels compiled on first start. Stop: podman rm -f -t 10 tensorfold
set -euo pipefail
IMAGE=${IMAGE:-localhost/tensorfold:v0.6.6-sm86-p4}
MODEL=${MODEL:-TensorFold/Qwen3.8-27B-MLX-4bit}
exec podman run -d --name tensorfold --device nvidia.com/gpu=all --security-opt label=disable --cap-drop ALL \
  --security-opt no-new-privileges -e TENSORFOLD_NO_UPDATE_CHECK=1 \
  -v /home/operator/ai/models:/models:ro -v tensorfold-cache:/cache -p 127.0.0.1:18080:8080 \
  "$IMAGE" serve "$MODEL" --name bench --host 0.0.0.0 --port 8080 "$@"
