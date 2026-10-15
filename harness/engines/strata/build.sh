#!/bin/bash
# Build localhost/strata:<tag>-sm86 (on Saturn since 2026-10-07; copy with podman save | ssh titan podman load) (Model Master, 2026-10-05; derived from
# titan-config/images/strata/build.sh by titan's previous agent). Pinned: Strata tag+commit,
# llama.cpp zip by commit+sha256, CUDA images by digest (Containerfile). CPU-only build.
#   cd ~/ai/strata/build && nice -n 15 ./build.sh
# Since 0.1.44.1 (2026-10-15): each tag writes its own image-id-<tag>.txt (image-id.txt stays 0.1.42's), and the build is
# fenced for Saturn's memory guardrails: JOBS nvcc jobs (default 3) and MEMORY for the build containers (default 8g;
# they run in their own cgroups, so a scope around this script alone would not cap them). Run it inside a scope too:
#   systemd-run --user --scope -q -p MemoryMax=9G -p MemorySwapMax=0 nice -n 15 env STRATA_TAG=... STRATA_COMMIT=... ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
STRATA_TAG=${STRATA_TAG:-v0.1.40.3}
STRATA_COMMIT=${STRATA_COMMIT:-d5ea7133741e67743c0e886bb426c0ce8d69cf6c}
LLAMA_CPP_COMMIT=3cf03257f219afbe7334045ff7c6a06ac68c627d
LLAMA_CPP_SHA256=cbe23c594282ead2937abb3f008e51fcec4609d9256652fff42c7cc1c21ea47b
IMAGE=localhost/strata:${STRATA_TAG}-sm86
ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
git clone -q --depth 1 --branch "$STRATA_TAG" https://github.com/Niko1221/Strata.git "$ctx/src"
[ "$(git -C "$ctx/src" rev-parse HEAD)" = "$STRATA_COMMIT" ] || { echo "tag $STRATA_TAG moved"; exit 1; }
grep -q "LLAMA_CPP_COMMIT = \"$LLAMA_CPP_COMMIT\"" "$ctx/src/setup.py" || { echo "Strata's pinned llama.cpp changed"; exit 1; }
rm -rf "$ctx/src/.git"; mkdir "$ctx/inputs"
curl -fsSL -o "$ctx/inputs/llama.cpp-$LLAMA_CPP_COMMIT.zip" "https://github.com/ggml-org/llama.cpp/archive/$LLAMA_CPP_COMMIT.zip"
echo "$LLAMA_CPP_SHA256  $ctx/inputs/llama.cpp-$LLAMA_CPP_COMMIT.zip" | sha256sum -c -
cp Containerfile "$ctx/"
grep -vE '^\s*(#|$)|cmake|ninja' "$ctx/src/requirements.txt" > "$ctx/python-requirements.txt"
podman build -t "$IMAGE" --memory "${MEMORY:-8g}" --memory-swap "${MEMORY:-8g}" --build-arg JOBS="${JOBS:-3}" \
  --build-arg LLAMA_CPP_COMMIT="$LLAMA_CPP_COMMIT" --build-arg LLAMA_CPP_SHA256="$LLAMA_CPP_SHA256" "$ctx"
podman image inspect "$IMAGE" --format '{{.Id}}' > "image-id-$STRATA_TAG.txt"
echo "built $IMAGE $(cat "image-id-$STRATA_TAG.txt")"
