#!/usr/bin/env bash
# Test 4: build and test one source tree in a container, as evalbox (suites/test4/README.md).
#
#   grade-test4.sh TREE_DIR [TICKET]
#
# TREE_DIR is a finished case's work tree (or suites/test4/project for the baseline). With TICKET, the
# ticket's hidden checks (suites/test4/tickets/TICKET/hidden) run against the built server too.
# Prints one JSON object on stdout (suites/test4/grader/in_container.py); grade-test4.py calls this.
#
# The tree is model-written code: it is only ever built and run inside the container. The host makes
# a private snapshot (without target/ and .git), hands it to evalbox and mounts it read-only.
# One build at a time: a lock file serialises concurrent graders.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/evalbox-lib.sh"   # local podman runs as evalbox
TREE="${1:?tree directory}"; TICKET="${2:-}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
# the grading replay, never the one the running cases use (8126)
HA_URL="${GRADE_HA_URL:-http://host.containers.internal:8127}"
HA_TOKEN="${HA_TOKEN:-bakeoff-placeholder-token}"

[ -d "$TREE" ] || { echo "grade-test4.sh: no such tree: $TREE" >&2; exit 2; }
TREE=$(realpath "$TREE")
GRADER=$(eb_input "$HERE/suites/test4/grader") || exit 1
HMOUNT=()
if [ -n "$TICKET" ]; then
  [ -f "$HERE/suites/test4/tickets/$TICKET/hidden/checks.py" ] || { echo "grade-test4.sh: unknown ticket: $TICKET" >&2; exit 2; }
  HID=$(eb_input "$HERE/suites/test4/tickets/$TICKET/hidden") || exit 1
  HMOUNT=(-v "$HID":/hidden:ro,z)
fi

mkdir -p "$HERE/tmp"
# plain mkdir, not mktemp -d: mktemp's mode 700 masks the group ACL evalbox reads through
snap="$HERE/tmp/t4snap.$$.$RANDOM"; mkdir -p "$snap"
name="t4grade-$$-$RANDOM"
cleanup(){ "$PODMAN" rm -f "$name" >/dev/null 2>&1; rm -rf "$snap" 2>/dev/null || eb_rm "$snap"; }
trap cleanup EXIT INT TERM
tar -C "$TREE" --exclude=./target --exclude=./.git -cf - . 2>/dev/null | tar -C "$snap" -xf - 2>/dev/null
eb_take "$snap" || { echo "grade-test4.sh: could not hand the snapshot to evalbox" >&2; exit 1; }

exec 9>"$HERE/tmp/test4-grade.lock"
flock 9
out=$(timeout -k 30 "${GRADE_TIMEOUT:-5400}" "$PODMAN" run --rm --name "$name" --userns=keep-id:uid=1000,gid=1000 \
      --add-host=host.containers.internal:host-gateway \
      --memory=4g --pids-limit=1024 --cap-drop=ALL --security-opt=no-new-privileges \
      -v "$snap":/src:ro,Z -v "$GRADER":/grader:ro,z "${HMOUNT[@]}" \
      -e GRADE_ROOT=/home/agent/grading \
      -e CARGO_HOME=/home/agent/.cargo -e CARGO_BUILD_JOBS="${GRADE_JOBS:-6}" \
      -e HA_URL="$HA_URL" -e HA_BASE_URL="$HA_URL" -e HA_TOKEN="$HA_TOKEN" \
      "$IMAGE" python3 /grader/in_container.py 2>"$HERE/tmp/test4-grade-last.err" | tail -1)
flock -u 9
case "$out" in
  "{"*) printf '%s\n' "$out" ;;
  *) echo "grade-test4.sh: the container gave no result (see tmp/test4-grade-last.err)" >&2
     printf '{"builds": false, "note": "grading container gave no result", "tests": {}, "hidden": null}\n'; exit 1 ;;
esac
