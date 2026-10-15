"""Report whether a llama-swap model is MoE, its weight size and layer count.

  python3 is_moe.py <llama-swap-model-id>   ->   "yes|no <GiB> <block_count>"
  python3 is_moe.py <llama-swap-model-id> ctx   ->   "<native context_length>"

Reads the GGUF header, never the llama-swap config's -ncmoe value: plan-and-gate
rewrites that config as it runs, and reading back what it had just written made
an MoE model look dense and stopped it ever escalating its offload.

Committed here rather than kept in a scratch directory: it was lost once when
pluto rebooted, while plan-and-gate2.sh still depended on it.
"""
import glob, io, os, re, struct, sys

CFG = "/home/operator/ai/config/llama-swap.yaml"
MODELS = "/home/operator/ai/models"


def main(mid, want="moe"):
    s = io.open(CFG, encoding="utf-8").read()
    m = re.search(r"^  %s:\n(?:.*\n)*?^\s+-m\s+(\S+)" % re.escape(mid), s, re.M)
    if not m:
        print("no 0 0"); return
    path = m.group(1).replace("/models", MODELS, 1)
    shards = glob.glob(re.sub(r"-\d{5}-of-\d{5}\.gguf$", "-*.gguf", path)) or [path]
    shards = [x for x in shards if "mmproj" not in x and "draft" not in x and os.path.isfile(x)]
    if not shards:
        print("no 0 0"); return
    f = open(sorted(shards)[0], "rb")
    if f.read(4) != b"GGUF":
        print("no 0 0"); return
    struct.unpack("<I", f.read(4)); struct.unpack("<Q", f.read(8)); nkv, = struct.unpack("<Q", f.read(8))

    def rs():
        n, = struct.unpack("<Q", f.read(8)); return f.read(n).decode("utf8", "replace")

    def rv(t):
        if t in (0, 1): return struct.unpack("<b" if t == 0 else "<B", f.read(1))[0]
        if t in (2, 3): return struct.unpack("<h" if t == 2 else "<H", f.read(2))[0]
        if t in (4, 5): return struct.unpack("<i" if t == 4 else "<I", f.read(4))[0]
        if t == 6: return struct.unpack("<f", f.read(4))[0]
        if t == 7: return struct.unpack("<?", f.read(1))[0]
        if t == 8: return rs()
        if t == 9:
            et, = struct.unpack("<I", f.read(4)); n, = struct.unpack("<Q", f.read(8))
            return [rv(et) for _ in range(n)]
        if t in (10, 11): return struct.unpack("<q" if t == 10 else "<Q", f.read(8))[0]
        if t == 12: return struct.unpack("<d", f.read(8))[0]
        raise ValueError(t)

    moe, blocks, ctx = "no", 0, 0
    for _ in range(nkv):
        k = rs(); t, = struct.unpack("<I", f.read(4)); v = rv(t)
        if k.endswith(".expert_count") and isinstance(v, int) and v > 0:
            moe = "yes"
        if k.endswith(".block_count") and isinstance(v, int):
            blocks = v
        if k.endswith(".context_length") and isinstance(v, int):
            ctx = v
    if want == "ctx":
        print(ctx); return
    gib = sum(os.path.getsize(x) for x in shards) / 2**30
    print("%s %d %d" % (moe, round(gib), blocks))


if __name__ == "__main__":
    main(*sys.argv[1:3])
