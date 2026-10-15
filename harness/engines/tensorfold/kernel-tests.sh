#!/bin/bash
# TensorFold's own tests inside the patched image on titan's RTX 3090: the host tests that encode the GPU
# floor, then the kernel tests for the paths a 4-bit MLX Qwen 27B checkpoint takes. Needs the GPU lease.
# pytest is not in the image; it is installed into /tmp of the throwaway container.
set -u
IMAGE=${IMAGE:-localhost/tensorfold:v0.6.6-sm86-p4}
HOST="tests/test_cuda_build.py tests/test_cuda_gpu_floor.py tests/test_cuda_precision.py tests/test_cuda_cli.py"
GPU="tests/cuda/test_build.py tests/cuda/test_qmm.py tests/cuda/test_qwen27_qmm.py tests/cuda/test_qwen27_prefill.py
 tests/cuda/test_qwen27_forward.py tests/cuda/test_gdn.py tests/cuda/test_prefill_attention.py
 tests/cuda/test_qwen27_dflash2_blocks.py tests/cuda/test_qwen27_glue.py tests/cuda/test_qwen27_draft_attention.py"
podman run --rm --name tensorfold-tests --device nvidia.com/gpu=all --security-opt label=disable --cap-drop ALL \
  --security-opt no-new-privileges -v /home/operator/ai/models:/models:ro -v tensorfold-cache:/cache \
  --entrypoint bash "$IMAGE" -c "
    pip install -q --no-cache-dir --target /tmp/pt 'pytest>=8,<9' 2>&1 | tail -2
    export PYTHONPATH=/tmp/pt
    echo '== host tests'; timeout 600 python -m pytest -p no:cacheprovider -q -rfEs $(echo $HOST) 2>&1 | tail -40
    for t in $(echo $GPU); do echo \"== \$t\"; timeout 900 python -m pytest -p no:cacheprovider -q -rfEs \$t 2>&1 | tail -25; done
    echo '== TESTS DONE'"
