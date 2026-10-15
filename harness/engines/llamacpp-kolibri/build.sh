#!/bin/sh
# llama.cpp v0.6.0 + Hob-forge kolibri1 patch (Kolibri1ForCausalLM support), CUDA sm86.
# Runs ON SATURN (operator 2026-10-05: compile on Saturn), then the image is copied to titan:
#   ssh saturn 'podman save localhost/llamacpp-kolibri:v0.6.0-sm86' | ssh titan 'podman load'
# The patch (4 commits, written against upstream 836d571, 2026-10-03) applies cleanly to v0.6.0.
set -eu
REV=d81235049384534c167caea52b85a694f6103d14  # llama.cpp v0.6.0 (d81235049)
PATCH_URL=https://huggingface.co/Hob-forge/Kolibri-1-GGUF/resolve/3fc032594aef/kolibri1-llama.cpp.patch
PATCH_SHA=$(cat "$(dirname "$0")/patch.sha256")
B=$HOME/build/llamacpp-kolibri; mkdir -p $B; cd $B
# shallow fetch of the one commit (a full clone took >12 min next to the NAS downloads)
rm -rf llama.cpp; mkdir llama.cpp; cd llama.cpp; git init -q; git remote add origin https://github.com/ggml-org/llama.cpp
git fetch -q --depth 1 origin $REV; git checkout -q FETCH_HEAD
curl -sfL -o ../kolibri1.patch "$PATCH_URL"
echo "$PATCH_SHA  ../kolibri1.patch" | sha256sum -c -
git apply ../kolibri1.patch
nice -n 10 podman build -f .devops/cuda.Dockerfile --target server \
  --build-arg CUDA_DOCKER_ARCH=86 --build-arg APP_VERSION=v0.6.0-kolibri1 --build-arg APP_REVISION=$REV \
  -t localhost/llamacpp-kolibri:v0.6.0-sm86 .
podman image inspect localhost/llamacpp-kolibri:v0.6.0-sm86 --format '{{.Id}}' | tee $B/image-id.txt
