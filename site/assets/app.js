// The Bake-off page. Fetches data/bakeoff.json and renders every section from it. Each section
// renders inside its own try/catch so one odd record never blanks the page; a section that throws
// is named in data-render-error on <body> (site/tools/render_smoke.sh looks for it).
// Prose is kept to titles, labels and numbers: the charts carry the story, long text sits behind disclosures.
import * as D from './data.js';
import { el, clear, $, familyChip, verdictChip, kindChip, revealList, repoLink, onReducedMotion } from './dom.js';
import { speedLadder, struggleStrip, abDumbbell, pairDumbbell, petalScore, pips, beforeAfter, bigNumeral, runLine, ofMax } from './charts.js';
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
  section('caveats', () => renderFoot(data));
  section('motifs', () => renderMotifs(data));
  document.body.dataset.rendered = '1';
  // a deep link (#oneshots) was resolved against the empty page; re-aim it now that the chapters have their height
  if (location.hash && /^#[A-Za-z0-9_-]+$/.test(location.hash)) {
    const target = $(location.hash.slice(1));
    if (target && target.tagName === 'DETAILS') target.open = true;
    if (target) target.scrollIntoView({ behavior: onReducedMotion() ? 'auto' : 'instant', block: 'start' });
  }
  // the caveats live in a closed disclosure in the footer; the nav link opens it
  addEventListener('hashchange', () => { if (location.hash === '#caveats') { const d = $('caveats'); if (d) d.open = true; } });
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
// A small closed disclosure for text that should not be read unless asked for.
const disclosure = (label, cls, ...children) => (children.some(Boolean) ? el('details', { class: `fold ${cls || ''}` }, el('summary', {}, label), ...children) : null);
const plural = (n, one, many) => (n === 1 ? `1 ${one}` : `${fmt(n, 0)} ${many || one + 's'}`);

