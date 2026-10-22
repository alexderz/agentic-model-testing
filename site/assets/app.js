// The Bake-off page. Fetches data/bakeoff.json and renders every section from it. Each section
// renders inside its own try/catch so one odd record never blanks the page; a section that throws
// is named in data-render-error on <body> (site/tools/render_smoke.sh looks for it).
import * as D from './data.js';
import { el, svg, clear, $, familyChip, verdictChip, kindChip, revealList, repoLink, onReducedMotion } from './dom.js';
import { speedLadder, struggleStrip, abDumbbell, petalScore, pips, beforeAfter, bigNumeral, runLine, ofMax } from './charts.js';
import { renderHero } from './hero.js';
import { chapterMotif } from './motifs.js';
import { openViewer } from './viewer.js';

const { fmt, fmtMinutes, fmtDate } = D;

async function main() {
  let raw;
  try {
    const res = await fetch('data/bakeoff.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    raw = await res.json();
  } catch (e) {
    const p = $('load-error'); p.hidden = false;
    p.textContent = `The data file could not be loaded (${e && e.message ? e.message : e}). The page is a renderer for data/bakeoff.json; without it there is nothing to show.`;
    return;
  }
  const data = D.normalize(raw);
  document.title = `${data.title} · local models on one GPU`;
  section('top', () => renderTop(data));
  section('machine', () => renderMachine(data));
  section('tests', () => renderTests(data));
  section('picks', () => renderPicks(data));
  section('runs', () => renderRuns(data));
  section('struggle', () => renderStruggle(data));
  section('test3', () => renderTest3(data));
  section('ab', () => renderAB(data));
  section('oneshots', () => renderOneshots(data));
  section('findings', () => renderFindings(data));
  section('timeline', () => renderTimeline(data));
  section('log', () => renderLog(data));
  section('caveats', () => renderCaveats(data));
  section('links', () => renderLinks(data));
  section('motifs', () => renderMotifs(data));
  document.body.dataset.rendered = '1';
  // a deep link (#oneshots) was resolved against the empty page; re-aim it now that the chapters have their height
  if (location.hash && /^#[A-Za-z0-9_-]+$/.test(location.hash)) {
    const target = $(location.hash.slice(1));
    if (target) target.scrollIntoView({ behavior: onReducedMotion() ? 'auto' : 'instant', block: 'start' });
  }
}
function section(id, fn) {
  try { fn(); } catch (e) {
    const host = $(id);
    if (host) host.appendChild(el('p', { class: 'empty render-error' }, `This section could not be drawn from the current data (${e && e.message ? e.message : e}).`));
    const prev = document.body.dataset.renderError;
    document.body.dataset.renderError = prev ? `${prev} ${id}` : id;
    console.error(id, e);
  }
}
const stat = (k, v, unit) => el('div', {}, el('dt', {}, k), el('dd', {}, fmt(v, 0), unit ? el('small', {}, unit) : null));

// ------------------------------------------------------------------- hero
function renderTop(data) {
  $('title').textContent = data.title;
  $('tagline').textContent = data.tagline;
  const s = D.summary(data);
  const stats = $('hero-stats'); clear(stats);
  stats.append(stat('models', s.models), stat('families', s.families), stat('agent runs', s.runs), stat('passes', s.passes), stat('one-shots', s.oneshots), stat('frames', s.frames));
  if (s.playable > 0) stats.append(stat('live pieces', s.playable));
  if (s.fastest != null) stats.append(stat('fastest run', s.fastest, 'tok/s'));
  if (s.agentHours > 0) stats.append(stat('agent hours', Math.round(s.agentHours)));
  // freshness: the run table is a snapshot; findings are written as they happen and are usually newer
  const gen = $('generated'); clear(gen);
  const bit = (k, v) => el('span', { class: 'fresh' }, el('small', {}, k), ' ', v);
  if (data.generated) gen.appendChild(bit('data generated', data.generated));
  if (data.built) gen.appendChild(bit('site built', data.built));
  if (s.last) gen.appendChild(bit('newest run', fmtDate(s.last)));
  if (s.newestFinding) gen.appendChild(bit('newest finding', fmtDate(s.newestFinding)));
  if (!gen.childNodes.length) gen.textContent = 'Data snapshot';
  renderHero(data, $('orrery'), $('hero-caption'), $('hero-legend'));
}

// ---------------------------------------------------------------- machine
function renderMachine(data) {
  const dl = $('hardware'); clear(dl);
  const entries = Object.entries(data.hardware);
  if (!entries.length) { dl.appendChild(el('p', { class: 'empty' }, 'No hardware recorded.')); return; }
  for (const [k, v] of entries) dl.appendChild(el('div', {}, el('dt', {}, k.replace(/_/g, ' ')), el('dd', {}, v)));
}

// ------------------------------------------------------------------ tests
function renderTests(data) {
  const host = $('test-cards'); clear(host);
  if (!data.tests.length) { host.appendChild(el('p', { class: 'empty' }, 'No tests described yet.')); return; }
  const seen = new Set();
  for (const t of data.tests) {
    seen.add(t.number);
    host.appendChild(testCard(t, D.testCount(data, t.number)));
  }
  // tests that appear in the data but are not described
  const extra = new Set();
  for (const r of data.runs) { const k = D.effectiveTest(r); if (!seen.has(k)) extra.add(k); }
  for (const rows of Object.values(data.oneshots)) for (const r of rows) if (!seen.has(r.test)) extra.add(r.test);
  if (data.test3.length && !seen.has('3')) extra.add('3');
  for (const k of [...extra].sort()) host.appendChild(testCard(D.testOf(data, k), D.testCount(data, k), true));
}
function testCard(t, n, undocumented = false) {
  const kindCls = (t.kind || '').replace(/[^a-z-]/gi, '').toLowerCase();
  return el('article', { class: `test-card ${kindCls}` },
    el('span', { class: 'tn', 'aria-hidden': 'true' }, t.number || '?'),
    el('h3', {}, el('span', { class: 'sr' }, `Test ${t.number}: `), t.name),
    t.what ? el('p', { class: 'what' }, t.what) : undocumented ? el('p', { class: 'what empty' }, 'Appears in the results but is not described yet.') : null,
    t.graded ? el('p', { class: 'graded' }, t.graded) : null,
    el('div', { class: 'meta' }, t.kind ? kindChip(t.kind, kindCls) : null, el('span', { class: 'n' }, n === 1 ? '1 graded run' : `${fmt(n, 0)} graded runs`)));
}

// ------------------------------------------------------------------ picks
function renderPicks(data) {
  const { overall, uncensored } = D.pickCards(data);
  fill($('pick-overall'), overall, pickCard, 'No overall picks yet.');
  fill($('pick-uncensored'), uncensored, pickCard, 'No uncensored picks yet.');
  const fam = $('pick-families'); clear(fam);
  const rows = D.familyPickRows(data);
  if (!rows.length) fam.appendChild(el('p', { class: 'empty' }, 'No family table yet.'));
  for (const f of rows) {
    fam.appendChild(el('div', { class: 'fam-row', style: { '--c': f.color } },
      el('div', { class: 'famhead' }, familyChip(f.family, f.color), el('div', { class: 'count' }, f.models === 1 ? '1 model tried' : `${f.models} models tried`)),
      ...f.cells.map(([k, v]) => el('div', { class: 'cell' }, el('small', {}, k), v ? el('b', {}, v) : el('span', { class: 'none' }, 'none yet'))),
      f.note ? el('p', { class: 'note' }, f.note) : null));
  }
}
function fill(host, items, render, emptyText) {
  clear(host);
  if (!items.length) host.appendChild(el('p', { class: 'empty' }, emptyText));
  for (const it of items) host.appendChild(render(it));
}
function pickCard(p) {
  return el('article', { class: 'pick-card', style: { '--c': p.color } },
    el('div', { class: 'role' }, p.role),
    el('h4', {}, p.short || p.model || 'unnamed'),
    el('div', { class: 'meta' }, familyChip(p.family, p.color), p.uncensored ? kindChip('uncensored') : null, p.quant ? el('span', { class: 'mono' }, p.quant) : null, p.engine ? el('span', { class: 'mono' }, p.engine) : null, p.missing ? kindChip('no model card in data') : null),
    p.verdict ? el('p', { class: 'verdict-text' }, p.verdict) : null,
    p.tradeoff ? el('p', { class: 'trade' }, p.tradeoff) : null,
    p.runs.length ? el('ul', {}, ...p.runs.map(runLine)) : null);
}

// ------------------------------------------------------------------- runs
function renderRuns(data) {
  const opts = D.runFilterOptions(data);
  const sel = (id, values, labelFn) => { const s = $(id); clear(s); s.appendChild(el('option', { value: 'all' }, 'all')); for (const v of values) s.appendChild(el('option', { value: v }, labelFn ? labelFn(v) : v)); };
  sel('f-test', opts.tests, (t) => { const tt = D.testOf(data, t); return `${t} · ${tt.name}`; });
  sel('f-family', opts.families);
  sel('f-verdict', opts.verdicts);
  const form = $('run-filters');
  let limit = 40;
  const draw = () => {
    const f = { test: $('f-test').value, family: $('f-family').value, verdict: $('f-verdict').value, uncensored: $('f-unc').value, q: $('f-q').value.trim() };
    const rows = D.runRows(data, f, $('f-sort').value);
    $('f-count').textContent = `${rows.length} of ${data.runs.length} runs`;
    const host = $('ladder'); clear(host); host.appendChild(speedLadder(rows, { limit }));
    const more = $('ladder-more');
    more.hidden = rows.length <= limit;
    more.textContent = `Show ${Math.min(40, rows.length - limit)} more rows (${rows.length - limit} left)`;
    const tbl = $('run-table'); clear(tbl); tbl.appendChild(runTable(rows));
  };
  form.addEventListener('input', () => { limit = 40; draw(); });
  form.addEventListener('submit', (e) => e.preventDefault());
  $('ladder-more').addEventListener('click', () => { limit += 40; draw(); });
  draw();
}
function runTable(rows) {
  const cols = [
    ['Model', (r) => el('span', {}, r.short, el('span', { class: 'case' }, r.case))],
    ['Test', (r) => `${r.test}${r.flavor ? ' · ' + r.flavor : ''}`],
    ['Verdict', (r) => verdictChip(r.verdict)],
    ['Checks', (r) => ofMax(r.checks, r.checksMax), 'n'],
    ['Tests', (r) => (r.tests_pass == null ? '–' : fmt(r.tests_pass, 0) + (r.tests_fail ? ` (${fmt(r.tests_fail, 0)} fail)` : '')), 'n'],
    ['tok/s', (r) => fmt(r.tps, 1), 'n'],
    ['Time', (r) => fmtMinutes(r.minutes), 'n'],
    ['Context', (r) => (r.ctx == null ? '–' : `${fmt(r.ctx / 1024, 0)}k`) + (r.kv ? ` ${r.kv}` : ''), 'n'],
    ['Errors/kloc', (r) => (r.struggle && r.struggle.errors_per_kloc != null ? fmt(r.struggle.errors_per_kloc, 1) : '–'), 'n'],
    ['Agent', (r) => r.agent || '–'],
    ['Finished', (r) => r.finished || '–'],
  ];
  const table = el('table', { class: 'runs' }, el('caption', { class: 'sr' }, 'Matching runs'));
  table.appendChild(el('thead', {}, el('tr', {}, ...cols.map(([h, , c]) => el('th', { scope: 'col', class: c || '' }, h)))));
  const body = el('tbody', {});
  rows.slice(0, 300).forEach((r) => body.appendChild(el('tr', {}, ...cols.map(([h, f, c]) => el('td', { class: c || '', 'data-l': h }, f(r))))));
  table.appendChild(body);
  if (rows.length > 300) table.appendChild(el('tfoot', {}, el('tr', {}, el('td', { colspan: String(cols.length) }, `Showing the first 300 of ${rows.length}; narrow the filters to see the rest.`))));
  return table;
}

// --------------------------------------------------------------- struggle
function renderStruggle(data) {
  const rows = D.struggleRows(data);
  const host = $('struggle-chart'); clear(host);
  if (!rows.length) { host.appendChild(el('p', { class: 'empty' }, 'No test-2 runs with a struggle score yet.')); return; }
  const draw = () => { clear(host); host.appendChild(struggleStrip(rows, host.clientWidth - 16)); };
  draw();
  let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(draw, 150); });
  const sum = D.struggleSummary(rows);
  const row = $('struggle-summary'); clear(row);
  for (const v of ['pass', 'partial', 'fail']) {
    if (!sum[v]) continue;
    row.appendChild(el('div', { class: 'stat' }, el('div', { class: 'k' }, verdictChip(v), `${sum[v].n} runs`), el('div', { class: 'v' }, fmt(sum[v].median, 1), el('small', {}, ' median errors / kloc'))));
  }
  const c = D.cleanestRun(rows);
  if (c) row.appendChild(el('div', { class: 'stat' }, el('div', { class: 'k' }, 'cleanest passing build'),
    el('div', { class: 'v' }, c.short, el('small', {}, ` ${fmt(c.struggle.errors_per_kloc, 1)} errors / kloc · ${fmt(c.struggle.compiles, 0)} build${c.struggle.compiles === 1 ? '' : 's'} · ${fmt(c.struggle.loc, 0)} lines`)),
    el('div', { class: 'k' }, verdictChip(c.verdict))));
}

