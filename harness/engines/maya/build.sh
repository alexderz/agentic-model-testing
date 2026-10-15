#!/bin/bash
# Build localhost/maya:<tag>-sm86 on Saturn (Model Master, 2026-10-07), then copy it to titan with
# podman save | ssh titan podman load. Pinned: Maya tag+commit, llama.cpp zip by commit+sha256 (Strata's pin), CUDA
# images by digest (Containerfile). CPU-only build. Capped: run under
#   systemd-run --user --scope -p CPUQuota=600% -p MemoryMax=24G nice -n 15 ./build.sh
# Since 2026-10-15 (Maya v1.1.11 beside v1.0.4, the engine A/B; Model Master 2): a tag other than v1.0.4 takes its
# patches from patches-<tag>/ (re-ported by hand, never the old diffs) and writes image-id-<tag>.txt; patches/ and
# image-id.txt stay v1.0.4's. The podman build is capped too (MEMORY, default 8g; JOBS, default 6), because
# rootless podman runs the build's RUN steps outside the calling scope. Saturn's caps since 2026-10-10:
#   systemd-run --user --scope -q -p MemoryMax=9G -p MemorySwapMax=0 nice -n 15 \
#     env MAYA_TAG=v1.1.11 MAYA_COMMIT=89313399b330600b455603d3c569c1f188f96db1 JOBS=3 MEMORY=8g ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
MAYA_TAG=${MAYA_TAG:-v1.0.4}                                   # VERSION 1.3.0 (the tags were renumbered)
MAYA_COMMIT=${MAYA_COMMIT:-70e0746e6f2d02a7cbdb22ac33c1b31ee2ce1213}
LLAMA_CPP_COMMIT=3cf03257f219afbe7334045ff7c6a06ac68c627d
LLAMA_CPP_SHA256=cbe23c594282ead2937abb3f008e51fcec4609d9256652fff42c7cc1c21ea47b
if [ "$MAYA_TAG" = v1.0.4 ]; then PDIR=patches; IDFILE=image-id.txt; else PDIR=patches-$MAYA_TAG; IDFILE=image-id-$MAYA_TAG.txt; fi
[ -d "$PDIR" ] || { echo "$PDIR missing"; exit 1; }
PATCHED=$(find "$PDIR" -maxdepth 1 -name '*.patch' | wc -l)   # (not ls: with pipefail it fails when there is none)
SUFFIX=; if [ "$PATCHED" -gt 0 ]; then SUFFIX=-p$PATCHED; fi
IMAGE=localhost/maya:${MAYA_TAG}-sm86$SUFFIX
ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
git clone -q --depth 1 --branch "$MAYA_TAG" https://github.com/mw00/project-maya.git "$ctx/src"
[ "$(git -C "$ctx/src" rev-parse HEAD)" = "$MAYA_COMMIT" ] || { echo "tag $MAYA_TAG moved"; exit 1; }
grep -q "LLAMA_CPP_COMMIT = \"$LLAMA_CPP_COMMIT\"" "$ctx/src/setup.py" || { echo "Maya's pinned llama.cpp changed"; exit 1; }
# our patches ($PDIR/*.patch, applied in order; each is opt-in by an env setting, so defaults stay upstream's)
for p in "$PDIR"/*.patch; do [ -e "$p" ] || continue; git -C "$ctx/src" apply --verbose "$(realpath "$p")"; done
rm -rf "$ctx/src/.git"; mkdir "$ctx/inputs"
curl -fsSL -o "$ctx/inputs/llama.cpp-$LLAMA_CPP_COMMIT.zip" "https://github.com/ggml-org/llama.cpp/archive/$LLAMA_CPP_COMMIT.zip"
echo "$LLAMA_CPP_SHA256  $ctx/inputs/llama.cpp-$LLAMA_CPP_COMMIT.zip" | sha256sum -c -
cp Containerfile "$ctx/"
podman build -t "$IMAGE" --memory "${MEMORY:-8g}" --memory-swap "${MEMORY:-8g}" \
  --build-arg LLAMA_CPP_COMMIT="$LLAMA_CPP_COMMIT" --build-arg LLAMA_CPP_SHA256="$LLAMA_CPP_SHA256" \
  --build-arg JOBS="${JOBS:-6}" "$ctx"
podman image inspect "$IMAGE" --format '{{.Id}}' > "$IDFILE"
echo "built $IMAGE $(cat "$IDFILE")"
