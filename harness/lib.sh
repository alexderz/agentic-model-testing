#!/usr/bin/env bash
# Shared helpers for the Titan model bake-off.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/evalbox-lib.sh"   # local podman runs as evalbox
TITAN=${TITAN:-192.0.2.62}
TITAN_URL="http://$TITAN:8080/v1"
LS_CFG=/home/operator/ai/config/llama-swap.yaml
RESULTS=${RESULTS:-$HOME/bakeoff/results}

_g=$'\033[32m'; _y=$'\033[33m'; _r=$'\033[31m'; _d=$'\033[2m'; _n=$'\033[0m'
log(){ printf '%s\n' "${_d}··${_n} $*"; }
ok(){ printf '%s\n' "${_g}ok${_n} $*"; }
chg(){ printf '%s\n' "${_y}->${_n} $*"; }
err(){ printf '%s\n' "${_r}!!${_n} $*" >&2; }

# -n is load-bearing: without it ssh swallows the caller's stdin. Inside the
# matrix's `while read` loop that ate the rest of matrix.tsv and the run
# stopped after one case.
tssh(){ ssh -n -o ConnectTimeout=10 -o BatchMode=yes "$TITAN" "$@" 2>/dev/null; }

# Rewrite one model's cmd line in llama-swap.yaml, then restart.
# set_variant <model-id> <flags> [spec-override-json]   e.g. set_variant qwen3.8-27b "-ngl 999 -c 65536"
# The override is a matrix note's `spec={...}` (engines/ENTRY-SPEC.md); it wins over values read from the flags.
set_variant() {
  local id="$1" flags="$2" res
  # Container-engine entries (SGLang/EXL3) carry their flags inside the
  # podman spec and have no -ngl line to rewrite. Passing empty flags means
  # "use the entry as configured", which is the only correct behaviour for
  # them -- rewriting would corrupt the entry and restarting llama-swap for
  # nothing would evict the resident model mid-matrix.
  # "-" means "use the entry as configured". An EMPTY column cannot express
  # this: IFS=$'\t' treats tab as whitespace, so bash collapses runs of tabs
  # and an empty middle field silently shifts the next column into flags.
  case "$flags" in ""|-) log "variant: using $id as configured (no flag rewrite)"; return 0;; esac
  # Invariant: a model that offloads experts to CPU must load EAGERLY. With
  # -ncmoe, llama.cpp mmaps the expert tensors, reports "loaded in 4s" having read
  # almost nothing, then the first inference page-faults ~90 GiB off NFS for 8-9
  # minutes and the agent's 300s stream timeout retries forever. This line used
  # to REPLACE the whole -ngl line, silently stripping a `-lm none` someone had
  # put there; wave A survived only because those pages happened to be warm.
  # Enforce it here so no caller can lose it.
  case "$flags" in *-ncmoe*) case "$flags" in *"-lm "*) ;; *) flags="$flags -lm none";; esac;; esac
  res=$(tssh "python3 - <<'PY'
import io,re
p='$LS_CFG'
s=io.open(p,encoding='utf-8').read()
m=re.search(r'(^  $id:\\n(?:.*\\n)*?)(^      -ngl[^\\n]*\\n)', s, re.M)
if not m:
    raise SystemExit('BLOCK_NOT_FOUND')
s=s[:m.start(2)]+'      $flags\\n'+s[m.end(2):]
io.open(p,'w',encoding='utf-8').write(s)
print('SET_OK')
PY")
  if [ "$res" != "SET_OK" ]; then
    err "set_variant $id: could not rewrite llama-swap.yaml ($res)"
    return 1
  fi
  # bakeoff.spec: keep the entry's spec file on titan in step with the flag line just written (served_context,
  # kv_type, thinking.server_budget, placement; cmd_sha256 recomputed). The yaml reference never changes. An entry
  # without a spec is left alone and the runners fall back to their old limits, loudly. MODEL-CHECKLIST.md.
  python3 -I "$(dirname "${BASH_SOURCE[0]}")/tools/entry_spec.py" --rewrite "$id" --flags "$flags" \
    ${3:+--override "$3"} </dev/null >&2 || { err "set_variant $id: bakeoff.spec rewrite failed"; return 1; }
  # Restarting llama-swap does NOT run cmdStop for container entries: their podman containers
  # outlive it, keep the GPU and the fixed --name, and every later load fails (2026-10-05:
  # an orphaned llamacpp6 held 23 GB, the 8 h orcarouter run was refused, Kolibri never loaded).
  # Stop the bake-off's rewritable container entries first. Never touches hyperqwen/flashnext/strata
  # (they are "-" rows and return above without a restart).
  # LLAMA_SERVER_SLOTS_DEBUG=1 on containerised llama.cpp entries (operator-approved 2026-10-06,
  # for the tty11 live IN/OUT view): /slots returns prompt/generated only with it; native entries
  # inherit it from the llama-swap container, our own `podman run` containers do not. Idempotent;
  # applied here because this is the moment the queue edits the yaml and restarts llama-swap anyway,
  # so no running model is disturbed.
  tssh "python3 - <<'PY'
import io,re
p='$LS_CFG'
s=io.open(p,encoding='utf-8').read()
n=0
# One SLOTS_DEBUG line per entry, right after the podman run line (and its spec label, which
# tools/add_entry_specs.py keeps first). The entry may also carry a
# --label bakeoff.spec line there (2026-10-09), so look at the whole command block, and drop the
# duplicates an earlier version of this check added (one per queue restart).
def fix(m):
    global n
    head, body = m.group(1), m.group(2)
    body2 = re.sub(r'^      -e LLAMA_SERVER_SLOTS_DEBUG=1\\n', '', body, flags=re.M)
    out = head + '      -e LLAMA_SERVER_SLOTS_DEBUG=1\\n' + body2
    if out != m.group(0): n += 1
    return out
s2=re.sub(r'(^      podman run --name (?:llamacpp6|llamacpp-kolibri|llamacpp-prism) --rm\\n(?:      --label bakeoff\.spec=\S+\\n)?)((?:      .*\\n)*)', fix, s, flags=re.M)
if n:
    with open(p,'r+',encoding='utf-8') as f: f.seek(0); f.write(s2); f.truncate()
print('SLOTS_DEBUG fixed in', n, 'entries')
PY" >&2
  tssh "podman stop -t 15 llamacpp6 llamacpp-kolibri llamacpp-prism >/dev/null 2>&1; true"
  tssh "systemctl --user restart llama-swap.service" || { err "llama-swap restart failed"; return 1; }
  sleep 8
}

