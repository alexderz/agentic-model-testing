#!/usr/bin/env bash
# The coarse fill probe stepped ncmoe by start/8 and found no improvement for
# the three biggest models -- one step overshot their free VRAM, so it recorded
# "no headroom" when 6-15 GB was sitting idle. Bisect between the last value
# that loaded and the first that OOM'd.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"; source lib.sh
OUT="${OUT:-$HERE/results-r2/fill-bisect.tsv}"
printf 'model\tctx\tok_hi\tfail_lo\tbest\tvram_mib\theadroom_mib\n' > "$OUT"

# model:ctx:known_ok:known_fail
for e in "qwen3-235b-a22b:40960:94:83" "nemotron3-super-120b:1048576:88:77" "glm-4.5-air:131072:47:42"; do
  m="${e%%:*}"; r="${e#*:}"; ctx="${r%%:*}"; r="${r#*:}"; hi="${r%%:*}"; lo="${r##*:}"
  echo "=== $m ctx=$ctx bisect ($lo, $hi] ==="
  best="$hi"; bv=""
  while [ $((hi - lo)) -gt 1 ]; do
    mid=$(( (hi + lo) / 2 ))
    printf '  ncmoe %-3s ' "$mid"
    if set_variant "$m" "-ngl 999 -ncmoe $mid -c $ctx" >/dev/null 2>&1 && \
       ls=$(warm "$m" 2>/dev/null) && [ "$ls" != "-1" ]; then
      v=$(vram); printf 'OK  %s MiB (%s free)\n' "$v" "$((24576 - v))"
      hi="$mid"; best="$mid"; bv="$v"
    else
      printf 'FAIL\n'; lo="$mid"
    fi
  done
  if [ "$best" != "${e#*:*:}" ] && [ -n "$bv" ]; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$m" "$ctx" "$hi" "$lo" "$best" "$bv" "$((24576 - bv))" >> "$OUT"
    echo "  best: ncmoe $best ($bv MiB)"
  else
    printf '%s\t%s\t%s\t%s\tNONE\t\t\n' "$m" "$ctx" "$hi" "$lo" >> "$OUT"
    echo "  no improvement"
  fi
done
echo; column -t -s$'\t' "$OUT"