// ----------------------------------------------------------------- test 3
function renderTest3(data) {
  const { groups, rubricMax } = D.test3Groups(data);
  const host = $('test3-groups');
  const btn = $('test3-more');
  const r = revealList(host, groups, (g) => el('article', { class: 't3', style: { '--c': g.color } },
    el('div', { class: 'head' }, el('b', {}, g.short), el('div', { class: 'chips' }, familyChip(g.family, g.color), g.uncensored ? kindChip('uncensored') : null)),
    el('div', { class: 'flavors' }, ...g.rows.map((row) => el('div', { class: 't3-row' },
      el('span', { class: 'flavor', title: `flavor ${row.flavor}` }, row.flavor),
      el('div', { class: 'facts' },
        el('span', {}, 'MCP facts ', pips(row.mcp_facts.got, row.mcp_facts.of), ` ${row.mcp_facts.text}`),
        el('span', {}, 'API facts ', pips(row.api_facts.got, row.api_facts.of, 'api'), ` ${row.api_facts.text}`),
        el('span', {}, 'rubric ', pips(row.rubric, rubricMax, 'rubric'), el('span', { class: 'rubric-num' }, ` ${ofMax(row.rubric, rubricMax)}`)),
        el('span', { class: `judge ${row.judgement_right === true ? 'ok' : row.judgement_right === false ? 'bad' : ''}` }, row.judgement_right === true ? '✓ judged the server right' : row.judgement_right === false ? '✗ misjudged the server' : 'judgement not recorded')),
      el('span', { class: 'num' }, `${fmt(row.tps, 1)} tok/s · ${fmtMinutes(row.minutes)}`),
      ...noteBlock(row.note, 220))))), { step: 8, label: 'Show more models' });
  btn.hidden = true; // revealList carries its own button
  return r;
}

