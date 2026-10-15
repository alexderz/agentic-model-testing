#!/bin/bash
# tests/test_engine_ab.sh: stands in for "ssh titan CMD" (AB_SSH, and SSH for the steps' probe()). llama-swap's :8081
# answers "nothing loaded"; every other command (stat and tail of a log, date) runs here, on the test's own files, with
# podman logs [--since RFC3339] reading $AB_PODMAN_LOG ("EPOCH<tab>line", fractional; missing: the container is gone, exit 125) and
# nvidia-smi a constant. The real podman and nvidia-smi are never called.
podman() {
  local s=0
  [ "$1" = logs ] || return 99
  if [ "$2" = --since ]; then   # RFC 3339 to the nanosecond, as the step sends it; inclusive, as podman's
    s=$(date -d "$3" +%s.%N 2>/dev/null) || { echo "Error: parsing --since \"$3\"" >&2; return 125; }
  fi
  [ -f "${AB_PODMAN_LOG:-}" ] || { echo "Error: no container with name or ID \"exllamav3\" found" >&2; return 125; }
  awk -F'\t' -v s="$s" '$1 + 0 >= s + 0 { print $2 }' "$AB_PODMAN_LOG"
}
nvidia-smi() { echo "1234 MiB"; }
export -f podman nvidia-smi
case "$*" in *127.0.0.1:8081*) echo '{"running":[]}' ;; *) exec bash -c "$*" ;; esac
