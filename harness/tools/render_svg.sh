#!/bin/bash
# Render frames of an untrusted SVG (model output) in a sealed container: no network, no capabilities,
# read-only root, the file mounted read-only, as the capped evalbox account. Never open model-written
# SVG or HTML in a browser on the host: the hosts have Internet access (operator, 2026-10-11).
#   tools/render_svg.sh <file.svg> <out-dir> [ms ...]      default times: 100 2000 6000
# Writes <out-dir>/frame-<ms>.png. The file is shown as its own document in an iframe filling a 1000 x 1000 window
# (tools/svg_fit.py sets its root to 100% so it fits like object-fit:contain). The iframe is sandboxed without
# allow-scripts, so the file's scripts do not run; its SMIL and CSS animation do. meta.json's static.script says
# whether it relies on script. The wrapper page (ours) seeks the frame to the exact time: SMIL with
# pauseAnimations + setCurrentTime on every <svg> (a nested one keeps its own clock), CSS animations through
# getAnimations() (pause, currentTime). SMIL that begins on a click or "indefinite" (a script's job) stays still.
# 2026-10-14: until then the file was an <img> and the frame time was left to --virtual-time-budget, which does not
# advance SVG animation in this Chromium: every frame was the first one.
# Never add allow-scripts to the iframe: with allow-same-origin that undoes the sandbox. Since 2026-10-15 the two files
# are served over http on the container's loopback (python3 http.server on /in, read-only) instead of file://, and
# Chromium no longer gets --allow-file-access-from-files, so the SVG cannot paint other files of the container into its
# frame. Any path on that origin is requestable, but /in holds only the two regular files this script writes
# (index.html, page.svg) (Grok reviews 2026-10-14 and 2026-10-15; operator left the choice to Claw). If the server
# does not answer within about 10 s the container exits without a frame. A missing frame prints "!! no frame" but
# the exit status stays 0, as the queue scripts expect.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; source "$HERE/evalbox-lib.sh"
SVG=$(realpath "$1"); OUT=$2; shift 2; TIMES=("${@:-}"); [ -n "${TIMES[0]}" ] || TIMES=(100 2000 6000)
for t in "${TIMES[@]}"; do [[ $t =~ ^[0-9]+$ ]] || { echo "!! time $t is not a whole number of ms"; exit 1; }; done
mkdir -p "$OUT"; OUT=$(realpath "$OUT")
S=""; IN=""; W=""
cleanup(){ [ -n "$W" ] && eb_rm "$W"; [ -n "$IN" ] && { eb_rm "$IN"; rm -f "$IN.stamp"; }; [ -n "$S" ] && rm -rf "$S"; }
trap cleanup EXIT
S=$(mktemp -d "$HERE/tmp/render-in.XXXXXX") || { echo "!! no temp dir"; S=""; exit 1; }
python3 -I "$HERE/tools/svg_fit.py" "$SVG" "$S/page.svg" || { echo "!! could not fit the svg"; exit 1; }
cat > "$S/index.html" <<'EOF'
<!doctype html><html><body style="margin:0;background:#888;overflow:hidden">
<iframe id="f" sandbox="allow-same-origin" style="display:block;border:0;width:100vw;height:100vh"></iframe>
<script>
const T = Number(location.hash.slice(1)) || 0, f = document.getElementById('f');
function seek() {
  const d = f.contentDocument, r = d && d.documentElement;
  if (!r) return;
  // the file's own CSS must not resize the root away from the window
  if (r.style) { r.style.setProperty('width', '100%', 'important'); r.style.setProperty('height', '100%', 'important'); }
  // Chromium keeps a separate clock for each nested <svg>, so seek them all
  for (const s of d.querySelectorAll('svg')) if (s.pauseAnimations) { s.pauseAnimations(); s.setCurrentTime(T / 1000); }
  if (d.getAnimations) for (const a of d.getAnimations()) try { a.pause(); a.currentTime = T; } catch (e) {}
}
// seek on load and once more after it, in case the SMIL clock was not running yet
f.addEventListener('load', () => { seek(); setTimeout(seek, 0); });
f.src = 'page.svg';
</script></body></html>
EOF
chmod -R g+rX,o+rX "$S"
IN=$(eb_input "$S") || { echo "!! could not hand the file to evalbox"; IN=""; exit 1; }
W="/srv/bakeoff/inputs/render-out.$$.$RANDOM"; "$PODMAN" unshare mkdir -p "$W"
for t in "${TIMES[@]}"; do
  timeout -k 10 120 "$PODMAN" run --rm --network=none --cap-drop=ALL --security-opt=no-new-privileges --read-only \
    --tmpfs /tmp:rw,size=512m --tmpfs /root:rw,size=64m --memory=3g --pids-limit=512 \
    -v "$IN":/in:ro,z -v "$W":/out:Z localhost/bakeoff-render \
    sh -c 'python3 -I -m http.server 8000 --bind 127.0.0.1 --directory /in >/dev/null 2>&1 &
      up=; for i in $(seq 1 100); do python3 -I -c "import urllib.request as u; u.urlopen(\"http://127.0.0.1:8000/index.html\", timeout=1)" \
        >/dev/null 2>&1 && { up=1; break; }; sleep 0.1; done
      [ -n "$up" ] || exit 3
      exec chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars --user-data-dir=/tmp/p \
        --window-size=1000,1000 --virtual-time-budget=3000 --screenshot="/out/frame-$1.png" "http://127.0.0.1:8000/index.html#$1"' \
      sh "$t" >/dev/null 2>&1
  [ -s "$W/frame-$t.png" ] && cp "$W/frame-$t.png" "$OUT/" && echo "frame-$t.png" || echo "!! no frame at $t ms"
done
