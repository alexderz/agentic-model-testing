#!/usr/bin/env python3
"""The only reader of `bakeoff.spec` (engines/ENTRY-SPEC.md): what each titan llama-swap entry serves.

  entry_spec.py [--titan | --yaml PATH] [--entry ID] [--json]   print specs (all entries, or one)
  entry_spec.py [--titan | --yaml PATH] --limits ID              print "served reply context thinking"
  entry_spec.py --rewrite ID --flags "..." [--override JSON] [--record DIR]   (set_variant's spec step)
  entry_spec.py [--titan | --yaml PATH] --check                  validate every spec; report missing references,
                                                                 staleness against the entry's cmd, and drift between
                                                                 titan's copy and the repo copy (engines/entry-specs/)

Each entry references one JSON file by path: `--label bakeoff.spec=<path>` on a container entry, or
`BAKEOFF_SPEC=<path>` in a native entry's llama-swap `env`. --titan reads the yaml and the referenced files
read-only over ssh (never a llama-swap request); --yaml reads a local yaml copy and resolves each reference to the
repo copy engines/entry-specs/<id>.json. Nothing here parses engine flags.
Exit codes: 3 the asked entry has no spec, 2 a spec is invalid, 1 --check found problems.
"""
import argparse, hashlib, json, os, re, subprocess, sys

TITAN = "192.0.2.62"
YAML_PATH = "/home/operator/ai/config/llama-swap.yaml"
SPEC_DIR = "/home/operator/ai/config/specs"
MIRROR_DIR = "/etc/llama-bored/specs"   # read by llama-watch (llama-bored #92); titan's owner made it, we only fill it
REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engines", "entry-specs")
LABEL_RE = re.compile(r"--label bakeoff\.spec=(\S+)")
ENV_KEY = "BAKEOFF_SPEC="
ENGINES = {"llama.cpp", "vllm", "strata", "maya", "sglang", "exllamav3"}
GROUPS = {
    "thinking": ("default_on", "server_budget", "request_field", "budget_tokens"),
    "observability": ("metrics", "slots_debug", "prompt_tokens_details", "force_include_usage"),
    "placement": ("gpu_layers", "experts_on_cpu", "mmap", "ram_pinned_gb"),
    "serving": ("port", "proxy", "container_name", "max_num_seqs", "batch_tokens", "prefix_caching", "flash_attn"),
    "speculative": ("type", "draft_model", "n_max", "acceptance_note"),
    "templates": ("chat_template_kwargs", "reasoning_parser", "tool_call_parser", "reasoning_start", "reasoning_end"),
    "endpoints": ("health", "metrics", "slots", "props"),
    "role": ("daily_driver", "bakeoff_status"),
}
TOP = {"schema", "generated", "cmd_sha256", "model_id", "model_meta", "model_file", "engine", "engine_version",
       "served_context", "parallel", "kv_type", "sampling", "spec_decode", "storage", "multi_agent_ok",
       "report"} | set(GROUPS)
# The optional `report` block: how the report names the entry (tools/catalog.py). Not part of what the entry serves.
REPORT_KEYS = {"label", "note", "base", "arch", "engine", "quant"}
META_KEYS = {"schema", "version", "generated", "location", "display_name", "family", "base_model", "arch",
             "params_total_b", "params_active_b", "quant", "weights", "vision", "native_context", "expert_count",
             "uncensored", "template_quirks", "requires", "recommended_sampling", "reasoning_markers",
             "tool_call_format", "drafters", "source", "license", "used_by"}
META_OPTIONAL = {"kind"}   # for the report; optional so a record written before the field existed stays valid
MODELS_HOST = "/home/operator/ai/models/"
AI_HOST = "/home/operator/ai/"
META_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engines", "model-meta")


SAMPLING_KEYS = ("temp", "top_p", "top_k", "min_p", "presence_penalty")
_SAMPLING_ALIASES = {"temperature": "temp", "top-p": "top_p", "top-k": "top_k", "min-p": "min_p",
                     "presence-penalty": "presence_penalty"}