// -------------------------------------------------------------------- A/B
function renderAB(data) {
  const { groups, engines, colors, max } = D.abGroups(data);
  const legend = $('ab-legend'); clear(legend);
  for (const e of engines) legend.appendChild(el('li', {}, el('i', { style: { '--c': colors.get(e) }, 'aria-hidden': 'true' }), `engine ${e}`));
  if (engines.length) legend.appendChild(el('li', {}, 'dot = one probe variant; the line spans the model’s range; ×n is the gain between engines with the same flags'));
  const host = $('ab-groups'); clear(host);
  if (!groups.length) { host.appendChild(el('p', { class: 'empty' }, 'No engine probes yet.')); return; }
  for (const g of groups.filter((g) => !g.allFailed)) host.appendChild(abDumbbell(g, max, colors));
  const failed = data.ab.filter((r) => r.decode == null);
  if (failed.length) {
    host.appendChild(el('details', { class: 'ab-errors' }, el('summary', {}, `${failed.length} probe${failed.length === 1 ? '' : 's'} failed to load`),
      el('ul', {}, ...failed.map((r) => el('li', {}, el('b', {}, D.shortLabel(D.modelOf(data, r.model).label)), ` · ${r.engine} · ${r.variant}: `, el('code', {}, r.error.slice(0, 160) || 'no error text'))))));
  }
}

