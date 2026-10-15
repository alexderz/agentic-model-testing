#!/bin/bash
# Build localhost/tabbyapi-exl3:<TabbyAPI commit, 8 chars>-exl3-<exllamav3 version> (Model Master 2, 2026-10-13).
# Same route as engines/tensorfold/build.sh: the context is assembled here on Saturn (a clone at the pinned
# commit, unpatched), copied to titan and built there. CPU-only build; the GPU is not touched.
#   ./build.sh            # run as operator on Saturn
# Since 2026-10-15 (exllamav3 1.6.2 beside 1.6.1, the engine A/B): another version keeps its own files,
# pip-freeze-<version>.txt and image-id-<version>.txt (pip-freeze.txt and image-id.txt stay 1.6.1's). Its first
# build takes CONSTRAIN_FROM (a freeze file, default pip-freeze.txt) as the constraints, so every wheel but torch and
# exllamav3 (pinned by URL) stays the one the old image has. BUILD_ON=saturn builds here instead of on titan, which
# then only loads the image (podman save | podman load; the ID is kept): titan's CPU, disk and network stay with a
# running case. Fence it, e.g.
#   systemd-run --user --scope -q -p MemoryMax=9G -p MemorySwapMax=0 nice -n 15 \
#     env TABBY_COMMIT=d6e622706d5511769034446d1bd14dab2a723679 EXL3_VERSION=1.6.2 BUILD_ON=saturn ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
TABBY_COMMIT=${TABBY_COMMIT:-a3fed43efae3b18ec6181618d6a4a66153a9d14e}
EXL3_VERSION=${EXL3_VERSION:-1.6.1}
TITAN=${TITAN:-"ssh -o HostKeyAlias=titan -o ConnectTimeout=8 192.0.2.62"}
BUILD_ON=${BUILD_ON:-titan}
IMAGE=localhost/tabbyapi-exl3:${TABBY_COMMIT:0:8}-exl3-${EXL3_VERSION}
if [ "$EXL3_VERSION" = 1.6.1 ]; then FREEZE=pip-freeze.txt; IDFILE=image-id.txt
else FREEZE=pip-freeze-$EXL3_VERSION.txt; IDFILE=image-id-$EXL3_VERSION.txt; fi
case "$BUILD_ON" in titan) ON=$TITAN ;; saturn) ON="" ;; *) echo "BUILD_ON is titan or saturn"; exit 1 ;; esac
ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
git init -q "$ctx/src"
git -C "$ctx/src" fetch -q --depth 1 https://github.com/theroyallab/tabbyAPI.git "$TABBY_COMMIT"
git -C "$ctx/src" checkout -q FETCH_HEAD
[ "$(git -C "$ctx/src" rev-parse HEAD)" = "$TABBY_COMMIT" ] || { echo "not at $TABBY_COMMIT"; exit 1; }
# the commit must still pin the exllamav3 release this image is named after
grep -q "releases/download/v${EXL3_VERSION}/exllamav3-${EXL3_VERSION}+cu128.torch2.9.0-cp312-cp312-linux_x86_64.whl" \
  "$ctx/src/pyproject.toml" || { echo "pyproject.toml does not pin exllamav3 $EXL3_VERSION"; exit 1; }
rm -rf "$ctx/src/.git"
cp Containerfile "$ctx/"
# $FREEZE is the wheel pin: absent on a version's first build (pip resolves within CONSTRAIN_FROM, we record),
# enforced afterwards. torch and exllamav3 are pinned by URL in pyproject.toml; pip takes no URL lines in a
# constraints file.
SEED=$FREEZE; [ -s "$SEED" ] || SEED=${CONSTRAIN_FROM:-}
if [ -n "$SEED" ] && [ -s "$SEED" ]; then grep -v ' @ ' "$SEED" > "$ctx/constraints.txt"; else : > "$ctx/constraints.txt"; fi
if [ "$BUILD_ON" = titan ]; then
  remote=$($TITAN mktemp -d /var/tmp/exllamav3-ctx.XXXXXX)
  tar -C "$ctx" -c . | $TITAN "tar -C $remote -x && podman build -t $IMAGE -f $remote/Containerfile $remote; rc=\$?; rm -rf $remote; exit \$rc"
else
  podman build -t "$IMAGE" --memory "${MEMORY:-8g}" --memory-swap "${MEMORY:-8g}" -f "$ctx/Containerfile" "$ctx"
fi
# The image must hold exactly the recorded wheels. This is also the check on torch and exllamav3: pip freeze records
# the sha256 of the files their URLs delivered. On a difference the new list is kept beside the old one and the
# build fails; nothing is overwritten.
$ON podman run --rm --network none --entrypoint cat "$IMAGE" /opt/pip-freeze.txt > "$ctx/pip-freeze.new"
if [ -s "$FREEZE" ] && ! diff -u "$FREEZE" "$ctx/pip-freeze.new"; then
  cp "$ctx/pip-freeze.new" "$FREEZE.new"
  echo "the built image differs from $FREEZE (see $FREEZE.new); $IDFILE not updated"; exit 1
fi
cp "$ctx/pip-freeze.new" "$FREEZE"
id=$($ON podman image inspect "$IMAGE" --format '{{.Id}}')
if [ "$BUILD_ON" = saturn ]; then
  podman save "$IMAGE" | $TITAN "ionice -c3 nice -n 15 podman load"
  [ "$($TITAN "podman image inspect $IMAGE --format '{{.Id}}'")" = "$id" ] || { echo "titan's copy has another ID"; exit 1; }
fi
echo "$id" > "$IDFILE"
echo "built $IMAGE $id (on $BUILD_ON; on titan)"
