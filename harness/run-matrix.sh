#!/usr/bin/env bash
# Run every case in matrix.tsv sequentially, fastest expected first.
# Each case is capped at CASE_TIMEOUT (default 3h). A case that fails to load,
# times out, or leaves no record is recorded anyway and the matrix continues --
# every case leaves a meta.json, no exceptions.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
LOG="${RESULTS:-$HERE/results}/matrix.log"
mkdir -p "${RESULTS:-$HERE/results}"

# Wait for any in-flight Pi run (e.g. the trial) so the GPU is ours.
while pgrep -f "pi --model" >/dev/null 2>&1; do sleep 30; done

# Who owns titan's bakeoff lease. The queues (run-next-*.sh) take it before they start and keep it, with an hourly
# refresher, until every step is done; releasing it after each case (as this script did until 2026-10-15) let another
# caller take the GPU between two cases of a queue that still had steps to run. So the release after a case happens
# only when this script took the lease itself, and only if the lease is still exactly the one it wrote ("eval case
# <case>"): a queue's refresher that rewrote it meanwhile wins. BAKEOFF_LEASE_HELD=1 says the caller holds it (kept),
# =0 that it does not (taken and released per case, the old behaviour). Unset, the status decides before each case:
# held by bakeoff and not stale, with a reason that is not this script's own "eval case ..." (a leftover from a run
# that died), means a queue holds it. While a queue holds it, the per-case acquire (still needed for
# GPU_LEASE_KEEP_MODEL) keeps the queue's reason in front, so the next case (often a new process: tune_and_run.py
# runs one per row) still sees a queue's lease. STALE counts as free, as in gpu-lease. A status that cannot be read
# (three tries) leaves the lease alone for that case: no acquire, no release.
lease_tidy() { tr -cd 'A-Za-z0-9 ._:,/()+=@#\133\135-' | cut -c1-200; }   # safe inside the ssh command's single quotes
lease_read() {   # titan's `gpu-lease status` -> lst, lstate (FREE|HELD|STALE, empty if unreadable), lholder, lreason
  local i
  for i in 1 2 3; do
    lst=$(timeout 60 ssh -n "${TITAN:-192.0.2.62}" '~/bin/gpu-lease status' 2>/dev/null)
    case "$lst" in
      FREE*) lstate=FREE; lholder=; lreason=; return 0 ;;
      "HELD by "*" since "*)
        lstate=HELD; lholder=$(printf '%s\n' "$lst" | sed -n '1s/^HELD by \([^ ]*\) since .*/\1/p')
        lreason=$(printf '%s\n' "$lst" | sed -n 's/^  reason: //p' | head -1); return 0 ;;
      "STALE (was "*)
        lstate=STALE; lholder=$(printf '%s\n' "$lst" | sed -n '1s/^STALE (was \([^,]*\), .*/\1/p')
        lreason=$(printf '%s\n' "$lst" | sed -n '1s/^STALE (was [^,]*, \(.*\)) -- treat as free$/\1/p'); return 0 ;;
    esac
    [ "$i" = 3 ] || sleep 10
  done
  lst=; lstate=; lholder=; lreason=; return 1
}
gpu_wait_tick() {   # one minute of waiting for someone else's lease; gives up at GPU_WAIT_MAX
  sleep 60; waited=$((waited+60))
  if [ "$waited" -ge "${GPU_WAIT_MAX:-43200}" ]; then
    echo "!! GPU held for ${waited}s -- stopping the matrix rather than thrashing" | tee -a "$LOG"
    command -v claude-poke >/dev/null 2>&1 && CLAUDE_POKE_FROM=run-matrix \
      claude-poke "matrix paused: GPU held by another session for ${waited}s" >/dev/null
    exit 0
  fi
}

