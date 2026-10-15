#!/bin/sh
# Build localhost/bitnet-cpp:0b341e5-relu2 ON TITAN (CPU-only image). 2026-10-15.
# Started from Saturn with (fenced per RULES: one heavy job, 12G cap, 6 cores, nice 19):
#   systemd-run --user --unit=build-bitnet-cpp --collect -p MemoryMax=12G -p CPUQuota=600% \
#     nice -n 19 sh ~/build/bitnet-cpp/build.sh
# Log: ~/build/bitnet-cpp/build.log on titan (copied beside this file afterwards).
set -eu
B=$HOME/build/bitnet-cpp
cd $B
TAG=localhost/bitnet-cpp:0b341e5-relu2
podman build --pull=missing --memory 12g --cpu-period 100000 --cpu-quota 600000 \
  --build-arg JOBS=6 -t $TAG -f Containerfile . > $B/build.log 2>&1
podman image inspect $TAG --format '{{.Id}} {{.Size}} {{.Created}}' | tee $B/image-id.txt
podman run --rm --network none --entrypoint /app/llama-server $TAG --version >> $B/image-id.txt 2>&1 || true
cat $B/image-id.txt
