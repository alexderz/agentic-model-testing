// Tiny DOM builder. Everything is createElement + textContent; attributes go through setAttribute
// after validation. No HTML-string insertion anywhere.
import { isFrameUrl, isLiveUrl, isRepoUrl, OTHER_COLOR } from './data.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'action', 'formaction', 'poster']);
// Colours reach CSS only through the --c custom property; anything but a plain hex/hsl token is dropped.
const COLOR_RE = /^(#[0-9a-f]{3,8}|hsl\(\d{1,3} \d{1,3}% \d{1,3}%\)|rgba?\([\d., %]+\))$/i;

function setAttrs(node, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') { node.setAttribute('class', String(v)); continue; }
    if (k === 'text') { node.textContent = String(v); continue; }
    if (k === 'style' && typeof v === 'object') {
      for (const [p, val] of Object.entries(v)) {
        if (val == null) continue;
        if (p.startsWith('--')) { if (COLOR_RE.test(String(val))) node.style.setProperty(p, String(val)); }
        else node.style[p] = val;
      }
      continue;
    }
    if (k.startsWith('on') || k === 'style') continue; // no inline handlers or style strings
    if (URL_ATTRS.has(k)) {
      const s = String(v);
      // src: frames for anything, a live piece only on an <iframe> (viewer.js adds the sandbox before the src)
      if (k === 'src' && !(node.tagName === 'IFRAME' ? isLiveUrl(s) : isFrameUrl(s))) continue;
      if (k === 'href' && !(isRepoUrl(s) || /^#[A-Za-z0-9_-]+$/.test(s))) continue;
      if (k !== 'src' && k !== 'href') continue;
    }
    node.setAttribute(k, v === true ? '' : String(v));
  }
  return node;
}
function append(node, children) {
  for (const c of [].concat(children)) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) { append(node, c); continue; }
    node.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  }
  return node;
}
export function el(tag, attrs, ...children) {
  return append(setAttrs(document.createElement(tag), attrs), children);
}
export function svg(tag, attrs, ...children) {
  return append(setAttrs(document.createElementNS(SVG_NS, tag), attrs), children);
}
export function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); return node; }
export const $ = (id) => document.getElementById(id);
export function frag(children) { return append(document.createDocumentFragment(), children); }

// External link to the repo (validated), or plain text when the URL is not allowed.
export function repoLink(href, text, attrs = {}) {
  if (!isRepoUrl(href)) return el('span', attrs, text);
  return el('a', { href, rel: 'noopener noreferrer', target: '_blank', ...attrs }, text);
}

// Family colour swatch + name chip. The colour comes from data.js familyColors; Other is the neutral silver.
export function familyChip(name, color, extra = '') {
  return el('span', { class: `chip fam ${extra}`, style: { '--c': color || OTHER_COLOR } },
    el('i', { class: 'swatch', 'aria-hidden': 'true' }), name || 'Other');
}
export const VERDICT_GLYPH = { pass: '●', partial: '◐', fail: '○' };
export function verdictChip(v) {
  const k = (v || 'unknown').toLowerCase();
  return el('span', { class: `chip verdict v-${k}` }, el('span', { class: 'glyph', 'aria-hidden': 'true' }, VERDICT_GLYPH[k] || '◌'), k);
}
export function kindChip(text, cls = '') { return el('span', { class: `chip kind ${cls}` }, text); }

// A list that reveals `step` items at a time with a "show more" button.
export function revealList(container, items, render, { step = 24, label = 'Show more' } = {}) {
  clear(container);
  let shown = 0;
  const more = el('button', { type: 'button', class: 'more' });
  const list = el('div', { class: 'reveal-list' });
  container.append(list, more);
  const next = () => {
    const slice = items.slice(shown, shown + step);
    slice.forEach((it, i) => { const node = render(it, shown + i); if (node) list.appendChild(node); });
    shown += slice.length;
    const left = items.length - shown;
    more.textContent = left > 0 ? `${label} (${Math.min(step, left)} of ${left} left)` : '';
    more.hidden = left <= 0;
  };
  more.addEventListener('click', next);
  next();
  if (!items.length) list.appendChild(el('p', { class: 'empty' }, 'Nothing here yet.'));
  return { next };
}
export function onReducedMotion() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}