echo "=== matrix started $(date -Is) ===" | tee -a "$LOG"
while IFS=$'\t' read -r case model flags note; do
  [ -z "${case:-}" ] && continue
  # resume: a case that already produced a good result is not re-run
  # Skip any case with a recorded result, whatever its status. Skipping only
  # "ok" meant a relaunch re-ran recorded FAILURES and destroyed them, which is
  # exactly the evidence worth keeping. Set RERUN=1 to force.
  if [ -f "${RESULTS:-results}/$case/meta.json" ] && [ "${RERUN:-0}" != "1" ]; then
    st=$(jq -r .status "${RESULTS:-results}/$case/meta.json" 2>/dev/null)
    echo "--- skip $case (recorded: $st) ---" | tee -a "$LOG"
    continue
  fi
  # Yield the GPU to real work. llama-swap only arbitrates between its own
  # models; a System One runtime started outside it is invisible to llama-swap,
  # which would still try to load and OOM. The lease is the shared signal.
  # Eval work always waits -- it is never the priority holder.
  LEASE_OURS=0; areason=
  if command -v ssh >/dev/null 2>&1; then
    waited=0
    while :; do   # until the acquire below goes through (another holder can slip in before it)
    # Wait only for SOMEONE ELSE's lease. Waiting on our own label deadlocks the
    # matrix against a lease this harness took earlier and did not release.
    while :; do
      lease_read
      [ "$lstate" = HELD ] && [ "$lholder" != bakeoff ] || break
      [ "$waited" -eq 0 ] && echo "   waiting for GPU: $(printf '%s\n' "$lst" | head -1)" | tee -a "$LOG"
      gpu_wait_tick
    done
    [ "$waited" -gt 0 ] && echo "   GPU free after ${waited}s" | tee -a "$LOG"
    # Whose lease this is (see the top of the file).
    qreason=$(printf '%s\n' "$lreason" | sed 's/ \[eval case [^]]*\]$//' | lease_tidy)
    LEASE_OURS=0; LEASE_TOUCH=1   # decided afresh on every pass (a retry after a lost acquire may see a queue's lease)
    case "${BAKEOFF_LEASE_HELD:-}" in
      1) how="held by the caller (BAKEOFF_LEASE_HELD=1): kept after the case" ;;
      0) LEASE_OURS=1; how="taken for the case and released after it (BAKEOFF_LEASE_HELD=0)" ;;
      *) if [ -z "$lstate" ]; then
           LEASE_TOUCH=0; how="status unreadable: left as it is for this case"
         elif [ "$lstate" = HELD ] && [ "$lholder" = bakeoff ] && [ "${qreason#eval case }" = "$qreason" ]; then
           how="held by the caller (${qreason:-no reason}): kept after the case"
         else
           LEASE_OURS=1; how="taken for the case and released after it"
         fi ;;
    esac
    [ "$how" = "${how_said:-}" ] || { echo "   bakeoff lease $how" | tee -a "$LOG"; how_said=$how; }
    if [ "$LEASE_OURS" = 1 ]; then areason="eval case $case"; else areason="${qreason:-queue lease} [eval case $case]"; fi
    areason=$(printf '%s' "$areason" | lease_tidy)
    # Belt and braces: the lease is advisory, so also confirm the card is
    # actually empty. If something is holding VRAM without a lease, acquiring
    # and loading anyway just produces an OOM that looks like a bad flag set.
    used=$(ssh -n "${TITAN:-192.0.2.62}" \
      'nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits' 2>/dev/null || echo 0)
    if [ "${used:-0}" -gt "${GPU_FREE_MIB:-2000}" ]; then
      echo "   ${used} MiB held with no lease -- checking who" | tee -a "$LOG"
      ssh -n "${TITAN:-192.0.2.62}" \
        'nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader' \
        2>/dev/null | sed 's/^/     /' | tee -a "$LOG"
      # llama-swap holding its own model is fine; it swaps on demand. Ask
      # whether it has ANY model, in ANY state -- requiring "ready" rejected a
      # model that was merely still loading after a config reload.
      # llama-swap what it has resident rather than matching process names --
      # container-engine entries run sglang::scheduler, not llama-server, and
      # name-matching rejected a model llama-swap was legitimately serving.
      if ! ssh -n "${TITAN:-192.0.2.62}" \
           'curl -s -m 8 http://127.0.0.1:8081/running' 2>/dev/null \
           | grep -q '"model"'; then
        echo "!! non-llama-server process on the GPU and no lease -- not starting $case" | tee -a "$LOG"
        command -v claude-poke >/dev/null 2>&1 && CLAUDE_POKE_FROM=run-matrix \
          claude-poke "matrix stopped: ${used} MiB held by a non-llama-server process, no lease" >/dev/null
        exit 0
      fi
    fi
    # Tell the lease which model we are about to use, so it does not unload a
    # model that is already loading for us.
    # Re-acquiring the bakeoff lease while a queue holds it is allowed (same holder) and only renews it.
    [ "$LEASE_TOUCH" = 1 ] || break
    aout=$(ssh -n "${TITAN:-192.0.2.62}" \
      "GPU_LEASE_KEEP_MODEL='$model' ~/bin/gpu-lease acquire bakeoff '$areason'" 2>&1)
    # Someone else took the lease between the status read and the acquire: wait for them like any other holder.
    # Any other failure (ssh) goes on as before.
    printf '%s\n' "$aout" | grep -q '^HELD by ' || break
    echo "   lease taken before our acquire: $(printf '%s\n' "$aout" | grep -m1 '^HELD by ')" | tee -a "$LOG"
    gpu_wait_tick
    done
  fi
  # A swap away from a container entry can leave its container running while
  # the next model loads (2026-10-06: an lcpp6 container still held 23.5 GB
  # when Strata started, and every Strata start then failed). Fixed rows skip
  # set_variant, so stop the llama.cpp containers here too, except the one this
  # case uses (llama-swap's own swap handles that one).
  case "$model" in
    lcpp6-*) keep=llamacpp6 ;; kolibri-*) keep=llamacpp-kolibri ;; bonsai2-27b-pq2-med) keep=llamacpp-prism ;; *) keep= ;;
  esac
  stop=$(printf '%s ' llamacpp6 llamacpp-kolibri llamacpp-prism | sed "s/\b$keep\b //")
  [ -n "$keep" ] || stop="llamacpp6 llamacpp-kolibri llamacpp-prism"
  ssh -n "${TITAN:-192.0.2.62}" "podman stop -t 15 $stop >/dev/null 2>&1; true"
  echo "--- $(date -Is)  $case ---" | tee -a "$LOG"
  # </dev/null so nothing downstream can consume the loop's input either
  # Hard cap per case. An agent can issue a command that never returns -- one
  # wrote `curl -X HEAD` (curl waits for a body the server correctly never
  # sends) with no -m, and blocked the whole matrix for two hours. Without this
  # a single hung tool call stalls an overnight run to no purpose.
  timeout -k 30 "${CASE_TIMEOUT:-10800}" \
    "${RUNNER:-./run-case.sh}" "$case" "$model" "$flags" </dev/null 2>&1 | tee -a "$LOG"
  crc=${PIPESTATUS[0]}
  # Release only a lease this script took, and only while it is still the one written above; a queue's lease (or
  # one its refresher rewrote during the case) stays for the queue's next case or step.
  if [ "$LEASE_OURS" = 1 ]; then
    if lease_read && [ "$lholder" = bakeoff ] && [ "$lreason" = "$areason" ]; then
      ssh -n "${TITAN:-192.0.2.62}" "~/bin/gpu-lease release bakeoff" >/dev/null 2>&1 || true
    else
      now=$(printf '%s\n' "$lst" | head -1)
      echo "   bakeoff lease not released: it is now ${now:-unreadable}" | tee -a "$LOG"
    fi
  fi
  if [ "$crc" -eq 124 ] || [ "$crc" -eq 137 ]; then
    echo "!! $case exceeded CASE_TIMEOUT=${CASE_TIMEOUT:-10800}s -- killed" | tee -a "$LOG"
    podman rm -f "bakeoff-$case" >/dev/null 2>&1 || true
    python3 - "$case" "$model" "${RESULTS:-results}" <<PYEOF
