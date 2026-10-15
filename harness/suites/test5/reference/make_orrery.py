#!/usr/bin/env python3
"""Writes brass-orrery.svg: a clockwork orrery, SMIL-animated, no scripts."""
import math, random

C = 600                      # centre of a 1200 x 1200 canvas
YEAR = 12.0                  # seconds for one Earth year
DAY = 3.0                    # seconds for one Earth day (compressed scale, see note in the SVG)
M = 4.0                      # gear module: pitch radius = M * teeth / 2
PIN = 12                     # teeth on every drive pinion

# name, sidereal period (years), wheel teeth, orbit radius, planet radius, start angle
P = [("Mercury", 0.2408467, 20, 235, 8, 200), ("Venus", 0.61519726, 29, 272, 12, 320),
     ("Earth", 1.0000174, 38, 312, 13, 75), ("Mars", 1.8808476, 47, 350, 10, 150),
     ("Jupiter", 11.862615, 56, 408, 24, 20), ("Saturn", 29.447498, 65, 470, 19, 260),
     ("Uranus", 84.016846, 74, 522, 15, 110), ("Neptune", 164.79132, 83, 565, 15, 305)]
# inertial spin period in seconds, + prograde / - retrograde
SPIN = {"Mercury": 0.2408467 * YEAR * 58.646 / 87.969, "Venus": -0.61519726 * YEAR * 243.02 / 224.70,
        "Earth": DAY * 0.9973, "Mars": DAY * 1.026, "Jupiter": DAY * 0.4135, "Saturn": DAY * 0.444,
        "Uranus": -DAY * 0.718, "Neptune": DAY * 0.671}
METAL = [("#fff1a8", "#d9b23c", "#8c6a17"), ("#ffd9a0", "#c98a3a", "#7a4a14"), ("#f7e9b0", "#c9a94a", "#77601c"),
         ("#ffcfa8", "#c2733f", "#6e3a17")]

f = lambda x: f"{x:.2f}".rstrip("0").rstrip(".")
pol = lambda r, a: (r * math.cos(a), r * math.sin(a))


def gear(n, m):
    """Outline with a tooth centred on angle 0."""
    rp = m * n / 2; rr = rp - 1.25 * m; rt = rp + m; p = 2 * math.pi / n; pts = []
    for k in range(n):
        a = k * p
        for da, r in ((-0.30, rr), (-0.14, rt), (0.14, rt), (0.30, rr)):
            pts.append(pol(r, a + da * p))
    return "M" + "L".join(f"{f(x)},{f(y)}" for x, y in pts) + "Z"


def windows(r1, r2, k, gap):
    """k see-through sectors between radii r1 and r2 (spokes are what is left)."""
    d = ""
    for i in range(k):
        a1 = 2 * math.pi * i / k + gap / r2; a2 = 2 * math.pi * (i + 1) / k - gap / r2
        b1 = 2 * math.pi * i / k + gap / r1; b2 = 2 * math.pi * (i + 1) / k - gap / r1
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = pol(r2, a1), pol(r2, a2), pol(r1, b2), pol(r1, b1)
        d += (f"M{f(x1)},{f(y1)}A{f(r2)},{f(r2)} 0 0 1 {f(x2)},{f(y2)}L{f(x3)},{f(y3)}"
              f"A{f(r1)},{f(r1)} 0 0 0 {f(x4)},{f(y4)}Z")
    return d


def spin(dur, sign, body):
    """Rotate body about the origin; sign +1 is counter-clockwise on screen (prograde)."""
    return (f'<g><animateTransform attributeName="transform" type="rotate" from="0" to="{-360 * sign}" '
            f'dur="{dur:.4f}s" repeatCount="indefinite"/>{body}</g>')