// ---------------------------------------------------------------- gallery
function renderOneshots(data) {
  const sets = D.oneshotSets(data);
  const setRow = $('oneshot-sets'); clear(setRow);
  for (const s of sets) {
    setRow.appendChild(el('div', { class: 'set-card' }, el('b', {}, `Test ${s.test} · ${s.name}`),
      el('span', {}, `${s.n} replies · ${s.withFrames} rendered · ${s.full} full marks · ${s.zero} scored zero`),
      el('span', {}, `${s.cut} cut off by the token cap${s.mean != null ? ` · mean ${fmt(s.mean, 1)}` : ''}`),
      s.live > 0 ? el('span', { class: 'live-n' }, el('i', { 'aria-hidden': 'true' }, '▶'), ` ${s.live} can be played live`) : null));
  }
  // header line: how many pieces can be played, from the data
  const liveLine = $('oneshot-live');
  const playable = sets.reduce((n, s) => n + (s.live || 0), 0), total = sets.reduce((n, s) => n + s.n, 0);
  if (liveLine) {
    clear(liveLine);
    liveLine.hidden = playable <= 0;
    if (playable > 0) liveLine.append(el('i', { 'aria-hidden': 'true' }, '▶'), ` ${fmt(playable, 0)} of the ${fmt(total, 0)} replies produced a file you can run here, exactly as the model wrote it: `,
      sets.filter((s) => s.live > 0).map((s) => `${fmt(s.live, 0)} ${plural(s.set, s.live)}`).join(' and '),
      '. Press “Play live” on a card; each piece runs alone, in a sandboxed frame.');
  }
  const tsel = $('o-test'); clear(tsel); tsel.appendChild(el('option', { value: 'all' }, 'all'));
  for (const s of sets) tsel.appendChild(el('option', { value: s.test }, `${s.test} · ${s.name}`));
  const form = $('oneshot-filters');
  const grid = $('oneshot-grid');
  let current = [];
  const draw = () => {
    const cards = D.oneshotCards(data, { test: tsel.value, sort: $('o-sort').value, q: $('o-q').value.trim() });
    current = cards;
    const live = cards.filter((c) => c.live).length;
    $('o-count').textContent = `${cards.length} replies${live ? ` · ${live} playable` : ''}`;
    revealList(grid, cards, (c, i) => shotCard(c, () => openViewerAt(current, i)), { step: 12, label: 'Show more replies' });
  };
  const openViewerAt = (cards, i) => { const btn = grid.querySelector(`.shot[data-case="${CSS.escape(cards[i].case)}"] .play`); openViewer(cards, i, btn); };
  form.addEventListener('input', draw);
  form.addEventListener('submit', (e) => e.preventDefault());
  draw();
  startFlipbooks(grid);
}
const plural = (w, n) => (n === 1 ? w : /y$/.test(w) ? `${w.slice(0, -1)}ies` : `${w}s`);
const blankCard = (c) => el('div', { class: 'blank' }, el('span', {}, el('i', { 'aria-hidden': 'true' }, '∅'), c.finish === 'length' ? 'Cut off by the token cap, nothing to render' : c.frames.length ? 'The renders could not be loaded' : 'No render available'));
function shotCard(c, onPlay) {
  const pic = el('div', { class: 'pic' });
  const frames = c.frames;
  if (frames.length) {
    const last = frames.length - 1;
    let failed = 0;
    // The last frame is the richest, so it is shown first and fetched eagerly; the others load lazily and the
    // flipbook only ever advances onto a frame that has really loaded. If none loads the card goes blank.
    const imgs = frames.map((f, i) => {
      const im = el('img', { src: f.url, alt: `${c.alt}, frame at ${f.ms == null ? '?' : fmt(f.ms, 0)} ms`, loading: i === last ? 'eager' : 'lazy', decoding: 'async', width: c.set === 'orrery' ? 1000 : 1280, height: c.set === 'orrery' ? 1000 : 800, class: i === last ? 'on' : '' });
      im.addEventListener('load', () => { if (im.classList.contains('on')) pic.dataset.loaded = '1'; });
      im.addEventListener('error', () => { im.classList.add('broken'); if (++failed === frames.length) { clear(pic); delete pic.dataset.flip; pic.appendChild(blankCard(c)); } });
      return im;
    });
    pic.append(...imgs);
    const dots = el('ol', { class: 'frames', 'aria-label': 'Frame' });
    frames.forEach((f, i) => {
      const b = el('button', { type: 'button', 'aria-pressed': String(i === last), 'aria-label': `frame at ${fmt(f.ms, 0)} ms` }, f.ms == null ? String(i + 1) : f.ms >= 1000 ? `${(f.ms / 1000).toFixed(f.ms % 1000 ? 1 : 0)}s` : `${f.ms}ms`);
      b.addEventListener('click', () => { pic.dataset.manual = '1'; showFrame(pic, i); });
      dots.appendChild(b);
    });
    pic.appendChild(dots);
    pic.dataset.flip = '1';
    pic.dataset.frame = String(last);
  } else {
    pic.appendChild(blankCard(c));
  }
  // the live control: only for rows whose `live` path passed the allow-list in data.js (anything else is null)
  if (c.live && onPlay) {
    const play = el('button', { type: 'button', class: 'play', 'aria-label': `Play live: ${c.alt}` }, el('i', { 'aria-hidden': 'true' }, '▶'), ' Play live');
    play.addEventListener('click', onPlay);
    pic.appendChild(play);
    if (c.full) pic.appendChild(el('span', { class: 'ribbon', 'aria-hidden': 'true' }, 'live'));
  }
  const [note, noteBtn] = noteBlock(c.note, 160);
  const body = el('div', { class: 'body' },
    el('div', {}, el('b', {}, c.short), el('div', { class: 'meta' }, familyChip(c.family, c.color), c.uncensored ? kindChip('uncensored') : null,
      el('span', {}, `${fmt(c.tok_s, 1)} tok/s`), el('span', {}, `${fmt(c.tokens, 0)} tokens`), c.finish === 'length' ? el('span', { class: 'cut' }, 'hit the cap') : null)),
    petalScore(c), note);
  const pmax = c.pointMax > 0 ? c.pointMax : 1;
  if (c.points.length) body.appendChild(el('div', { class: 'pts' }, ...c.points.map((p) => { const v = p.value || 0; return el('span', { class: v <= 0 ? 'l0' : v >= pmax ? 'l2' : 'l1' }, `${p.name} ${fmt(p.value)}`); })));
  if (noteBtn) body.appendChild(noteBtn);
  return el('article', { class: `shot${c.full && frames.length ? ' featured' : ''}${c.live ? ' playable' : ''}`, title: c.case, 'data-case': c.case, style: { '--c': c.color } }, pic, body);
}
// A clamped note plus a "full note" toggle when it is long. Returns [p, button|null].
function noteBlock(text, threshold) {
  if (!text) return [null, null];
  const p = el('p', { class: 'note' }, text);
  if (text.length <= threshold) return [p, null];
  const b = el('button', { type: 'button', class: 'noteb', 'aria-expanded': 'false' }, 'full note');
  b.addEventListener('click', () => { const open = p.classList.toggle('open'); b.setAttribute('aria-expanded', String(open)); b.textContent = open ? 'less' : 'full note'; });
  return [p, b];
}
const imgLoaded = (im) => im.complete && im.naturalWidth > 0;
function showFrame(pic, i) {
  const imgs = pic.querySelectorAll('img'), btns = pic.querySelectorAll('.frames button');
  imgs.forEach((im, j) => im.classList.toggle('on', j === i));
  btns.forEach((b, j) => b.setAttribute('aria-pressed', String(j === i)));
  pic.dataset.frame = String(i);
  if (imgs[i] && imgLoaded(imgs[i])) pic.dataset.loaded = '1'; else delete pic.dataset.loaded;
}
// Flipbooks advance only while on screen, only when motion is allowed, and only onto frames that have loaded;
// a manual click stops the loop for that card.
function startFlipbooks(grid) {
  if (onReducedMotion() || !('IntersectionObserver' in window)) return;
  const live = new Set();
  const io = new IntersectionObserver((es) => { for (const e of es) { if (e.isIntersecting) live.add(e.target); else live.delete(e.target); } }, { threshold: 0.4 });
  const seen = new WeakSet();
  const scan = () => grid.querySelectorAll('.pic[data-flip]').forEach((p) => { if (!seen.has(p)) { seen.add(p); io.observe(p); } });
  scan();
  new MutationObserver(scan).observe(grid, { childList: true, subtree: true });
  setInterval(() => {
    for (const pic of live) {
      if (pic.dataset.manual || !pic.dataset.flip) continue;
      const imgs = [...pic.querySelectorAll('img')];
      const n = imgs.length; if (n < 2) continue;
      const cur = pic.dataset.frame == null ? n - 1 : +pic.dataset.frame;
      for (let k = 1; k <= n; k++) { const j = (cur + k) % n; if (imgLoaded(imgs[j])) { if (j !== cur) showFrame(pic, j); break; } }
    }
  }, 1400);
}

