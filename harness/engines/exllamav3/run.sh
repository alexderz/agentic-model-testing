#!/bin/bash
# Start exllamav3 (TabbyAPI) on titan by hand, outside llama-swap:  ./run.sh [dflash2|mtp|nodraft] [3bpw]
#   dflash2  the DFlash2 drafter (default)      mtp  the EXL3 file's own MTP head      nodraft  no drafting
#   3bpw     the 3.00bpw weights instead of 4.00bpw
# Take the GPU lease first and make sure llama-swap has nothing loaded. Listens on 127.0.0.1:18081 on titan.
# Further TABBY_<SECTION>_<KEY> settings can be passed in EXTRA_ENV, e.g. EXTRA_ENV="-e TABBY_MODEL_CACHE_SIZE=32768".
# The volume exllamav3-cache keeps what Triton compiles. TabbyAPI insists on a log directory under /app, which is
# read-only for its user, so it gets a tmpfs; the same log is on stdout (podman logs exllamav3). Stop: podman rm -f -t 10 exllamav3
set -euo pipefail
cd "$(dirname "$0")"
# the image by id when image-id.txt lies beside this script (build.sh writes it), else by tag
IMAGE=${IMAGE:-$(cat image-id.txt 2>/dev/null || echo localhost/tabbyapi-exl3:a3fed43e-exl3-1.6.1)}
mode=${1:-dflash2}; weights=${2:-4bpw}
case $mode in dflash2) dm=model;; mtp) dm=mtp;; nodraft) dm=disabled;; *) echo "mode: dflash2, mtp or nodraft"; exit 2;; esac
case $weights in 4bpw) rev=113cf7ab958054860e43fb7f3063b1af19171095;; 3bpw) rev=6fe61ad620abfe97c5b49f9722c2bceeea4ccc28;;
  *) echo "weights: 4bpw or 3bpw"; exit 2;; esac
# shellcheck disable=SC2086
exec podman run -d --name exllamav3 --device nvidia.com/gpu=all --security-opt label=disable --cap-drop ALL \
  --read-only -e HOME=/tmp \
  --security-opt no-new-privileges -e TABBY_DRAFT_MODEL_DRAFT_MODE=$dm -e TABBY_MODEL_MODEL_NAME=$rev ${EXTRA_ENV:-} \
  -v /home/operator/ai/models:/models:ro -v "$PWD/config.yml:/app/config.yml:ro" -v exllamav3-cache:/cache \
  --tmpfs /app/logs:rw,size=64m,mode=1777 \
  -p 127.0.0.1:18081:5000 "$IMAGE"
