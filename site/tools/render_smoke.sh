#!/usr/bin/env bash
# Local render smoke test. Where check_site.mjs proves the derivations in data.js never throw, this proves the
# page itself renders: for the real data and for every mutated copy the checker produces, it stages the site in
# a temporary directory, serves it on 127.0.0.1, loads it in headless Chromium and fails if any section wrote the
# data-render-error marker onto <body> (app.js sets it when a section throws, and keeps drawing the others).
# Local tool only; CI runs check_site.mjs. Needs chromium-browser, python3 and node.
# Usage: bash site/tools/render_smoke.sh [--keep]     (--keep leaves the temp dir with DOM dumps and logs)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
site=$(cd "$here/.." && pwd)
keep=0; [ "${1:-}" = "--keep" ] && keep=1
for tool in chromium-browser python3 node mktemp; do command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 2; }; done

# Everything this script creates lives under one mktemp directory in /var/tmp; cleanup removes only that.
work=$(mktemp -d /var/tmp/amt-render-smoke.XXXXXX)
server_pid=""
stop_server() {
  if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    server_pid=""
  fi
}
cleanup() {
  stop_server
  if [ "$keep" = 1 ]; then echo "kept $work"; else rm -rf -- "$work"; fi
}
trap cleanup EXIT

echo "== data checks (also writes the mutated copies)"
node "$site/tools/check_site.mjs" --emit-mutations "$work/mut" > "$work/check_site.log" || { cat "$work/check_site.log"; echo "check_site.mjs failed" >&2; exit 1; }
tail -1 "$work/check_site.log"

failures=0
for json in "$work"/mut/*.json; do
  name=$(basename "$json" .json)
  stage="$work/site-$name"
  mkdir -p "$stage"
  cp -a "$site/." "$stage/"
  rm -rf "$stage/tools"
  cp "$json" "$stage/data/bakeoff.json"

  # free port: ask for 0 and read back the one the server bound
  python3 -u -m http.server 0 --bind 127.0.0.1 --directory "$stage" > "$work/$name.server.log" 2>&1 &
  server_pid=$!
  port=""
  for _ in $(seq 1 50); do
    port=$(sed -n 's/.*port \([0-9]*\).*/\1/p' "$work/$name.server.log" | head -1)
    [ -n "$port" ] && break
    sleep 0.1
  done
  if [ -z "$port" ]; then echo "  FAIL $name: server did not report a port"; cat "$work/$name.server.log"; failures=$((failures + 1)); stop_server; continue; fi

  dom="$work/$name.dom.html"
  chromium-browser --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
    --user-data-dir="$work/profile-$name" --virtual-time-budget=10000 --window-size=1440,4000 \
    --dump-dom "http://127.0.0.1:$port/" > "$dom" 2> "$work/$name.chromium.log" || true
  stop_server

  problems=()
  grep -q '<body[^>]*data-rendered="1"' "$dom" || problems+=("page never finished rendering")
  if grep -q '<body[^>]*data-render-error=' "$dom"; then problems+=("render error in: $(grep -o '<body[^>]*data-render-error="[^"]*"' "$dom" | sed 's/.*data-render-error="//; s/"$//')"); fi
  grep -q 'id="load-error"[^>]*hidden' "$dom" || problems+=("the data file failed to load")
  grep -q '<dl class="hero-stats"[^>]*><div><dt>' "$dom" || problems+=("hero stats are empty")
  grep -q 'class="motif"' "$dom" || problems+=("no chapter motif was drawn")
  if [ "$name" = real ]; then
    loaded=$(grep -o 'data-loaded="1"' "$dom" | wc -l)
    [ "$loaded" -ge 1 ] || problems+=("no gallery frame reported loaded")
    grep -q 'class="shot featured' "$dom" || problems+=("no full-marks card in the gallery wall")
    grep -q 'class="play"' "$dom" || problems+=("no Play live control in the gallery")
    grep -q '<iframe' "$dom" && problems+=("an iframe exists before the viewer was opened")
  fi
  if [ "${#problems[@]}" -eq 0 ]; then
    echo "  ok   $name: rendered, no section errors ($(grep -o 'class="chapter-head"' "$dom" | wc -l) chapters)"
  else
    failures=$((failures + 1))
    for p in "${problems[@]}"; do echo "  FAIL $name: $p"; done
    grep -i 'uncaught\|error' "$work/$name.chromium.log" | grep -v 'Page load' | head -5 || true
  fi
done

if [ "$failures" -gt 0 ]; then echo "$failures render(s) failed"; exit 1; fi
echo "all renders passed"
