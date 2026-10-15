#!/bin/sh
# llama.cpp-ada-ternary, branch bonsai-q8-product (professorpalmer/bonsai-ada-surgery: PrismML llama.cpp adfffbe + 46
# patches: tiered KV, MTP drafting at every depth, lookup drafting, reasoning-effort/budget harness-proofing, tool-call
# grammar fixes) for Bonsai 2 27B PTQ1_0 with the grafted MTP head. CUDA sm86. Operator 2026-10-09: "Let's try" it.
# Runs ON SATURN, then: podman save | ssh titan podman load.
set -eu
REV=5251968b01a28ca6b59613254efd58e639586ad8  # bonsai-q8-product, 2026-10-09
B=$HOME/build/llamacpp-bonsai-ada; mkdir -p $B; cd $B
rm -rf src; mkdir src; cd src; git init -q; git remote add origin https://github.com/professorpalmer/llama.cpp-ada-ternary
git fetch -q --depth 1 origin $REV; git checkout -q FETCH_HEAD
nice -n 10 podman build -f .devops/cuda.Dockerfile --target server \
  --build-arg CUDA_DOCKER_ARCH=86 --build-arg APP_VERSION=bonsai-ada-5251968 --build-arg APP_REVISION=$REV \
  -t localhost/llamacpp-bonsai-ada:5251968-sm86 .
podman image inspect localhost/llamacpp-bonsai-ada:5251968-sm86 --format '{{.Id}}' | tee $B/image-id.txt
