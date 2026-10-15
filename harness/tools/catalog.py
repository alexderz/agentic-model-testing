"""The model catalog as the report and the model cards see it.

The only reader of engines/entry-specs/ (retired/ included) and engines/model-meta/ for tools/build_report.py and
tools/model_cards.py; neither opens those folders itself. Today the catalog is the reviewed JSON files
(engines/ENTRY-SPEC.md). When it becomes one YAML file, this module is the one place to change.

  entries()            {entry id: config spec}, retired entries included
  models()             {record key: model record}; the key is the record's path, e.g. "nas/llm/tiel-coder-35b"
  entry(id)            one spec, or None
  model_of_entry(id)   (record key, record) of the entry's model, or (None, None)
  entry_ids(keys)      the entries of those records, in `used_by` order
  report(id, spec)     the report's row for an entry: id, family, label, base, arch, engine, quant, kind, uncensored,
                       note, vision. `spec` is for an entry the catalog does not hold (the spec saved in a case folder).
  vision_record(key)   what a model record can see and what a head costs (engines/vision/heads.tsv)
  vision(id)           the same for one entry, plus where its head lives and what it measured, if it loads one
  vision_overview(ids) every record behind those entries, with its vision setups (configured and planned)

family and kind come from the model record, label and note from the spec's `report` block. base, arch, engine and
quant are derived from the record and the spec; a `report` block may state any of them where the derived text is not
what the report should say.

Vision is read from engines/vision/: heads.tsv (one row per record: head, native tower or none),
report/vis-setups.tsv (which entries load a head and where; generated from llama-swap.yaml and the -vis dry run by
report/make_setups.py) and, once the smoke step has run, the newest valid vis-entries/smoke-YYYY-MM-DD.tsv. Until a
setup is measured, its extra VRAM and tokens per screenshot are the estimates of engines/vision/README.md, marked "est.".
The projector is the first word of heads.tsv's engine_note ("Projector <name>" also counts); the rest of the note may
name other projectors. A head whose note says the pair "loads in no engine" is shown as not loadable.
"""
import csv, functools, glob, json, os, re, sys
import entry_spec as E

SPECS = os.path.normpath(E.REPO_DIR)
METAS = os.path.normpath(E.META_REPO)
VISION = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engines", "vision"))
VIS_HEADS = os.path.join(VISION, "heads.tsv")
VIS_SETUPS = os.path.join(VISION, "report", "vis-setups.tsv")
VIS_SMOKE = os.path.join(VISION, "vis-entries", "smoke-*.tsv")
SMOKE_NAME = re.compile(r"smoke-(\d{4}-\d{2}-\d{2})\.tsv$")
VIS_LABEL = {"head": "yes (head)", "native": "yes (built in)", "base-head-unverified": "base head, unverified", "none": "no"}
UNLOADABLE = "head on disk, no engine loads it"
NO_ENGINE = re.compile(r"loads in no engine")
PROJECTORS = ("qwen3vl_merger", "glm5next", "glm5v", "gemma4v", "pixtral")
# Tokens one 1280x720 screenshot costs, by projector: engines/vision/README.md "Tokens per image" (GGUF hparams and the
# mtmd preprocessing rules; not measured). A native Qwen3.8 tower has the same patch 16 / merge 2 as qwen3vl_merger.
SHOT_TOKENS = {"qwen3vl_merger": 920, "glm5v": 1200, "glm5next": 1200, "pixtral": 1000, "gemma4v": 400}
# Extra VRAM of a head on the GPU, GB (weights + CLIP compute buffer at the warmup image): engines/vision/README.md
# "VRAM per head", an estimate. Q8_0 heads are smaller.
HEAD_VRAM = {"qwen3vl_merger": (1.4, 2.7), "qwen3vl_merger Q8_0": (1.1, 2.1), "glm5v": (1.6, 2.7), "glm5next": (1.6, 2.7),
             "gemma4v": (1.4, 1.7), "pixtral": (1.1, 1.4)}
PLACE = {"gpu": "GPU", "cpu": "CPU (--no-mmproj-offload)", "host-ram": "host RAM (engine offload)",
         "built-in": "built in (engine-managed)", "gpu-default": "GPU (vLLM default)"}
# How the report names an engine build (the spec's engine_version). An unlisted build shows as "<engine> <version>".
ENGINE = {"0.4-native": "llama.cpp 0.4", "0.6": "llama.cpp 0.6", "kolibri": "llama.cpp 0.6 + Kolibri patch",
          "prism": "PrismML llama.cpp", "hyperqwen-0.30": "vLLM (HyperQwen)", "strata-0.1.40.3": "Strata",
          "maya-1.3.0": "Maya 1.3 (patched)", "sglang-exl3": "SGLang",
          "tabbyapi-a3fed43e-exl3-1.6.1": "exllamav3 1.6.1 (TabbyAPI)"}
