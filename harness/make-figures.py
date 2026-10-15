#!/usr/bin/env python3
"""Report figures drawn from VictoriaMetrics.

Grafana is the live console; these are the static figures for the writeup, so
they are generated from the same series rather than screenshotted, which keeps
them reproducible and diffable.
"""
import json, urllib.parse, urllib.request, datetime as dt, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

VM = "http://127.0.0.1:8428/api/v1/query_range"

def rng(q, start, end, step=60):
    u = VM + "?" + urllib.parse.urlencode(
        {"query": q, "start": start, "end": end, "step": step})
    return json.load(urllib.request.urlopen(u, timeout=45))["data"]["result"]

end = int(dt.datetime.now().timestamp())
start = end - 50400          # the working day

util  = rng("llamaswap_gpu_util_percent", start, end)
power = rng("llamaswap_gpu_power_draw_watts", start, end)
load  = rng("llamabored_model_loaded", start, end, 300)

def series(res):
    if not res:
        return [], []
    xs = [dt.datetime.fromtimestamp(float(t)) for t, _ in res[0]["values"]]
    ys = [float(v) for _, v in res[0]["values"]]
    return xs, ys

ux, uy = series(util)
px, py = series(power)

fig, (ax, ax2) = plt.subplots(
    2, 1, figsize=(11, 6.2), sharex=True,
    gridspec_kw={"height_ratios": [3, 1], "hspace": 0.12})

ax.fill_between(ux, uy, color="#2f6f9f", alpha=.30, linewidth=0)
ax.plot(ux, uy, color="#2f6f9f", linewidth=.8)
ax.set_ylabel("GPU utilisation (%)")
ax.set_ylim(0, 105)
ax.grid(alpha=.25, linewidth=.5)
ax.set_title("One RTX 3090, one day of agentic model evaluation",
             loc="left", fontsize=13, weight="bold")

# Model residency bands underneath, so idle-but-loaded is visible.
bands, cur, t0, tlast = [], None, None, None
rows = sorted(
    (float(t), r["metric"].get("full_name", "?"))
    for r in load for t, v in r["values"] if v == "1")
for t, name in rows:
    if name != cur:
        if cur:
            bands.append((t0, tlast, cur))
        cur, t0 = name, t
    tlast = t
if cur:
    bands.append((t0, tlast, cur))

colors = plt.cm.tab20.colors
seen = {}
for i, (s, e, name) in enumerate(bands):
    if (e - s) < 300:
        continue
    c = seen.setdefault(name, colors[len(seen) % len(colors)])
    ax2.axvspan(dt.datetime.fromtimestamp(s), dt.datetime.fromtimestamp(e),
                color=c, alpha=.85)
ax2.set_yticks([])
ax2.set_ylabel("resident\nmodel", fontsize=8)
ax2.grid(False)
for sp in ("top", "right", "left"):
    ax2.spines[sp].set_visible(False)

handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in seen.values()]
ax2.legend(handles, [n[:34] for n in seen], ncol=4, fontsize=7,
           loc="upper center", bbox_to_anchor=(.5, -.35), frameon=False)

ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
busy = sum(1 for v in uy if v > 5) / max(len(uy), 1) * 100
ax.annotate(f"GPU busy {busy:.0f}% of the day;\npeak power {max(py or [0]):.0f} W",
            xy=(.985, .93), xycoords="axes fraction", ha="right", va="top",
            fontsize=9, color="#444")
fig.savefig("figures/gpu-timeline.png", dpi=150, bbox_inches="tight")
print("wrote figures/gpu-timeline.png")
print(f"  bands: {len(bands)}  gpu busy: {busy:.1f}%  peak: {max(py or [0]):.0f} W")
