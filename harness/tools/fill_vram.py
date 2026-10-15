"""Fill the 3090 for one model: the largest context it will hold, then (for MoE)
as many expert layers back on the GPU as the leftover VRAM allows.

  python3 tools/fill_vram.py <model-id> "<gated flags>"   ->  prints tuned flags

Operator, 2026-10-02: models were running 128k context with 6-7 GB of VRAM
unused. Rule: keep the gated KV cache type, raise -c towards the model's native
context_length (GGUF header), then lower -ncmoe while it still fits. A setting
"fits" when llama-swap loads it, it answers, and VRAM stays under LIMIT_MIB.

Each probe is a real load through lib.sh set_variant + warm, so the tuned line
is exactly what the case will run. Leaves llama-swap.yaml on the tuned flags.
"""
import json, os, re, subprocess, sys, time

HERE = __file__.rsplit("/tools/", 1)[0]
LIMIT_MIB = 24576 - 640   # 3090 total minus headroom for buffers allocated after load (vision, sampler)
STEP = 8192


def sh(script, timeout=3600):
    r = subprocess.run(["bash", "-c", f"cd {HERE} && source lib.sh && {script}"],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def native_ctx(mid):
    # The model record is the source. /tmp/is_moe.py was missing on 2026-10-13, so this
    # returned 0 and the LFM tune never left 32k.
    spec_path = os.path.join(HERE, "engines", "entry-specs", mid + ".json")
    try:
        meta = json.load(open(spec_path)).get("model_meta") or ""
        prefix = "/home/operator/ai/models/"
        local = "/srv/store/models/" + meta[len(prefix):] if meta.startswith(prefix) else ""
        n = int(json.load(open(local)).get("native_context") or 0) if local else 0
    except Exception:
        n = 0
    if n:
        return n
    out = subprocess.run(["ssh", "-n", "titan", "python3", "/tmp/is_moe.py", mid, "ctx"],
                         capture_output=True, text=True).stdout.strip()
    return int(out or 0)


def with_flag(flags, flag, value):
    if re.search(rf"(^|\s){flag}\s+\S+", flags):
        return re.sub(rf"(^|\s){flag}\s+\S+", rf"\g<1>{flag} {value}", flags)
    return f"{flags} {flag} {value}"


def get(flags, flag):
    m = re.search(rf"(^|\s){flag}\s+(\S+)", flags)
    return m.group(2) if m else None


tried = {}


def fits(mid, flags):
    if flags in tried:
        return tried[flags]
    rc, _ = sh(f'set_variant {mid} "{flags}" >/dev/null')
    if rc != 0:
        sys.exit(f"set_variant failed for {flags}")
    rc, out = sh(f"WARM_RETRIES=3 warm {mid} >/dev/null 2>&1 && vram")
    mib = int(out) if rc == 0 and out.isdigit() else None
    ok = mib is not None and mib <= LIMIT_MIB
    print(f"  {'fit ' if ok else 'NO  '} {mib or '-':>6} MiB  {flags}", file=sys.stderr, flush=True)
    tried[flags] = (ok, mib)
    return ok, mib


def main(mid, flags):
    flags = re.sub(r"\s+-lm\s+none", "", flags).strip()
    top = native_ctx(mid)
    cur = int(get(flags, "-c"))
    print(f"== {mid}: gated -c {cur}, native {top}", file=sys.stderr, flush=True)
    ok, mib = fits(mid, flags)
    if not ok:
        # The starting point does not load (gemma-4-31b at 98k q8_0 OOMed and
        # the case then ran against a model that could never start). Search
        # DOWN for the largest context that loads, floor 32k, rather than give up.
        lo, hi = 32768 // STEP - 1, cur // STEP           # hi fails
        while hi - lo > 1:
            m = (lo + hi) // 2
            if fits(mid, with_flag(flags, "-c", m * STEP))[0]:
                lo = m
            else:
                hi = m
        if lo * STEP < 32768:
            sys.exit(f"does not load even at 32k ({mib} MiB)")
        flags = with_flag(flags, "-c", lo * STEP); cur = lo * STEP
        print(f"  gated -c did not load; largest that does: {cur}", file=sys.stderr, flush=True)
        return finish(mid, flags)
    best = flags
    # 1. context: try native outright, else binary search in STEP units.
    if top > cur:
        if fits(mid, with_flag(flags, "-c", top))[0]:
            best = with_flag(flags, "-c", top)
        else:
            lo, hi = cur // STEP, top // STEP          # lo fits, hi does not
            while hi - lo > 1:
                m = (lo + hi) // 2
                if fits(mid, with_flag(flags, "-c", m * STEP))[0]:
                    lo = m
                else:
                    hi = m
            best = with_flag(flags, "-c", lo * STEP)
    return finish(mid, best)


def finish(mid, best):
    # 2. experts: with whatever VRAM is left, bring expert layers back.
    n = get(best, "-ncmoe")
    if n and int(n) > 0:
        lo, hi = -1, int(n)                            # hi fits; find the smallest that fits
        if fits(mid, with_flag(best, "-ncmoe", 0))[0]:
            hi = 0
        else:
            lo = 0
            while hi - lo > 1:
                m = (lo + hi) // 2
                if fits(mid, with_flag(best, "-ncmoe", m))[0]:
                    hi = m
                else:
                    lo = m
        best = with_flag(best, "-ncmoe", hi)
        if hi == 0:
            best = re.sub(r"\s+-ncmoe\s+0", "", best)
    ok, mib = fits(mid, best)                         # leave llama-swap on the winner
    if not ok:
        sys.exit("tuned config failed its final load")
    print(f"== {mid}: {best}  ({mib} MiB)", file=sys.stderr, flush=True)
    print(best)




if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
