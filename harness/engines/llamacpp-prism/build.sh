#!/bin/sh
# PrismML llama.cpp fork (branch `prism`), CUDA sm86, for Ternary Bonsai 2 (PTQ1_0 / PQ2_0 need it).
# Runs ON SATURN (operator: compile on Saturn); then copy to titan:
#   ssh saturn 'podman save localhost/llamacpp-prism:<rev12>-sm86' | ssh titan 'podman load'
# Operator 2026-10-07: rerun Bonsai on a current build with the makers' agent settings
# (reasoning_effort medium + a thinking budget); our first runs used a 2026-09-25 build at xhigh.
set -eu
REV=${REV:-6bfcd79a2d426abcd2b50e3c2d09ae2225e70a17}  # prism head 2026-10-05 (#265)
B=$HOME/build/llamacpp-prism; mkdir -p $B; cd $B
rm -rf llama.cpp; mkdir llama.cpp; cd llama.cpp; git init -q; git remote add origin https://github.com/PrismML-Eng/llama.cpp
git fetch -q --depth 1 origin $REV; git checkout -q FETCH_HEAD
T=localhost/llamacpp-prism:$(echo $REV | cut -c1-12)-sm86
nice -n 10 podman build -f .devops/cuda.Dockerfile --target server \
  --build-arg CUDA_DOCKER_ARCH=86 --build-arg APP_VERSION=prism-$(echo $REV | cut -c1-12) --build-arg APP_REVISION=$REV \
  -t $T .
podman image inspect $T --format '{{.Id}}' | tee $B/image-id.txt
