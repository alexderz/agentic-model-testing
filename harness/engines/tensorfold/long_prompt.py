#!/usr/bin/env python3
"""One long prompt with a fact hidden in the middle: does the large context window really work, how fast is
the prompt read, and what does the card hold afterwards. Usage: long_prompt.py BASE MODEL LINES [SEED]
A different SEED gives a prompt that differs from the first line on, so no engine can reuse an earlier prompt."""
import json, random, sys, time, urllib.request

base, model, lines = sys.argv[1], sys.argv[2], int(sys.argv[3])
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 7
rnd = random.Random(seed)
rows = [f"Record {i:05d}: sensor {rnd.randrange(100, 999)} read {rnd.randrange(1000, 9999)} units." for i in range(lines)]
rows[lines // 2] = "Record %05d: the vault code is 48213-KESTREL." % (lines // 2)
body = {"model": model, "temperature": 0, "max_tokens": 40, "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": "\n".join(rows) + "\n\nWhat is the vault code? Answer with the code only."}]}
start = time.time()
req = urllib.request.Request(base + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
reply = json.load(urllib.request.urlopen(req, timeout=1800))
took = time.time() - start
usage = reply["usage"]
print(f"prompt_tokens {usage['prompt_tokens']}  completion_tokens {usage['completion_tokens']}  wall {took:.1f}s  "
      f"about {usage['prompt_tokens'] / took:.0f} prompt tok/s  answer {reply['choices'][0]['message']['content']!r}")
t = reply.get("timings")           # llama.cpp reports its own split; TensorFold logs prefill= and cached= on the server
if t:
    print(f"   server: read {t.get('prompt_n')} new tokens in {t.get('prompt_ms', 0) / 1000:.1f}s "
          f"({t.get('prompt_per_second', 0):.0f} tok/s), reused {t.get('cache_n')} from cache")
