#!/bin/bash
# One-time Strata data for the bakeoff on titan (CPU only, no GPU). Data dir: ~/ai/strata/data
#   packs/iq3_s, mtp/  : copied from the earlier evaluation (~/ai/models-local/strata-data, same GGUF)
#   packs/swift-iq3_xxs, packs/coder-iq1_m : tools/iq_pack.py on the NAS GGUFs (read-only)
#   configs/*.json     : one per model, 262k context, int8 KV, MTP spec 4 (Strata setup's defaults)
set -euo pipefail
IMAGE=${IMAGE:-localhost/strata:v0.1.40.3-sm86}
D=$HOME/ai/strata/data; OLD=$HOME/ai/models-local/strata-data
mkdir -p "$D/packs" "$D/mtp" "$D/configs" "$D/logs"
[ -d "$D/packs/iq3_s" ] || cp -a "$OLD/packs/iq3_s" "$D/packs/"
[ -f "$D/mtp/rt/experts.bin" ] || cp -a "$OLD/mtp/." "$D/mtp/"
L=/models/llm
pack() {  # name gguf
  [ -f "$D/packs/$1/native_experts.txt" ] && return 0
  podman run --rm --userns=keep-id:uid=10001,gid=10001 --security-opt label=disable --cap-drop ALL \
    --security-opt no-new-privileges -v "$HOME/ai/models:/models:ro" -v "$D:/data" --entrypoint python \
    "$IMAGE" tools/iq_pack.py --gguf "$2" --out "/data/packs/$1"
}
pack swift-iq3_xxs $L/swift15-flash-next/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
pack coder-iq1_m   $L/qwen3.8-flash-next-coder/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
cfg() {  # name pack shard1 shard2 profile model_name
  python3 - "$@" <<'PY'
import json, sys
name, pack, s1, s2, prof, mname = sys.argv[1:7]
json.dump({"exe": "/opt/strata/engine/strata",
  "args": ["--pack", f"/data/packs/{pack}", "--native", s1, "--ple-gguf", s2,
           "--expert-profile", f"/opt/strata/data/{prof}", "--expert-cache", "auto", "--prefill", "auto",
           "--spec", "4", "--spec-min-p", "0.5", "--mtp", "/data/mtp/rt",
           "--max-context", "262144", "--kv", "int8", "--kv-resident", "32768"],
  "cwd": "/opt/strata", "tokenizer": f"/data/packs/{pack}/tokenizer", "model_name": mname,
  "log": f"/logs/{name}.log", "lib_dirs": ["/usr/local/cuda/lib64"], "port": 8793, "host": "0.0.0.0",
  # llama-swap reaches it as strata:8793; Strata's DNS-rebinding guard 403s any
  # other Host, so the health check never passed (2026-10-05).
  "allowed_hosts": ["strata", "strata:8793"],
  # Same 24k thinking cap the other engines get (Strata: off by default). The
  # coder run without it looped in its thinking until the 32k reply cap (2026-10-05).
  "reasoning_budget_tokens": 24000},
  open(f"/home/operator/ai/strata/data/configs/{name}.json", "w"), indent=1)
PY
}
U=$L/qwen3.8-flash-next-unpruned/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-0000
S=$L/swift15-flash-next/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-0000
C=$L/qwen3.8-flash-next-coder/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-0000
cfg flash-next iq3_s         ${U}1-of-00002.gguf ${U}2-of-00002.gguf expert-profile.bin       qwen3.8-flash-next
# swift15 keeps per_layer_token_embd in shard 1, not 2 (start failed 2026-10-05: "not in ...00002")
cfg swift15    swift-iq3_xxs ${S}1-of-00002.gguf ${S}1-of-00002.gguf expert-profile.bin       swift-1.5
cfg coder      coder-iq1_m   ${C}1-of-00002.gguf ${C}2-of-00002.gguf expert-profile-coder.bin qwen3.8-flash-next-coder
ls -la "$D/configs"; du -sh "$D"/packs/* "$D/mtp"
