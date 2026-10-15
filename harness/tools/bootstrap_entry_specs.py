# Kept for the record: how engines/entry-specs/ and engines/model-meta/ were first filled on 2026-10-09 from a copy of
# titan's llama-swap.yaml, report/data.json and DAILY-DRIVERS.md. The repo copies are the reviewed source now; do not
# rerun this over them (it would overwrite hand review). Usage then: bootstrap_entry_specs.py YAML_COPY /dev/null engines/entry-specs engines/model-meta
# One-time bootstrap of engines/entry-specs.json from the current titan yaml (2026-10-09). The output is a reviewed
# table; nothing reads command lines after this. Hand overrides at the bottom.
import yaml, re, json, sys
Y = sys.argv[1]
M = yaml.safe_load(open(Y))["models"]
H = "/home/operator/ai"
def last(pat, c, cast=str):
    r = re.findall(pat, c)
    return cast(r[-1]) if r else None
out = {}
for k, v in M.items():
    c = " ".join(v["cmd"].split()); env = v.get("env") or []
    native = not c.startswith("podman run")
    s = {"schema": 1}
    if "hyperqwen" in c or "/app/venv/bin/vllm" in c: s["engine"] = "vllm"
    elif "/opt/strata" in c or "--config /data/configs/" in c: s["engine"] = "maya" if "maya" in c else "strata"
    elif "sglang" in c: s["engine"] = "sglang"
    else: s["engine"] = "llama.cpp"
    if s["engine"] == "llama.cpp":
        if c.startswith("/usr/local/bin/llama-server") or "${srv}" in v["cmd"]: ver = "0.4-native"
        elif "/models/prism/" in c or "--name llamacpp-prism" in c: ver = "prism"
        elif "llamacpp-kolibri" in c: ver = "kolibri"
        elif "llamacpp-glm5next" in c: ver = "glm5next"
        elif "llamacpp6" in c: ver = "0.6"
        else: ver = None
        s["engine_version"] = ver
        cmd = v["cmd"].replace("${kv8}", "-ctk q8_0 -ctv q8_0")
        cc = " ".join(cmd.split())
        s["served_context"] = last(r"(?:^| )-c (\d+)", cc, int)
        s["parallel"] = last(r"(?: -np | --parallel )(\d+)", cc, int)
        s["kv_type"] = last(r" -ctk (\S+)", cc) or "f16"
        en = last(r'enable_thinking"\s*:\s*(true|false)', cc)
        s["thinking"] = {"default_on": {"true": True, "false": False}.get(en),
                         "server_budget": last(r"--reasoning-budget (\d+)", cc, int),
                         "request_field": "thinking_budget_tokens" if ver == "0.6" else None,
                         "budget_tokens": None}
        smp = {}
        for f, n in (("--temp", "temp"), ("--top-p", "top_p"), ("--top-k", "top_k"), ("--min-p", "min_p")):
            x = last(f + r" (\S+)", cc, float)
            if x is not None: smp[n] = x
        s["sampling"] = smp
        s["spec_decode"] = last(r"--spec-type (\S+)", cc)
        s["observability"] = {"metrics": "--metrics" in cc or ("${srv}" in v["cmd"]),
                              "slots_debug": "LLAMA_SERVER_SLOTS_DEBUG=1" in cc or any("SLOTS_DEBUG" in e for e in env),
                              "prompt_tokens_details": None, "force_include_usage": None}
        mp = last(r" -m (\S+)", cc)
        mnt = last(r"-v (\S+):/models:ro", cc)
        host = (mnt.replace("/home/", "/var/home/", 1) if mnt else H + "/models")
        s["model_path"] = mp.replace("/models", host, 1) if mp else None
        s["storage"] = "ssd" if "models-local" in host else "nas"
        s["multi_agent_ok"] = True
    out[k] = s
# --- hand-reviewed entries (values from the configs read on titan 2026-10-09) ---
obs_v = {"metrics": True, "slots_debug": None, "prompt_tokens_details": True, "force_include_usage": True}
qwen = lambda ctx, spec, model: {"schema": 1, "engine": "vllm", "engine_version": "hyperqwen-0.30", "served_context": ctx,
        "parallel": None, "kv_type": None,
        "thinking": {"default_on": True, "server_budget": None, "request_field": "thinking_token_budget", "budget_tokens": None},
        "sampling": {}, "spec_decode": spec, "observability": obs_v, "model_path": H + "/hyperqwen/models" + model,
        "storage": "ssd", "multi_agent_ok": True}