// --------------------------------------------------------------- findings
function renderFindings(data) {
  const host = $('findings-list'); clear(host);
  if (!data.findings.length) { host.appendChild(el('p', { class: 'empty' }, 'No headline findings yet.')); return; }
  for (const f of data.findings) {
    const metrics = D.findingMetrics(f);
    const right = el('div', { class: 'numbers' });
    if (metrics.length) {
      // the lead metric is the typographic moment; the rest are bars under it
      const lead = metrics.find((m) => m.after != null) || metrics[0];
      right.appendChild(bigNumeral(lead));
      const rest = metrics.filter((m) => m !== lead);
      if (rest.length) {
        right.appendChild(el('div', { class: 'ba-key' }, el('span', {}, el('i', { class: 'before' }), 'before'), el('span', {}, el('i', { class: 'after' }), 'after')));
        for (const m of rest) right.appendChild(beforeAfter(m));
      }
    }
    if (f.quality) right.appendChild(el('p', { class: 'quality', 'data-k': 'quality check' }, f.quality));
    if (f.caveat) right.appendChild(el('p', { class: 'caveat', 'data-k': 'caveat' }, f.caveat));
    host.appendChild(el('article', { class: 'finding' },
      el('div', { class: 'when' }, f.date ? el('time', { datetime: f.date }, fmtDate(f.date)) : null, kindChip(f.kind)),
      el('h3', {}, f.title),
      el('div', {}, el('p', { class: 'summary' }, f.summary), f.settings ? el('p', { class: 'settings' }, 'settings ', el('code', {}, f.settings)) : null),
      right));
  }
}

