// One row per published setup that was actually tested. Cells use bakeoff.json only; missing facts stay blank.
import { el, clear, $, familyChip } from './dom.js';
import { checksMax, rubricMax, pointMax, familyColors, colorOf, modelOf, shortLabel, fmt } from './data.js';

const GRADE = ['t1', 't2', 't2t', 't3', 't4', 't5', 't6', 't7', 't8'];
const COLS = [['name', 'Setup'], ['ctx', 'Context'], ['kv', 'KV'], ['speed', 'Speed'], ['t1', 't1'], ['t2', 't2'], ['t2t', 't2T'], ['t3', 't3'], ['t4', 't4'], ['t5', 't5 orrery'], ['t6', 't6 pagoda'], ['t7', 't7'], ['t8', 't8 agent']];
const median = (xs) => {
  const a = xs.filter((x) => x != null && Number.isFinite(x)).sort((p, q) => p - q);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
};
const uniq = (xs) => [...new Set(xs.filter((x) => x != null && x !== ''))];
const nfmt = (n, d = 0) => (n == null || !Number.isFinite(+n) ? '' : fmt(n, d));
const isTrust = (r) => r.flavor === '2T' || /^wt-/.test(r.case || '') || /(^|[-_])t2t([-_]|$)/.test(r.case || '');
function family(r) {
  if (isTrust(r)) return 't2t';
  if (r.test === '1' || r.test === '2' || r.test === '4' || r.test === '7') return 't' + r.test;
  return '';
}
function shotFamily(set, test) {
  const name = String(set || '');
  if (test === '8' || name.startsWith('agent-')) return 't8';
  if (name === 'orrery' || test === '5') return 't5';
  if (name === 'pagoda' || test === '6') return 't6';
  if (test === '7') return 't7';
  return '';
}
function checksText(data, r) {
  if (r.checks == null) return '';
  const max = checksMax(data, r.test);
  return max != null ? nfmt(r.checks) + '/' + nfmt(max) + ' checks' : nfmt(r.checks) + ' checks';
}
function testsText(r) {
  if (r.tests_pass == null && r.tests_fail == null) return '';
  if (r.tests_pass != null && r.tests_fail != null) return nfmt(r.tests_pass) + '/' + nfmt(r.tests_pass + r.tests_fail) + ' tests';
  return r.tests_pass != null ? nfmt(r.tests_pass) + ' tests passed' : nfmt(r.tests_fail) + ' tests failed';
}
function bestFrac(lines) {
  let best = null;
  for (const line of lines) {
    const m = String(line).match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
    if (!m || +m[2] <= 0) continue;
    const v = +m[1] / +m[2];
    if (best == null || v > best) best = v;
  }
  return best;
}
export function compareRows(data) {
  const colors = familyColors(data);
  const ids = uniq([
    ...data.runs.map((r) => r.model),
    ...data.test3.map((r) => r.model),
    ...Object.values(data.oneshots || {}).flat().map((r) => r.entry),
    ...data.ab.map((r) => r.model),
  ]).filter((id) => data.models[id]);
  const rmax = rubricMax(data);
  const rows = [];
  for (const id of ids) {
    const m = modelOf(data, id);
    const runs = data.runs.filter((r) => r.model === id);
    const grades = Object.fromEntries(GRADE.map((k) => [k, []]));
    for (const r of runs) {
      const key = family(r);
      const line = [checksText(data, r), testsText(r)].filter(Boolean).join(', ');
      if (key && line) grades[key].push(line);
    }
    for (const r of data.test3) {
      if (r.model !== id) continue;
      const bits = [];
      if (r.flavor && r.flavor !== '?') bits.push(r.flavor);
      if (r.mcp_facts && r.mcp_facts.got != null) bits.push(r.mcp_facts.of != null ? nfmt(r.mcp_facts.got) + '/' + nfmt(r.mcp_facts.of) + ' MCP' : nfmt(r.mcp_facts.got) + ' MCP');
      if (r.api_facts && r.api_facts.got != null) bits.push(r.api_facts.of != null ? nfmt(r.api_facts.got) + '/' + nfmt(r.api_facts.of) + ' REST' : nfmt(r.api_facts.got) + ' REST');
      if (r.rubric != null && rmax) bits.push(nfmt(r.rubric) + '/' + nfmt(rmax) + ' rubric');
      if (bits.length) grades.t3.push(bits.join(' '));
    }
    for (const [set, list] of Object.entries(data.oneshots || {})) {
      for (const r of list) {
        if (r.entry !== id || r.total == null) continue;
        const key = shotFamily(set, r.test);
        if (!key || !grades[key]) continue;
        const denom = r.points && r.points.length ? r.points.length * (pointMax(data, r.test) || 0) : 0;
        const label = key === 't8' ? String(set).replace(/^agent-/, '') : '';
        grades[key].push((label ? label + ' ' : '') + (denom > 0 ? nfmt(r.total) + '/' + nfmt(denom) : nfmt(r.total)));
      }
    }
    const groups = new Map();
    for (const r of runs) {
      if (r.tps == null) continue;
      const gkey = (r.ctx == null ? '' : r.ctx) + '|' + (r.kv || '');
      const g = groups.get(gkey) || { ctx: r.ctx, kv: r.kv || '', tps: [], tests: new Set() };
      g.tps.push(r.tps);
      g.tests.add(isTrust(r) ? '2T' : (r.test || '?'));
      groups.set(gkey, g);
    }
    const speed = [];
    let speedSort = null;
    for (const g of groups.values()) {
      const med = median(g.tps);
      if (med == null) continue;
      const lo = Math.min(...g.tps), hi = Math.max(...g.tps);
      const span = lo === hi ? '' : ' · ' + nfmt(lo, 1) + '–' + nfmt(hi, 1);
      const where = [g.ctx != null ? 'context ' + nfmt(g.ctx) : 'context not recorded', g.kv ? 'KV ' + g.kv : ''].filter(Boolean).join(' · ');
      speed.push({ med, text: nfmt(med, 1) + ' tok/s decode · median' + span + ' · n=' + g.tps.length + ' · test ' + [...g.tests].sort().join(', ') + ' · ' + where });
      if (speedSort == null || med > speedSort) speedSort = med;
    }
    speed.sort((a, b) => b.med - a.med);
    for (const r of data.ab) {
      if (r.model !== id || r.prefill == null) continue;
      speed.push({ med: null, text: nfmt(r.prefill, 1) + ' tok/s prefill · engine probe · ' + r.engine + ' · ' + r.variant });
    }
    if (!runs.some((r) => r.tps != null)) {
      for (const r of data.ab) {
        if (r.model === id && r.decode != null) speed.push({ med: null, text: nfmt(r.decode, 1) + ' tok/s decode · engine probe · ' + r.engine + ' · ' + r.variant });
      }
    }
    const ctxs = uniq(runs.map((r) => r.ctx)).sort((a, b) => a - b);
    const kvs = uniq(runs.map((r) => r.kv));
    const ctxText = [ctxs.map((n) => nfmt(n)).join(' · '), runs.some((r) => r.ctx == null) && runs.some((r) => r.ctx != null) ? 'not recorded' : ''].filter(Boolean).join(' · ');
    const kvText = [kvs.join(' · '), runs.some((r) => !r.kv) && kvs.length ? 'not recorded' : ''].filter(Boolean).join(' · ');
    const sort = { name: shortLabel(m.label).toLowerCase(), ctx: ctxs.length ? Math.max(...ctxs) : null, kv: (kvs[0] || '').toLowerCase(), speed: speedSort };
    for (const key of GRADE) sort[key] = bestFrac(grades[key]);
    rows.push({ id, label: m.label, short: shortLabel(m.label), quant: m.quant, engine: m.engine, family: m.family, color: colorOf(colors, m.family), ctx: ctxText, kv: kvText, speed: speed.map((s) => s.text), grades, sort });
  }
  return rows;
}
export function renderCompare(data) {
  const host = $('compare-table');
  if (!host || !data) return;
  const rows = compareRows(data);
  const famSel = $('c-family');
  if (famSel && famSel.options.length < 2) {
    for (const f of uniq(rows.map((r) => r.family)).sort()) famSel.appendChild(el('option', { value: f }, f));
  }
  const state = renderCompare.state || (renderCompare.state = { q: '', family: 'all', ctx: 'all', sort: 'speed', dir: -1 });
  const prev = state.sort;
  state.q = (($('c-q') && $('c-q').value) || '').trim().toLowerCase();
  state.family = $('c-family') ? $('c-family').value : 'all';
  state.ctx = $('c-ctx') ? $('c-ctx').value : 'all';
  state.sort = $('c-sort') ? $('c-sort').value : state.sort;
  if (state.sort !== prev) state.dir = state.sort === 'name' || state.sort === 'kv' ? 1 : -1;
  const min = { 32: 32768, 128: 131072, 200: 200000 }[state.ctx];
  const shown = rows.filter((r) => {
    if (state.family !== 'all' && r.family !== state.family) return false;
    if (state.ctx === 'recorded' && r.sort.ctx == null) return false;
    if (state.ctx === 'blank' && r.sort.ctx != null) return false;
    if (min && !(r.sort.ctx != null && r.sort.ctx >= min)) return false;
    return !state.q || (r.label + ' ' + r.quant + ' ' + r.engine + ' ' + r.id).toLowerCase().includes(state.q);
  });
  const dir = state.dir, key = state.sort;
  shown.sort((a, b) => {
    const av = a.sort[key], bv = b.sort[key];
    const an = av == null || av === '', bn = bv == null || bv === '';
    if (an || bn) return an === bn ? a.sort.name.localeCompare(b.sort.name) : an ? 1 : -1;
    return (typeof av === 'string' || typeof bv === 'string' ? String(av).localeCompare(String(bv)) * dir : (av - bv) * dir) || a.sort.name.localeCompare(b.sort.name);
  });
  clear(host);
  const table = el('table', { class: 'compare' });
  const hr = el('tr');
  for (const [id, label] of COLS) {
    const btn = el('button', { type: 'button', class: 'sort', 'aria-sort': state.sort === id ? (dir < 0 ? 'descending' : 'ascending') : 'none' }, label);
    btn.addEventListener('click', () => {
      if (state.sort === id) state.dir *= -1;
      else { state.sort = id; state.dir = id === 'name' || id === 'kv' ? 1 : -1; }
      if ($('c-sort')) $('c-sort').value = id;
      renderCompare(data);
    });
    hr.appendChild(el('th', { scope: 'col' }, btn));
  }
  const tb = el('tbody');
  for (const r of shown) {
    const tr = el('tr');
    tr.appendChild(el('th', { scope: 'row' }, familyChip(r.family, r.color), el('span', { class: 'name', title: r.label }, r.short), el('span', { class: 'meta' }, [r.quant, r.engine].filter(Boolean).join(' · '))));
    tr.appendChild(el('td', { class: 'num' }, r.ctx));
    tr.appendChild(el('td', {}, r.kv));
    tr.appendChild(el('td', {}, r.speed.map((t) => el('span', { class: 'line' }, t))));
    for (const id of GRADE) tr.appendChild(el('td', {}, r.grades[id].map((t) => el('span', { class: 'line' }, t))));
    tb.appendChild(tr);
  }
  table.append(el('thead', {}, hr), tb);
  host.appendChild(table);
  const count = $('compare-count');
  if (count) count.textContent = shown.length + ' of ' + rows.length;
  const form = $('compare-filters');
  if (form && !form.dataset.bound) {
    form.dataset.bound = '1';
    form.addEventListener('input', () => renderCompare(data));
  }
}