// ------------------------------------------------------------------- hero
function renderTop(data) {
  $('title').textContent = data.title;
  $('tagline').textContent = data.tagline;
  const s = D.summary(data);
  const stats = $('hero-stats'); clear(stats);
  stats.append(stat('models', s.models), stat('families', s.families), stat('agent runs', s.runs), stat('passes', s.passes), stat('one-shots', s.oneshots));
  if (s.agentPieces > 0) stats.append(stat('agent pieces', s.agentPieces));
  if (s.playable > 0) stats.append(stat('live pieces', s.playable));
  if (s.fastest != null) stats.append(stat('fastest run', s.fastest, 'tok/s'));
  if (s.agentHours > 0) stats.append(stat('agent hours', Math.round(s.agentHours)));
  // freshness, derived: the span of everything dated in the file, and when the file was built
  const gen = $('generated'); clear(gen);
  const bit = (k, v) => el('span', { class: 'fresh' }, el('small', {}, k), ' ', v);
  if (s.covers.from && s.covers.to) gen.appendChild(bit('covers', s.covers.from === s.covers.to ? fmtDate(s.covers.to) : `${fmtDate(s.covers.from)} – ${fmtDate(s.covers.to)}`));
  if (data.built) gen.appendChild(bit('built', data.built));
  else if (data.generated) gen.appendChild(bit('generated', data.generated));
  if (!gen.childNodes.length) gen.textContent = 'Data snapshot';
  // the key to the orrery: four marks, four words each
  const key = $('hero-key'); clear(key);
  const mark = (cls) => el('i', { class: `mark ${cls}`, 'aria-hidden': 'true' });
  key.append(el('li', {}, mark('speed'), 'speed · best tok/s'), el('li', {}, mark('size'), 'size · runs'), el('li', {}, mark('halo'), 'halo · passed test 2'), el('li', {}, mark('unc'), 'dashed · uncensored'));
  renderHero(data, $('orrery'), $('hero-caption'), $('hero-legend'));
  $('hero-caption').textContent = '';
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
  return el('article', { class: `test-card ${kindCls}${n ? '' : ' pending'}` },
    el('span', { class: 'tn', 'aria-hidden': 'true' }, t.number || '?'),
    el('h3', {}, el('span', { class: 'sr' }, `Test ${t.number}: `), t.name),
    t.what ? el('p', { class: 'what' }, t.what) : undocumented ? el('p', { class: 'what empty' }, 'Not described yet.') : null,
    el('div', { class: 'meta' }, t.kind ? kindChip(t.kind, kindCls) : null, el('span', { class: 'n' }, n ? plural(n, 'graded run') : 'no graded runs yet')),
    disclosure('grading', 'small', t.graded ? el('p', {}, t.graded) : null));
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
      el('div', { class: 'famhead' }, familyChip(f.family, f.color), el('div', { class: 'count' }, plural(f.models, 'model'))),
      ...f.cells.map(([k, v]) => el('div', { class: 'cell' }, el('small', {}, k), v ? el('b', {}, v) : el('span', { class: 'none' }, '–'))),
      disclosure('note', 'small', f.note ? el('p', {}, f.note) : null)));
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
    p.verdict ? el('p', { class: 'verdict-text' }, D.firstSentence(p.verdict)) : null,
    p.runs.length ? el('ul', {}, ...p.runs.map(runLine)) : null,
    disclosure('trade-off', 'small', p.tradeoff ? el('p', {}, p.tradeoff) : null));
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
    more.textContent = `Show ${Math.min(40, rows.length - limit)} more (${rows.length - limit} left)`;
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
  onResize(draw);
  const sum = D.struggleSummary(rows);
  const row = $('struggle-summary'); clear(row);
  for (const v of ['pass', 'partial', 'fail']) {
    if (!sum[v]) continue;
    row.appendChild(el('div', { class: 'stat' }, el('div', { class: 'k' }, verdictChip(v), plural(sum[v].n, 'run')), el('div', { class: 'v' }, fmt(sum[v].median, 1), el('small', {}, ' median err / kloc'))));
  }
  const c = D.cleanestRun(rows);
  if (c) row.appendChild(el('div', { class: 'stat wide' }, el('div', { class: 'k' }, 'cleanest pass'),
    el('div', { class: 'v' }, c.short, el('small', {}, ` ${fmt(c.struggle.errors_per_kloc, 1)} err / kloc · ${plural(c.struggle.compiles, 'build')} · ${fmt(c.struggle.loc, 0)} lines`))));
}
let resizeFns = [];
function onResize(fn) {
  resizeFns.push(fn);
  if (resizeFns.length === 1) { let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => resizeFns.forEach((f) => f()), 150); }); }
}

// ----------------------------------------------------------------- test 3
function renderTest3(data) {
  const { groups, flavors, rubricMax } = D.test3Groups(data);
  const lede = $('test3-lede');
  const t = D.testOf(data, '3');
  // the flavours, as the data names them, make the one line under the title
  lede.textContent = flavors.length ? flavors.map((f) => `${f}: ${/G$/i.test(f) ? 'known-good server' : /O$/i.test(f) ? "the model's own server" : 'flavour'}`).join(' · ') : (t.what || '');
  const host = $('test3-groups');
  const head = el('div', { class: 't3-head', 'aria-hidden': 'true' }, el('span', {}), el('span', {}, 'MCP facts'), el('span', {}, 'API facts'), el('span', {}, 'rubric'), el('span', {}, 'judged'), el('span', { class: 'num' }, 'speed · time'));
  revealList(host, groups, (g) => el('article', { class: 't3', style: { '--c': g.color } },
    el('div', { class: 'head' }, el('b', {}, g.short), el('div', { class: 'chips' }, familyChip(g.family, g.color), g.uncensored ? kindChip('uncensored') : null)),
    el('div', { class: 'flavors' }, ...g.rows.map((row) => {
      const [note, noteBtn] = noteBlock(row.note);
      const judge = row.judgement_right === true ? 'ok' : row.judgement_right === false ? 'bad' : '';
      return el('div', { class: 't3-row' },
        el('span', { class: 'flavor', title: `flavor ${row.flavor}` }, row.flavor),
        el('span', { class: 'cell' }, pips(row.mcp_facts.got, row.mcp_facts.of), el('small', {}, row.mcp_facts.text)),
        el('span', { class: 'cell' }, pips(row.api_facts.got, row.api_facts.of, 'api'), el('small', {}, row.api_facts.text)),
        el('span', { class: 'cell' }, pips(row.rubric, rubricMax, 'rubric'), el('small', { class: 'rubric-num' }, ofMax(row.rubric, rubricMax))),
        el('span', { class: `judge ${judge}`, role: 'img', 'aria-label': judge === 'ok' ? 'judged the server right' : judge === 'bad' ? 'misjudged the server' : 'judgement not recorded', title: judge === 'ok' ? 'judged the server right' : judge === 'bad' ? 'misjudged the server' : 'judgement not recorded' }, judge === 'ok' ? '✓' : judge === 'bad' ? '✗' : '·'),
        el('span', { class: 'num' }, `${fmt(row.tps, 1)} tok/s · ${fmtMinutes(row.minutes)}`, noteBtn),
        note);
    }))), { step: 8, label: 'Show more models' });
  if (groups.length) host.insertBefore(head, host.firstChild);
}