// --------------------------------------------------------------- timeline
function renderTimeline(data) {
  const ol = $('timeline-list'); clear(ol);
  if (!data.timeline.length) { ol.appendChild(el('li', { class: 'empty' }, 'No timeline yet.')); return; }
  for (const t of data.timeline) {
    ol.appendChild(el('li', {},
      el('div', { class: 'date' }, t.date ? el('time', { datetime: t.date }, fmtDate(t.date)) : null, t.era ? el('span', { class: 'era' }, t.era) : null),
      el('h3', {}, t.title), t.what ? el('p', { class: 'what' }, t.what) : null, t.why ? el('p', { class: 'why' }, t.why) : null));
  }
}

// -------------------------------------------------------------------- log
function renderLog(data) {
  const kinds = D.eventKinds(data);
  const row = $('event-kinds'); clear(row);
  let active = 'all';
  const host = $('events-list');
  const draw = () => {
    const items = active === 'all' ? data.events : data.events.filter((e) => e.kind === active);
    revealList(host, items, (e) => el('article', { class: 'event' },
      el('div', {}, el('time', {}, e.when), kindChip(e.kind)), el('p', {}, e.text)), { step: 12, label: 'Show more entries' });
    row.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.kind === active)));
  };
  const mk = (kind, label) => { const b = el('button', { type: 'button', 'data-kind': kind, 'aria-pressed': 'false' }, label); b.addEventListener('click', () => { active = kind; draw(); }); return el('li', {}, b); };
  row.appendChild(mk('all', `all ${data.events.length}`));
  for (const k of kinds) row.appendChild(mk(k.kind, `${k.kind} ${k.n}`));
  draw();
}

