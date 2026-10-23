// Hand-built SVG/HTML charts. Each takes already-derived rows and a width in CSS px.
import { el, svg, verdictChip, VERDICT_GLYPH } from './dom.js';
import { fmt, fmtMinutes, logScale, logTicks, shortLabel, OTHER_COLOR } from './data.js';

// "n/m" when the data gives a scale for that test, else just "n".
export const ofMax = (n, max) => (n == null ? '–' : max != null ? `${fmt(n, 0)}/${fmt(max, 0)}` : fmt(n, 0));

// Speed ladder: one thin bar per run on a log scale, colour = verdict (status), glyph + text carry it too.
export function speedLadder(rows, { limit = 40 } = {}) {
  const scale = logScale(rows.map((r) => r.tps));
  const ticks = logTicks(scale);
  const wrap = el('div', { class: 'ladder' });
  const axis = el('div', { class: 'ladder-axis', 'aria-hidden': 'true' });
  for (const t of ticks) {
    const tick = el('span', { class: 'tick' }, `${fmt(t, 0)}`);
    tick.style.left = `${scale.pos(t) * 100}%`;
    axis.appendChild(tick);
  }
  // the verdict key rides the head, in the colours the bars use
  const key = el('span', { class: 'vkey' }, ...['pass', 'partial', 'fail'].map((v) => el('span', { class: `v-${v}` }, el('span', { 'aria-hidden': 'true' }, VERDICT_GLYPH[v]), ` ${v}`)));
  wrap.appendChild(el('div', { class: 'ladder-head' }, key, axis, el('span', { class: 'num' }, 'tok/s')));
  const list = el('ol', { class: 'ladder-rows' });
  rows.slice(0, limit).forEach((r) => {
    const pct = Math.max(0.6, scale.pos(r.tps) * 100);
    const bar = el('span', { class: `bar v-${r.verdict}` });
    bar.style.width = `${pct}%`;
    const cap = el('span', { class: `cap v-${r.verdict}`, 'aria-hidden': 'true' }, VERDICT_GLYPH[r.verdict] || '◌');
    cap.style.left = `${pct}%`;
    const title = `${r.modelLabel} · test ${r.test}${r.flavor ? ` (${r.flavor})` : ''} · ${r.verdict} · ${fmt(r.tps, 1)} tok/s · ${fmtMinutes(r.minutes)}`;
    list.appendChild(el('li', { class: 'ladder-row', title },
      el('span', { class: 'lbl' }, el('i', { class: 'fam-dot', 'aria-hidden': 'true', style: { '--c': r.color } }), el('b', {}, r.short), el('small', {}, ` t${r.test}${r.flavor ? '·' + r.flavor : ''}${r.uncensored ? ' · unc' : ''}`)),
      el('span', { class: 'track' }, bar, cap),
      el('span', { class: 'num' }, fmt(r.tps, 1), el('span', { class: 'sr' }, ` tok/s, ${r.verdict}`))));
  });
  wrap.appendChild(list);
  if (!rows.length) wrap.appendChild(el('p', { class: 'empty' }, 'No runs match these filters.'));
  return wrap;
}

