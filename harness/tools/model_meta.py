#!/usr/bin/env python3
"""Build a `bakeoff-model` v1 record (engines/ENTRY-SPEC.md) for one model folder, from the files in it: weight files
and sizes, GGUF header fields (native context, license, source, chat template) or HF config.json /
generation_config.json, drafters and mmproj files. Standard library only, so it also runs on titan over ssh:

  model_meta.py FOLDER [--root nas|titan-ssd --dir REL]          print the facts read from the folder as JSON

The reviewed records live in engines/model-meta/<root>/<dir>.json; tools/add_entry_specs.py syncs them to
`bakeoff-model.json` in the model folder. The facts that need judgment (family, base model, quirks, uncensored) are
added by hand in the repo copy; this tool only reads files.
"""
import argparse, json, os, re, struct, sys

WEIGHT_EXT = (".gguf", ".safetensors")
GGUF_TYPES = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def gguf_header(path, want_prefixes=("general.", "tokenizer.chat_template")):
    """Return the scalar and string metadata of a GGUF file (arrays skipped)."""
    out = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            return out
        version, = struct.unpack("<I", f.read(4))
        n_tensors, n_kv = struct.unpack("<QQ", f.read(16))
        def rstr():
            n, = struct.unpack("<Q", f.read(8)); return f.read(n).decode("utf-8", "replace")
        def rval(t):
            if t == 8: return rstr()
            if t == 9:
                at, n = struct.unpack("<IQ", f.read(12))
                if at == 8:
                    for _ in range(n): m, = struct.unpack("<Q", f.read(8)); f.seek(m, 1)
                else:
                    f.seek(struct.calcsize(GGUF_TYPES[at]) * n, 1)
                return None
            fmt = GGUF_TYPES[t]; return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
        for _ in range(n_kv):
            k = rstr(); t, = struct.unpack("<I", f.read(4)); v = rval(t)
            if v is not None:
                out[k] = v
    return out


def chat_template_facts(tpl):
    """Reasoning markers and tool-call format, read from a chat template's text."""
    if not tpl:
        return None, None
    markers = None
    for s, e in (("<think>", "</think>"), ("<|channel>thought", "<channel|>"), ("<|thinking|>", "<|/thinking|>")):
        if s in tpl:
            markers = {"start": s, "end": e}; break
    fmt = None
    for tag, name in (("<tool_call>", "<tool_call> tags (Hermes/Qwen style)"), ("[TOOL_CALLS]", "[TOOL_CALLS] (Mistral)"),
                      ("<|tool_call>", "<|tool_call> (Gemma 4)"), ("<|tool▁call", "DeepSeek tool-call tokens"),
                      ("<arg_key>", "GLM <arg_key>/<arg_value>")):
        if tag in tpl:
            fmt = name; break
    return markers, fmt


def build(folder):
    files = []
    for dp, dn, fn in os.walk(folder):
        for n in fn:
            p = os.path.join(dp, n)
            if n.endswith(WEIGHT_EXT) and not n.endswith((".bak", ".bak_embed")):
                files.append((os.path.relpath(p, folder), os.path.getsize(p)))
    files.sort()
    # a drafter sits in a drafter folder or is named like one; a main file may still carry "mtp" (…-plus-mtp.gguf)
    is_draft = lambda f: re.search(r"(^|/)[^/]*(dflash|mtp|assistant|draft)[^/]*/|(^|/)(mtp-|model-mtp\.|dflash)|[-_]draft\.|DFlash", f, re.I)
    is_mmproj = lambda f: "mmproj" in f.lower()
    weights = [{"file": f, "bytes": b} for f, b in files if not is_draft(f) and not is_mmproj(f)]
    drafters = [{"type": "dflash" if re.search("dflash", f, re.I) else "mtp" if re.search("mtp", f, re.I) else "draft-model",
                 "file": f} for f, _ in files if is_draft(f)]
    mmproj = next((f for f, _ in files if is_mmproj(f)), None)
    r = {"weights": weights, "drafters": drafters, "mmproj": mmproj, "native_context": None, "license": None,
         "source_repo": None, "source_revision": None, "gguf_name": None, "gguf_arch": None,
         "reasoning_markers": None, "tool_call_format": None, "recommended_sampling": {}, "expert_count": None}
    first = next((w["file"] for w in weights if w["file"].endswith(".gguf") and re.search(r"(00001-of|^[^-]*$|\.gguf$)", w["file"])), None)
    first = next((w["file"] for w in weights if w["file"].endswith(".gguf") and "-00001-of-" in w["file"]), first)
    if first:
        h = gguf_header(os.path.join(folder, first))
        arch = h.get("general.architecture")
        r["gguf_arch"] = arch; r["gguf_name"] = h.get("general.name")
        r["native_context"] = h.get(f"{arch}.context_length") if arch else None
        r["expert_count"] = h.get(f"{arch}.expert_count") if arch else None
        r["license"] = h.get("general.license")
        r["source_repo"] = (h.get("general.source.huggingface.repository") or h.get("general.base_model.0.repo_url")
                            or h.get("general.source.url"))
        samp = {k.split(".")[-1]: v for k, v in h.items() if k.startswith("general.sampling.")}
        r["recommended_sampling"] = samp
        r["reasoning_markers"], r["tool_call_format"] = chat_template_facts(h.get("tokenizer.chat_template"))
    cfg = os.path.join(folder, "config.json")
    if os.path.exists(cfg):
        c = json.load(open(cfg)); tc = c.get("text_config", c)
        r["native_context"] = r["native_context"] or tc.get("max_position_embeddings")
        r["expert_count"] = r["expert_count"] or tc.get("num_experts") or tc.get("n_routed_experts")
    gc = os.path.join(folder, "generation_config.json")
    if os.path.exists(gc):
        g = json.load(open(gc))
        r["recommended_sampling"] = {k: g[k] for k in ("temperature", "top_p", "top_k", "min_p") if k in g}
    tj = os.path.join(folder, "chat_template.jinja")
    if os.path.exists(tj) and not r["reasoning_markers"]:
        r["reasoning_markers"], r["tool_call_format"] = chat_template_facts(open(tj).read())
    rd = os.path.join(folder, "README.md")
    if os.path.exists(rd) and not r["license"]:
        m = re.search(r"^license:\s*(\S+)", open(rd, errors="replace").read(4000), re.M)
        r["license"] = m.group(1) if m else None
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("folder")
    a = ap.parse_args()
    print(json.dumps(build(a.folder)))