out["qwen3.8-27b-vllm"] = qwen(150000, "mtp", "")
out["qwen3.8-27b-uncensored-vllm"] = qwen(150000, "mtp", "/Qwen3.8-27B-Uncensored-W4A16")
out["qwen3.8-27b-vllm-240k"] = qwen(245760, "dflash2", "")
out["qwen3.8-27b-vllm-64k"] = qwen(65536, "dflash2", "")
out["qwen3.8-27b-vllm-quote"] = qwen(57344, "dflash2", "")
out["gemma-4-26b-a4b-vllm"] = {"schema": 1, "engine": "vllm", "engine_version": "hyperqwen-0.30", "served_context": 73728,
    "parallel": 8, "kv_type": "auto",
    "thinking": {"default_on": True, "server_budget": None, "request_field": "thinking_token_budget", "budget_tokens": None},
    "sampling": {}, "spec_decode": "draft-model", "observability": obs_v,
    "model_path": H + "/models/vllm/gemma-4-26b-a4b-awq", "storage": "nas", "multi_agent_ok": True}
strata = lambda ver, cfg, par, ok, path: {"schema": 1, "engine": "strata", "engine_version": "strata-0.1.40.3",
    "served_context": 262144, "parallel": par, "kv_type": "int8",
    "thinking": {"default_on": True, "server_budget": 24000, "request_field": None, "budget_tokens": None},
    "sampling": {}, "spec_decode": "strata-mtp", "observability": {"metrics": None, "slots_debug": None,
    "prompt_tokens_details": None, "force_include_usage": None}, "model_path": H + "/models/llm/" + path,
    "storage": "nas", "multi_agent_ok": ok}
out["strata-flash-next"] = strata(0, "flash-next", 1, False, "qwen3.8-flash-next-unpruned")
out["strata-flash-next-p2"] = strata(0, "flash-next-p2", 2, True, "qwen3.8-flash-next-unpruned")
out["strata-swift15"] = strata(0, "swift15", 1, False, "swift15-flash-next")
out["strata-coder"] = strata(0, "coder", 1, False, "qwen3.8-flash-next-coder")
out["maya-glm-5.3-flash"] = {"schema": 1, "engine": "maya", "engine_version": "maya-1.3.0", "served_context": 131072,
    "parallel": 1, "kv_type": None,
    "thinking": {"default_on": True, "server_budget": 24000, "request_field": None, "budget_tokens": None},
    "sampling": {"temp": 1.0, "top_p": 0.95}, "spec_decode": None,
    "observability": {"metrics": None, "slots_debug": None, "prompt_tokens_details": None, "force_include_usage": None},
    "model_path": H + "/models/llm/glm-5.3-flash-maya/Maya-S-v2-IQ2_XXS/pack", "storage": "nas", "multi_agent_ok": True}
out["flashnext"] = {"schema": 1, "engine": "sglang", "engine_version": "sglang-exl3", "served_context": 204800,
    "parallel": 2, "kv_type": None,
    "thinking": {"default_on": True, "server_budget": None, "request_field": None, "budget_tokens": None},
    "sampling": {}, "spec_decode": None,
    "observability": {"metrics": None, "slots_debug": None, "prompt_tokens_details": None, "force_include_usage": None},
    "model_path": H + "/models/llm/turboderp-Qwen3.8-Flash-Next-exl3-3.05bpw_h5_ng5", "storage": "nas", "multi_agent_ok": False}
pass
print(len(out), "entries")
for k, s in out.items():
    nulls = [f for f in ("engine_version", "served_context", "parallel", "kv_type", "spec_decode", "model_path") if s.get(f) is None]
    tn = [f for f, x in s["thinking"].items() if x is None]
    print(f"{k:38} {s['engine']:9} ctx={s['served_context']} kv={s['kv_type']} th={s['thinking']} st={s['storage']} nulls={nulls}")

# ---- extra groups (coordinator 2026-10-09: everything KrakenViz can display), filled from the yaml, the report and
# DAILY-DRIVERS.md once; reviewed. ----
R = json.load(open("report/data.json"))
RM = R["models"]
runs = {}
for r in R["runs"]:
    runs.setdefault(r["model"], []).append((r["case"], r["verdict"]))
def status(mid):
    v = runs.get(mid)
    if not v: return "untested"
    ver = [x for _, x in v]
    if all(x == "fail" for x in ver): return "fail"
    a = [x for c, x in v if c.startswith("wa-")]; b = [x for c, x in v if c.startswith(("wb-", "wt-"))]
    if b and "pass" in b and (not a or "pass" in a): return "pass"
    return "partial"
def params(arch):
    m = re.search(r"(\d+(?:\.\d+)?)B(?: / (\d+(?:\.\d+)?)B active)?", arch or "")
    if not m: return None, None
    tot = float(m.group(1)); act = float(m.group(2)) if m.group(2) else (tot if arch.startswith("dense") else None)
    return tot, act
