#!/usr/bin/env python3
"""Apply `bakeoff.spec` (engines/ENTRY-SPEC.md) from the reviewed repo copies. Runs on Saturn. Dry run by default.

  python3 tools/add_entry_specs.py            dry run: what would be written where, and the yaml diff summary
  python3 tools/add_entry_specs.py --apply    write it (only with nothing loaded on titan)

What it writes:
  1. Model records engines/model-meta/nas/<dir>.json -> /srv/store/models/<dir>/bakeoff-model.json (Saturn is the NAS
     host; titan sees them read-only under ~/ai/models/<dir>/).
  2. Model records engines/model-meta/titan-ssd/<dir>.json -> titan ~/ai/<dir>/bakeoff-model.json.
  3. Config specs engines/entry-specs/<id>.json -> titan ~/ai/config/specs/<id>.json.
  3b. The same specs with their model record embedded under `model` -> titan /etc/llama-bored/specs/<id>.json, for
     llama-watch (entry_spec.mirror_on_titan; a failure there only prints a line).
  4. References in titan's llama-swap.yaml: `--label bakeoff.spec=<path>` after `podman run --name X --rm` on container
     entries, `BAKEOFF_SPEC=<path>` in `env` on native entries.
Every file is written atomically (temp file, chmod 644, rename). The yaml is edited in place under the usual rules:
nothing loaded, a backup, every other entry asserted unchanged, 20 s for llama-swap's reload.

Before writing it checks each spec's cmd_sha256 against the entry's current cmd. A llama.cpp entry whose flag line was
rewritten by a matrix row since the spec was reviewed is refreshed through entry_spec.apply_flags (the same code
set_variant uses); any other mismatch stops the run.
"""
import argparse, glob, json, os, re, shlex, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml
import entry_spec as E

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SPECS = os.path.join(HERE, "engines", "entry-specs")
METAS = os.path.join(HERE, "engines", "model-meta")


def new_yaml(text, refs_by_entry):
    M = yaml.safe_load(text)["models"]
    lines = text.split("\n"); out = []; cur = None; i = 0; placed = set()
    while i < len(lines):
        l = lines[i]
        m = re.match(r"^  ([A-Za-z0-9._-]+):\s*$", l)
        if m: cur = m.group(1)
        ref = refs_by_entry.get(cur) if cur in M else None
        if ref and (re.match(r"^      --label bakeoff\.spec=", l) or re.match(r"^      - '?" + E.ENV_KEY, l)):
            i += 1; continue
        out.append(l)
        container = ref and M[cur]["cmd"].lstrip().startswith("podman run")
        if container and re.match(r"^      podman run --name \S+ --rm\s*$", l):
            out.append(f"      --label bakeoff.spec={ref}"); placed.add(cur)
        if ref and not container and l == "    env:":
            j = i + 1
            while j < len(lines) and lines[j].startswith("      - "):
                if not re.match(r"^      - '?" + E.ENV_KEY, lines[j]): out.append(lines[j])
                j += 1
            out.append(f"      - '{E.ENV_KEY}{ref}'"); placed.add(cur); i = j; continue
        if ref and not container and l == "    cmd: |" and "env" not in M[cur]:
            out.pop(); out += ["    env:", f"      - '{E.ENV_KEY}{ref}'", l]; placed.add(cur)
        i += 1
    s2 = "\n".join(out)
    missing = set(refs_by_entry) - placed
    assert not missing, f"no place for a reference in {sorted(missing)}"
    M2 = yaml.safe_load(s2)["models"]
    assert set(M2) == set(M)
    for k in M:
        a, b = dict(M[k]), dict(M2[k])
        strip = lambda c: "\n".join(x for x in E.LABEL_RE.sub("", c).split("\n") if x.strip())
        a["cmd"], b["cmd"] = strip(a["cmd"]), strip(b["cmd"])
        ea = [e for e in a.pop("env", None) or [] if not str(e).startswith(E.ENV_KEY)]
        eb = [e for e in b.pop("env", None) or [] if not str(e).startswith(E.ENV_KEY)]
        assert a == b and ea == eb, k
    return s2


