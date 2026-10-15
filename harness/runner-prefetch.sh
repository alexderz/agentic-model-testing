#!/usr/bin/env bash
# Runner wrapper: warm the model's weights through FS-Cache, then run the case.
#
# A cold 95 GiB load reads NFS at ~180 MiB/s via mmap page faults and twice
# outran llama-swap's health check. A sequential `cat` reads at 390 MiB/s, and
# with the weights cached the same model loaded in 9s instead of 20+ minutes.
#
# The prefetch runs HERE -- immediately before the case, with no other model
# resident -- and never in parallel with a running case: titan has 125 GB of RAM
# and these models are ~95 GiB, so streaming a second one would evict the
# running model's pages.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:-}"

# llama-swap id -> directory under ~/ai/models/llm, plus the shard glob.
# Explicit rather than derived: the earlier attempt to parse this out of
# llama-swap.yaml over ssh failed silently twice.
case "$MODEL" in
  orcarouter-fn-uncensored)
    d=orcarouter-flash-next-uncensored; g='Qwen3.8-Flash-Next-Uncensored-IQ4_XS-*.gguf';;
  flashnext-abliterated-s15)
    d=flashnext-abliterated-s15;        g='Qwen3.8-Flash-Next-Abliterated-s1.5-IQ4_XS.gguf';;
  flashnext-heretic2)
    d=flashnext-heretic2;               g='*.gguf';;   # weights + mmproj
  *) d=""; g="";;
esac

if [ -n "$d" ]; then
  echo "  prefetch: warming $d through FS-Cache"
  "$HERE/prefetch-model.sh" "$d" "$g" 2>&1 | sed 's/^/  /' || echo "  prefetch failed (continuing; load will read NFS)"
fi

exec "$HERE/run-case-sandboxed.sh" "$CASE" "$MODEL" "$FLAGS"