ARCH = {"dense": "dense", "moe": "MoE", "hybrid-moe": "hybrid MoE"}


@functools.lru_cache(None)
def entries():
    fs = glob.glob(os.path.join(SPECS, "*.json")) + glob.glob(os.path.join(SPECS, "retired", "*.json"))
    return {os.path.basename(f)[:-5]: json.load(open(f)) for f in sorted(fs, key=os.path.basename)}


@functools.lru_cache(None)
def models():
    fs = sorted(glob.glob(os.path.join(METAS, "**", "*.json"), recursive=True))
    return {os.path.relpath(f, METAS)[:-5]: json.load(open(f)) for f in fs}


def entry(eid):
    return entries().get(eid)


def _model(spec):
    rp = E.meta_repo_path((spec or {}).get("model_meta") or "")
    key = os.path.relpath(rp, METAS)[:-5] if rp else None
    return (key, models()[key]) if key in models() else (None, None)


def model_of_entry(eid):
    return _model(entry(eid))


def entry_ids(keys):
    return [i for k in keys for i in models()[k]["used_by"]]


def _arch(m):
    a, t, act = ARCH.get(m.get("arch"), m.get("arch") or ""), m.get("params_total_b"), m.get("params_active_b")
    if not t: return a
    return f"{a} {t:g}B" if a == "dense" else f"{a} {t:g}B / {act:g}B active"


def _quant(s, m):
    """The record's quant; when the folder holds several, the one named in the weights file this entry serves."""
    q = m.get("quant") or ""
    hit = [x for x in q.split(", ") if x in os.path.basename(s.get("model_file") or "")]
    return hit[0] if len(hit) == 1 else q


def report(eid, spec=None):
    s = spec or entry(eid) or {}
    m = _model(s)[1] or {}
    kind, v = m.get("kind"), s.get("engine_version")
    row = dict(id=eid, family=m.get("family") or "Other", label=m.get("display_name") or eid,
               base=m.get("base_model") or "", arch=_arch(m),
               engine=ENGINE.get(v) or " ".join(x for x in (s.get("engine"), v) if x), quant=_quant(s, m),
               kind=kind or "unknown", uncensored=kind != "stock" if kind else bool(m.get("uncensored")), note="")
    row.update(s.get("report") or {})
    row["vision"] = vision(eid, _model(s)[0])
    return row


# ---------------------------------------------------------------- vision
def _tsv(p):
    if not os.path.exists(p): return []
    rows = [r for r in csv.reader(open(p), delimiter="\t") if r and not r[0].startswith("#")]
    return [dict(zip(rows[0], r + [""] * (len(rows[0]) - len(r)))) for r in rows[1:]] if rows else []


@functools.lru_cache(None)
def vis_heads():
    return {r["model_record"]: r for r in _tsv(VIS_HEADS)}


@functools.lru_cache(None)
def vis_setups():
    return {r["entry"]: r for r in _tsv(VIS_SETUPS)}


@functools.lru_cache(None)
def vis_smoke():
    """(file name, {entry: row}) of the newest valid smoke-YYYY-MM-DD.tsv, or (None, {}) before the smoke step has run.
    Files named otherwise, or without an `entry` column, are skipped with a warning: their setups stay estimates."""
    fs = sorted((m.group(1), f) for f in glob.glob(VIS_SMOKE) if (m := SMOKE_NAME.search(os.path.basename(f))))
    for f in set(glob.glob(VIS_SMOKE)) - {f for _, f in fs}:
        print(f"!! catalog: skipped {os.path.basename(f)}: not named smoke-YYYY-MM-DD.tsv", file=sys.stderr)
    for _, f in reversed(fs):
        try:
            rows = _tsv(f)
            if rows and "entry" in rows[0]: return os.path.basename(f), {r["entry"]: r for r in rows if r["entry"]}
            print(f"!! catalog: skipped {os.path.basename(f)}: no rows or no entry column", file=sys.stderr)
        except (OSError, csv.Error, UnicodeDecodeError) as e:
            print(f"!! catalog: skipped {os.path.basename(f)}: {e}", file=sys.stderr)
    return None, {}