def flag_line(cmd):
    m = re.findall(r"^-ngl .*$", cmd, re.M)
    return m[-1] if m else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    text = E.ssh(f"cat {E.YAML_PATH}")
    R = E.refs(text)
    specs = {os.path.basename(f)[:-5]: json.load(open(f)) for f in sorted(glob.glob(os.path.join(SPECS, "*.json")))}
    problems, refreshed = [], []
    for k, s in specs.items():
        bad = E.validate(s, k)
        if bad: problems.append(f"{k}: {bad}")
        if k not in R: problems.append(f"{k}: no such entry on titan"); continue
        cmd = R[k][0]
        if s["cmd_sha256"] != E.cmd_hash(cmd):
            fl = flag_line(cmd)
            if s["engine"] == "llama.cpp" and fl:
                s2 = E.apply_flags(s, fl); s2["cmd_sha256"] = E.cmd_hash(cmd); specs[k] = s2
                refreshed.append(f"{k} (flag line now: {fl})")
            else:
                problems.append(f"{k}: cmd changed since the spec was reviewed; review the spec again")
    untabled = [k for k in R if k not in specs]
    metas = {}
    for f in glob.glob(os.path.join(METAS, "**", "*.json"), recursive=True):
        m = json.load(open(f)); bad = E.validate_meta(m)
        if bad: problems.append(f"{f}: {bad}")
        metas[f] = m
    for k, s in specs.items():
        rp = E.meta_repo_path(s["model_meta"])
        if not rp or os.path.abspath(rp) not in {os.path.abspath(x) for x in metas}:
            problems.append(f"{k}: model record {s['model_meta']} has no repo copy")
    refs_by_entry = {k: f"{E.SPEC_DIR}/{k}.json" for k in specs if k in R}
    s2 = new_yaml(text, refs_by_entry)
    import difflib
    d = [x for x in difflib.unified_diff(text.split("\n"), s2.split("\n"), lineterm="", n=0)
         if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    nas_writes, titan_writes = [], {}
    for f, m in metas.items():
        body = json.dumps(m, indent=1) + "\n"
        if m["location"]["root"] == "nas":
            dest = os.path.join(m["location"]["saturn_path"], "bakeoff-model.json")
            old = open(dest).read() if os.path.exists(dest) else None
            nas_writes.append((dest, body, "new" if old is None else "same" if old == body else "changed"))
        else:
            titan_writes[m["location"]["titan_path"] + "/bakeoff-model.json"] = body
    for k, s in specs.items():
        if k in R: titan_writes[f"{E.SPEC_DIR}/{k}.json"] = json.dumps(s, indent=1) + "\n"
    print(f"config specs: {len(specs)}; entries on titan without a spec: {' '.join(untabled) or '-'}")
    print(f"refreshed from the current flag line: {len(refreshed)}"); [print("  " + x) for x in refreshed]
    print(f"model records on the NAS: {len(nas_writes)} ("
          + ", ".join(f"{sum(1 for w in nas_writes if w[2] == t)} {t}" for t in ("new", "changed", "same")) + ")")
    print(f"files on titan: {len(titan_writes)} (specs dir {E.SPEC_DIR}, plus SSD model records)")
    print(f"yaml: +{sum(1 for x in d if x[0] == '+')} -{sum(1 for x in d if x[0] == '-')} lines, other entries unchanged")
    for x in d[:6]: print("  " + x[:160])
    if problems:
        print("PROBLEMS (nothing written):"); [print("  " + p) for p in problems]; sys.exit(1)
    if not a.apply:
        print("dry run; pass --apply in a gap with nothing loaded"); return
    # titan first: refuse unless idle, then files, then the yaml (same inode)
    bundle = json.dumps({"files": titan_writes, "yaml": s2, "yaml_path": E.YAML_PATH})
    prog = r'''
import json, os, sys, shutil, tempfile, time, urllib.request
b = json.load(sys.stdin)
if json.load(urllib.request.urlopen("http://127.0.0.1:8081/running", timeout=10))["running"]:
    sys.exit("a model is loaded; nothing changed")
for p, body in b["files"].items():
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, t = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".bakeoff-")
    with os.fdopen(fd, "w") as f: f.write(body)
    os.chmod(t, 0o644); os.replace(t, p)
P = b["yaml_path"]; stamp = time.strftime("%Y%m%d-%H%M%S"); shutil.copy2(P, P + ".bak-entry-specs-" + stamp)
ino = os.stat(P).st_ino
with open(P, "r+", encoding="utf-8") as f:
    f.seek(0); f.write(b["yaml"]); f.truncate(); f.flush(); os.fsync(f.fileno())
assert os.stat(P).st_ino == ino
time.sleep(20)
print("titan: %d files written; yaml backup .bak-entry-specs-%s" % (len(b["files"]), stamp))
'''
    r = subprocess.run(["ssh", "-o", "HostKeyAlias=titan", E.TITAN, "python3 -c " + shlex.quote(prog)], input=bundle,
                       capture_output=True, text=True, timeout=300)
    print(r.stdout.strip(), r.stderr.strip())
    if r.returncode != 0: sys.exit("titan step failed; NAS records not written")
    print(E.mirror_on_titan())
    for dest, body, state in nas_writes:
        if state == "same": continue
        fd, t = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".bakeoff-")
        with os.fdopen(fd, "w") as f: f.write(body)
        os.chmod(t, 0o644); os.replace(t, dest)
    print(f"NAS: {sum(1 for w in nas_writes if w[2] != 'same')} model records written")


if __name__ == "__main__":
    main()
