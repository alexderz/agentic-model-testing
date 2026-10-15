#!/usr/bin/env bash
# Screening runner: prefetch weights, run the case, then grade by EXECUTING the
# model's code inside a container.
#
# The grading container is the point: this imports and runs model-written,
# unreviewed Python. It never touches the host interpreter.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE="${1:?case}"; MODEL="${2:?model}"; FLAGS="${3:-}"
OUT="${RESULTS:?}/$CASE"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"

case "$MODEL" in
  orcarouter-fn-uncensored) d=orcarouter-flash-next-uncensored; g='Qwen3.8-Flash-Next-Uncensored-IQ4_XS-*.gguf';;
  flashnext-abliterated-s15) d=flashnext-abliterated-s15; g='Qwen3.8-Flash-Next-Abliterated-s1.5-IQ4_XS.gguf';;
  flashnext-heretic2) d=flashnext-heretic2; g='*.gguf';;
  *) d=""; g="";;
esac
if [ -n "$d" ]; then
  echo "  prefetch: $d"
  "$HERE/prefetch-model.sh" "$d" "$g" 2>&1 | sed 's/^/  /' || echo "  prefetch failed (load will read NFS)"
fi

SCORER=skip "$HERE/run-case-sandboxed.sh" "$CASE" "$MODEL" "$FLAGS"
rc=$?
# A harness failure already wrote meta.json and must not be overwritten with a
# code-quality verdict.
if [ -f "$OUT/meta.json" ]; then
  echo "  runner already recorded $(python3 -c "import json;print(json.load(open('$OUT/meta.json')).get('status'))" 2>/dev/null)"
  exit $rc
fi

load_s=$(python3 -c "print(open('$OUT/load_s').read().strip())" 2>/dev/null || echo -1)
vram=$(python3 -c "print(open('$OUT/vram').read().strip())" 2>/dev/null || echo -1)
dur=$(python3 -c "print(open('$OUT/duration_s').read().strip())" 2>/dev/null || echo -1)

echo "  grading (in container: model-written code)"
podman run --rm --network=none --memory=2g --pids-limit=256 \
  --cap-drop=ALL --security-opt=no-new-privileges --userns=keep-id \
  -v "$OUT":/case:Z -v "$HERE/score-screen.py":/score-screen.py:ro,Z \
  "$IMAGE" python3 /score-screen.py /case "$CASE" "$MODEL" "$FLAGS" "$load_s" "$vram" "$dur" \
  2>&1 | sed 's/^/  /'
