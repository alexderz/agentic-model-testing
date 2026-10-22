// The hero orrery: the GPU is the sun, each model family an orbit band, each model a planet.
// Orbit speed = best tok/s seen for that model, size = how often it ran, halo = passed test 2.
import { el, svg, clear, familyChip, onReducedMotion } from './dom.js';
import { heroPlanets, heroLayout, fmt } from './data.js';

export function renderHero(data, mount, caption, legend) {
  clear(mount); clear(legend);
  const { planets, bands } = heroLayout(heroPlanets(data), { rMin: 72, rMax: 318 });
  const S = 340;
  const root = svg('svg', { class: 'orrery', viewBox: `${-S} ${-S} ${2 * S} ${2 * S}`, role: 'group', 'aria-label': `Orrery of ${planets.length} models in ${bands.length} families orbiting one GPU` });
  const defs = svg('defs', {});
  const grad = svg('radialGradient', { id: 'sun-grad' });
  grad.append(svg('stop', { offset: '0%', 'stop-color': '#fff6d6' }), svg('stop', { offset: '45%', 'stop-color': '#f2c14e' }), svg('stop', { offset: '100%', 'stop-color': '#b8780a' }));
  const glow = svg('radialGradient', { id: 'sun-glow' });
  glow.append(svg('stop', { offset: '0%', 'stop-color': '#f2c14e', 'stop-opacity': '0.55' }), svg('stop', { offset: '100%', 'stop-color': '#f2c14e', 'stop-opacity': '0' }));
  defs.append(grad, glow);
  root.appendChild(defs);

  // bands
  bands.forEach((b, i) => {
    root.appendChild(svg('circle', { r: b.r1, class: 'band', style: { '--c': b.color } }));
    // band name on an arc; every label rides the upper arc so it always reads upright; offsets alternate so neighbours do not stack
    const id = `band-arc-${i}`;
    const r = b.r1 - 4;
    defs.appendChild(svg('path', { id, d: `M ${-r} 0 A ${r} ${r} 0 0 1 ${r} 0`, fill: 'none' }));
    const t = svg('text', { class: 'band-label' });
    const tp = svg('textPath', { href: `#${id}`, startOffset: ['50%', '22%', '78%'][i % 3], 'text-anchor': 'middle' }, b.family);
    t.appendChild(tp);
    root.appendChild(t);
  });
  // sun
  root.appendChild(svg('circle', { r: 110, fill: 'url(#sun-glow)', class: 'sun-glow' }));
  root.appendChild(svg('circle', { r: 30, fill: 'url(#sun-grad)', class: 'sun' }));
  const gpu = (data.hardware && data.hardware.gpu) || 'one GPU';
  root.appendChild(svg('text', { y: 50, class: 'sun-label', 'text-anchor': 'middle' }, gpu.split(',')[0]));

  // planets
  const groups = [];
  const motion = !onReducedMotion();
  for (const p of planets) {
    root.appendChild(svg('circle', { r: p.r, class: 'orbit' }));
    const g = svg('g', { class: `planet${p.passed2 ? ' passed' : ''}${p.uncensored ? ' unc' : ''}`, tabindex: 0, role: 'img', style: { '--c': p.color }, 'data-family': p.family, transform: `rotate(${p.angle0.toFixed(1)})`,
      'aria-label': describe(p) });
    g.appendChild(svg('title', {}, describe(p)));
    if (p.passed2) g.appendChild(svg('circle', { cx: p.r, cy: 0, r: p.size + 3.2, class: 'halo' }));
    g.appendChild(svg('circle', { cx: p.r, cy: 0, r: p.size, class: 'body' }));
    if (p.uncensored) g.appendChild(svg('circle', { cx: p.r, cy: 0, r: p.size + 1.6, class: 'unc-ring' }));
    g.appendChild(svg('circle', { cx: p.r, cy: 0, r: Math.max(9, p.size + 5), class: 'hit' }));
    const show = () => { caption.textContent = describe(p); };
    g.addEventListener('mouseenter', show); g.addEventListener('focus', show);
    root.appendChild(g);
    groups.push({ g, p });
  }
  mount.appendChild(root);
  caption.textContent = planets.length ? 'Hover or tab onto a planet to read its card line.' : 'No models yet: the orrery fills in as runs arrive.';

  // legend: one chip per family; click to spotlight
  let active = null;
  const spot = (fam) => {
    active = active === fam ? null : fam;
    for (const { g, p } of groups) g.classList.toggle('dim', active != null && p.family !== active);
    legend.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.family === active)));
  };
  for (const b of bands) {
    const n = planets.filter((p) => p.family === b.family).length;
    const btn = el('button', { type: 'button', class: 'legend-btn', 'data-family': b.family, 'aria-pressed': 'false' }, familyChip(b.family, b.color), el('small', {}, ` ${n}`));
    btn.addEventListener('click', () => spot(b.family));
    legend.appendChild(el('li', {}, btn));
  }

  // motion
  if (motion && groups.length) {
    let last = performance.now();
    let running = true;
    const tick = (now) => {
      if (!running) return;
      const dt = Math.min(0.1, (now - last) / 1000); last = now;
      for (const { g, p } of groups) {
        p.angle0 = (p.angle0 + (360 / p.period) * dt) % 360;
        g.setAttribute('transform', `rotate(${p.angle0.toFixed(2)})`);
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    // pause when off-screen or hidden
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((es) => { for (const e of es) { const was = running; running = e.isIntersecting; if (running && !was) { last = performance.now(); requestAnimationFrame(tick); } } }).observe(mount);
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden && running) last = performance.now(); });
  }
  return { planets, bands };
}
function describe(p) {
  const bits = [p.label, p.family];
  bits.push(p.bestTps != null ? `best ${fmt(p.bestTps, 1)} tok/s` : 'no speed recorded');
  bits.push(p.appearances === 1 ? '1 appearance' : `${p.appearances} appearances`);
  if (p.passed2) bits.push('passed test 2');
  if (p.uncensored) bits.push('uncensored');
  return bits.join(' · ');
}