// Struggle strip: test-2 runs by compiler errors per 1,000 lines (log), one lane per verdict.
export function struggleStrip(rows, width) {
  const lanes = ['pass', 'partial', 'fail'].filter((v) => rows.some((r) => r.verdict === v));
  for (const r of rows) if (!lanes.includes(r.verdict)) lanes.push(r.verdict);
  const W = Math.max(320, width || 720), left = 78, right = 16, laneH = 58, top = 34, H = top + lanes.length * laneH + 34;
  const vals = rows.map((r) => Math.max(0.3, r.struggle.errors_per_kloc));
  const scale = logScale(vals.map((v) => (v <= 0 ? 0.3 : v)), 1.3);
  const x = (v) => left + scale.pos(Math.max(0.3, v)) * (W - left - right);
  const root = svg('svg', { class: 'strip', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': `Compiler errors per thousand lines for ${rows.length} test-2 runs, by verdict` });
  for (const t of logTicks(scale)) {
    root.appendChild(svg('line', { x1: x(t), x2: x(t), y1: top - 6, y2: H - 30, class: 'grid' }));
    root.appendChild(svg('text', { x: x(t), y: H - 12, class: 'axis', 'text-anchor': 'middle' }, fmt(t, 0)));
  }
  root.appendChild(svg('text', { x: W - right, y: 12, class: 'axis dim', 'text-anchor': 'end' }, 'compiler errors per 1,000 lines →'));
  lanes.forEach((lane, li) => {
    const cy = top + li * laneH + laneH / 2;
    root.appendChild(svg('line', { x1: left, x2: W - right, y1: cy, y2: cy, class: 'lane' }));
    root.appendChild(svg('text', { x: left - 10, y: cy + 4, class: `axis v-${lane}`, 'text-anchor': 'end' }, `${VERDICT_GLYPH[lane] || '◌'} ${lane}`));
    // simple beeswarm: sort by x, push overlapping dots up/down
    const pts = rows.filter((r) => r.verdict === lane).map((r) => ({ r, x: x(r.struggle.errors_per_kloc), y: cy })).sort((a, b) => a.x - b.x);
    const placed = [];
    for (const p of pts) {
      let k = 0;
      for (;;) {
        const dy = (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 9;
        if (!placed.some((q) => Math.abs(q.x - p.x) < 9 && Math.abs(q.y - (cy + dy)) < 9) || k > 10) { p.y = cy + dy; break; }
        k++;
      }
      placed.push(p);
      const g = svg('g', { class: 'dot-g', tabindex: 0 });
      g.appendChild(svg('title', {}, `${p.r.modelLabel} · ${fmt(p.r.struggle.errors_per_kloc, 1)} errors/kloc · ${fmt(p.r.struggle.failed_compiles, 0)} of ${fmt(p.r.struggle.compiles, 0)} builds failed · ${fmt(p.r.struggle.loc, 0)} lines · ${lane}`));
      g.appendChild(svg('circle', { cx: p.x, cy: p.y, r: 4.5, class: `dot v-${lane}` }));
      root.appendChild(g);
    }
  });
  return root;
}

// One shot against agent: one row per model, a hollow mark for the best one-shot score and a filled mark (family colour)
// for the agent score on a 0..max axis, joined by a line that is green when the agent did better. Numbers sit at the end
// of every row, so the chart needs no legend beyond the two glyphs in its head.
export function pairDumbbell(panel, width) {
  const W = Math.max(320, width || 560), left = Math.min(230, Math.max(120, Math.round(W * 0.38))), right = 72, rowH = 24, top = 30, bottom = 24;
  const rows = panel.rows;
  const H = top + (rows.length + 1) * rowH + bottom;
  const x = (v) => left + (Math.max(0, Math.min(panel.max, v)) / panel.max) * (W - left - right);
  const root = svg('svg', { class: 'pairs', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img',
    'aria-label': `${panel.baseLabel} one-shot against ${panel.label} for ${rows.length} models, scores out of ${fmt(panel.max, 0)}: ` + rows.map((r) => `${r.short} ${r.oneshot == null ? 'no one-shot' : fmt(r.oneshot)} to ${r.agent == null ? 'not graded' : fmt(r.agent)}`).join('; ') });
  const ticks = [0, panel.max / 2, panel.max];
  for (const t of ticks) {
    root.appendChild(svg('line', { x1: x(t), x2: x(t), y1: top - 4, y2: H - bottom + 4, class: 'grid' }));
    root.appendChild(svg('text', { x: x(t), y: H - 6, class: 'axis', 'text-anchor': 'middle' }, fmt(t, 0)));
  }
  root.appendChild(svg('text', { x: left - 10, y: 14, class: 'axis dim', 'text-anchor': 'end' }, 'model'));
  const head = svg('text', { x: W - 6, y: 14, class: 'axis dim', 'text-anchor': 'end' });
  head.append(svg('tspan', { class: 'one' }, '○'), svg('tspan', {}, ' one-shot → '), svg('tspan', { class: 'agent' }, '●'), svg('tspan', {}, ' agent'));
  root.appendChild(head);
  const draw = (r, i, cls = '') => {
    const cy = top + i * rowH + rowH / 2;
    const g = svg('g', { class: `pair ${cls}`, tabindex: 0 });
    g.appendChild(svg('title', {}, `${r.label}: one-shot ${r.oneshot == null ? 'none' : fmt(r.oneshot) + (r.oneshotN > 1 ? ` (best of ${r.oneshotN})` : '')} → agent ${r.agent == null ? 'not graded' : fmt(r.agent)}${r.agentN > 1 ? ` (best of ${r.agentN})` : ''}`));
    const maxChars = Math.max(12, Math.floor((left - 14) / 7.2));
    const name = r.short.length > maxChars ? r.short.slice(0, maxChars - 1).trimEnd() + '…' : r.short;
    g.appendChild(svg('text', { x: left - 10, y: cy + 4, class: 'axis lbl', 'text-anchor': 'end' }, name));
    if (r.oneshot != null && r.agent != null) g.appendChild(svg('line', { x1: x(r.oneshot), x2: x(r.agent), y1: cy, y2: cy, class: `link ${r.agent > r.oneshot ? 'up' : r.agent < r.oneshot ? 'down' : 'flat'}` }));
    if (r.oneshot != null) g.appendChild(svg('circle', { cx: x(r.oneshot), cy, r: 5, class: 'one' }));
    if (r.agent != null) g.appendChild(svg('circle', { cx: x(r.agent), cy, r: 6, class: 'agent', style: { '--c': r.color } }));
    g.appendChild(svg('text', { x: W - right + 8, y: cy + 4, class: 'axis num' }, `${r.oneshot == null ? '–' : fmt(r.oneshot)} → ${r.agent == null ? '–' : fmt(r.agent)}`));
    root.appendChild(g);
  };
  rows.forEach((r, i) => draw(r, i));
  if (rows.length) {
    root.appendChild(svg('line', { x1: 8, x2: W - 8, y1: top + rows.length * rowH + 1, y2: top + rows.length * rowH + 1, class: 'lane' }));
    draw({ label: `mean of ${rows.length}`, short: 'mean', oneshot: panel.meanOneshot, agent: panel.meanAgent, color: '#f2c14e', oneshotN: 1, agentN: 1 }, rows.length, 'mean');
  }
  return root;
}

// Dumbbell for the A/B speed probes: decode tok/s per engine, same model on one line. Colours come per engine value.
export function abDumbbell(group, max, colors) {
  const W = 100;
  const wrap = el('div', { class: 'ab-row' });
  const ok = group.rows.filter((r) => r.decode != null);
  const track = el('div', { class: 'ab-track' });
  if (ok.length >= 2) {
    const xs = ok.map((r) => (r.decode / (max || 1)) * W);
    const line = el('span', { class: 'ab-line' });
    line.style.left = `${Math.min(...xs)}%`; line.style.width = `${Math.max(...xs) - Math.min(...xs)}%`;
    track.appendChild(line);
  }
  ok.forEach((r) => {
    const dot = el('span', { class: 'ab-dot', style: { '--c': (colors && colors.get(r.engine)) || OTHER_COLOR }, title: `${group.label} · ${r.engine} · ${r.variant} · decode ${fmt(r.decode, 1)} tok/s${r.quote != null ? ` · quote ${fmt(r.quote, 1)}` : ''}${r.prefill != null ? ` · prefill ${fmt(r.prefill, 0)}` : ''}${r.vram != null ? ` · ${fmt(r.vram, 0)} MiB` : ''}`, tabindex: 0 });
    dot.style.left = `${(r.decode / (max || 1)) * W}%`;
    track.appendChild(dot);
  });
  wrap.append(el('span', { class: 'lbl' }, el('b', {}, group.short), group.gain ? el('small', { class: 'gain' }, ` ×${fmt(group.gain, 2)}`) : null), track,
    el('span', { class: 'num' }, group.best != null ? fmt(group.best, 1) : 'failed'));
  return wrap;
}

// Petal score: n arcs of 0..pointMax points around a ring, with the total in the middle.
export function petalScore(card) {
  const pts = card.points.length ? card.points : [];
  const pmax = card.pointMax > 0 ? card.pointMax : 1;
  const n = pts.length || 5, R = 26, r0 = 12, cx = 32, cy = 32;
  const root = svg('svg', { class: 'petals', viewBox: '0 0 64 64', width: 64, height: 64, role: 'img', 'aria-label': `Score ${fmt(card.total)} of ${fmt(card.max)}${pts.length ? ': ' + pts.map((p) => `${p.name} ${fmt(p.value)}`).join(', ') : ''}` });
  const gap = 0.07;
  pts.forEach((p, i) => {
    const a0 = (i / n) * Math.PI * 2 - Math.PI / 2 + gap, a1 = ((i + 1) / n) * Math.PI * 2 - Math.PI / 2 - gap;
    const frac = Math.max(0, Math.min(1, (p.value == null ? 0 : p.value) / pmax));
    const rr = r0 + (R - r0) * frac;
    root.appendChild(svg('path', { d: arcPath(cx, cy, r0, R, a0, a1), class: 'petal-bg' }));
    if (frac > 0) root.appendChild(svg('path', { d: arcPath(cx, cy, r0, rr, a0, a1), class: `petal lvl-${frac >= 1 ? 2 : 1}` }));
  });
  root.appendChild(svg('text', { x: cx, y: cy + 4, class: 'petal-total', 'text-anchor': 'middle' }, fmt(card.total)));
  return root;
}
function arcPath(cx, cy, r0, r1, a0, a1) {
  const p = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M ${p(r0, a0)} L ${p(r1, a0)} A ${r1} ${r1} 0 ${large} 1 ${p(r1, a1)} L ${p(r0, a1)} A ${r0} ${r0} 0 ${large} 0 ${p(r0, a0)} Z`;
}

// Pips: n of m filled squares (facts found, rubric points).
export function pips(got, of, cls = '') {
  const m = of != null ? of : Math.max(got || 0, 1);
  const wrap = el('span', { class: `pips ${cls}`, role: 'img', 'aria-label': `${fmt(got, 0)} of ${fmt(m, 0)}` });
  for (let i = 0; i < Math.min(m, 40); i++) wrap.appendChild(el('i', { class: got != null && i < got ? 'on' : '' }));
  return wrap;
}

// Before/after bars for a finding metric. Fractional values keep one decimal.
export function beforeAfter(m) {
  const row = el('div', { class: 'ba' });
  const bars = el('div', { class: 'ba-bars' });
  const b = el('span', { class: 'ba-bar before' }); b.style.width = `${m.beforePct == null ? 0 : m.beforePct}%`;
  const a = el('span', { class: 'ba-bar after' }); a.style.width = `${m.afterPct == null ? 0 : m.afterPct}%`;
  bars.append(el('span', { class: 'ba-track' }, b), el('span', { class: 'ba-track' }, a));
  row.append(el('span', { class: 'ba-label' }, m.label), bars,
    el('span', { class: 'ba-num' }, m.before == null ? el('small', {}, 'new ') : el('small', {}, `${fmt(m.before, 1)} → `), el('b', {}, fmt(m.after, 1)), el('small', {}, ` ${m.unit}`),
      m.gain ? el('span', { class: 'gain' }, ` ×${fmt(m.gain, 1)}`) : null));
  return row;
}
// The typographic moment: the lead metric of a finding as big numerals, before → after, with the gain.
export function bigNumeral(m) {
  return el('div', { class: 'big-num', role: 'img', 'aria-label': `${m.label}: ${m.before == null ? 'new' : fmt(m.before, 1)} to ${fmt(m.after, 1)} ${m.unit}${m.gain ? `, ${fmt(m.gain, 1)} times` : ''}` },
    el('span', { class: 'lbl', 'aria-hidden': 'true' }, m.label),
    el('span', { class: 'row', 'aria-hidden': 'true' },
      m.before == null ? el('span', { class: 'from new' }, 'new') : el('span', { class: 'from' }, fmt(m.before, 1)),
      el('span', { class: 'arrow' }, '→'),
      el('span', { class: 'to' }, fmt(m.after, 1)),
      el('span', { class: 'unit' }, m.unit),
      m.gain ? el('span', { class: 'gainbadge' }, `×${fmt(m.gain, 1)}`) : null));
}

// Small inline run summary used in pick cards.
export function runLine(r) {
  const bits = [`test ${r.test}${r.flavor ? ' · ' + r.flavor : ''}`, fmt(r.tps, 1) + ' tok/s', fmtMinutes(r.minutes)];
  if (r.checks != null) bits.push(`${ofMax(r.checks, r.checksMax)} checks`);
  if (r.tests_pass != null) bits.push(`${fmt(r.tests_pass, 0)} tests`);
  return el('li', { class: 'runline' }, verdictChip(r.verdict), ' ', bits.join(' · '));
}
export { shortLabel };