def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def vision_record(key):
    """What the record can see: label, projector, head file and size, tokens per 1280x720 screenshot (est.)."""
    h = vis_heads().get(key)
    if not h: return dict(label="not surveyed", status=None)
    note = h["engine_note"]
    first = re.match(r"\s*(?:Projector\s+)?([A-Za-z0-9_]+)", note)
    p = first.group(1) if first and first.group(1) in PROJECTORS else None
    if not p and h["vision"] == "native":   # the tower inside a vLLM / SGLang / exllamav3 checkpoint
        base = h["base_model"].lower()
        p, tower = ("gemma4v", "Gemma 4") if "gemma" in base else (("qwen3vl_merger", "Qwen3.8 VL") if "qwen3" in base else (None, None))
        proj = f"built-in tower ({tower})" if tower else "built-in tower"
    else:
        proj = (p or "") + (" Q8_0" if p and re.match(rf"\s*{p} Q8_0", note) else "")
    b = _num(h["head_bytes"])
    loadable = not (h["vision"] != "none" and NO_ENGINE.search(note))
    label = VIS_LABEL.get(h["vision"], h["vision"]) if loadable else UNLOADABLE
    return dict(label=label, status=h["vision"], loadable=loadable, projector=proj or None,
                head_file=None if h["head_file"] in ("-", "") else h["head_file"],
                head_gb=round(b / 1e9, 2) if b else None,
                head_vram_est=HEAD_VRAM.get(proj, HEAD_VRAM.get(p)) if b else None,
                shot_tokens=SHOT_TOKENS.get(p), engine_note=note)


def _setup(eid, s, rec):
    """One entry's vision setup: where the head lives, extra VRAM and tokens per screenshot, measured or est."""
    smoke_file, smoke = vis_smoke()
    m, place = smoke.get(eid) or {}, s["place"]
    d = dict(entry=eid, source=s["source_entry"], status=s["status"], place=place, where=PLACE.get(place, place),
             head_file=s["head_file"], flags=s["flags"])
    lo_hi, gb = rec.get("head_vram_est"), rec.get("head_gb")
    delta = _num(m.get("vram_delta_mib"))
    if delta is not None:
        d.update(extra_vram=f"{delta / 1024:+.1f} GB", extra_src="measured",
                 vram_gb=round(_num(m.get("vis_vram_mib")) / 1024, 1) if _num(m.get("vis_vram_mib")) else None)
    elif place == "gpu" and lo_hi:
        d.update(extra_vram=f"+{lo_hi[0]:g}-{lo_hi[1]:g} GB", extra_src="est.")
    elif place == "cpu":
        d.update(extra_vram="~0 GB", extra_src="est.",
                 ram=f"{gb:.1f} GB head + buffers in system RAM" if gb else "head + buffers in system RAM")
    elif place == "host-ram":
        d.update(extra_vram="~0 GB", extra_src="est.",
                 ram=f"tower ({gb:.1f} GB) in pinned host RAM" if gb else "tower (~0.9 GB est.) in pinned host RAM")
    else:
        d.update(extra_vram="in the load", extra_src="est.")   # built-in towers are not separable from the weights
    tok = _num(m.get("image_tokens"))
    if tok is not None: d.update(shot_tokens=int(tok), tokens_src="measured")
    elif rec.get("shot_tokens"): d.update(shot_tokens=rec["shot_tokens"], tokens_src="est.")
    else: d.update(shot_tokens=None, tokens_src=None)
    if m:
        d.update(smoke=smoke_file, encode_s=_num(m.get("image_req_s")), probe=m.get("probe_status") or None,
                 two_images=m.get("two_image_status") or None, errors=m.get("errors") or None)
    return d


def vision(eid, key=None):
    """The record's vision fields plus this entry's setup (None when the entry loads no head: blind)."""
    key = key or model_of_entry(eid)[0]
    s = vis_setups().get(eid)
    if s and not key: key = s["record"]
    rec = vision_record(key) if key else dict(label="not surveyed", status=None)
    out = dict(record=key, **rec)
    out["setup"] = _setup(eid, s, rec) if s else None
    return out


def vision_overview(ids):
    """Every record behind these entries (in id order), with the vision setups of any of its entries, the planned
    -vis entries included. `smoke` names the measurement file, None while every figure is an estimate."""
    by, order = {}, []
    for i in ids:
        k = model_of_entry(i)[0]
        if k and k not in by: by[k] = []; order.append(k)
    for e, s in vis_setups().items():
        k = s["record"]
        if k not in by: continue
        by[k].append(_setup(e, s, vision_record(k)))
    # two records with one display name (a GGUF and a vLLM checkpoint of one model) are told apart by their quant
    name = {k: models()[k].get("display_name") or k for k in order}
    dup = {n for n in name.values() if list(name.values()).count(n) > 1}
    recs = []
    for k in order:
        r, q = vision_record(k), models()[k].get("quant")
        recs.append(dict(record=k, model=f"{name[k]} ({q})" if name[k] in dup and q else name[k],
                         entries=models()[k]["used_by"], **r, setups=sorted(by[k], key=lambda d: (d["status"], d["entry"]))))
    return dict(smoke=vis_smoke()[0], records=recs)
