#!/usr/bin/env bash
# run-case.sh <case-name> <model-id> <llama-swap-flags> [declared-ctx]
# One test case: set the variant, warm it, run Pi in a clean folder, save stats.
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
PROMPT_FILE="${PROMPT_FILE:-$HERE/prompt.txt}"
[ -s "$PROMPT_FILE" ] || { echo "prompt file missing/empty: $PROMPT_FILE" >&2; exit 1; }
PROMPT="$(cat "$PROMPT_FILE")"
CASE="$1"; MODEL="$2"; FLAGS="$3"; DECL_CTX="${4:-}"

OUT="$RESULTS/$CASE"
# A recorded result is evidence -- a failure record is as valuable as a success
# and the user asked for failures to be kept. Archive rather than destroy.
if [ -f "$OUT/meta.json" ]; then
  arch="$RESULTS/superseded/$CASE-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$(dirname "$arch")"; mv "$OUT" "$arch"
  echo "  archived prior result -> $arch"
fi
rm -rf "$OUT"; mkdir -p "$OUT/work"

# The model works in a clean tree with no AGENTS.md/CLAUDE.md anywhere above
# it, so nothing ambient can reach it and it cannot wander up into the repo
# while exploring. Ancestry /work/tmp/bakeoff -> /work/tmp -> /work
# -> / is verified clean. Output is copied back into results/ afterwards.
WORKROOT="${BAKEOFF_WORKROOT:-/work/tmp/bakeoff}"
WORK="$WORKROOT/$CASE"
rm -rf "$WORK"; mkdir -p "$WORK"
META="$OUT/meta.json"

echo "=== $CASE : $MODEL : $FLAGS ==="

# 1. apply the variant and restart llama-swap
set_variant "$MODEL" "$FLAGS" >/dev/null 2>&1 || { err "could not set variant"; echo '{"case":"'"$CASE"'","status":"variant_failed"}' > "$META"; exit 1; }

# 2. warm: load the model so its load time is NOT inside the measured run
load_s=$(warm "$MODEL" || echo "-1")
if [ "$load_s" = "-1" ]; then
  err "$CASE: model failed to load with [$FLAGS]"
  echo '{"case":"'"$CASE"'","model":"'"$MODEL"'","flags":"'"$FLAGS"'","status":"load_failed"}' > "$META"
  exit 1
fi
v=$(vram)
ok "loaded in ${load_s}s, VRAM ${v} MiB"

# 3. run Pi, isolated cwd + session dir, JSONL events for stats
# No time or turn cap: a slow model is allowed to take days. The one guard is
# for the pathology the MiMo trial exposed -- a tool-call format the server
# cannot parse, so every turn runs to the output-token limit and is rejected,
# producing turns forever and never a file. Once ANY file exists the guard is
# disarmed and the run is left alone.
NOPROGRESS_S="${NOPROGRESS_S:-2700}"   # 45 min with zero files written
MIN_TURNS_STALL="${MIN_TURNS_STALL:-5}"

PROXY_LOG="${PROXY_LOG:-/tmp/ha-proxy-access.log}"
proxy_start=$(wc -l < "$PROXY_LOG" 2>/dev/null || echo 0)

t0=$(date +%s.%N)
# setsid so the guard can kill the whole process group. Killing the subshell
# alone orphans the real `pi` process -- that is how the trial's `timeout` left
# a pi still pinning the GPU after the wrapper had already exited.
# -nc is essential: without it Pi walks up the tree and loads
# ~/src/AGENTS.md and ~/src/<agent workspace>/AGENTS.md, whose SDLC instructions
# made qwen3.6-35b stop and ask permission instead of writing any code. The
# test is meant to be an unguided prompt, so all ambient discovery is off:
#   -nc no AGENTS.md/CLAUDE.md   -ns no skills
#   -np no prompt templates      -ne no extensions
setsid env HA_URL="${HA_URL:-http://127.0.0.1:8124}" \
    HA_TOKEN="${HA_TOKEN:-bakeoff-placeholder-token}" \
    bash -c 'cd "$1" && exec pi --model "titan/$2" --mode json \
    -nc -ns -np -ne \
    --session-dir "$3" -p "$4"' _ "$WORK" "$MODEL" "$OUT/session" "$PROMPT" \
    > "$OUT/events.jsonl" 2> "$OUT/stderr.log" &
pi_pid=$!

( while kill -0 "$pi_pid" 2>/dev/null; do
    sleep 60
    nfiles=$(find "$WORK" -type f 2>/dev/null | wc -l)
    [ "$nfiles" -gt 0 ] && break          # real progress: never interfere again
    elapsed=$(( $(date +%s) - ${t0%.*} ))
    [ "$elapsed" -lt "$NOPROGRESS_S" ] && continue
    nturns=$(grep -c '"type":"turn_start"' "$OUT/events.jsonl" 2>/dev/null || echo 0)
    if [ "$nturns" -ge "$MIN_TURNS_STALL" ]; then
      echo "STALLED: ${elapsed}s, ${nturns} turns, 0 files -- aborting $CASE" >> "$OUT/stderr.log"
      kill -- -"$pi_pid" 2>/dev/null || kill "$pi_pid" 2>/dev/null
      sleep 5
      kill -9 -- -"$pi_pid" 2>/dev/null || kill -9 "$pi_pid" 2>/dev/null
      break
    fi
  done ) &