# Engines whose server applies the model's own defaults when no flag is given: vLLM reads generation_config.json
# (--generation-config auto, the default). llama.cpp builds carry the GGUF general.sampling.* keys, but whether every
# build on titan applies them is not verified (0.4 native, prism, kolibri), and bonsai2-27b-ada degenerated without
# explicit flags, so for llama.cpp the recommendation must be explicit (C13).
IMPLICIT_DEFAULTS = {"vllm": "generation_config"}
# What OpenCode itself sends per request (opencode 1.18.35, ProviderTransform temperature/topP/topK): a temperature of
# 1 for ids containing these strings, nothing for Qwen, Gemma and the other open models we serve.
OPENCODE_TEMP_IDS = ("glm-4.6", "glm-4.7", "minimax-m2", "north-mini-code")


def rec_sampling(meta):
    """The model record's recommended sampling with canonical keys, and where it came from
    (gguf, generation_config, card or None)."""
    raw = dict((meta or {}).get("recommended_sampling") or {})
    src = raw.pop("from", None)
    out = {}
    for k, v in raw.items():
        k2 = _SAMPLING_ALIASES.get(k, k)
        if k2 in SAMPLING_KEYS and v is not None: out[k2] = float(v)
    if src is None and out:
        src = "generation_config" if "temperature" in raw else "gguf"
    return out, src


def request_sampling(entry, case=""):
    """Sampling the client adds per request: OpenCode's own temperature for some ids, and the runner's -pp."""
    r = {}
    if any(x in (entry or "").lower() for x in OPENCODE_TEMP_IDS): r["temp"] = 1.0
    if case.endswith("-pp"): r["presence_penalty"] = 1.5
    return r


def sampling_check(spec, meta, entry, case=""):
    """C13: [(level, message)] comparing what the entry serves (plus the per-request additions) with the model's
    recommendation. Explicit conflicts FAIL; a recommended key left to the engine FAILs on llama.cpp, WARNs where the
    engine applies the model's own file (vLLM) or where we do not know (Strata, Maya, SGLang); presence_penalty
    differences WARN (Qwen's card allows 0-2 against endless repetition)."""
    rec, src = rec_sampling(meta)
    if not rec: return [("WARN", "the model record states no recommended sampling")]
    served = {_SAMPLING_ALIASES.get(k, k): v for k, v in (spec.get("sampling") or {}).items() if v is not None}
    eff = dict(served); eff.update(request_sampling(entry, case))
    out = []
    for k, want in rec.items():
        have = eff.get(k)
        if have is None:
            if k == "presence_penalty" and want == 0.0: continue        # engine default is 0
            eng = spec.get("engine")
            if IMPLICIT_DEFAULTS.get(eng) == src:
                out.append(("WARN", f"{k} left to {eng}'s {src} default ({want:g}); state it in the entry"))
            elif eng == "llama.cpp":
                out.append(("FAIL", f"{k} not set; the model recommends {want:g} ({src}); add the flag"))
            else:
                out.append(("WARN", f"{k} not set on {eng}; the model recommends {want:g} ({src})"))
        elif abs(float(have) - want) > 0.011:
            lvl = "WARN" if k == "presence_penalty" else "FAIL"
            out.append((lvl, f"{k} {float(have):g} differs from the model's recommendation {want:g} ({src})"
                        + (" (the -pp case adds 1.5; Qwen allows 0-2 against endless repetition)" if k == "presence_penalty" else "")))
    return out


def sampling_flags(rec):
    """llama-server flags for a recommendation."""
    names = {"temp": "--temp", "top_p": "--top-p", "top_k": "--top-k", "min_p": "--min-p", "presence_penalty": "--presence-penalty"}
    return " ".join(f"{names[k]} {int(v) if k == 'top_k' else (f'{v:g}')}" for k, v in rec.items() if k != "presence_penalty" or v)


def meta_repo_path(titan_meta_path):
    """Repo copy of a bakeoff-model.json, from its path on titan."""
    d = os.path.dirname(titan_meta_path)
    if d.startswith(MODELS_HOST): return os.path.join(META_REPO, "nas", d[len(MODELS_HOST):] + ".json")
    if d.startswith(AI_HOST): return os.path.join(META_REPO, "titan-ssd", d[len(AI_HOST):] + ".json")
    return None