DD = {"qwen3.8-27b-vllm": "fast", "orcasaq2-cyber-27b": "cyber-fast", "maya-glm-5.3-flash": "smart",
      "lcpp6-orcarouter-fn-uncensored": "cyber-smart"}
UNC_FIX = {"lcpp-glm-5.3-flash-orcarouter": True}   # report says False; it is the uncensored Orcarouter build
for k, s in out.items():
    v = M[k]; raw = v["cmd"]; c = " ".join(raw.replace("${kv8}", "-ctk q8_0 -ctv q8_0").split())
    rm = RM.get(k, {})
    arch = rm.get("arch")
    tot, act = params(arch)
    archk = None if not arch else ("hybrid-moe" if "hybrid" in arch else "moe" if arch.lower().startswith("moe") else "dense")
    f = last(r" -m (\S+)", c) or last(r"--glm-pack (\S+)", c) or None
    if s["engine"] == "vllm": f = last(r"serve (\S+)", c) or last(r"-e MODEL=(\S+)", c) or "/app/models (HyperQwen default)"
    if s["engine"] in ("strata", "maya"): f = s["model_path"]
    if s["engine"] == "sglang": f = "/models"
    s["model"] = {"id": k, "display_name": v.get("name"), "family": rm.get("family"), "base_model": rm.get("base"),
                  "arch": archk, "params_total_b": tot, "params_active_b": act, "quant": rm.get("quant"),
                  "file": f, "vision": bool(re.search(r"--mmproj|/vision/", c)) or "vl" in k,
                  "uncensored": UNC_FIX.get(k, rm.get("uncensored"))}
    lc = s["engine"] == "llama.cpp"
    s["placement"] = {"gpu_layers": last(r" -ngl (\d+)", c, int) if lc else None,
                      "experts_on_cpu": (last(r" -ncmoe (\d+)", c, int) or 0) if lc else None,
                      "mmap": (" -lm none" not in c) if lc else None,
                      "ram_pinned_gb": 95 if s["engine"] == "maya" else None}
    proxy = v.get("proxy"); port = last(r":(\d+)$", proxy or "", int)
    s["serving"] = {"port": port, "proxy": proxy, "container_name": last(r"podman run --name (\S+)", c) or "llama-swap",
                    "max_num_seqs": last(r"--max-num-seqs (\d+)", c, int) or last(r"--max-running-requests (\d+)", c, int),
                    "batch_tokens": last(r"--max-num-batched-tokens (\d+)", c, int) or last(r" -b (\d+)", c, int),
                    "prefix_caching": True if (lc or "--enable-prefix-caching" in c or "PREFIX_CACHE=1" in c) else None,
                    "flash_attn": True if (lc and (" -fa on" in c or "${srv}" in raw)) else None}
    if lc and "/models/prism/llama-server" in c: s["serving"]["flash_attn"] = " -fa on" in c
    sd = s["spec_decode"]
    s["speculative"] = {"type": sd or "none",
                        "draft_model": last(r" -md (\S+)", c) or ("/models/assistant" if "--speculative-config" in c else None),
                        "n_max": last(r"--spec-draft-n-max (\d+)", c, int) or last(r'num_speculative_tokens":(\d+)', c, int)
                                 or last(r"DFLASH_TOKENS=(\d+)", c, int),
                        "acceptance_note": None}
    ctk = last(r"--(?:default-)?chat-template-kwargs '(\{[^']*\})'", raw.replace("\n", " "))
    rc = last(r"--reasoning-config '?(\{[^']*?\})", raw.replace("\n", " "))
    rcj = json.loads(rc) if rc else {}
    s["templates"] = {"chat_template_kwargs": json.loads(ctk) if ctk else None,
                      "reasoning_parser": last(r"--reasoning-parser (\S+)", c),
                      "tool_call_parser": last(r"--tool-call-parser (\S+)", c),
                      "reasoning_start": rcj.get("reasoning_start_str"), "reasoning_end": rcj.get("reasoning_end_str")}
    met = s["observability"]["metrics"]
    s["endpoints"] = {"health": v.get("checkEndpoint") or "/health",
                      "metrics": "/metrics" if met else None,
                      "slots": "/slots" if lc else None, "props": "/props" if lc else None}
    s["role"] = {"daily_driver": DD.get(k), "bakeoff_status": status(k)}
# hand fixes for the extra groups
for k in ("strata-flash-next", "strata-flash-next-p2", "strata-swift15", "strata-coder"):
    out[k]["speculative"]["n_max"] = 4
