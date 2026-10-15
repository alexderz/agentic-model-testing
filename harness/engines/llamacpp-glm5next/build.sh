#!/bin/sh
# llama.cpp from Unsloth's glm5next/upstream branch (PR 27754, closed unmerged), CUDA sm86, for
# Orcarouter's GLM-5.3-Flash Uncensored GGUFs: their general.architecture is "glm5next", the name this
# branch uses; mainline (since 2026-10) calls it "glm5-next" and refuses these files.
# Runs ON SATURN (operator: compile on Saturn), then: podman save | ssh titan podman load.
set -eu
REV=86ebfef2c6a0f3359a2a07d2c215d61b0fa885c9  # unslothai/llama.cpp glm5next/upstream, 2026-09-16
B=$HOME/build/llamacpp-glm5next; mkdir -p $B; cd $B
rm -rf llama.cpp; mkdir llama.cpp; cd llama.cpp; git init -q; git remote add origin https://github.com/unslothai/llama.cpp
git fetch -q --depth 1 origin $REV; git checkout -q FETCH_HEAD
nice -n 10 podman build -f .devops/cuda.Dockerfile --target server \
  --build-arg CUDA_DOCKER_ARCH=86 --build-arg APP_VERSION=glm5next-86ebfef --build-arg APP_REVISION=$REV \
  -t localhost/llamacpp-glm5next:86ebfef-sm86 .
podman image inspect localhost/llamacpp-glm5next:86ebfef-sm86 --format '{{.Id}}' | tee $B/image-id.txt
