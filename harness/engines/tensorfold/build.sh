#!/bin/bash
# Build localhost/tensorfold:<tag>-sm86-p<patch revision> ON TITAN (Model Master 2, 2026-10-13). The context is assembled
# here on Saturn (pinned clone + our patches), copied to titan and built there, because the image carries torch and
# a CUDA compiler (several GB) and titan is where it runs. CPU-only build; the GPU is not touched.
#   ./build.sh            # run as operator on Saturn
set -euo pipefail
cd "$(dirname "$0")"
TF_TAG=${TF_TAG:-v0.6.6}
TF_COMMIT=${TF_COMMIT:-cb2ebf0540f42604e2759b2ddef497861e928248}
TITAN=${TITAN:-"ssh -o HostKeyAlias=titan -o ConnectTimeout=8 192.0.2.62"}
# bump PATCH_REV whenever anything under patches/ changes, so an image tag always names one patch state
PATCH_REV=${PATCH_REV:-4}
IMAGE=localhost/tensorfold:${TF_TAG}-sm86-p${PATCH_REV}
ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
git clone -q --depth 1 --branch "$TF_TAG" https://github.com/ashhart/TensorFold.git "$ctx/src"
[ "$(git -C "$ctx/src" rev-parse HEAD)" = "$TF_COMMIT" ] || { echo "tag $TF_TAG moved"; exit 1; }
for p in patches/*.patch; do [ -e "$p" ] || continue; git -C "$ctx/src" apply --verbose "$(realpath "$p")"; done
rm -rf "$ctx/src/.git"
cp Containerfile "$ctx/"
# pip-freeze.txt is the wheel pin: absent on the very first build (pip resolves, we record), enforced afterwards
if [ -s pip-freeze.txt ]; then cp pip-freeze.txt "$ctx/constraints.txt"; else : > "$ctx/constraints.txt"; fi
remote=$($TITAN mktemp -d /var/tmp/tensorfold-ctx.XXXXXX)
tar -C "$ctx" -c . | $TITAN "tar -C $remote -x && podman build -t $IMAGE -f $remote/Containerfile $remote; rc=\$?; rm -rf $remote; exit \$rc"
$TITAN "podman image inspect $IMAGE --format '{{.Id}}'" > image-id.txt
$TITAN "podman run --rm --entrypoint cat $IMAGE /opt/pip-freeze.txt" > pip-freeze.txt
echo "built $IMAGE $(cat image-id.txt) on titan"