# Load the model and wait until it answers, so load time is not measured.
# Verifies BOTH the HTTP status and that real content came back: `curl -o
# /dev/null` exits 0 on a 404/500, which once made a nonexistent model look
# like a successful warm with 34 MiB of VRAM in use.
warm() {
  local id="$1" t0 t1 code body
  t0=$(date +%s)
  # 2400s, not 900: a cold 95 GiB IQ4_XS reads off NFS at ~180 MiB/s and
  # cannot answer for ~9-20 min depending on what FS-Cache already holds.
  # At 900 this recorded LOAD_FAILED for a model that was loading fine.
  body=$(curl -s -m 2400 -w '\n%{http_code}' "$TITAN_URL/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$id\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}") || return 1
  t1=$(date +%s)
  code=$(printf '%s' "$body" | tail -1)
  # A 5xx immediately after set_variant is llama-swap's proxy answering before
  # its upstream is ready -- set_variant restarts the service and sleeps only 8s.
  # Treating that as a load failure recorded three models as `load_failed` in
  # wave A that had gated successfully minutes earlier. Retry transient 5xx.
  tries=0
  while { [ "$code" = "500" ] || [ "$code" = "502" ] || [ "$code" = "503" ]; } \
        && [ "$tries" -lt "${WARM_RETRIES:-10}" ]; do
    tries=$((tries+1))
    log "warm $id: HTTP $code (upstream not ready), retry $tries/${WARM_RETRIES:-10} in 30s"
    sleep 30
    t0=$(date +%s)
    body=$(curl -s -m 2400 -w '\n%{http_code}' "$TITAN_URL/chat/completions" \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"$id\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}") || return 1
    t1=$(date +%s)
    code=$(printf '%s' "$body" | tail -1)
  done
  [ "$code" = "200" ] || { err "warm $id: HTTP $code after $tries retries"; return 1; }
  printf '%s' "$body" | head -n -1 | jq -e '.choices[0].message' >/dev/null 2>&1 || { err "warm $id: no message in response"; return 1; }
  echo $((t1-t0))
}

vram() { tssh "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits"; }