for k in ("qwen3.8-27b-vllm", "qwen3.8-27b-uncensored-vllm", "qwen3.8-27b-vllm-240k", "qwen3.8-27b-vllm-64k", "qwen3.8-27b-vllm-quote"):
    out[k]["model"]["file"] = "/app/models" + ("/Qwen3.8-27B-Uncensored-W4A16" if "uncensored" in k else " (HyperQwen default)")
pass
sizes = sorted((len(json.dumps(s, separators=(",", ":"))), k) for k, s in out.items())
print("compact JSON size: min", sizes[0], "max", sizes[-1])

# ---- v3 (coordinator 2026-10-09): config spec per entry + bakeoff-model.json per model folder ----
import os, datetime, subprocess
sys.path.insert(0, "tools")
from entry_spec import cmd_hash, SPEC_DIR
from model_meta import build as build_meta
CFG_DIR, META_DIR = sys.argv[3], sys.argv[4]
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
HM = H + "/models/"
def folder_of(k, s):
    p = s["model_path"]
    if k.startswith("qwen3.8-27b") and s["engine"] == "vllm":
        name = "Qwen3.8-27B-Uncensored-W4A16" if "uncensored" in k else "Qwen3.8-27B-W4A16-AutoRound"
        return "titan-ssd", "hyperqwen/models/" + name
    if p.startswith(HM):
        parts = p[len(HM):].split("/"); return "nas", "/".join(parts[:2])
    if p.startswith(H + "/models-local/"):
        parts = p[len(H) + 1:].split("/"); return "titan-ssd", "/".join(parts[:3])
    raise SystemExit(f"{k}: cannot place {p}")
def titan_path(root, d): return (HM + d) if root == "nas" else (H + "/" + d)
def saturn_path(root, d): return ("/srv/store/models/" + d) if root == "nas" else None
facts_cache = {}
def facts(root, d):
    if (root, d) in facts_cache: return facts_cache[root, d]
    if root == "nas":
        f = build_meta(saturn_path(root, d))
    else:
        r = subprocess.run(["ssh", "-o", "HostKeyAlias=titan", "192.0.2.62", "python3", "-", titan_path(root, d)],
                           input=open("tools/model_meta.py").read(), capture_output=True, text=True, timeout=300)
        f = json.loads(r.stdout)
    facts_cache[root, d] = f; return f
def rnd(d): return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}
QUIRKS = {"Gemma 4": (["Thinking is off unless the request or server sets chat_template_kwargs enable_thinking=true; "
                       "without it Gemma answers short and quits agent tasks early (bakeoff 2026-10)."], {"enable_thinking": True})}
metas = {}
for k, s in out.items():
    root, d = folder_of(k, s)
    m = s.pop("model"); mp = s.pop("model_path")
    meta_path = titan_path(root, d) + "/bakeoff-model.json"
    cfg = {"schema": 1, "generated": now, "cmd_sha256": cmd_hash(M[k]["cmd"]), "model_meta": meta_path, "model_file": mp}
    cfg.update({x: y for x, y in s.items() if x != "schema"})
    cfg["model_id"] = k
    json.dump(cfg, open(os.path.join(CFG_DIR, k + ".json"), "w"), indent=1); open(os.path.join(CFG_DIR, k + ".json"), "a").write("\n")
    if (root, d) in metas:
        metas[root, d]["used_by"].append(k); continue
    f = facts(root, d)
    q, req = QUIRKS.get(m["family"], ([], None))
    metas[root, d] = {"schema": "bakeoff-model", "version": 1, "generated": now,
        "location": {"root": root, "dir": d, "titan_path": titan_path(root, d), "saturn_path": saturn_path(root, d)},
        "display_name": (RM.get(k, {}).get("label") or m["display_name"] or d).split(" · ")[0],
        "family": m["family"], "base_model": m["base_model"], "arch": m["arch"],
        "params_total_b": m["params_total_b"], "params_active_b": m["params_active_b"], "quant": m["quant"],
        "weights": f["weights"], "vision": {"supported": bool(m["vision"] or f["mmproj"]), "mmproj": f["mmproj"]},
        "native_context": f["native_context"], "expert_count": f["expert_count"], "uncensored": m["uncensored"],
        "template_quirks": q, "requires": {"chat_template_kwargs": req},
        "recommended_sampling": rnd(f["recommended_sampling"]), "reasoning_markers": f["reasoning_markers"],
        "tool_call_format": f["tool_call_format"], "drafters": f["drafters"],
        "source": {"repo": f["source_repo"], "revision": f["source_revision"]}, "license": f["license"],
        "used_by": [k]}
for (root, d), mm in metas.items():
    p = os.path.join(META_DIR, root, d + ".json"); os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(mm, open(p, "w"), indent=1); open(p, "a").write("\n")
print("wrote", len(out), "config specs and", len(metas), "model records")