import json, os, sys
case, model, res = sys.argv[1], sys.argv[2], sys.argv[3]
d = os.path.join(res, case); os.makedirs(d, exist_ok=True)
json.dump({"case": case, "model": model, "status": "timeout",
           "reason": f"exceeded CASE_TIMEOUT; killed", "sandboxed": True},
          open(os.path.join(d, "meta.json"), "w"), indent=2)
PYEOF
  fi

  # A case MUST leave a record. Twice in the 2026-09-30 cohort a case finished
  # normally and wrote no meta.json -- the runner died somewhere after the model
  # loaded -- so a later check for the record file reported "no result" while a
  # full work tree with 17 source files sat in the directory. That produced two
  # wrong conclusions, including "no baseline exists". Never rely on the runner.
  CASEDIR="${RESULTS:-results}/$case"
  if [ ! -f "$CASEDIR/meta.json" ] && [ -d "$CASEDIR" ]; then
    echo "   no meta.json from the runner -- reconstructing" | tee -a "$LOG"
    python3 "$HERE/distil-meta.py" "$CASEDIR" "$case" "$model" "$flags" 0 0 0 "" \
      >/dev/null 2>&1 || true
    if [ ! -f "$CASEDIR/meta.json" ]; then
      python3 - "$case" "$model" "$CASEDIR" <<'PYEOF2'
import json, os, sys
case, model, d = sys.argv[1], sys.argv[2], sys.argv[3]
ev = os.path.join(d, "events.jsonl")
n = os.path.getsize(ev) if os.path.exists(ev) else 0
json.dump({"case": case, "model": model,
           "status": "unrecorded" if n else "no_output",
           "reason": "runner wrote no meta.json; events.jsonl %d bytes" % n,
           "sandboxed": True, "reconstructed": True},
          open(os.path.join(d, "meta.json"), "w"), indent=2)
PYEOF2
    fi
  fi

  # Poke after EVERY case so the watching session can review it, not just at the
  # end of the matrix.
  if command -v claude-poke >/dev/null 2>&1; then
    st=$(jq -r '.status // "?"' "$CASEDIR/meta.json" 2>/dev/null || echo "?")
    extra=$(jq -r '"tools=\(.tool_events // "?") rs=\(.rs_files // "?") tps=\(.tok_per_s_agent // .tok_per_s // "?")"' \
             "$CASEDIR/meta.json" 2>/dev/null || echo "")
    CLAUDE_POKE_FROM="run-matrix" claude-poke "case $case ($model): $st  $extra" >/dev/null
  fi
done < <(grep -v '^#' "${MATRIX:-matrix.tsv}")
echo "=== matrix finished $(date -Is) ===" | tee -a "$LOG"

# Wake the watching Claude session. There is no CLI that injects a message into
# a running session, so this drops a sentinel that a tracked watcher blocks on.
# Harmless if nobody is watching.
if command -v claude-poke >/dev/null 2>&1; then
  done_n=$(ls -d "${RESULTS:-results}"/*/meta.json 2>/dev/null | wc -l)
  CLAUDE_POKE_FROM="run-matrix" claude-poke \
    "matrix ${MATRIX:-matrix.tsv} finished: ${done_n} cases with results in ${RESULTS:-results}" >/dev/null
fi
