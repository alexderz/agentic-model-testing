// The live viewer: a full-viewport <dialog> that runs one model-written one-shot piece (a pagoda page or an orrery
// SVG) inside a sandboxed iframe, next to the facts about that reply. Rules, in order of importance:
//   - the iframe is created with sandbox="allow-scripts" only (never allow-same-origin, -top-navigation, -popups,
//     -forms or -modals), referrerpolicy="no-referrer", and its src is set only when the viewer opens;
//   - on close or when stepping to another piece the src is set to about:blank and the element removed, so at most
//     one WebGL page ever runs at a time;
//   - the src must have passed data.js isLiveUrl (dom.js refuses anything else on an <iframe>);
//   - focus is trapped inside the dialog, Esc and the close button close it, and focus returns to the card.
import { isLiveUrl, fmt } from './data.js';
import { el, clear, familyChip, kindChip } from './dom.js';
import { petalScore } from './charts.js';

// the iframe carries tabindex="-1": the pieces are animations, and keeping focus out of the opaque frame keeps Esc and the arrow keys working
const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
const SVG_ROOT_RE = /<svg\b[^>]*>/i;
let dlg = null;       // the one dialog element, built on first use
let state = null;     // { cards, index, returnTo } while open
let frame = null;     // the running iframe, or null
let stageObserver = null;

// Public: open the viewer on cards[index]. `cards` is the gallery's current filtered order; only cards with a live
// path are stepped through. `returnTo` gets focus back on close.
export function openViewer(cards, index, returnTo) {
  const playable = cards.filter((c) => c && c.live && isLiveUrl(c.live));
  const start = Math.max(0, playable.indexOf(cards[index]));
  if (!playable.length) return;
  state = { cards: playable, index: start, returnTo };
  build();
  document.body.classList.add('viewer-open');
  if (!dlg.open) dlg.showModal();
  show();
}

function build() {
  if (dlg) return;
  dlg = el('dialog', { class: 'viewer', 'aria-labelledby': 'viewer-title', 'aria-describedby': 'viewer-unedited' });
  const closeBtn = el('button', { type: 'button', class: 'vclose', 'aria-label': 'Close the viewer' }, '×');
  closeBtn.addEventListener('click', closeViewer);
  const prev = el('button', { type: 'button', class: 'vnav prev', 'aria-label': 'Previous piece' }, '‹');
  const next = el('button', { type: 'button', class: 'vnav next', 'aria-label': 'Next piece' }, '›');
  prev.addEventListener('click', () => step(-1));
  next.addEventListener('click', () => step(1));
  const stage = el('div', { class: 'stage', 'data-state': 'idle' }, el('div', { class: 'stage-box' }));
  const side = el('aside', { class: 'vside' });
  dlg.append(
    el('header', { class: 'vhead' }, el('span', { class: 'kicker' }, 'Live piece'), el('h2', { id: 'viewer-title' }), el('span', { class: 'vpos', 'aria-live': 'polite' }), closeBtn),
    el('div', { class: 'vmain' }, stage, side),
    el('footer', { class: 'vfoot' }, prev, el('span', { class: 'vhint' }, 'arrow keys step, Esc closes'), next),
  );
  // Esc fires `cancel` on a modal dialog; route it through closeViewer so the iframe is torn down first.
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); closeViewer(); });
  dlg.addEventListener('close', teardownFrame); // safety net for any other close path
  dlg.addEventListener('keydown', onKey);
  dlg.addEventListener('click', (e) => { if (e.target === dlg) closeViewer(); }); // backdrop click
  if ('ResizeObserver' in window) { stageObserver = new ResizeObserver(() => fitFrame()); stageObserver.observe(stage); }
  document.body.appendChild(dlg);
}

function onKey(e) {
  if (e.key === 'ArrowRight') { e.preventDefault(); step(1); return; }
  if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); return; }
  if (e.key !== 'Tab') return;
  // focus trap: Tab from the last focusable wraps to the first and Shift+Tab from the first wraps to the last
  const nodes = [...dlg.querySelectorAll(FOCUSABLE)].filter((n) => n.getClientRects().length > 0);
  if (!nodes.length) return;
  const first = nodes[0], last = nodes[nodes.length - 1];
  const active = document.activeElement;
  if (e.shiftKey && (active === first || active === dlg)) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
}

