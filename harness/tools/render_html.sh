#!/bin/bash
# Render frames of an untrusted single-file HTML page (model output, test 6) in a sealed container: no network, no
# capabilities, read-only root, the page mounted read-only, as the capped evalbox account. Never open model-written
# SVG or HTML in a browser on a host: the hosts have Internet access (operator, 2026-10-11).
#   tools/render_html.sh <page.html> <out-dir> [ms ...]      default times: 1500 5000 10000
# Writes <out-dir>/frame-<ms>.png (1280 x 800), console-<ms>.txt (the page's console lines and uncaught errors, from
# Chromium's log) and <out-dir>/rewrites.txt. The page's scripts do run, inside the
# container. three.js is not fetched: three.js URLs in the page are rewritten to a local copy of three 0.186.1 (npm
# tarball checked against THREE_SHA below, unpacked at $THREE_DIR). That covers any CDN path into build/,
# examples/jsm/ or addons/, and a bare package URL such as https://esm.sh/three@0.186.1 (to the module build). A
# classic global build (three.min.js) is not provided: 0.186 has none. WebGL is software (SwiftShader). A page that
# loads anything else from the network gets nothing. The page can read files inside the container
# (--allow-file-access-from-files): only its own copy and the three.js copy are there, read-only; accepted.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; source "$HERE/evalbox-lib.sh"
THREE_DIR=${THREE_DIR:-/srv/bakeoff/vendor/three-0.186.1/package}
THREE_SHA="sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA=="
PAGE=$(realpath "$1"); OUT=$2; shift 2; TIMES=("${@:-}"); [ -n "${TIMES[0]}" ] || TIMES=(1500 5000 10000)
[ -f "$THREE_DIR/build/three.module.js" ] || { echo "!! three.js copy missing at $THREE_DIR"; exit 1; }
TGZ=${THREE_TGZ:-$(dirname "$THREE_DIR")/three-0.186.1.tgz}
[ "sha512-$(openssl dgst -sha512 -binary "$TGZ" | base64 -w0)" = "$THREE_SHA" ] || { echo "!! $TGZ does not match THREE_SHA"; exit 1; }
mkdir -p "$OUT"; OUT=$(realpath "$OUT")
S=$(mktemp -d "$HERE/tmp/render-in.XXXXXX"); mkdir -p "$S/three"
cp -r "$THREE_DIR/build" "$S/three/build"; cp -r "$THREE_DIR/examples" "$S/three/examples"
python3 -I "$HERE/tools/three_rewrite.py" "$PAGE" "$S/index.html" "$OUT/rewrites.txt" || { echo "!! three.js rewrite failed"; rm -rf "$S"; exit 1; }
chmod -R g+rX,o+rX "$S"
IN=$(eb_input "$S") || { echo "!! could not hand the page to evalbox"; rm -rf "$S"; exit 1; }
W="/srv/bakeoff/inputs/render-out.$$.$RANDOM"; "$PODMAN" unshare mkdir -p "$W"
for t in "${TIMES[@]}"; do
  timeout -k 10 180 "$PODMAN" run --rm --network=none --cap-drop=ALL --security-opt=no-new-privileges --read-only \
    --tmpfs /tmp:rw,size=512m --tmpfs /root:rw,size=64m --memory=3g --pids-limit=512 \
    -v "$IN":/in:ro,z -v "$W":/out:Z localhost/bakeoff-render \
    chromium --headless --no-sandbox --disable-dev-shm-usage --hide-scrollbars --user-data-dir=/tmp/p \
      --allow-file-access-from-files --use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist \
      --enable-logging=stderr --v=0 \
      --window-size=1280,800 --virtual-time-budget="$t" --screenshot="/out/frame-$t.png" file:///in/index.html \
      >/dev/null 2>"$OUT/.chromium-$t.log"
  # the page's console messages and uncaught errors, for grading point A (a blank frame needs a reason)
  grep -aE 'CONSOLE|Uncaught' "$OUT/.chromium-$t.log" | grep -av 'source: chrome://' | cut -c1-500 | head -n 200 > "$OUT/console-$t.txt"; rm -f "$OUT/.chromium-$t.log"
  [ -s "$W/frame-$t.png" ] && cp "$W/frame-$t.png" "$OUT/" && echo "frame-$t.png" || echo "!! no frame at $t ms"
done
eb_rm "$W" "$IN"; rm -f "$IN.stamp"; rm -rf "$S"
