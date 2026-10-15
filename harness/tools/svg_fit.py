"""Copy a model-written SVG so that it fills the render window: the root <svg> gets width and height of 100%, and a
viewBox made from its own width and height when it has none. Only the root tag's size attributes change; the drawing is
left alone. Default preserveAspectRatio (xMidYMid meet) then fits it like the old <img object-fit:contain> did.
  python3 -I tools/svg_fit.py <in.svg> <out.svg>
Either path may be - for stdin or stdout (sandbox/t8/preview.py uses that, so its /fit needs no temp files).
The root is the first element after the prolog (XML declaration, comments, processing instructions, DOCTYPE with its
internal subset); attributes are read with their quotes, so a '>' or 'width=' inside a value is not taken for markup.
When the size is in units other than px and there is no viewBox, the file is copied unchanged (no coordinate system to
scale). Anything this script cannot read is copied unchanged too.
"""
import io
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
s = (io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace").read() if src == "-"
     else open(src, encoding="utf-8", errors="replace").read())


def done(text):
    if dst == "-":
        sys.stdout.buffer.write(text.encode("utf-8"))
    else:
        open(dst, "w", encoding="utf-8").write(text)
    sys.exit(0)


PROLOG = re.compile(r"\s+|<\?.*?\?>|<!--.*?-->|<!DOCTYPE(?:[^\[>]|\[.*?\])*>", re.S | re.I)
TAG = re.compile(r"<((?:[\w.-]+:)?svg)((?:\s+[^\s=/>]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)(\s*/?>)")
ATTR = re.compile(r"(\s+)([^\s=/>]+)(\s*=\s*)(\"[^\"]*\"|'[^']*')")

pos = 0
while True:
    m = PROLOG.match(s, pos)
    if not m or m.end() == pos:
        break
    pos = m.end()
m = TAG.match(s, pos)
if not m:
    done(s)
attrs = [(a.group(2), a.group(4)[1:-1], a.group(0)) for a in ATTR.finditer(m.group(2))]
names = [n for n, _, _ in attrs]
if len(set(names)) != len(names):
    done(s)
val = {n: v for n, v, _ in attrs}


def num(v):
    a = re.fullmatch(r"\s*\+?((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:px)?\s*", v or "", re.I)
    x = float(a.group(1)) if a else 0.0
    return x if 0 < x < 1e7 else None


def fmt(x):
    return ("%.6f" % x).rstrip("0").rstrip(".")


extra = ' width="100%" height="100%"'
if "viewBox" not in val:
    w, h = num(val.get("width")), num(val.get("height"))
    if "width" in val or "height" in val:
        if not (w and h):
            done(s)
        extra += ' viewBox="0 0 %s %s"' % (fmt(w), fmt(h))
kept = []
for n, v, raw in attrs:
    if n in ("width", "height"):
        continue
    if n == "style" and re.search(r"(^|[;\s])(width|height)\s*:", v, re.I):
        # an inline style size beats the attributes; ours goes last so it wins
        q = '"' if '"' not in v else "'"
        raw = " style=%s%s;width:100%%;height:100%%%s" % (q, v.rstrip().rstrip(";"), q)
    kept.append(raw)
new = "<" + m.group(1) + extra + "".join(kept) + m.group(3)
done(s[:m.start()] + new + s[m.end():])
