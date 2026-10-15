# Local containers run as the capped evalbox account (Saturn, 2026-10-07). Sourced by lib.sh,
# the graders and the wave runners; safe to source from scripts without `set -e`.
#
# Rootless podman can relabel (:Z / :z) only files its own account owns: a bind mount of a file
# owned by the harness user fails with "lsetxattr ... operation not permitted". So every path a
# container mounts is first handed to evalbox:
#   eb_take PATH...   writable per-case paths: replaced in place by an evalbox-owned copy
#   eb_input PATH     read-only shared inputs (scripts, docs): an evalbox-owned mirror under
#                     $EB_INPUTS, refreshed when the source changes; prints the mirror's path.
#                     Mount it with :ro,z (shared label), never :Z.
#   eb_rm PATH...     remove trees that hold files owned by a container's user range
# `podman unshare` runs as root of evalbox's user namespace: what it creates is owned by evalbox on
# the host, and it reads our files through group evals (the /srv/bakeoff tree is setgid evals with a
# default ACL group::rwx, so the harness user keeps read/write on everything evalbox creates).

EB_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PODMAN="${PODMAN:-$EB_HERE/tools/podman-eb}"
EB_INPUTS="${EB_INPUTS:-/srv/bakeoff/inputs}"
export PODMAN
podman(){ "$PODMAN" "$@"; }

eb_rm(){ local p; for p; do [ -e "$p" ] || continue; podman unshare rm -rf -- "$(realpath "$p")"; done; }

eb_take(){
  local p
  for p; do
    p=$(realpath "$p") || return 1
    podman unshare cp -r -- "$p" "$p.eb" || { echo "eb_take: copy of $p failed" >&2; return 1; }
    rm -rf -- "$p" && mv -- "$p.eb" "$p" || { echo "eb_take: swap of $p failed" >&2; return 1; }
  done
}

eb_input(){
  local s d stamp
  s=$(realpath "$1") || return 1
  d="$EB_INPUTS/$(printf '%s' "$s" | sha1sum | cut -c1-12)-$(basename "$s")"
  stamp=$(find "$s" -printf '%T@ %s %P\n' | sort | sha1sum | cut -c1-40)
  if [ "$(cat "$d.stamp" 2>/dev/null)" != "$stamp" ]; then
    mkdir -p "$EB_INPUTS"; eb_rm "$d"
    podman unshare cp -r -- "$s" "$d" || { echo "eb_input: copy of $s failed" >&2; return 1; }
    printf '%s\n' "$stamp" > "$d.stamp"
  fi
  printf '%s\n' "$d"
}
