// Decorative chapter motifs, each drawn from that chapter's own numbers (data.js motifs()). They are
// aria-hidden ornaments: every fact they encode is also in the chapter's text or charts.
import { svg } from './dom.js';

const W = 200, H = 110;
const VERDICT = { pass: 'var(--pass)', partial: 'var(--partial)', fail: 'var(--fail)' };
const vcol = (v) => VERDICT[v] || 'var(--unknown)';
const root = (cls) => svg('svg', { class: `motif-svg ${cls}`, viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true', focusable: 'false' });
const polar = (cx, cy, r, a) => `${(cx + r * Math.cos(a)).toFixed(1)} ${(cy + r * Math.sin(a)).toFixed(1)}`;

const DRAW = {
  // 01 the machine: a die with one lead per spec line
  machine(m) {
    const s = root('m-machine'), cx = 100, cy = 55;
    s.appendChild(svg('rect', { x: cx - 34, y: cy - 24, width: 68, height: 48, rx: 6, class: 'chip-body' }));
    s.appendChild(svg('rect', { x: cx - 18, y: cy - 12, width: 36, height: 24, rx: 3, class: 'chip-die' }));
    m.forEach((lead, i) => {
      const y = cy - 18 + (Math.floor(i / 2) % 5) * 9, x0 = lead.side < 0 ? cx - 34 : cx + 34, x1 = x0 + lead.side * (26 + (i % 3) * 8);
      s.appendChild(svg('line', { x1: x0, y1: y, x2: x1, y2: y, class: 'chip-lead' }));
      s.appendChild(svg('circle', { cx: x1, cy: y, r: 2.4, class: 'chip-pad' }));
    });
    return s;
  },
  // 02 tests: one seal per test, area by graded runs
  tests(m) {
    if (!m.length) return null;
    const s = root('m-tests'), max = Math.max(1, ...m.map((t) => t.n)), step = W / (m.length + 1);
    m.forEach((t, i) => {
      const r = 7 + 13 * Math.sqrt(t.n / max), cx = step * (i + 1), cy = 55 + (i % 2 ? 14 : -14);
      s.appendChild(svg('circle', { cx, cy, r: r + 4, class: 'seal-ring' }));
      s.appendChild(svg('circle', { cx, cy, r, class: `seal ${(t.kind || 'other').replace(/[^a-z-]/gi, '').toLowerCase()}` }));
      s.appendChild(svg('text', { x: cx, y: cy + 3.5, class: 'seal-num', 'text-anchor': 'middle' }, t.number));
    });
    return s;
  },
  // 03 picks: a laurel ring, one arc per family, length by models tried
  picks(m) {
    if (!m.length) return null;
    const s = root('m-picks'), cx = 100, cy = 55, R = 44, r0 = 30, gap = 0.05;
    let a = -Math.PI / 2;
    for (const f of m) {
      const span = Math.max(0.02, f.share * (Math.PI * 2 - gap * m.length));
      const a0 = a + gap / 2, a1 = a + gap / 2 + span; a += span + gap;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      s.appendChild(svg('path', { d: `M ${polar(cx, cy, r0, a0)} L ${polar(cx, cy, R, a0)} A ${R} ${R} 0 ${large} 1 ${polar(cx, cy, R, a1)} L ${polar(cx, cy, r0, a1)} A ${r0} ${r0} 0 ${large} 0 ${polar(cx, cy, r0, a0)} Z`, fill: f.color, class: 'laurel' }));
    }
    s.appendChild(svg('circle', { cx, cy, r: 9, class: 'laurel-core' }));
    return s;
  },
  // 04 runs: a constellation, x by speed, each star a run
  runs(m) {
    if (!m.stars.length) return null;
    const s = root('m-runs');
    const P = (st) => [8 + st.x * 184, 10 + st.y * 90];
    for (const [i, j] of m.links) { const [x1, y1] = P(m.stars[i]), [x2, y2] = P(m.stars[j]); s.appendChild(svg('line', { x1, y1, x2, y2, class: 'star-link' })); }
    for (const st of m.stars) { const [cx, cy] = P(st); s.appendChild(svg('circle', { cx, cy, r: st.verdict === 'pass' ? 2.2 : 1.4, fill: vcol(st.verdict), class: 'star' })); }
    return s;
  },
  // 05 struggle: a skyline of compiler-error spikes, cleanest left
  struggle(m) {
    if (!m.length) return null;
    const s = root('m-struggle'), w = 190 / m.length;
    m.forEach((r, i) => { const h = 5 + 92 * r.h; s.appendChild(svg('rect', { x: 5 + i * w, y: H - 4 - h, width: Math.max(0.8, w - 0.9), height: h, fill: vcol(r.verdict), class: 'spike' })); });
    return s;
  },
  // 06 test 3: a mosaic, one tile per row, brightness by rubric, pink frame when the server was misjudged
  test3(m) {
    if (!m.length) return null;
    const s = root('m-test3'), cols = Math.ceil(Math.sqrt(m.length * (W / H))), rows = Math.ceil(m.length / cols), cell = Math.min(W / cols, H / rows);
    const ox = (W - cols * cell) / 2, oy = (H - rows * cell) / 2;
    m.forEach((t, i) => {
      const x = ox + (i % cols) * cell, y = oy + Math.floor(i / cols) * cell;
      s.appendChild(svg('rect', { x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, rx: 2, fill: t.color, 'fill-opacity': (0.12 + 0.88 * t.level).toFixed(2), class: `tile${t.right === false ? ' wrong' : ''}` }));
    });
    return s;
  },
  // 07 engines: tuning forks, one bar per probe, colour by engine
  ab(m) {
    if (!m.length) return null;
    const s = root('m-ab'), gw = 188 / m.length;
    m.forEach((rows, i) => {
      const bw = Math.min(10, gw / (rows.length + 1));
      rows.forEach((r, j) => { const h = 6 + 92 * r.h; s.appendChild(svg('rect', { x: 6 + i * gw + j * (bw + 1.5), y: H - 4 - h, width: bw, height: h, rx: 1.5, fill: r.color, class: 'fork' })); });
    });
    return s;
  },
  // 08 one-shots: a gear for the orrery set (one tooth per reply), a flower for the pagodas (one petal per reply)
  oneshots(m) {
    if (!m.length) return null;
    const s = root('m-oneshots'), n = m.length;
    m.forEach((set, i) => {
      const cx = (W / n) * (i + 0.5), cy = 55, R = Math.min(48, W / n / 2 - 4), k = Math.max(1, set.values.length);
      if (set.shape === 'gear') {
        const r0 = R * 0.52;
        let d = '';
        set.values.forEach((v, j) => {
          const a0 = (j / k) * Math.PI * 2, a1 = ((j + 0.5) / k) * Math.PI * 2, r1 = r0 + (R - r0) * (0.2 + 0.8 * v);
          d += `${j ? 'L' : 'M'} ${polar(cx, cy, r0, a0)} L ${polar(cx, cy, r1, a0 + (a1 - a0) * 0.15)} L ${polar(cx, cy, r1, a1 - (a1 - a0) * 0.15)} L ${polar(cx, cy, r0, a1)} `;
        });
        s.appendChild(svg('path', { d: d + 'Z', class: 'gear' }));
        s.appendChild(svg('circle', { cx, cy, r: r0 * 0.45, class: 'gear-hub' }));
      } else if (set.shape === 'flower') {
        set.values.forEach((v, j) => {
          const a = (j / k) * Math.PI * 2, len = R * (0.25 + 0.75 * v), wdt = Math.max(0.08, Math.min(0.5, Math.PI / k));
          s.appendChild(svg('path', { d: `M ${polar(cx, cy, 4, a)} Q ${polar(cx, cy, len * 0.55, a - wdt)} ${polar(cx, cy, len, a)} Q ${polar(cx, cy, len * 0.55, a + wdt)} ${polar(cx, cy, 4, a)} Z`, class: 'petal-m', 'fill-opacity': (0.35 + 0.6 * v).toFixed(2) }));
        });
        s.appendChild(svg('circle', { cx, cy, r: 5, class: 'flower-core' }));
      } else {
        set.values.forEach((v, j) => { const a = (j / k) * Math.PI * 2; s.appendChild(svg('line', { x1: polar(cx, cy, R * 0.35, a).split(' ')[0], y1: polar(cx, cy, R * 0.35, a).split(' ')[1], x2: polar(cx, cy, R * (0.4 + 0.6 * v), a).split(' ')[0], y2: polar(cx, cy, R * (0.4 + 0.6 * v), a).split(' ')[1], class: 'ray' })); });
      }
    });
    return s;
  },
  // 09 findings: comet streaks, before → after
  findings(m) {
    if (!m.length) return null;
    const s = root('m-findings'), step = 90 / m.length;
    m.forEach((f, i) => {
      const y = 12 + i * step + step / 2, x0 = 10 + (f.isNew ? 0 : f.from) * 170, x1 = 10 + f.to * 170;
      s.appendChild(svg('line', { x1: Math.min(x0, x1), y1: y, x2: Math.max(x0, x1), y2: y, class: 'comet-tail' }));
      if (!f.isNew) s.appendChild(svg('circle', { cx: x0, cy: y, r: 1.8, class: 'comet-from' }));
      s.appendChild(svg('circle', { cx: x1, cy: y, r: 3.2, class: 'comet-head' }));
    });
    return s;
  },
  // 10 timeline: a river with one stone per era
  timeline(m) {
    if (!m.length) return null;
    const s = root('m-timeline');
    const pts = []; for (let x = 6; x <= 194; x += 4) pts.push(`${x} ${(55 + 20 * Math.sin(x / 19)).toFixed(1)}`);
    s.appendChild(svg('path', { d: 'M ' + pts.join(' L '), class: 'river-path' }));
    for (const t of m) { const x = 6 + t.x * 188; s.appendChild(svg('circle', { cx: x, cy: 55 + 20 * Math.sin(x / 19), r: 3.4, class: 'stone' })); }
    return s;
  },
  // 11 the notebook: a bar per kind of entry
  log(m) {
    if (!m.length) return null;
    const s = root('m-log'), w = 188 / m.length;
    m.forEach((k, i) => { const h = 8 + 90 * k.h; s.appendChild(svg('rect', { x: 6 + i * w + 2, y: H - 4 - h, width: Math.max(2, w - 4), height: h, rx: 2, fill: k.color, class: 'logbar' })); });
    return s;
  },
  // 11 compare: one dot per setup, rightward is a larger recorded context, upward is faster
  compare(m) {
    if (!m.length) return null;
    const s = root('m-compare');
    m.forEach((p) => s.appendChild(svg('circle', { cx: (12 + (Number(p.x) || 0) * 176).toFixed(1), cy: (100 - (Number(p.y) || 0) * 86).toFixed(1), r: 2.2, class: 'cmp-dot' })));
    return s;
  },
  // 12 caveats: warning rings, one per caveat
  caveats(m) {
    if (!m.length) return null;
    const s = root('m-caveats'), cx = 100, cy = 98;
    m.forEach((c, i) => {
      const r = 16 + i * (76 / Math.max(1, m.length)), span = Math.PI * (0.45 + 0.5 * c.len), a0 = -Math.PI / 2 - span / 2, a1 = -Math.PI / 2 + span / 2;
      s.appendChild(svg('path', { d: `M ${polar(cx, cy, r, a0)} A ${r} ${r} 0 ${span > Math.PI ? 1 : 0} 1 ${polar(cx, cy, r, a1)}`, class: 'warn-ring', 'stroke-opacity': (0.9 - 0.12 * i).toFixed(2) }));
    });
    s.appendChild(svg('circle', { cx, cy, r: 4, class: 'warn-core' }));
    return s;
  },
};

// Returns an SVG for the chapter, or null when there is nothing to draw.
export function chapterMotif(key, m) {
  const fn = DRAW[key];
  if (!fn || m == null) return null;
  return fn(m);
}
export const MOTIF_KEYS = Object.keys(DRAW);
