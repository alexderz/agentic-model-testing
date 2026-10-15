#!/bin/bash
# Swap the GLM-5.3-Flash chat template in Maya's pack for zai-org's revision 46a050be (bakeoff, 2026-10-15).
# Run on Saturn as operator from this directory:  ./apply.sh [--check | --rollback]
# Maya reads <pack>/tokenizer/chat_template.jinja once, when its container starts; titan reads the pack over NFS. No
# llama-swap edit, reload or restart is involved: the next load of maya-glm-5.3-flash picks the file up. Refuses while
# titan's /running lists a Maya entry. Asks titan's llama-swap only GET /running (never /unload).
set -euo pipefail
cd "$(dirname "$0")"
DIR=/srv/store/models/llm/glm-5.3-flash-maya/Maya-S-v2-IQ2_XXS/pack/tokenizer
LIVE=$DIR/chat_template.jinja
BAK=$DIR/chat_template.jinja.bak-zai-03eb5366
NEW=chat_template-46a050be.jinja
OLD=pack-03eb5366.chat_template.jinja
NEW_SHA=9f48a59d6e5e9a604a3f250a990fcbb21dc6a2674d918f480419cb71fa775c0f
OLD_SHA=a4fddbbf0b432101a296c17094f8bc5a2b0d30713b5b5cd92f86be78511aa724
T=${TITAN:-192.0.2.62}
SSH="ssh -n -o BatchMode=yes -o ConnectTimeout=20 -o HostKeyAlias=titan $T"
mode=${1:-apply}
case "$mode" in apply | --check | --rollback) ;; *) echo "usage: $0 [--check | --rollback]"; exit 2 ;; esac
sha() { sha256sum "$1" | cut -d' ' -f1; }

# One run at a time, from the first look at the live file to the last check.
exec 9> "${XDG_RUNTIME_DIR:-/tmp}/bakeoff-maya-glm-template.lock"
flock -n 9 || { echo "another apply.sh run holds the lock"; exit 1; }

[ "$(sha "$NEW")" = "$NEW_SHA" ] || { echo "staged $NEW does not match its sha256"; exit 1; }
[ "$(sha "$OLD")" = "$OLD_SHA" ] || { echo "$OLD does not match its sha256"; exit 1; }
live_state() {
  case "$(sha "$LIVE")" in
    "$NEW_SHA") echo new ;;
    "$OLD_SHA") echo old ;;
    *) echo other ;;
  esac
}
state=$(live_state)
echo "live template: $state ($(sha "$LIVE"))"
[ "$state" = other ] && { echo "the live template is neither the old nor the new one; stop and look"; exit 1; }
[ "$mode" = --check ] && exit 0

# Fail closed: anything but a well-formed {"running": [{"model": "<id>", ...}, ...]} with no maya* id stops here.
running=$($SSH 'curl -fsS --max-time 10 http://localhost:8080/running') || { echo "cannot read titan /running"; exit 1; }
printf '%s' "$running" | python3 -I -c '
import json, sys
try:
    r = json.load(sys.stdin)["running"]
    ids = [e["model"] for e in r]
    assert isinstance(r, list) and all(isinstance(i, str) and i for i in ids)
except Exception as e:
    sys.exit(f"unexpected /running response ({type(e).__name__}); stop and look")
maya = [i for i in ids if i.lower().startswith("maya")]
if maya:
    sys.exit(f"a Maya entry is loaded on titan ({maya[0]}); try again when it is not")
print("titan /running:", ", ".join(ids) or "nothing loaded")
'
# The idle check is advisory: nothing stops llama-swap from starting Maya between this check and the rename. That is
# safe because the rename is atomic, so a Maya that starts in the gap reads either the whole old or the whole new file,
# and both are valid templates that render the same prompts for Maya's requests (check_render.py). A Maya that is
# already running read its template at start and is not affected. (operator's podman on titan does not list
# llama-swap's model containers, so /running is the only check.)

tmp=
trap '[ -n "$tmp" ] && rm -f "$tmp"' EXIT
swap() {   # swap <source file> <expected sha> <expected live state>: temp file, verify, fsync, atomic rename, verify
  tmp=$(mktemp "$DIR/.chat_template.jinja.XXXXXX")
  cat "$1" > "$tmp"
  chmod 0644 "$tmp"
  python3 -I -c 'import os, sys; f = os.open(sys.argv[1], os.O_RDONLY); os.fsync(f); os.close(f)' "$tmp"
  [ "$(sha "$tmp")" = "$2" ] || { echo "the temp copy has the wrong sha; live file untouched"; exit 1; }
  [ "$(live_state)" = "$3" ] || { echo "the live template changed during this run; live file untouched"; exit 1; }
  mv -f "$tmp" "$LIVE"
  tmp=
  python3 -I -c 'import os, sys; f = os.open(sys.argv[1], os.O_RDONLY); os.fsync(f); os.close(f)' "$DIR"
  [ "$(sha "$LIVE")" = "$2" ] || { echo "after the swap the live sha is wrong"; exit 1; }
}
if [ "$mode" = --rollback ]; then
  [ "$state" = old ] && { echo "already the old template"; exit 0; }
  swap "$OLD" "$OLD_SHA" new   # from the copy in this directory, not from the backup
  echo "rolled back to the pack's original template (zai-org 03eb5366)"
  exit 0
fi
[ "$state" = new ] && { echo "already applied"; exit 0; }
if [ -e "$BAK" ] || [ -L "$BAK" ]; then
  { [ -f "$BAK" ] && [ ! -L "$BAK" ] && [ "$(sha "$BAK")" = "$OLD_SHA" ]; } \
    || { echo "$BAK exists but is not a regular file with the old sha; stop and look"; exit 1; }
else
  cp -p --update=none "$LIVE" "$BAK"
  [ -f "$BAK" ] && [ ! -L "$BAK" ] && [ "$(sha "$BAK")" = "$OLD_SHA" ] || { echo "backup check failed"; exit 1; }
fi
swap "$NEW" "$NEW_SHA" old
echo "applied: $LIVE is zai-org/GLM-5.3-Flash@46a050be (index form [0]); backup $BAK"
echo "takes effect the next time maya-glm-5.3-flash loads"
