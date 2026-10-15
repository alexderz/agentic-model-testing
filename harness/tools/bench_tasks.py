#!/usr/bin/env python3
"""Decode speed by task (code, prose, structured) of an OpenAI-compatible server, measured from the stream.

Five prompts a task, one request each, thinking off. tok/s = (completion tokens - 1) / (last piece - first piece),
the span after the first token, so prompt processing is not in it. Written for the engine comparison of
2026-10-13 (TensorFold + DFlash2 against llama.cpp on the RTX 3090); the method follows the published RTX 5090
comparison: 5 prompts a task, a fresh server start a round. Standard library only.

  python3 bench_tasks.py http://127.0.0.1:8080 MODEL --tokens 400 --output round1.json
"""
import argparse, json, statistics, sys, time, urllib.request

TASKS = {
    "code": [
        "Write a Python function that parses an ISO 8601 duration string such as P3DT4H30M into a timedelta. Include type hints and handle invalid input.",
        "Write a Rust function that merges overlapping closed intervals in a Vec<(i64, i64)> and returns them sorted. Add unit tests.",
        "Write a TypeScript class implementing an LRU cache with get, set and delete in O(1), generic over key and value types.",
        "Write a Go HTTP handler that accepts a JSON body with fields name and email, validates both, and answers with JSON errors per field.",
        "Write a Python script that walks a directory tree, hashes every file with SHA-256 and prints groups of duplicate files, largest first.",
    ],
    "prose": [
        "Explain to a curious adult why the sky is blue at noon and red at sunset. About four paragraphs.",
        "Write a short essay on why public libraries still matter in a town where everyone owns a phone.",
        "Describe how a bill becomes a law in a parliamentary system, in plain language, for a school newspaper.",
        "Write a product description for a hand-forged kitchen knife: who makes it, how, and how to care for it.",
        "Tell the story of the first ascent of a fictional mountain, as a mountaineering magazine would report it.",
    ],
    "structured": [
        "Return only JSON: an array of 12 objects describing fictional employees, each with id, first_name, last_name, department, salary, start_date, and skills (array of 3 strings).",
        "Return only JSON: a product catalog with 3 categories, each holding 4 products with sku, name, price, currency, in_stock, and dimensions {width_mm, height_mm, depth_mm}.",
        "Return only JSON: an OpenAPI-style description of 5 endpoints of a to-do list API, each with method, path, summary, parameters (array) and responses (object keyed by status code).",
        "Return only JSON: a weekly schedule, one key per weekday, each an array of 4 events with start, end, title, location and attendees (array of 2 names).",
        "Return only YAML: a Kubernetes Deployment and a Service for a web app named storefront with 3 replicas, resource limits, liveness and readiness probes, and two environment variables.",
    ],
}


def one(base, model, prompt, tokens, temperature):
    body = {"model": model, "max_tokens": tokens, "temperature": temperature, "stream": True,
            "stream_options": {"include_usage": True}, "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False}}
    if temperature > 0:
        body.update(top_k=20, top_p=0.95)
    req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    first = last = None
    usage, text = None, []
    with urllib.request.urlopen(req, timeout=900) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[5:])
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                d = choice.get("delta") or {}
                piece = d.get("content") or d.get("reasoning_content") or ""
                if piece:
                    now = time.perf_counter()
                    first = first if first is not None else now
                    last = now
                    text.append(piece)
    n = (usage or {}).get("completion_tokens") or 0
    span = (last - first) if first is not None and last is not None else 0.0
    return {"completion_tokens": n, "prompt_tokens": (usage or {}).get("prompt_tokens"), "ttft_s": round((first or start) - start, 3),
            "decode_s": round(span, 3), "tok_s": round((n - 1) / span, 1) if n > 1 and span > 0 else None,
            "text": "".join(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("model")
    ap.add_argument("--tokens", type=int, default=400)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--tasks", default="code,prose,structured")
    ap.add_argument("--label", default="")
    ap.add_argument("--output")
    a = ap.parse_args()
    out = {"label": a.label, "base": a.base, "model": a.model, "tokens": a.tokens, "temperature": a.temperature,
           "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "runs": [], "tok_s": {}}
    for task in a.tasks.split(","):
        rates = []
        for i, prompt in enumerate(TASKS[task]):
            r = one(a.base.rstrip("/"), a.model, prompt, a.tokens, a.temperature)
            r.update(task=task, prompt=i)
            out["runs"].append(r)
            if r["tok_s"]:
                rates.append(r["tok_s"])
            print(f"{task:10s} {i} {r['completion_tokens']:4d} tok  ttft {r['ttft_s']:6.2f}s  {r['tok_s']} tok/s", flush=True)
        out["tok_s"][task] = round(statistics.mean(rates), 1) if rates else None
    print("mean tok/s  " + "  ".join(f"{k} {v}" for k, v in out["tok_s"].items()), flush=True)
    if a.output:
        json.dump(out, open(a.output, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