def validate_meta(m):
    p = []
    if m.get("schema") != "bakeoff-model" or m.get("version") != 1: p.append("model record is not bakeoff-model v1")
    if set(m) - META_OPTIONAL != META_KEYS: p.append(f"model record fields differ: {sorted(set(m) - META_OPTIONAL ^ META_KEYS)}")
    if not isinstance(m.get("kind", ""), str): p.append("kind is not a string")
    if m.get("native_context") is not None and not isinstance(m["native_context"], int): p.append("native_context not an int")
    return p



GPU_MIB = 24576   # titan's RTX 3090


def gpu_fit_check(spec, meta):
    """C15: a dense model (no expert_count) on llama.cpp must leave 3 GiB of the GPU for the KV cache and buffers, or
    llama.cpp (-ngl auto / --fit) puts layers in RAM. Returns a FAIL message or None."""
    meta = meta or {}
    w = {os.path.basename(x["file"]): x["bytes"] for x in (meta.get("weights") or []) if x.get("bytes")}.get(
        os.path.basename(spec.get("model_file") or ""))
    if (spec["engine"].startswith("llama.cpp") and not meta.get("expert_count")
            and not (spec["placement"]["experts_on_cpu"] or 0) and w and w / 2**20 + 3072 > GPU_MIB):
        return (f"weights {w / 2**20:.0f} MiB leave under 3 GiB of the GPU; layers spill to RAM (the Q38 Q6_K ran "
                "4.5 tok/s that way); pick a smaller quant, or ignore=C15 with the reason")
    return None

def cmd_hash(cmd):
    """sha256 of an entry's cmd with the spec reference removed and whitespace collapsed. lib.sh set_variant carries
    a copy of this function for the titan side; keep them identical."""
    c = " ".join(LABEL_RE.sub("", cmd).split())
    return hashlib.sha256(c.encode()).hexdigest()