function step(d) {
  if (!state || state.cards.length < 2) return;
  const n = state.cards.length;
  state.index = (state.index + d + n) % n;
  show();
}

// Render the current card: tear the old iframe down, fill the sidebar, then start the new iframe.
function show() {
  const c = state.cards[state.index];
  teardownFrame();
  const stage = dlg.querySelector('.stage'), box = stage.querySelector('.stage-box');
  clear(box);
  dlg.querySelector('#viewer-title').textContent = `${c.short} · ${c.setLabel || set0(c.live)}`;
  dlg.querySelector('.vpos').textContent = `${state.index + 1} of ${state.cards.length}`;
  fillSide(dlg.querySelector('.vside'), c);
  dlg.querySelectorAll('.vnav').forEach((b) => { b.disabled = state.cards.length < 2; });
  stage.dataset.state = 'loading';
  stage.dataset.kind = /\.svg$/.test(c.live) ? 'svg' : 'page';
  // the iframe: sandbox and referrer policy first, src last (dom.js only lets a live path through on an iframe)
  const f = el('iframe', { sandbox: 'allow-scripts', referrerpolicy: 'no-referrer', loading: 'lazy', title: `${c.setLabel || set0(c.live)} by ${c.short}: the model's own output, running`, tabindex: '-1' });
  f.addEventListener('load', () => { if (frame === f) stage.dataset.state = 'running'; });
  frame = f;
  f.fit = { mode: 'fill' };
  box.appendChild(f);
  if (stage.dataset.kind === 'svg') measureSvg(c.live, f);
  fitFrame();
  f.setAttribute('src', c.live);
  if (!dlg.contains(document.activeElement) || document.activeElement === dlg) dlg.querySelector('.vclose').focus();
}

const set0 = (live) => String(live).split('/')[1] || '';
function fillSide(side, c) {
  clear(side);
  const pmax = c.pointMax > 0 ? c.pointMax : 1;
  side.append(
    el('div', { class: 'vmeta' }, familyChip(c.family, c.color), kindChip(`test ${c.test}`, c.kind === 'agentic' ? 'agentic' : ''), c.uncensored ? kindChip('uncensored') : null, el('span', { class: 'mono case' }, c.case)),
    el('div', { class: 'vscore' }, petalScore(c), el('div', { class: 'pts' },
      ...(c.points.length ? c.points.map((p) => { const v = p.value || 0; return el('span', { class: v <= 0 ? 'l0' : v >= pmax ? 'l2' : 'l1' }, el('b', {}, p.name), ` ${fmt(p.value)}`); }) : [el('span', { class: 'l0' }, 'not graded')]),
      el('span', { class: 'total' }, `${fmt(c.total)} of ${fmt(c.max)}`))),
    el('dl', { class: 'vnums' },
      el('div', {}, el('dt', {}, 'speed'), el('dd', {}, fmt(c.tok_s, 1), el('small', {}, ' tok/s'))),
      el('div', {}, el('dt', {}, 'reply'), el('dd', {}, fmt(c.tokens, 0), el('small', {}, ' tokens'))),
      c.wall_s != null ? el('div', {}, el('dt', {}, 'wall'), el('dd', {}, fmt(c.wall_s, 0), el('small', {}, ' s'))) : null,
      /length|cap/i.test(c.finish) ? el('div', { class: 'cut' }, el('dt', {}, 'finish'), el('dd', {}, c.finish === 'length' ? 'hit the cap' : c.finish)) : null),
    c.note ? el('p', { class: 'vnote' }, el('span', { class: 'k' }, 'grader'), c.note) : el('p', { class: 'vnote empty' }, 'No grader note.'),
    c.frames.length ? el('div', { class: 'vstrip', role: 'group', 'aria-label': 'Offline render frames' },
      ...c.frames.map((fr) => el('figure', {}, el('img', { src: fr.url, alt: `${c.alt}, offline frame at ${fr.ms == null ? '?' : fmt(fr.ms, 0)} ms`, loading: 'lazy', decoding: 'async' }), el('figcaption', {}, fr.ms == null ? 'frame' : fr.ms >= 1000 ? `${(fr.ms / 1000).toFixed(fr.ms % 1000 ? 1 : 0)} s` : `${fr.ms} ms`)))) : null,
    el('p', { class: 'vunedited', id: 'viewer-unedited' }, 'Unedited model output, byte for byte, in a sandboxed frame.'),
  );
}

