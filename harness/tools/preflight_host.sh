#!/usr/bin/env bash
# Check that THIS host can run the bakeoff. Read-only: it starts nothing on titan
# and sends no inference request (a request would make llama-swap load a model).
#   ./tools/preflight_host.sh        -> one line per check, non-zero exit on any FAIL
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
fail=0; ok(){ printf 'ok    %s\n' "$*"; }; bad(){ printf 'FAIL  %s\n' "$*"; fail=1; }
command -v podman >/dev/null && ok "podman $(podman --version | awk '{print $3}')" || bad "podman missing"
for i in localhost/bakeoff-agent localhost/bakeoff-grader; do
  podman image exists $i && ok "image $i" || bad "image $i missing (Containerfile.agent / Containerfile.grader)"; done
podman image exists ghcr.io/syv-ai/hyperqwen >/dev/null 2>&1 || true   # lives on titan, not here
ssh -n -o BatchMode=yes -o ConnectTimeout=8 titan true 2>/dev/null && ok "ssh alias 'titan'" || bad "ssh alias 'titan' (scripts call 'ssh titan')"
ssh -n -o BatchMode=yes titan '~/bin/gpu-lease status' >/dev/null 2>&1 && ok "gpu-lease on titan" || bad "gpu-lease on titan"
code=$(ssh -n titan "curl -s -m 5 -o /dev/null -w '%{http_code}' localhost:8081/running" 2>/dev/null); [ "$code" = 200 ] && ok "llama-swap admin :8081 via ssh titan" || bad "llama-swap admin :8081 on titan ($code; it is loopback-only)"
code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.0.2.62:8080/v1/models); [ "$code" = 200 ] && ok "llama-swap :8080 /v1/models" || bad "llama-swap :8080 ($code)"
for p in 8126 8127; do ss -ltn "sport = :$p" | grep -q '0.0.0.0:'"$p" && ok "replay :$p on 0.0.0.0" || bad "replay :$p not listening on 0.0.0.0 (./start-replay.sh)"; done
c=$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST -H 'Authorization: Bearer bakeoff-placeholder-token' http://127.0.0.1:8126/api/services/light/turn_on)
case $c in 403|404|405) ok "replay refuses writes ($c)";; *) bad "replay accepted a write ($c)";; esac
cin=$(timeout 40 podman run --rm --add-host=host.containers.internal:host-gateway localhost/bakeoff-agent \
  curl -s -m 8 -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer bakeoff-placeholder-token' \
  http://host.containers.internal:8126/api/states 2>/dev/null)
[ "$cin" = 200 ] && ok "container reaches replay via host.containers.internal" || bad "container -> replay ($cin)"
free=$(df -BG --output=avail . | tail -1 | tr -dc 0-9); [ "${free:-0}" -gt 100 ] && ok "disk ${free}G free here" || bad "disk only ${free}G free (cases use 1-3 GB each, rust target dirs)"
command -v claude-poke >/dev/null && ok "claude-poke (optional)" || echo "info  claude-poke absent (optional; run-matrix only uses it if present)"
exit $fail