def ssh(cmd, stdin=None):
    # input="" when there is nothing to send: an inherited stdin would be swallowed (the matrix loop reads its rows
    # from stdin; tssh in lib.sh uses ssh -n for the same reason)
    r = subprocess.run(["ssh", "-o", "HostKeyAlias=titan", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", TITAN, cmd],
                       input=stdin if stdin is not None else "", capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise SystemExit(f"ssh to titan failed: {r.stderr.strip()}")
    return r.stdout


def refs(text):
    """{entry: (cmd, referenced path or None)}."""
    import yaml
    out = {}
    for k, v in yaml.safe_load(text)["models"].items():
        found = LABEL_RE.findall(v.get("cmd", ""))
        found += [e[len(ENV_KEY):] for e in v.get("env") or [] if isinstance(e, str) and e.startswith(ENV_KEY)]
        if len(found) > 1:
            raise SystemExit(f"{k}: more than one bakeoff.spec reference")
        out[k] = (v.get("cmd", ""), found[0] if found else None)
    return out


def validate(spec, entry=None):
    """A list of problems; empty when the spec is valid."""
    p = []
    def typ(key, types, none_ok=True):
        v = spec.get(key)
        if v is None and none_ok: return
        if not isinstance(v, types) or isinstance(v, bool) and bool not in (types if isinstance(types, tuple) else (types,)):
            p.append(f"{key}={v!r} has the wrong type")
    if spec.get("schema") != 1: p.append("schema is not 1")
    for k in ("generated", "cmd_sha256"):
        if not isinstance(spec.get(k), str): p.append(f"{k} missing")
    if spec.get("engine") not in ENGINES: p.append(f"engine {spec.get('engine')!r} unknown")
    typ("engine_version", str); typ("served_context", int, False); typ("parallel", int); typ("kv_type", str)
    typ("sampling", dict, False); typ("spec_decode", str); typ("model_file", str); typ("model_meta", str, False)
    if isinstance(spec.get("served_context"), int) and spec["served_context"] < 8192: p.append("served_context below 8192")
    if spec.get("storage") not in ("nas", "ssd"): p.append("storage must be nas or ssd")
    if not isinstance(spec.get("multi_agent_ok"), bool): p.append("multi_agent_ok must be a bool")
    for g, keys in GROUPS.items():
        if not isinstance(spec.get(g), dict) or set(spec[g]) != set(keys):
            p.append(f"{g} must have exactly {keys}")
    rep = spec.get("report", {})
    if not isinstance(rep, dict) or set(rep) - REPORT_KEYS or not all(isinstance(v, str) for v in rep.values()):
        p.append(f"report must be an object of strings with keys from {sorted(REPORT_KEYS)}")
    extra = set(spec) - TOP
    if extra: p.append(f"unknown fields {sorted(extra)}")
    if entry and spec.get("model_id") != entry:
        p.append(f"model_id {spec.get('model_id')!r} is not the entry {entry!r}")
    return p


def repo_copy(entry):
    f = os.path.join(REPO_DIR, entry + ".json")
    return json.load(open(f)) if os.path.exists(f) else None


def load(titan=False, yaml_path=None):
    """{entry: {"cmd", "ref", "spec" (dict or None), "repo" (dict or None), "problems": [...]}}."""
    if titan:
        text = ssh(f"cat {YAML_PATH}")
    else:
        text = open(yaml_path or YAML_PATH, encoding="utf-8").read()
    R = refs(text)
    files = {}
    prog = ("import json,sys\nout={}\nfor p in sys.argv[1:]:\n try: out[p]=open(p).read()\n"
            " except Exception as e: out[p]=None\nprint(json.dumps(out))")
    if titan:
        paths = sorted({p for _, p in R.values() if p})
        if paths:
            files = json.loads(ssh("python3 - " + " ".join(paths), stdin=prog))
            metas = sorted({json.loads(v)["model_meta"] for v in files.values() if v})
            if metas:
                files.update(json.loads(ssh("python3 - " + " ".join(metas), stdin=prog)))
    out = {}
    for k, (cmd, ref) in R.items():
        e = {"cmd": cmd, "ref": ref, "spec": None, "meta": None, "repo": repo_copy(k), "problems": []}
        if ref:
            if titan:
                raw = files.get(ref)
                if raw is None: e["problems"].append(f"referenced file {ref} is missing on titan")
                else: e["spec"] = json.loads(raw)
            else:
                e["spec"] = e["repo"]
                if e["spec"] is None: e["problems"].append(f"no repo copy for {k}")
        if e["spec"] is not None:
            e["problems"] += validate(e["spec"], k)
            mp = e["spec"].get("model_meta")
            if titan:
                raw = files.get(mp)
                e["meta"] = json.loads(raw) if raw else None
            else:
                rp = meta_repo_path(mp or "")
                e["meta"] = json.load(open(rp)) if rp and os.path.exists(rp) else None
            if e["meta"] is None: e["problems"].append(f"model record {mp} not found")
            else: e["problems"] += validate_meta(e["meta"])
            if e["spec"].get("cmd_sha256") != cmd_hash(cmd):
                e["problems"].append("stale: cmd_sha256 does not match the entry's current cmd")
            if titan and e["repo"] is not None:
                diff = sorted(f for f in set(e["spec"]) | set(e["repo"])
                              if f != "generated" and e["spec"].get(f) != e["repo"].get(f))
                if diff: e["drift"] = diff
        out[k] = e
    return out


def note_override(note):
    """The JSON object after `spec=` in a matrix note, or None."""
    i = (note or "").find("spec={")
    if i < 0: return None
    obj, _ = json.JSONDecoder().raw_decode(note[i + 5:])
    return obj


def apply_flags(spec, flags, override=None):
    """The spec after a matrix row rewrites a llama.cpp entry's flag line (lib.sh set_variant). The only place that
    reads flags: the row's own `-c`, `-ctk`, `--reasoning-budget`, `-ngl`, `-ncmoe`, `-lm none` and sampling flags
    (`--temp`, `--top-p`, `--top-k`, `--min-p`, `--presence-penalty`), which the bake-off
    writes itself. An explicit `spec={...}` in the matrix note (override) wins over anything read from the flags."""
    import copy, datetime
    s = copy.deepcopy(spec)
    def num(pat):
        m = re.findall(pat, " " + flags + " "); return int(m[-1]) if m else None
    if num(r" -c (\d+) ") is not None: s["served_context"] = num(r" -c (\d+) ")
    m = re.findall(r" -ctk (\S+)", " " + flags); s["kv_type"] = m[-1] if m else s["kv_type"]
    if num(r" --reasoning-budget (\d+) ") is not None: s["thinking"]["server_budget"] = num(r" --reasoning-budget (\d+) ")
    if num(r" -ngl (\d+) ") is not None: s["placement"]["gpu_layers"] = num(r" -ngl (\d+) ")
    s["placement"]["experts_on_cpu"] = num(r" -ncmoe (\d+) ") or 0
    s["placement"]["mmap"] = " -lm none" not in " " + flags
    for flag, key in (("--temp", "temp"), ("--top-p", "top_p"), ("--top-k", "top_k"), ("--min-p", "min_p"),
                      ("--presence-penalty", "presence_penalty")):
        m = re.findall(r" %s (\S+)" % re.escape(flag), " " + flags)
        if m: s["sampling"] = dict(s.get("sampling") or {}); s["sampling"][key] = float(m[-1])
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(s.get(k), dict): s[k].update(v)
        else: s[k] = v
    s["generated"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    return s


def rewrite_on_titan(entry, flags, override=None, record_dir=None):
    """set_variant's spec step: rewrite the entry's spec file on titan atomically (the yaml reference never changes),
    with cmd_sha256 recomputed from the entry's current cmd. Returns the new spec, or None when the entry has no spec."""
    R = refs(ssh(f"cat {YAML_PATH}"))
    if entry not in R or not R[entry][1]:
        return None
    cmd, ref = R[entry]
    old = json.loads(ssh(f"cat {ref}"))
    new = apply_flags(old, flags, override)
    new["cmd_sha256"] = cmd_hash(cmd)
    bad = validate(new, entry)
    if bad: raise SystemExit(f"{entry}: rewritten spec invalid: {bad}")
    body = json.dumps(new, indent=1) + "\n"
    ssh(f"umask 022; t=$(mktemp {ref}.XXXXXX) && cat > \"$t\" && chmod 644 \"$t\" && mv -f \"$t\" {ref}", stdin=body)
    print(mirror_on_titan(), file=sys.stderr)
    if record_dir:
        os.makedirs(record_dir, exist_ok=True)
        json.dump({"entry": entry, "flags": flags, "override": override, "spec": new},
                  open(os.path.join(record_dir, "entry-spec-override.json"), "w"), indent=1)
    return new


MIRROR_PROG = r"""
import glob, json, os, re, sys, tempfile
src, dst, yml = sys.argv[1:4]
if not os.path.isdir(dst): print("mirror: no " + dst + ", skipped"); sys.exit(0)
ids = set(re.findall(r"^  ([A-Za-z0-9._-]+):\s*$", open(yml).read(), re.M))
want = {}
for f in glob.glob(src + "/*.json"):
    k = os.path.basename(f)[:-5]
    if k not in ids: continue
    try:
        s = json.load(open(f))
        try:
            m = json.load(open(s["model_meta"]))
            if len(json.dumps(m.get("weights", ""))) > 4096: m.pop("weights", None)
        except Exception: m = None
        s["model"] = m
        want[k] = json.dumps(s, indent=1) + "\n"
    except Exception as e: print("mirror: %s unreadable (%s)" % (k, e))
n = 0
for k, body in want.items():
    p = os.path.join(dst, k + ".json")
    if os.path.exists(p) and open(p).read() == body: continue
    fd, t = tempfile.mkstemp(dir=dst, prefix=".bakeoff-")
    with os.fdopen(fd, "w") as f: f.write(body)
    os.chmod(t, 0o644); os.replace(t, p); n += 1
gone = [f for f in glob.glob(dst + "/*.json") if os.path.basename(f)[:-5] not in want]
for f in gone: os.remove(f)
print("mirror: %d specs, %d written, %d removed" % (len(want), n, len(gone)))
"""


def mirror_on_titan():
    """Copy every entry's spec, with its model record embedded under `model`, to MIRROR_DIR on titan and drop mirrored
    files whose entry is gone. Built on titan from the files just written, so both writers (add_entry_specs.py and
    rewrite_on_titan) call it after their own write. Never fails the caller: the reader treats a missing file as
    "settings unknown"."""
    try:
        return ssh(f"python3 - {SPEC_DIR} {MIRROR_DIR} {YAML_PATH}", stdin=MIRROR_PROG).strip()
    except (SystemExit, Exception) as e:
        return f"mirror: failed ({e})"


MARGIN_FLOOR = 28672


def opencode_margin(served, reply):
    """served - context. OpenCode reserves the reply itself: it compacts once a step's total passes context - reply,
    and the next request asks for the full reply again, so a request can reach context + the prompt's growth since
    that step. The margin only has to cover that growth. Until 2026-10-14 it was max(reply, 16384) + served // 10,
    which also held a whole reply and compacted a 150k window at 71k (operator: "Give them large context. Saw
    compaction at 50 percent"). Growth census, 24,469 OpenCode steps on 2026-10-14: 99.9% grew by at most 24,961
    tokens; 8 steps grew by more than MARGIN_FLOOR, the largest by 43,593 (test 4). The margin is never larger than
    the old one, so windows under about 80k keep it (64k and 57k windows overflowed with less)."""
    return min(max(reply, 16384) + served // 10, max(MARGIN_FLOOR, served // 10))


def limits(spec):
    """(served, reply, context, thinking): the OpenCode limits for one entry (engines/ENTRY-SPEC.md)."""
    served = spec["served_context"]
    reply = min(32000, served // 4)
    margin = opencode_margin(served, reply)
    context = served - margin
    thinking = min(24000, reply - 6000)
    assert context > 0 and 0 < thinking < reply, (served, reply, context, thinking)
    return served, reply, context, thinking


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--yaml"); src.add_argument("--titan", action="store_true")
    ap.add_argument("--entry"); ap.add_argument("--limits", metavar="ID")
    ap.add_argument("--check", action="store_true"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--rewrite", metavar="ID", help="set_variant: rewrite ID's spec on titan from --flags/--override")
    ap.add_argument("--flags", default=""); ap.add_argument("--override", help="JSON from a matrix note's spec={...}")
    ap.add_argument("--record", metavar="DIR", help="also save the rewritten spec and override in DIR")
    ap.add_argument("--note-override", metavar="NOTE", help="print the spec={...} override in a matrix note, if any")
    ap.add_argument("--mirror", action="store_true", help="refresh the llama-watch copies in MIRROR_DIR on titan")
    a = ap.parse_args()
    if a.mirror: print(mirror_on_titan()); return
    if a.note_override is not None:
        o = note_override(a.note_override)
        if o is not None: print(json.dumps(o, separators=(",", ":")))
        return
    if a.rewrite:
        new = rewrite_on_titan(a.rewrite, a.flags, json.loads(a.override) if a.override else None, a.record)
        print(f"{a.rewrite}: " + ("no bakeoff.spec, nothing rewritten" if new is None else
              f"spec rewritten (served_context {new['served_context']}, kv {new['kv_type']})"))
        return
    S = load(a.titan, a.yaml)
    one = a.limits or a.entry
    if one:
        if one not in S: print(f"no entry {one}", file=sys.stderr); sys.exit(3)
        e = S[one]
        if e["spec"] is None: print(f"{one} has no bakeoff.spec ({'; '.join(e['problems']) or 'no reference'})", file=sys.stderr); sys.exit(3)
        hard = [p for p in e["problems"] if not p.startswith("stale")]
        if hard: print(f"{one}: invalid bakeoff.spec: {'; '.join(hard)}", file=sys.stderr); sys.exit(2)
        for p in e["problems"]: print(f"WARNING {one}: {p}", file=sys.stderr)
        if a.limits: print(*limits(e["spec"])); return
        print(json.dumps(e["spec"], indent=1)); return
    if a.json:
        print(json.dumps({k: e["spec"] for k, e in S.items()}, indent=1)); return
    bad = 0
    for k, e in S.items():
        if e["spec"] is None and not e["problems"]: line = "NO SPEC REFERENCE"
        elif e["spec"] is None: line = "BROKEN: " + "; ".join(e["problems"])
        else:
            s = e["spec"]
            line = f"{s['engine']:9} served={s['served_context']} multi={s['multi_agent_ok']}"
            if e["problems"]: line += "  PROBLEMS: " + "; ".join(e["problems"])
            if e.get("drift"): line += "  DRIFT vs repo: " + ",".join(e["drift"])
        bad += bool(e["problems"] or e["spec"] is None or e.get("drift"))
        if a.check or not e["problems"]: print(f"{k:38} {line}")
    if a.check:
        print(f"{len(S) - bad} of {len(S)} entries clean")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