guard_pid=$!

wait "$pi_pid" 2>/dev/null || true
kill "$guard_pid" 2>/dev/null || true
t1=$(date +%s.%N)

# bring the model's output back into results/ for archival and scoring
cp -a "$WORK/." "$OUT/work/" 2>/dev/null || true

# slice this case's own HA requests out of the shared proxy log
tail -n +$((proxy_start + 1)) "$PROXY_LOG" 2>/dev/null > "$OUT/ha-requests.jsonl" || true
dur=$(python3 -c "print(f'{float('$t1')-float('$t0'):.1f}')")

# 4. distil stats from the event stream
python3 - "$OUT" "$CASE" "$MODEL" "$FLAGS" "$load_s" "$v" "$dur" <<'PY'
import sys,json,os,glob
out,case,model,flags,load_s,vram,dur = sys.argv[1:8]
ev=[]
p=os.path.join(out,"events.jsonl")
if os.path.exists(p):
    for line in open(p,encoding="utf-8",errors="replace"):
        line=line.strip()
        if not line: continue
        try: ev.append(json.loads(line))
        except Exception: pass
def dig(o,*keys):
    for k in keys:
        if isinstance(o,dict) and k in o: o=o[k]
        else: return None
    return o
# Pi streams token-level `message_update` deltas whose usage fields are all
# zero; the real totals ride on message_end/turn_end. Taking a max across all
# events therefore reported 0 tokens for every model. Sum the terminal events
# and count turns from turn_start, not from every streamed message.
tin=tout=cacheR=cacheW=0
turns=sum(1 for e in ev if e.get("type")=="turn_start")
tools=sum(1 for e in ev if e.get("type")=="tool_execution_start")
for e in ev:
    if e.get("type") not in ("message_end","turn_end"): continue
    u=e.get("usage") or dig(e,"message","usage") or {}
    tin    += u.get("input")     or u.get("input_tokens")  or u.get("prompt_tokens")     or 0
    tout   += u.get("output")    or u.get("output_tokens") or u.get("completion_tokens") or 0
    cacheR += u.get("cacheRead") or 0
    cacheW += u.get("cacheWrite") or 0
# Round 2 lets models install packages, so a work dir can contain a venv,
# pip's own source, caches and build artifacts. Counting those reported 816,923
# LOC for a ~300 line tool. Only count what the model actually authored.
_SKIP_DIRS = {"venv", ".venv", "env", ".env", "site-packages", "__pycache__",
              ".pytest_cache", ".git", "node_modules", "build", "dist",
              ".mypy_cache", ".ruff_cache", ".tox", "lib", "lib64", "bin",
              "include", "share", "wheels"}
def _authored(path, root):
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    if any(p in _SKIP_DIRS for p in parts[:-1]):
        return False
    if any(p.endswith(".egg-info") or p.endswith(".dist-info") for p in parts):
        return False
    return not path.endswith((".pyc", ".pyo", ".so", ".whl"))
_root=os.path.join(out,"work")
files=[f for f in glob.glob(os.path.join(_root,"**","*"),recursive=True)
       if os.path.isfile(f) and _authored(f,_root)]
# Detect python by shebang as well as extension: qwen3-coder writes
# `ha-api` with no extension, and an extension-only test scored that
# complete tool as 0 LOC.
def _is_py(path):
    if path.endswith(".py"): return True
    try:
        first=open(path,"rb").readline(200).decode("utf-8","replace")
        return first.startswith("#!") and "python" in first
    except Exception: return False
py=[f for f in files if _is_py(f)]
loc=0
for f in py:
    try: loc+=sum(1 for _ in open(f,encoding="utf-8",errors="replace"))
    except Exception: pass
import ast as _ast
def _ok(f):
    try: _ast.parse(open(f,encoding="utf-8",errors="replace").read()); return True
    except Exception: return False
syntax_ok=sum(1 for f in py if _ok(f))
_sz={}
for f in py: _sz.setdefault(os.path.getsize(f),[]).append(os.path.basename(f))
dupes=[v for v in _sz.values() if len(v)>1]
stalled=os.path.exists(os.path.join(out,"stderr.log")) and "STALLED:" in open(os.path.join(out,"stderr.log"),encoding="utf-8",errors="replace").read()
status="stalled_no_output" if stalled else ("ok" if files else ("no_files" if ev else "no_output"))
meta=dict(case=case,model=model,flags=flags,status=status,
          load_seconds=int(load_s),vram_mib=int(vram),duration_s=float(dur),
          events=len(ev),turns=turns,tool_events=tools,
          input_tokens=tin,output_tokens=tout,cache_read=cacheR,cache_write=cacheW,
          tok_per_s=round(tout/float(dur),2) if tout and float(dur)>0 else None,
          files_created=len(files),py_files=len(py),py_loc=loc,
          py_names=[os.path.basename(f) for f in py],
          py_syntax_ok=syntax_ok,duplicate_groups=dupes)
json.dump(meta,open(os.path.join(out,"meta.json"),"w"),indent=2)
print(f"  events={len(ev)} turns={turns} out_tok={tout} dur={dur}s files={len(files)} py_loc={loc}")
PY