def surface(name, r):
    s = r / 10.0
    c = lambda x, y, rr, fill, o=1: f'<circle cx="{f(x*s)}" cy="{f(y*s)}" r="{f(rr*s)}" fill="{fill}" opacity="{o}"/>'
    e = lambda x, y, rx, ry, fill, rot=0, o=1: (f'<ellipse cx="{f(x*s)}" cy="{f(y*s)}" rx="{f(rx*s)}" ry="{f(ry*s)}" '
                                               f'fill="{fill}" opacity="{o}" transform="rotate({rot} {f(x*s)} {f(y*s)})"/>')
    def bands(cols):
        h = 20.0 / len(cols)
        return "".join(f'<rect x="{f(-10*s)}" y="{f((-10+i*h)*s)}" width="{f(20*s)}" height="{f(h*s+0.3)}" fill="{col}"/>'
                       for i, col in enumerate(cols))
    if name == "Mercury":
        return "#a39c92", c(-3, -2, 2.6, "#7d766d") + c(4, 3, 2, "#877f75") + c(1, -6, 1.5, "#6f685f") + c(-4, 5, 1.6, "#bdb6ab")
    if name == "Venus":
        return "#e8cc8c", e(0, -4, 9, 1.6, "#f8ecc6", 12, .8) + e(1, 1, 9, 1.4, "#c9a05a", -8, .7) + e(-1, 6, 7, 1.3, "#f3e0ad", 10, .8)
    if name == "Earth":
        return "#2c6ed6", (e(-3, -3, 4.2, 2.6, "#3f9a4a", 30) + e(-1.5, 3.5, 2, 3.4, "#4aa655", -15) + e(5, -1, 2.6, 4, "#3d9247", 10)
                           + e(4.5, 6, 2.4, 1.2, "#5aa85a") + c(0, -9, 3, "#f4f8ff") + c(0, 9.4, 2.4, "#f4f8ff")
                           + e(-5, 1, 4, .8, "#ffffff", -20, .75) + e(3, -5, 4, .7, "#ffffff", 15, .7))
    if name == "Mars":
        return "#c4552f", e(-2, 1, 5, 2.2, "#8a3520", 20, .9) + e(4, -3, 3, 1.6, "#93391f", -30, .85) + c(0, -8.6, 2.6, "#fbf3ea") + c(3, 5, 1.6, "#de7f55")
    if name == "Jupiter":
        return "#d9b48a", (bands(["#b98a60", "#e6cfa6", "#b0683f", "#efdcb8", "#c98f5d", "#f1e2c2", "#a8623c", "#e2c79c", "#b98a60"])
                           + e(3.4, 3.2, 2.6, 1.5, "#b7402a") + e(3.4, 3.2, 1.5, .8, "#d86a4a"))
    if name == "Saturn":
        return "#e2c88e", bands(["#c9a970", "#ecd9a8", "#d3b379", "#f2e3b8", "#cfae74", "#ead6a2", "#c5a268"]) + e(-3, -1.4, 2.2, .7, "#fff6d8", 0, .8)
    if name == "Uranus":
        return "#9fe0e2", e(0, -3, 10, 1.3, "#d5f6f6", 0, .7) + e(0, 4, 10, 1, "#7cc8cf", 0, .6) + c(4, -6, 1.3, "#e9ffff", .8)
    return "#3558d8", e(-2.5, 2, 3, 1.8, "#1c2f8c") + e(3, -3.5, 4, .7, "#dfe8ff", -12, .85) + e(-1, -6, 3, .6, "#cdd9ff", 8, .7) + e(2, 6, 4.5, 1, "#2644b8")


