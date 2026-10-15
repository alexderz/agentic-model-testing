#!/bin/bash
# CPU-only smoke test of BitNet b1.58 2B4T (I2_S) in localhost/bitnet-cpp (default tag 0b341e5-relu2) on titan.
# Fence: whole script under `timeout 120`; container --memory 8g --cpus 8, server niced 19, -t 8,
# port published on 127.0.0.1 only, no GPU device. 2026-10-15.
set -u
N=bitnet-smoke
P=18103
IMG=${IMG:-localhost/bitnet-cpp:0b341e5-relu2}
OUT=$HOME/build/bitnet-cpp/smoke${1:+-$1}
shift || true
EXTRA=("$@")
mkdir -p $OUT
cleanup() { podman stop -t 5 $N >/dev/null 2>&1 || podman rm -f $N >/dev/null 2>&1; }
trap cleanup EXIT
podman run -d --name $N --rm --memory 8g --cpus 8 --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:$P:8080 -v /home/operator/ai/models:/models:ro \
  --entrypoint /usr/bin/nice $IMG -n 19 /app/llama-server \
  --host 0.0.0.0 --port 8080 -t 8 -c 4096 -ngl 0 --metrics \
  -m /models/llm/bitnet-b1.58-2b4t/ggml-model-i2_s.gguf "${EXTRA[@]}" > /dev/null
t0=$(date +%s)
until curl -sf http://127.0.0.1:$P/health >/dev/null; do
  sleep 1; [ $(( $(date +%s) - t0 )) -gt 60 ] && { echo "no health after 60 s"; podman logs $N 2>&1 | tail -30; exit 1; }
done
echo "healthy after $(( $(date +%s) - t0 )) s"
curl -s http://127.0.0.1:$P/v1/models > $OUT/models.json
curl -s http://127.0.0.1:$P/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "messages":[{"role":"system","content":"You are a helpful assistant."},
              {"role":"user","content":"Explain in three sentences why ternary weights make CPU inference cheaper."}],
  "max_tokens":200,"temperature":0}' > $OUT/chat.json
curl -s http://127.0.0.1:$P/v1/completions -H 'Content-Type: application/json' -d '{
  "prompt":"The capital of France is","max_tokens":128,"temperature":0,"ignore_eos":true}' > $OUT/completion.json
curl -s http://127.0.0.1:$P/completion -H 'Content-Type: application/json' -d '{
  "prompt":"Human: Explain in three sentences why ternary weights make CPU inference cheaper.\n\nBITNETAssistant:","n_predict":200,"temperature":0}' > $OUT/manual.json
podman logs $N > $OUT/server.log 2>&1
podman stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' $N
python3 -I - $OUT <<'PY'
import json, sys, os
d = sys.argv[1]
for f in ("chat.json", "completion.json", "manual.json"):
    j = json.load(open(os.path.join(d, f)))
    t = j.get("timings", {})
    c = j["choices"][0] if "choices" in j else {"text": j.get("content"), "finish_reason": j.get("stop_type")}
    txt = c.get("message", {}).get("content") if "message" in c else c.get("text")
    print(f, "| prompt", t.get("prompt_n"), "tok", round(t.get("prompt_per_second", 0), 1), "tok/s | gen",
          t.get("predicted_n"), "tok", round(t.get("predicted_per_second", 0), 1), "tok/s | finish", c.get("finish_reason"))
    print("  ->", (txt or "")[:400].replace("\n", " "))
print(json.load(open(os.path.join(d, "models.json"))).get("data", [{}])[0].get("id"))
PY
grep -E "system_info|n_threads|model type|file type|model size|model params|CPU_REPACK|AVX2" $OUT/server.log | head -12