// -------------------------------------------------------------------- A/B
function renderAB(data) {
  const { groups, engines, colors, max } = D.abGroups(data);
  const legend = $('ab-legend'); clear(legend);
  for (const e of engines) legend.appendChild(el('li', {}, el('i', { style: { '--c': colors.get(e) }, 'aria-hidden': 'true' }), e));
  const host = $('ab-groups'); clear(host);
  if (!groups.length) { host.appendChild(el('p', { class: 'empty' }, 'No engine probes yet.')); return; }
  for (const g of groups.filter((g) => !g.allFailed)) host.appendChild(abDumbbell(g, max, colors));
  const failed = data.ab.filter((r) => r.decode == null);
  if (failed.length) {
    host.appendChild(el('details', { class: 'ab-errors fold' }, el('summary', {}, `${plural(failed.length, 'probe')} failed to load`),
      el('ul', {}, ...failed.map((r) => el('li', {}, el('b', {}, D.shortLabel(D.modelOf(data, r.model).label)), ` · ${r.engine} · ${r.variant}: `, el('code', {}, r.error.slice(0, 160) || 'no error text'))))));
  }
}

// ---------------------------------------------------------------- gallery
function renderOneshots(data) {
  const sets = D.oneshotSets(data);
  const setRow = $('oneshot-sets'); clear(setRow);
  const n = (v, k) => el('span', { class: 'sn' }, el('b', {}, fmt(v, v != null && v < 10 && v % 1 ? 1 : 0)), ' ', k);
  for (const s of sets) {
    setRow.appendChild(el('div', { class: `set-card ${(s.kind || '').replace(/[^a-z-]/gi, '')}` },
      el('div', { class: 'set-head' }, el('b', {}, s.label), kindChip(`test ${s.test}`)),
      el('div', { class: 'set-nums' }, n(s.n, 'pieces'), s.live > 0 ? el('span', { class: 'sn live-n' }, el('i', { 'aria-hidden': 'true' }, '▶'), el('b', {}, fmt(s.live, 0)), ' live') : null,
        s.mean != null ? n(s.mean, `mean of ${fmt(s.max, 0)}`) : null, n(s.full, 'full'), n(s.zero, 'zero'), s.cut ? n(s.cut, 'cut') : null)));
  }
  renderPairs(data);
  const tsel = $('o-test'); clear(tsel); tsel.appendChild(el('option', { value: 'all' }, 'all'));
  for (const s of sets) tsel.appendChild(el('option', { value: s.set }, `${s.label} · test ${s.test}`));
  const form = $('oneshot-filters');
  const grid = $('oneshot-grid');
  let current = [];
  const draw = () => {
    const cards = D.oneshotCards(data, { test: tsel.value, sort: $('o-sort').value, q: $('o-q').value.trim() });
    current = cards;
    const live = cards.filter((c) => c.live).length;
    $('o-count').textContent = `${cards.length} pieces${live ? ` · ${live} live` : ''}`;
    revealList(grid, cards, (c, i) => shotCard(c, () => openViewerAt(current, i)), { step: 12, label: 'Show more' });
  };
  const openViewerAt = (cards, i) => { const btn = grid.querySelector(`.shot[data-case="${CSS.escape(cards[i].case)}"] .play`); openViewer(cards, i, btn); };
  form.addEventListener('input', draw);
  form.addEventListener('submit', (e) => e.preventDefault());
  draw();
  startFlipbooks(grid);
}
// One shot against agent: one paired chart per agent set, drawn from the same rows as the gallery.
function renderPairs(data) {
  const panels = D.agentPairs(data);
  const block = $('agent'), host = $('pairs'), lede = $('pairs-lede');
  clear(host);
  block.hidden = !panels.length;
  if (!panels.length) return;
  lede.textContent = 'Same model, same rubric; best of n one-shots.';
  const draw = () => {
    clear(host);
    const figs = panels.map((p) => {
      const fig = el('figure', { class: 'pair-fig' });
      fig.append(el('figcaption', {}, el('b', {}, p.baseLabel), el('span', { class: 'arrow' }, ' → '), el('b', {}, p.label),
        el('span', { class: 'pair-stat' }, `mean ${p.meanOneshot == null ? '–' : fmt(p.meanOneshot)} → ${p.meanAgent == null ? '–' : fmt(p.meanAgent)} · ${p.lifted} of ${p.paired} up`)));
      host.appendChild(fig);
      return fig;
    });
    // every figure is in the grid now, so each chart takes the width its figure really has (one or two columns)
    panels.forEach((p, i) => figs[i].appendChild(pairDumbbell(p, Math.max(280, figs[i].clientWidth - 22))));
  };
  draw();
  onResize(draw);
}
const blankCard = (c) => el('div', { class: 'blank' }, el('span', {}, el('i', { 'aria-hidden': 'true' }, '∅'), /length|cap/i.test(c.finish) ? 'cut off, nothing to render' : c.frames.length ? 'renders could not be loaded' : 'no render'));
function shotCard(c, onPlay) {
  const pic = el('div', { class: 'pic' });
  const frames = c.frames;
  const square = /orrery/i.test(c.set);
  if (frames.length) {
    const last = frames.length - 1;
    let failed = 0;
    // The last frame is the richest, so it is shown first and fetched eagerly; the others load lazily and the
    // flipbook only ever advances onto a frame that has really loaded. If none loads the card goes blank.
    const imgs = frames.map((f, i) => {
      const im = el('img', { src: f.url, alt: `${c.alt}, frame at ${f.ms == null ? '?' : fmt(f.ms, 0)} ms`, loading: i === last ? 'eager' : 'lazy', decoding: 'async', width: square ? 1000 : 1280, height: square ? 1000 : 800, class: i === last ? 'on' : '' });
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
  const [note, noteBtn] = noteBlock(c.note);
  const body = el('div', { class: 'body' },
    el('div', {}, el('b', {}, c.short), el('div', { class: 'meta' }, familyChip(c.family, c.color), kindChip(c.setLabel, c.kind === 'agentic' ? 'agentic' : ''), c.uncensored ? kindChip('uncensored') : null,
      el('span', {}, `${fmt(c.tok_s, 1)} tok/s`), /length|cap/i.test(c.finish) ? el('span', { class: 'cut' }, c.finish === 'length' ? 'hit the cap' : c.finish) : null, noteBtn)),
    petalScore(c), note);
  return el('article', { class: `shot${c.full && frames.length ? ' featured' : ''}${c.live ? ' playable' : ''}`, title: c.case, 'data-case': c.case, style: { '--c': c.color } }, pic, body);
}
// A grader's or operator's note, folded away behind a "note" toggle. Returns [p, button] or [null, null].
function noteBlock(text) {
  if (!text) return [null, null];
  const p = el('p', { class: 'note', hidden: true }, text);
  const b = el('button', { type: 'button', class: 'noteb', 'aria-expanded': 'false' }, 'note');
  b.addEventListener('click', () => { p.hidden = !p.hidden; b.setAttribute('aria-expanded', String(!p.hidden)); b.classList.toggle('open', !p.hidden); });
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
// A card leads with its numbers: the first metric as big numerals, the rest as before/after bars. The summary is
// its first sentence; the full text, settings, quality check and caveat fold away.
function renderFindings(data) {
  const host = $('findings-list');
  revealList(host, data.findings, (f) => {
    const metrics = D.findingMetrics(f);
    const right = el('div', { class: 'numbers' });
    if (metrics.length) {
      const lead = metrics.find((m) => m.after != null) || metrics[0];
      right.appendChild(bigNumeral(lead));
      for (const m of metrics.filter((m) => m !== lead)) right.appendChild(beforeAfter(m));
    }
    const line = D.firstSentence(f.summary);
    const more = disclosure('details', '',
      f.summary && f.summary !== line ? el('p', {}, f.summary) : null,
      f.settings ? el('p', { class: 'settings' }, 'settings ', el('code', {}, f.settings)) : null,
      f.quality ? el('p', { class: 'quality', 'data-k': 'quality check' }, f.quality) : null,
      f.caveat ? el('p', { class: 'caveat', 'data-k': 'caveat' }, f.caveat) : null);
    return el('article', { class: 'finding' },
      el('div', { class: 'when' }, f.date ? el('time', { datetime: f.date }, fmtDate(f.date)) : null, kindChip(f.kind)),
      el('h3', {}, f.title),
      el('div', { class: 'text' }, line ? el('p', { class: 'summary' }, line) : null, more),
      right);
  }, { step: 8, label: 'Show more findings' });
  if (!data.findings.length) { clear(host); host.appendChild(el('p', { class: 'empty' }, 'No headline findings yet.')); }
}

// --------------------------------------------------------------- timeline
// Date, title, the what line; a month mark where the month turns; why on hover, focus or the toggle.
function renderTimeline(data) {
  const ol = $('timeline-list'); clear(ol);
  if (!data.timeline.length) { ol.appendChild(el('li', { class: 'empty' }, 'No timeline yet.')); return; }
  let month = '';
  for (const t of data.timeline) {
    const m = t.date.slice(0, 7);
    if (m && m !== month) { month = m; ol.appendChild(el('li', { class: 'month', 'aria-hidden': 'true' }, el('span', {}, monthName(m)))); }
    const why = t.why ? el('p', { class: 'why' }, t.why) : null;
    const btn = why ? el('button', { type: 'button', class: 'noteb why-b', 'aria-expanded': 'false' }, 'why') : null;
    const li = el('li', {},
      el('div', { class: 'date' }, t.date ? el('time', { datetime: t.date }, dayLabel(t.date)) : null, t.era ? el('span', { class: 'era' }, t.era) : null),
      el('h3', {}, t.title), t.what ? el('p', { class: 'what' }, t.what, ' ', btn) : btn, why);
    if (btn) btn.addEventListener('click', () => { const open = li.classList.toggle('open'); btn.setAttribute('aria-expanded', String(open)); });
    ol.appendChild(li);
  }
}
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const monthName = (ym) => { const m = ym.match(/^(\d{4})-(\d{2})/); return m ? `${MONTHS[+m[2] - 1] || m[2]} ${m[1]}` : ym; };
const dayLabel = (d) => { const m = d.match(/^\d{4}-(\d{2})-(\d{2})/); return m ? `${(MONTHS[+m[1] - 1] || m[1]).slice(0, 3)} ${+m[2]}` : fmtDate(d); };

// ------------------------------------------------------------------ footer
function renderFoot(data) {
  const ol = $('caveat-list'); clear(ol);
  $('caveats-summary').textContent = data.caveats.length ? `${plural(data.caveats.length, 'caveat')}, read before quoting a number` : 'Caveats';
  if (!data.caveats.length) ol.appendChild(el('li', {}, 'No caveats are recorded in the data. Treat every number as one sample from a changing harness.'));
  for (const c of data.caveats) ol.appendChild(el('li', {}, c));
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