o = []
w = o.append
w(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1200" width="1200" height="1200" role="img"
     aria-label="Animated brass clockwork orrery: eight planets orbit the sun at their real relative speeds, each driven by a meshing wheel and pinion">
<title>Brass clockwork orrery</title>
<desc>Orbital periods are in true proportion (one Earth year = {YEAR:g} s). Every orbit wheel meshes with a {PIN}-tooth pinion;
tooth counts and speeds obey the gear law. Day lengths are compressed (one Earth day = {DAY:g} s) but keep their real ratios and directions
for Earth to Neptune; Mercury and Venus keep their real spin-to-orbit ratios. Sizes and distances are not to scale.</desc>
<defs>
<radialGradient id="sky" cx="50%" cy="50%" r="72%"><stop offset="0" stop-color="#232b45"/><stop offset=".55" stop-color="#111627"/><stop offset="1" stop-color="#05060c"/></radialGradient>
<radialGradient id="plate" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#2a1f14"/><stop offset=".45" stop-color="#17120d"/><stop offset="1" stop-color="#0b0a0c"/></radialGradient>
<radialGradient id="sun" cx="42%" cy="40%" r="62%"><stop offset="0" stop-color="#fffbe0"/><stop offset=".35" stop-color="#ffd95a"/><stop offset=".8" stop-color="#f08a1c"/><stop offset="1" stop-color="#b8500c"/></radialGradient>
<radialGradient id="halo" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#ffcf5a" stop-opacity=".75"/><stop offset=".35" stop-color="#ff9d2e" stop-opacity=".22"/><stop offset="1" stop-color="#ff8a1c" stop-opacity="0"/></radialGradient>
<linearGradient id="night" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#02030a" stop-opacity="0"/><stop offset=".40" stop-color="#02030a" stop-opacity="0"/><stop offset=".60" stop-color="#02030a" stop-opacity=".8"/><stop offset="1" stop-color="#02030a" stop-opacity=".92"/></linearGradient>
<radialGradient id="lit" cx="18%" cy="50%" r="60%"><stop offset="0" stop-color="#fff" stop-opacity=".38"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
<linearGradient id="rod" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff0a6"/><stop offset=".5" stop-color="#cfa431"/><stop offset="1" stop-color="#6f5312"/></linearGradient>
<radialGradient id="steel" cx="35%" cy="30%" r="80%"><stop offset="0" stop-color="#eef3fb"/><stop offset=".6" stop-color="#7f8ea8"/><stop offset="1" stop-color="#2c3550"/></radialGradient>''')
for i, (a, b, c_) in enumerate(METAL):
    w(f'<radialGradient id="m{i}" gradientUnits="userSpaceOnUse" cx="-40" cy="-60" r="330"><stop offset="0" stop-color="{a}"/>'
      f'<stop offset=".45" stop-color="{b}"/><stop offset="1" stop-color="{c_}"/></radialGradient>')
    w(f'<radialGradient id="p{i}" gradientUnits="userSpaceOnUse" cx="-8" cy="-10" r="40"><stop offset="0" stop-color="{a}"/>'
      f'<stop offset=".5" stop-color="{b}"/><stop offset="1" stop-color="{c_}"/></radialGradient>')
for name, _, _, _, r, _ in P:
    w(f'<clipPath id="c{name}"><circle r="{r}"/></clipPath>')
w('<clipPath id="ringclip" clip-rule="evenodd"><path clip-rule="evenodd" d="M-34,0A34,34 0 1 0 34,0A34,34 0 1 0 -34,0ZM-22,0A22,22 0 1 0 22,0A22,22 0 1 0 -22,0Z"/></clipPath>')
w('</defs>')

# backdrop, stars, base plate, bezel, orbit rails
w('<rect width="1200" height="1200" fill="url(#sky)"/>')
random.seed(1781)
for _ in range(190):
    x, y, r = random.uniform(0, 1200), random.uniform(0, 1200), random.choice([.6, .8, 1, 1.3, 1.7])
    w(f'<circle cx="{f(x)}" cy="{f(y)}" r="{r}" fill="#fff" opacity="{random.uniform(.25,.9):.2f}"/>')
w(f'<g transform="translate({C},{C})">')
w('<circle r="596" fill="url(#plate)"/>')
w('<circle r="591" fill="none" stroke="#6f5312" stroke-width="12"/><circle r="591" fill="none" stroke="#d9b23c" stroke-width="8"/>')
w(f'<circle r="591" fill="none" stroke="#3a2a0a" stroke-width="8" stroke-dasharray="1.2 {2*math.pi*591/360-1.2:.4f}"/>')
w(f'<circle r="589" fill="none" stroke="#3a2a0a" stroke-width="12" stroke-dasharray="2.4 {2*math.pi*589/12-2.4:.4f}"/>')
for name, _, _, R, _, _ in P:
    w(f'<circle r="{R}" fill="none" stroke="#c9a53a" stroke-width="1.3" opacity=".42"/>'
      f'<circle r="{R}" fill="none" stroke="#f3dc8a" stroke-width="3" opacity=".28" stroke-dasharray=".8 {2*math.pi*R/72-.8:.4f}"/>')
w('<circle r="226" fill="#0d0b0a" opacity=".55"/>')

# gear stack: biggest wheel at the bottom, each followed by its own pinion
for i in reversed(range(len(P))):
    name, T, N, R, r, a0 = P[i]
    dur = T * YEAR; rp = M * N / 2; theta = (i * 135) % 360; dist = M * (N + PIN) / 2
    d = gear(N, M)
    r2 = rp - 1.25 * M - 9
    if r2 - 30 >= 12:
        d += windows(30, r2, 5 if N < 50 else 6, 5)
    rivets = "".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="1.6" fill="#3a2a0a" opacity=".7"/>'
                     for x, y in (pol(rp - 1.25 * M - 4.5, 2 * math.pi * k / 12 + .26) for k in range(12)))
    w(f'<g transform="rotate({theta})"><!-- {name}: {N}-tooth wheel, {PIN}-tooth pinion -->')
    w(spin(dur, 1, f'<path d="{d}" fill="url(#m{i % 4})" fill-rule="evenodd" stroke="#33240a" stroke-width="1.1" stroke-linejoin="round"/>{rivets}'))
    pin = (f'<path d="{gear(PIN, M)}" fill="url(#p{(i + 2) % 4})" stroke="#33240a" stroke-width="1.1" stroke-linejoin="round"/>'
           f'<circle r="11" fill="none" stroke="#33240a" stroke-width="1" opacity=".6"/>'
           f'<path d="M-9,0H9M0,-9V9" stroke="#33240a" stroke-width="2.2" opacity=".55"/><circle r="5" fill="url(#steel)" stroke="#1a2032" stroke-width=".8"/>'
           f'<path d="M-3.2,0H3.2" stroke="#1a2032" stroke-width="1.1"/>')
    ph = 180 + 180.0 / PIN
    w(f'<g transform="translate({f(dist)},0)"><g><animateTransform attributeName="transform" type="rotate" from="{f(ph)}" to="{f(ph + 360)}" '
      f'dur="{dur * PIN / N:.4f}s" repeatCount="indefinite"/>{pin}</g></g></g>')

# arms and planets, above the gears, each turning with its wheel
for i in reversed(range(len(P))):
    name, T, N, R, r, a0 = P[i]
    dur = T * YEAR
    base, feats = surface(name, r)
    Ts = SPIN[name]; rel = (1 / Ts) - (1 / dur)          # spin as seen from the turning arm
    body = f'<circle r="{r}" fill="{base}"/>' + spin(1 / abs(rel), 1 if rel > 0 else -1, feats)
    extra_under = extra_over = ""
    if name == "Saturn":
        extra_under = ('<circle r="28" fill="none" stroke="#d8c48c" stroke-width="12" opacity=".9"/><circle r="29.5" fill="none" stroke="#5d4a22" stroke-width="1.2" opacity=".8"/>'
                       '<circle r="24.5" fill="none" stroke="#f3e6bd" stroke-width="1" opacity=".6"/>'
                       f'<rect x="0" y="{-r}" width="36" height="{2*r}" fill="#02030a" opacity=".6" clip-path="url(#ringclip)"/>')
    if name == "Earth":
        tm = 27.321661 / 365.256363 * YEAR; relm = 1 / tm - 1 / dur
        extra_over = spin(1 / relm, 1, '<circle r="22" fill="none" stroke="#c9a53a" stroke-width=".6" opacity=".5"/><path d="M13,0H20" stroke="#d9b23c" stroke-width="1.2"/>'
                                         '<circle cx="22" r="3" fill="#d9d6cf" stroke="#33240a" stroke-width=".5"/>')
    planet = (f'<g transform="translate({R},0)">{extra_under}<g clip-path="url(#c{name})">{body}'
              f'<rect x="{-r}" y="{-r}" width="{2*r}" height="{2*r}" fill="url(#lit)"/>'
              f'<rect x="{-r}" y="{-r}" width="{2*r}" height="{2*r}" fill="url(#night)"/></g>'
              f'<circle r="{r}" fill="none" stroke="#0a0a12" stroke-width=".8" opacity=".8"/>{extra_over}</g>')
    arm = (f'<path d="M-46,0H{R - r - 3}" stroke="#2a1d07" stroke-width="5.4" stroke-linecap="round"/>'
           f'<path d="M-46,0H{R - r - 3}" stroke="#d9b23c" stroke-width="3.4" stroke-linecap="round"/>'
           f'<path d="M-44,-0.9H{R - r - 5}" stroke="#fff1a8" stroke-width="1" stroke-linecap="round" opacity=".8"/>'
           f'<circle cx="-46" r="6.5" fill="url(#p{i % 4})" stroke="#2a1d07" stroke-width="1"/>'
           f'<circle cx="{R - r - 4}" r="3.2" fill="url(#p{i % 4})" stroke="#2a1d07" stroke-width=".8"/>')
    w(f'<g transform="rotate({a0})"><!-- {name}: period {dur:.3f} s -->' + spin(dur, 1, arm + planet) + '</g>')

# sun on the central post
w('<circle r="150" fill="url(#halo)"><animate attributeName="r" values="140;158;140" dur="6s" repeatCount="indefinite"/></circle>')
rays = "".join(f'<path d="M0,-33L3.2,-46L0,-{58 if k % 2 == 0 else 50}L-3.2,-46Z" fill="#ffd45a" stroke="#8c5a10" stroke-width=".7" transform="rotate({k*22.5})"/>' for k in range(16))
w(f'<g><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="90s" repeatCount="indefinite"/>{rays}</g>')
w('<circle r="34" fill="url(#sun)" stroke="#8c5a10" stroke-width="1.5"/><circle r="34" fill="none" stroke="#fff6c8" stroke-width="1" opacity=".5"/>')
w('</g>')
w('<g font-family="Georgia, \'Times New Roman\', serif" fill="#d9b23c" opacity=".85">'
  '<text x="34" y="1166" font-size="22" letter-spacing="5">BRASS ORRERY</text>'
  f'<text x="1166" y="1166" font-size="16" text-anchor="end" font-style="italic">one Earth year = {YEAR:g} s</text></g>')
w('</svg>')
open("brass-orrery.svg", "w").write("\n".join(o))
print(len("\n".join(o)), "bytes")