// ---------------------------------------------------------------- caveats
function renderCaveats(data) {
  const ol = $('caveat-list'); clear(ol);
  if (!data.caveats.length) ol.appendChild(el('li', {}, 'No caveats are recorded in the data. Treat every number as one sample from a changing harness.'));
  for (const c of data.caveats) ol.appendChild(el('li', {}, c));
}
function renderLinks(data) {
  const ul = $('links'); clear(ul);
  const names = { repo: 'Repository', cards: 'Model cards', method: 'Method', conclusions: 'Conclusions', log: 'Research log' };
  for (const [k, v] of Object.entries(data.links)) ul.appendChild(el('li', {}, repoLink(v, names[k] || k)));
}

// ----------------------------------------------------------------- motifs
// One ornament per chapter head, drawn from that chapter's numbers. Purely decorative, so drawn last.
function renderMotifs(data) {
  const m = D.motifs(data);
  for (const key of Object.keys(m)) {
    const sec = $(key); if (!sec) continue;
    const head = sec.querySelector('.chapter-head'); if (!head) continue;
    const old = head.querySelector('.motif'); if (old) old.remove();
    const node = chapterMotif(key, m[key]);
    if (node) head.appendChild(el('div', { class: 'motif', 'aria-hidden': 'true' }, node));
  }
}

main();
export { svg };