// Orrery SVGs come in three shapes: fixed width/height (laid out at that size, then scaled to fit), viewBox only
// (they scale themselves, so the iframe just takes the right aspect), or neither (fill the stage). Reading the
// root tag's attributes needs the file's text; it is fetched same-origin and only ever matched with a regex.
async function measureSvg(url, f) {
  let fit = { mode: 'fill' };
  try {
    const ctrl = 'AbortController' in window ? new AbortController() : null;
    const t = ctrl ? setTimeout(() => ctrl.abort(), 4000) : null;
    const res = await fetch(url, { signal: ctrl ? ctrl.signal : undefined, credentials: 'omit' });
    if (t) clearTimeout(t);
    const head = (await res.text()).slice(0, 4000);
    const m = head.match(SVG_ROOT_RE);
    if (m) {
      const attr = (n) => { const a = m[0].match(new RegExp(`\\s${n}\\s*=\\s*"([^"]*)"`, 'i')) || m[0].match(new RegExp(`\\s${n}\\s*=\\s*'([^']*)'`, 'i')); return a ? a[1].trim() : ''; };
      const px = (v) => (/^\d+(\.\d+)?(px)?$/.test(v) ? parseFloat(v) : null);
      const w = px(attr('width')), h = px(attr('height'));
      const vb = attr('viewBox').split(/[\s,]+/).map(Number);
      if (w > 0 && h > 0) fit = { mode: 'fixed', w, h };
      else if (vb.length === 4 && vb.every(Number.isFinite) && vb[2] > 0 && vb[3] > 0) fit = { mode: 'aspect', w: vb[2], h: vb[3] };
    }
  } catch { /* unreadable: fill the stage */ }
  if (frame === f) { f.fit = fit; fitFrame(); }
}

// Size the iframe to the stage according to its fit mode.
function fitFrame() {
  if (!frame || !dlg || !dlg.open) return;
  const stage = dlg.querySelector('.stage'), box = stage.querySelector('.stage-box');
  const W = stage.clientWidth, H = stage.clientHeight;
  const fit = frame.fit || { mode: 'fill' };
  const pad = 0;
  if (fit.mode === 'fill' || !(W > 0 && H > 0)) {
    box.style.width = '100%'; box.style.height = '100%'; frame.style.width = '100%'; frame.style.height = '100%'; frame.style.transform = ''; return;
  }
  const k = Math.min((W - pad) / fit.w, (H - pad) / fit.h);
  if (fit.mode === 'aspect') {
    box.style.width = `${Math.floor(fit.w * k)}px`; box.style.height = `${Math.floor(fit.h * k)}px`;
    frame.style.width = '100%'; frame.style.height = '100%'; frame.style.transform = '';
  } else { // fixed: the document is laid out at its own size and scaled down (never up) with a transform
    const s = Math.min(1, k);
    box.style.width = `${Math.floor(fit.w * s)}px`; box.style.height = `${Math.floor(fit.h * s)}px`;
    frame.style.width = `${fit.w}px`; frame.style.height = `${fit.h}px`; frame.style.transform = `scale(${s})`;
  }
}

// Stop the running piece: blank it, then remove it from the document.
function teardownFrame() {
  if (!frame) return;
  const f = frame; frame = null;
  f.setAttribute('src', 'about:blank');
  if (f.parentNode) f.parentNode.removeChild(f);
  const stage = dlg && dlg.querySelector('.stage');
  if (stage) stage.dataset.state = 'idle';
}

export function closeViewer() {
  if (!dlg || !state) return;
  const { cards, index, returnTo } = state;
  teardownFrame();
  state = null;
  if (dlg.open) dlg.close();
  document.body.classList.remove('viewer-open');
  // focus goes back to the card that is on screen: the one we ended on if its control is still in the page, else
  // the control that opened the viewer
  const current = cards[index] && document.querySelector(`.shot[data-case="${CSS.escape(cards[index].case)}"] .play`);
  const target = (current && current.isConnected ? current : null) || (returnTo && returnTo.isConnected ? returnTo : null);
  if (target) target.focus();
}
