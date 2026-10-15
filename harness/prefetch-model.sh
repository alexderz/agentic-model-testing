#!/usr/bin/env bash
# Pull a model's weights through FS-Cache before llama.cpp opens them.
#
# Why: llama.cpp mmaps the GGUF and page-faults through it. A cold 95 GiB
# IQ4_XS reads off NFS at ~180 MiB/s, which outran llama-swap's health check
# and killed the load twice. A sequential read populates FS-Cache with large
# requests against the mount's 1 MB rsize, so the load reads local disk.
#
# Run IMMEDIATELY BEFORE the load, never alongside a running case: titan has
# 125 GB RAM and these models are ~95 GiB, so streaming a second one evicts the
# resident model's pages and guts the case that is executing.
#
# Cache is 220 GiB and cachefilesd culls at 7% free, so consecutive 95 GiB
# models evict each other. This makes a load fast; the read still happens.
#
#   ./prefetch-model.sh <model-dir-name> [glob]
#
# Deliberately dumb: one `cat` over ssh. Two cleverer versions failed silently
# -- a heredoc script (ssh -n points stdin at /dev/null, so it never arrived)
# and an inline python3 -c (the remote shell re-split the unquoted program).
# Both exited 0 having read nothing.
set -uo pipefail
TITAN="${TITAN:-192.0.2.62}"
DIR="${1:?model dir under ~/ai/models/llm}"
GLOB="${2:-*.gguf}"
REMOTE_DIR="/home/operator/ai/models/llm/$DIR"

echo "prefetch $DIR ($GLOB)"
# Single-quoted remote command; $REMOTE_DIR/$GLOB are expanded by the REMOTE
# shell, so the glob matches every shard there.
ssh -n -o BatchMode=yes "$TITAN" \
  "sz=\$(du -cb $REMOTE_DIR/$GLOB 2>/dev/null | tail -1 | cut -f1); \
   t0=\$(date +%s); cat $REMOTE_DIR/$GLOB > /dev/null; rc=\$?; t1=\$(date +%s); \
   d=\$(( t1 - t0 )); [ \$d -eq 0 ] && d=1; \
   echo \"  \$(( sz/1024/1024/1024 )) GiB in \${d}s = \$(( sz/1024/1024/d )) MiB/s (cat rc=\$rc)\"" \
  2>&1 | grep -v -iE "xauth|X11"
