// Pure data derivation for the Bake-off site. No DOM here: site/tools/check_site.mjs runs these
// functions in node against the real JSON and against mutated copies, so every function must
// tolerate missing fields, nulls, empty lists, unknown tests and unknown model ids.

// Frame paths: relative, under frames/, every segment starts with a letter/digit/_/- (so "." and ".." segments and
// dot-files are impossible), no "//", and the lookahead rejects ".." anywhere at all.
export const FRAME_RE = /^(?!.*\.\.)frames\/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*\/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\.webp$/;
// Live pieces (the model's own one-shot file, run only inside a sandboxed iframe): exactly live/<set>/<case>/<file>
// with the two known sets and file names, one case segment of safe characters, and never ".." anywhere.
export const LIVE_RE = /^live\/(pagoda|orrery)\/[A-Za-z0-9._-]+\/(page\.html|orrery\.svg)$/;
export const REPO_PREFIX = 'https://github.com/alexderz/agentic-model-testing';
export const OTHER_FAMILIES = new Set(['other', 'unknown', '']);
export const OTHER_COLOR = '#8a94a8'; // neutral silver for Other/Unknown; never handed to a real family
// Jewel hues validated on the page's #0c1222 background; families past these get generated hues (colorSeries).
export const JEWELS = ['#12a195', '#c08f0a', '#5283fe', '#df4b9d', '#06a84e', '#a167f1', '#ec4f27', '#0f99c9'];
export const ENGINE_BASE = ['#a98bff', '#2ec4b6', '#f2c14e', '#ff6bb5', '#6c8dff', '#06a84e', '#ec4f27', '#0f99c9'];

export const arr = (x) => (Array.isArray(x) ? x : []);
export const obj = (x) => (x && typeof x === 'object' && !Array.isArray(x) ? x : {});
export const str = (x) => (x == null ? '' : String(x));
export function num(x) {
  if (typeof x === 'number') return Number.isFinite(x) ? x : null;
  if (typeof x === 'string' && x.trim() !== '' && Number.isFinite(+x)) return +x;
  return null;
}
export const isFrameUrl = (s) => typeof s === 'string' && FRAME_RE.test(s);
export const isLiveUrl = (s) => typeof s === 'string' && !s.includes('..') && LIVE_RE.test(s);
// Exactly the repository, or the repository followed by "/", "#" or "?". Nothing with "..", whitespace or quotes.
export function isRepoUrl(s) {
  if (typeof s !== 'string' || !s.startsWith(REPO_PREFIX)) return false;
  if (/[\s<>"'\\]/.test(s) || s.includes('..')) return false;
  const next = s.charAt(REPO_PREFIX.length);
  return next === '' || next === '/' || next === '#' || next === '?';
}

// digits = null picks one decimal below 10 and none above; pass a number to force it.
export function fmt(n, digits = null) {
  const v = num(n);
  if (v == null) return '–';
  const d = digits != null ? digits : Math.abs(v) < 10 ? 1 : 0;
  return v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 });
}
export function fmtMinutes(m) {
  const v = num(m);
  if (v == null) return '–';
  if (v < 60) return `${fmt(v, 0)} min`;
  const h = Math.floor(v / 60), r = Math.round(v - h * 60);
  return r ? `${h} h ${r} min` : `${h} h`;
}
export function fmtDate(s) {
  const t = str(s).trim();
  const m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return t;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const mi = +m[2] - 1;
  return `${months[mi] || m[2]} ${+m[3]}, ${m[1]}`;
}
export const shortLabel = (label) => str(label).split(' · ')[0].trim();
export const frameMs = (url) => { const m = str(url).match(/(\d+)\.webp$/); return m ? +m[1] : null; };
// Deterministic 0..1 from a string (FNV-1a); used to scatter decorative marks without Math.random.
export function hash01(s) {
  let h = 0x811c9dc5;
  for (const ch of str(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return (h % 100000) / 100000;
}

// ------------------------------------------------------------------ colours
function hexHue(hex) {
  const m = str(hex).match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (!m) return 0;
  const [r, g, b] = [1, 2, 3].map((i) => parseInt(m[i], 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (!d) return 0;
  let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h *= 60; return h < 0 ? h + 360 : h;
}
// n distinct colours: the base list first, then hues dropped into the widest gap on the wheel, so adding an item
// never recolours the ones before it. Works for any n; distinctness degrades gracefully.
export function colorSeries(n, base = JEWELS) {
  const out = base.slice(0, Math.max(0, n));
  const hues = out.map(hexHue);
  let k = 0;
  while (out.length < n) {
    const sorted = [...hues].sort((a, b) => a - b);
    let best = -1, h = 30;
    for (let i = 0; i < sorted.length; i++) {
      const a = sorted[i], b = i + 1 < sorted.length ? sorted[i + 1] : sorted[0] + 360;
      if (b - a > best) { best = b - a; h = ((a + b) / 2) % 360; }
    }
    hues.push(h);
    out.push(`hsl(${Math.round(h)} ${k % 2 ? 60 : 72}% ${k % 2 ? 50 : 61}%)`);
    k++;
  }
  return out;
}

// ---------------------------------------------------------------- normalize
export function normalize(raw) {
  const d = obj(raw);
  const picks = obj(d.picks);
  const models = {};
  for (const [k, v] of Object.entries(obj(d.models))) {
    const m = obj(v);
    models[k] = {
      id: str(m.id || k), family: str(m.family) || 'Other', label: str(m.label) || str(m.id || k),
      base: str(m.base), arch: str(m.arch), engine: str(m.engine), quant: str(m.quant), kind: str(m.kind) || 'stock',
      uncensored: m.uncensored === true, note: str(m.note),
      vision: m.vision ? { label: str(obj(m.vision).label), status: str(obj(m.vision).status) } : null,
    };
  }
  const runs = arr(d.runs).filter((r) => r && typeof r === 'object').map((r) => ({
    case: str(r.case), model: str(r.model), test: testKey(r.test), agent: str(r.agent),
    checks: num(r.checks), tests_pass: num(r.tests_pass), tests_fail: num(r.tests_fail), subcmds: num(r.subcmds),
    tps: num(r.tps), minutes: num(r.minutes), compactions: num(r.compactions), ctx: num(r.ctx), kv: str(r.kv),
    verdict: str(r.verdict).toLowerCase() || 'unknown', finished: str(r.finished),
    flavor: str(r.flavor) || (/^wt-/.test(str(r.case)) ? '2T' : ''), // wished field; today read from the case prefix
    struggle: r.struggle ? {
      compiles: num(obj(r.struggle).compiles), failed_compiles: num(obj(r.struggle).failed_compiles),
      rust_errors: num(obj(r.struggle).rust_errors), loc: num(obj(r.struggle).loc), errors_per_kloc: num(obj(r.struggle).errors_per_kloc),
    } : null,
  }));
  const test3 = arr(d.test3).filter((r) => r && typeof r === 'object').map((r) => ({
    case: str(r.case), model: str(r.model), flavor: str(r.flavor) || '?', mcp_facts: parseFacts(r.mcp_facts), api_facts: parseFacts(r.api_facts),
    judgement_right: r.judgement_right === true ? true : r.judgement_right === false ? false : null,
    rubric: num(r.rubric), note: str(r.note), tps: num(r.tps), minutes: num(r.minutes), finished: str(r.finished),
  }));
  const ab = arr(d.ab).filter((r) => r && typeof r === 'object').map((r) => ({
    model: str(r.model), engine: str(r.engine) || '?', variant: str(r.variant) || 'same flags',
    decode: num(r.decode), quote: num(r.quote), prefill: num(r.prefill), vram: num(r.vram), error: str(r.error),
  }));
  const oneshots = {};
  for (const [k, v] of Object.entries(obj(d.oneshots))) {
    oneshots[k] = arr(v).filter((r) => r && typeof r === 'object').map((r) => {
      const pts = obj(r.points);
      const points = Object.keys(pts).sort().map((p) => ({ key: str(p), value: num(pts[p]) }));
      let total = num(r.total);
      if (total == null && points.length) total = points.reduce((s, p) => s + (p.value || 0), 0);
      return {
        case: str(r.case), entry: str(r.entry), test: testKey(r.test), finish: str(r.finish), tokens: num(r.tokens),
        wall_s: num(r.wall_s), tok_s: num(r.tok_s), points, total,
        note: str(r.note), frames: arr(r.frames).filter(isFrameUrl).map((f) => ({ url: f, ms: frameMs(f) })),
        live: isLiveUrl(r.live) ? r.live : null, // anything that fails the allow-list gets no Play control
      };
    });
  }
  const tests = arr(d.tests).filter((t) => t && typeof t === 'object').map((t) => ({
    id: str(t.id) || `t${str(t.number)}`, number: str(t.number), name: str(t.name) || `Test ${str(t.number)}`,
    kind: str(t.kind), what: str(t.what), graded: str(t.graded), points: arr(t.points).map(str),
    // optional scale overrides; otherwise the page uses the largest value seen in the data
    max_checks: pos(num(t.max_checks)), max_point: pos(num(t.max_point)), max_rubric: pos(num(t.max_rubric)),
  }));
  return {
    schema: str(d.schema), generated: str(d.generated), built: str(d.built), title: str(d.title) || 'The Bake-off', tagline: str(d.tagline),
    links: Object.fromEntries(Object.entries(obj(d.links)).filter(([, v]) => isRepoUrl(v))),
    hardware: Object.fromEntries(Object.entries(obj(d.hardware)).map(([k, v]) => [k, str(v)]).filter(([, v]) => v)),
    caveats: arr(d.caveats).map(str).filter(Boolean),
    tests, findings: arr(d.findings).filter((f) => f && typeof f === 'object').map((f) => ({
      date: str(f.date), title: str(f.title) || 'Finding', kind: str(f.kind) || 'finding', summary: str(f.summary), settings: str(f.settings),
      metrics: arr(f.metrics).filter((m) => m && typeof m === 'object').map((m) => ({ label: str(m.label), before: num(m.before), after: num(m.after), unit: str(m.unit) })),
      quality: str(f.quality), caveat: str(f.caveat),
    })),
    picks: {
      overall: arr(picks.overall).filter((p) => p && typeof p === 'object').map(normPick),
      uncensored: arr(picks.uncensored).filter((p) => p && typeof p === 'object').map(normPick),
      families: arr(picks.families).filter((p) => p && typeof p === 'object').map((p) => ({
        family: str(p.family) || 'Other', smartest: str(p.smartest), fastest: str(p.fastest),
        unc_smartest: str(p.unc_smartest), unc_fastest: str(p.unc_fastest), note: str(p.note),
      })),
    },
    timeline: arr(d.timeline).filter((t) => t && typeof t === 'object').map((t) => ({
      date: str(t.date), era: str(t.era), title: str(t.title) || str(t.era) || 'Step', what: str(t.what), why: str(t.why),
    })).sort((a, b) => a.date.localeCompare(b.date)),
    events: arr(d.events).filter((e) => e && typeof e === 'object').map((e) => ({ when: str(e.when), kind: str(e.kind) || 'note', text: str(e.text) }))
      .filter((e) => e.text).sort((a, b) => b.when.localeCompare(a.when)),
    models, runs, test3, ab, oneshots, counts: obj(d.counts),
  };
}
const pos = (v) => (v != null && v > 0 ? v : null);
function normPick(p) {
  return { role: str(p.role) || 'Pick', model: str(p.model), verdict: str(p.verdict), tradeoff: str(p.tradeoff), cases: arr(p.cases).map(str) };
}
export function testKey(t) {
  if (t == null || t === '') return '?';
  return str(t).trim();
}
export function parseFacts(s) {
  const t = str(s).trim();
  const m = t.match(/^(\d+)\s*\/\s*(\d+)$/);
  if (m) return { got: +m[1], of: +m[2], text: t };
  const n = num(t);
  return { got: n, of: null, text: t || '–' };
}

// ------------------------------------------------------------------ lookups
export function modelOf(data, id) {
  const m = obj(data.models)[id];
  if (m) return m;
  return { id: str(id) || '?', family: 'Unknown', label: str(id) || 'unknown model', base: '', arch: '', engine: '', quant: '', kind: 'unknown', uncensored: false, note: '', vision: null, missing: true };
}
export function testOf(data, key) {
  const k = testKey(key);
  return arr(data.tests).find((t) => t.number === k || t.id === k || t.id === `t${k}`) || { id: `t${k}`, number: k, name: `Test ${k}`, kind: '', what: '', graded: '', points: [], max_checks: null, max_point: null, max_rubric: null };
}
// A run belongs to its flavor when it has one (2T), else to its test number. Every run has exactly one.
export const effectiveTest = (r) => r.flavor || r.test;

// Family order: the curated picks order first (so colours stay put as models arrive), then the rest alphabetically.
export function familyOrder(data) {
  const seen = new Set(), out = [];
  const push = (f) => { const k = str(f) || 'Other'; if (!seen.has(k)) { seen.add(k); out.push(k); } };
  for (const p of arr(data.picks && data.picks.families)) push(p.family);
  const rest = [...new Set(Object.values(obj(data.models)).map((m) => m.family))].filter((f) => !seen.has(f)).sort();
  for (const f of rest) push(f);
  for (const r of arr(data.runs)) push(modelOf(data, r.model).family);
  return out;
}
// Every real family gets its own colour; Other/Unknown share the neutral silver.
export function familyColors(data) {
  const order = familyOrder(data);
  const real = order.filter((f) => !OTHER_FAMILIES.has(f.toLowerCase()));
  const cols = colorSeries(real.length);
  const map = new Map(real.map((f, i) => [f, cols[i]]));
  for (const f of order) if (!map.has(f)) map.set(f, OTHER_COLOR);
  return map;
}
export const colorOf = (colors, family) => (colors && colors.has(family) ? colors.get(family) : OTHER_COLOR);

// ------------------------------------------------------------------- scales
// "n of m" scales come from the data: an optional tests[].max_* field, else the largest value seen.
export function checksMax(data, test) {
  const t = testOf(data, test);
  if (t.max_checks != null) return t.max_checks;
  const k = testKey(test);
  const seen = arr(data.runs).filter((r) => r.test === k || r.flavor === k).map((r) => r.checks).filter((v) => v != null);
  return seen.length ? Math.max(...seen) : null;
}
export function pointMax(data, test) {
  const t = testOf(data, test);
  if (t.max_point != null) return t.max_point;
  const k = testKey(test);
  const rows = Object.values(obj(data.oneshots)).flat();
  const of = (list) => list.flatMap((r) => r.points.map((p) => p.value)).filter((v) => v != null && v > 0);
  const own = of(rows.filter((r) => r.test === k)), any = of(rows);
  return own.length ? Math.max(...own) : any.length ? Math.max(...any) : 1;
}
export function rubricMax(data) {
  const t = testOf(data, '3');
  if (t.max_rubric != null) return t.max_rubric;
  const seen = arr(data.test3).map((r) => r.rubric).filter((v) => v != null && v > 0);
  return seen.length ? Math.max(...seen) : 1;
}

// ------------------------------------------------------------------ summary
export function summary(data) {
  const runs = arr(data.runs);
  const models = Object.keys(obj(data.models));
  const oneshotRows = Object.values(obj(data.oneshots)).flat();
  const frames = oneshotRows.reduce((s, r) => s + r.frames.length, 0);
  const playable = oneshotRows.filter((r) => r.live).length;
  const passes = runs.filter((r) => r.verdict === 'pass').length;
  const tps = runs.map((r) => r.tps).filter((v) => v != null);
  const dates = [...runs.map((r) => r.finished), ...arr(data.test3).map((r) => r.finished)].filter(Boolean).sort();
  const findingDates = arr(data.findings).map((f) => f.date).filter(Boolean).sort();
  const families = familyOrder(data).filter((f) => !OTHER_FAMILIES.has(f.toLowerCase()));
  const minutes = runs.reduce((s, r) => s + (r.minutes || 0), 0) + arr(data.test3).reduce((s, r) => s + (r.minutes || 0), 0);
  return {
    models: models.length, families: families.length, runs: runs.length, passes, test3: arr(data.test3).length,
    oneshots: oneshotRows.length, frames, playable, uncensored: models.filter((m) => data.models[m].uncensored).length,
    fastest: tps.length ? Math.max(...tps) : null, slowest: tps.length ? Math.min(...tps) : null,
    first: dates[0] || '', last: dates[dates.length - 1] || '', newestFinding: findingDates[findingDates.length - 1] || '', agentHours: minutes / 60,
    tests: new Set([...runs.map(effectiveTest), ...arr(data.test3).length ? ['3'] : [], ...oneshotRows.map((r) => r.test)]).size,
  };
}
// Each run is counted once, under its flavor when it has one; test 3 rows and one-shot replies under their test.
export function testCount(data, number) {
  const k = testKey(number);
  let n = arr(data.runs).filter((r) => effectiveTest(r) === k).length;
  if (k === '3') n += arr(data.test3).length;
  for (const rows of Object.values(obj(data.oneshots))) n += rows.filter((r) => r.test === k).length;
  return n;
}

// --------------------------------------------------------------------- hero
export function heroPlanets(data) {
  const colors = familyColors(data);
  const byModel = new Map();
  const touch = (id) => { if (!byModel.has(id)) byModel.set(id, { runs: 0, tps: [], passed2: false, test3: 0, oneshots: 0 }); return byModel.get(id); };
  for (const r of arr(data.runs)) { const m = touch(r.model); m.runs++; if (r.tps != null) m.tps.push(r.tps); if (r.test === '2' && r.verdict === 'pass') m.passed2 = true; }
  for (const r of arr(data.test3)) { const m = touch(r.model); m.test3++; if (r.tps != null) m.tps.push(r.tps); }
  for (const rows of Object.values(obj(data.oneshots))) for (const r of rows) { const m = touch(r.entry); m.oneshots++; if (r.tok_s != null) m.tps.push(r.tok_s); }
  const ids = new Set([...Object.keys(obj(data.models)), ...byModel.keys()]);
  const planets = [];
  for (const id of ids) {
    const m = modelOf(data, id), s = byModel.get(id) || { runs: 0, tps: [], passed2: false, test3: 0, oneshots: 0 };
    const appearances = s.runs + s.test3 + s.oneshots;
    planets.push({
      id, label: m.label, short: shortLabel(m.label), family: m.family, color: colorOf(colors, m.family), uncensored: m.uncensored,
      appearances, runs: s.runs, bestTps: s.tps.length ? Math.max(...s.tps) : null, passed2: s.passed2,
    });
  }
  planets.sort((a, b) => (b.bestTps || 0) - (a.bestTps || 0) || a.id.localeCompare(b.id));
  return planets;
}
// Orbit layout: one band per family, planets spread within the band, period from speed.
export function heroLayout(planets, { rMin = 70, rMax = 300 } = {}) {
  const fams = [...new Set(planets.map((p) => p.family))];
  fams.sort((a, b) => planets.filter((p) => p.family === b).length - planets.filter((p) => p.family === a).length || a.localeCompare(b));
  const bands = fams.length || 1, bandW = (rMax - rMin) / bands;
  const out = [];
  fams.forEach((f, bi) => {
    const list = planets.filter((p) => p.family === f);
    const r0 = rMin + bi * bandW;
    list.forEach((p, i) => {
      const r = r0 + bandW * ((i + 0.5) / list.length);
      const tps = p.bestTps == null ? 2 : Math.max(1, p.bestTps);
      const period = 120 / Math.sqrt(tps); // seconds per orbit: 3 tok/s ≈ 69 s, 170 tok/s ≈ 9 s
      const size = 2.2 + Math.min(6, Math.sqrt(p.appearances) * 1.4);
      const angle0 = ((i * 137.508) + bi * 61) % 360; // golden-angle spread
      out.push({ ...p, r, period, size, angle0, band: bi, bandLabel: f });
    });
  });
  return { planets: out, bands: fams.map((f, i) => ({ family: f, color: (planets.find((p) => p.family === f) || {}).color || OTHER_COLOR, r0: rMin + i * bandW, r1: rMin + (i + 1) * bandW })) };
}

// --------------------------------------------------------------------- runs
export function runFilterOptions(data) {
  const runs = arr(data.runs);
  const tests = [...new Set(runs.flatMap((r) => (r.flavor ? [r.test, r.flavor] : [r.test])))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const families = familyOrder(data).filter((f) => runs.some((r) => modelOf(data, r.model).family === f));
  const verdicts = [...new Set(runs.map((r) => r.verdict))].sort();
  const agents = [...new Set(runs.map((r) => r.agent).filter(Boolean))].sort();
  return { tests, families, verdicts, agents };
}
export function runRows(data, filters = {}, sort = 'tps') {
  const colors = familyColors(data);
  const cmax = new Map();
  let rows = arr(data.runs).map((r) => {
    const m = modelOf(data, r.model);
    if (!cmax.has(r.test)) cmax.set(r.test, checksMax(data, r.test));
    return { ...r, modelLabel: m.label, short: shortLabel(m.label), family: m.family, color: colorOf(colors, m.family), uncensored: m.uncensored, engine: m.engine, quant: m.quant, checksMax: cmax.get(r.test) };
  });
  // the test filter keeps a flavor inside its parent test ("2" shows 2 and 2T; "2T" shows only 2T)
  if (filters.test && filters.test !== 'all') rows = rows.filter((r) => r.test === filters.test || r.flavor === filters.test);
  if (filters.family && filters.family !== 'all') rows = rows.filter((r) => r.family === filters.family);
  if (filters.verdict && filters.verdict !== 'all') rows = rows.filter((r) => r.verdict === filters.verdict);
  if (filters.uncensored === 'yes') rows = rows.filter((r) => r.uncensored);
  if (filters.uncensored === 'no') rows = rows.filter((r) => !r.uncensored);
  if (filters.q) { const q = filters.q.toLowerCase(); rows = rows.filter((r) => (r.modelLabel + ' ' + r.case + ' ' + r.engine).toLowerCase().includes(q)); }
  const cmp = {
    tps: (a, b) => (b.tps || 0) - (a.tps || 0),
    minutes: (a, b) => (a.minutes || Infinity) - (b.minutes || Infinity),
    tests: (a, b) => (b.tests_pass || 0) - (a.tests_pass || 0),
    verdict: (a, b) => verdictRank(a.verdict) - verdictRank(b.verdict) || (b.checks || 0) - (a.checks || 0) || (b.tps || 0) - (a.tps || 0),
    finished: (a, b) => b.finished.localeCompare(a.finished),
    clean: (a, b) => epk(a) - epk(b),
  }[sort] || ((a, b) => (b.tps || 0) - (a.tps || 0));
  return rows.sort(cmp);
}
const epk = (r) => (r.struggle && r.struggle.errors_per_kloc != null ? r.struggle.errors_per_kloc : Infinity);
export const verdictRank = (v) => ({ pass: 0, partial: 1, fail: 2 }[v] ?? 3);
export function logScale(values, pad = 1.15) {
  const vs = values.filter((v) => v != null && v > 0);
  if (!vs.length) return { min: 1, max: 10, pos: () => 0 };
  const min = Math.min(...vs) / pad, max = Math.max(...vs) * pad;
  const lmin = Math.log(min), lmax = Math.log(max) || lmin + 1;
  return { min, max, pos: (v) => (v == null || v <= 0 ? 0 : Math.max(0, Math.min(1, (Math.log(v) - lmin) / (lmax - lmin || 1)))) };
}
export function logTicks(scale) {
  const out = [];
  for (const base of [1, 10, 100, 1000, 10000]) for (const k of [1, 2, 5]) { const v = base * k; if (v >= scale.min && v <= scale.max) out.push(v); }
  return out;
}

// ----------------------------------------------------------------- struggle
export function struggleRows(data) {
  return runRows(data, { test: '2' }, 'clean').filter((r) => r.struggle && r.struggle.errors_per_kloc != null && r.struggle.errors_per_kloc >= 0);
}
export function struggleSummary(rows) {
  const by = {};
  for (const r of rows) { (by[r.verdict] ||= []).push(r.struggle.errors_per_kloc); }
  return Object.fromEntries(Object.entries(by).map(([k, vs]) => { vs.sort((a, b) => a - b); return [k, { n: vs.length, median: vs[Math.floor(vs.length / 2)] }]; }));
}
// The cleanest run is a passing run that actually built something: lines written and at least one compile.
// Ties: fewer failed builds, then more lines.
export function cleanestRun(rows) {
  const ok = rows.filter((r) => r.verdict === 'pass' && r.struggle && (r.struggle.loc || 0) > 0 && (r.struggle.compiles || 0) >= 1 && r.struggle.errors_per_kloc != null);
  ok.sort((a, b) => epk(a) - epk(b) || (a.struggle.failed_compiles || 0) - (b.struggle.failed_compiles || 0) || (b.struggle.loc || 0) - (a.struggle.loc || 0));
  return ok[0] || null;
}

// ------------------------------------------------------------------- test 3
export function test3Groups(data) {
  const colors = familyColors(data);
  const groups = new Map();
  for (const r of arr(data.test3)) {
    const m = modelOf(data, r.model);
    if (!groups.has(r.model)) groups.set(r.model, { model: r.model, label: m.label, short: shortLabel(m.label), family: m.family, color: colorOf(colors, m.family), uncensored: m.uncensored, rows: [], best: 0 });
    const g = groups.get(r.model); g.rows.push(r); g.best = Math.max(g.best, r.rubric || 0);
  }
  const out = [...groups.values()];
  for (const g of out) g.rows.sort((a, b) => a.flavor.localeCompare(b.flavor));
  out.sort((a, b) => b.best - a.best || b.rows.reduce((s, r) => s + (r.rubric || 0), 0) - a.rows.reduce((s, r) => s + (r.rubric || 0), 0) || a.label.localeCompare(b.label));
  const flavors = [...new Set(arr(data.test3).map((r) => r.flavor))].sort();
  return { groups: out, flavors, rubricMax: rubricMax(data) };
}

// ---------------------------------------------------------------------- A/B
// One colour per distinct engine value, in numeric-aware order, so a third engine simply gets a third colour.
export function abGroups(data) {
  const groups = new Map();
  for (const r of arr(data.ab)) {
    const m = modelOf(data, r.model);
    if (!groups.has(r.model)) groups.set(r.model, { model: r.model, label: m.label, short: shortLabel(m.label), rows: [] });
    groups.get(r.model).rows.push(r);
  }
  const engines = [...new Set(arr(data.ab).map((r) => r.engine))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const cols = colorSeries(engines.length, ENGINE_BASE);
  const colors = new Map(engines.map((e, i) => [e, cols[i]]));
  const out = [...groups.values()];
  for (const g of out) {
    g.rows.sort((a, b) => a.engine.localeCompare(b.engine, undefined, { numeric: true }) || a.variant.localeCompare(b.variant));
    const ok = g.rows.filter((r) => r.decode != null);
    g.best = ok.length ? Math.max(...ok.map((r) => r.decode)) : null;
    g.allFailed = ok.length === 0;
    const base = g.rows.filter((r) => r.variant === 'same flags' && r.decode != null).sort((a, b) => a.engine.localeCompare(b.engine, undefined, { numeric: true }));
    g.gain = base.length >= 2 ? base[base.length - 1].decode / base[0].decode : null;
  }
  out.sort((a, b) => (b.best || 0) - (a.best || 0) || a.label.localeCompare(b.label));
  const decodes = arr(data.ab).map((r) => r.decode).filter((v) => v != null);
  return { groups: out, engines, colors, max: decodes.length ? Math.max(...decodes) : 0 };
}

// ----------------------------------------------------------------- oneshots
export function oneshotCards(data, { test = 'all', sort = 'score', q = '' } = {}) {
  const colors = familyColors(data);
  const pmax = new Map();
  let cards = [];
  for (const [set, rows] of Object.entries(obj(data.oneshots))) {
    for (const r of rows) {
      const m = modelOf(data, r.entry), t = testOf(data, r.test);
      if (!pmax.has(r.test)) pmax.set(r.test, pointMax(data, r.test));
      const pointNames = t.points.length ? t.points : [];
      const pointMaxV = pmax.get(r.test);
      const max = r.points.length * pointMaxV;
      cards.push({
        ...r, set, modelLabel: m.label, short: shortLabel(m.label), family: m.family, color: colorOf(colors, m.family), uncensored: m.uncensored,
        testName: t.name, pointMax: pointMaxV, max, full: max > 0 && r.total != null && r.total >= max,
        points: r.points.map((p, i) => ({ ...p, name: pointNames[i] || p.key })),
        alt: `${t.name || `Test ${r.test}`} by ${shortLabel(m.label)}, test ${r.test}`,
      });
    }
  }
  if (test !== 'all') cards = cards.filter((c) => c.test === test || c.set === test);
  if (q) { const s = q.toLowerCase(); cards = cards.filter((c) => (c.modelLabel + ' ' + c.case + ' ' + c.note).toLowerCase().includes(s)); }
  const cmp = {
    score: (a, b) => (b.total || 0) - (a.total || 0) || (b.frames.length - a.frames.length) || (b.tok_s || 0) - (a.tok_s || 0),
    speed: (a, b) => (b.tok_s || 0) - (a.tok_s || 0),
    model: (a, b) => a.modelLabel.localeCompare(b.modelLabel) || (b.total || 0) - (a.total || 0),
    newest: (a, b) => b.case.localeCompare(a.case),
  }[sort] || ((a, b) => (b.total || 0) - (a.total || 0));
  return cards.sort(cmp);
}
export function oneshotSets(data) {
  return Object.entries(obj(data.oneshots)).map(([set, rows]) => {
    const t = rows.length ? testOf(data, rows[0].test) : null;
    const pm = rows.length ? pointMax(data, rows[0].test) : 1;
    const graded = rows.filter((r) => r.total != null);
    return { set, test: rows.length ? rows[0].test : '?', name: t ? t.name : set, n: rows.length, withFrames: rows.filter((r) => r.frames.length).length, live: rows.filter((r) => r.live).length,
      pointMax: pm, full: graded.filter((r) => r.points.length && r.total >= r.points.length * pm).length, zero: graded.filter((r) => r.total === 0).length,
      cut: rows.filter((r) => r.finish === 'length').length, mean: graded.length ? graded.reduce((s, r) => s + r.total, 0) / graded.length : null };
  });
}

// -------------------------------------------------------------------- picks
export function pickCards(data) {
  const colors = familyColors(data);
  const resolve = (p) => {
    const m = modelOf(data, p.model);
    const runs = p.cases.map((c) => arr(data.runs).find((r) => r.case === c)).filter(Boolean).map((r) => ({ ...r, checksMax: checksMax(data, r.test) }));
    return { ...p, modelLabel: m.label, short: shortLabel(m.label), family: m.family, color: colorOf(colors, m.family), uncensored: m.uncensored, engine: m.engine, quant: m.quant, arch: m.arch, missing: !!m.missing, runs };
  };
  return { overall: arr(data.picks.overall).map(resolve), uncensored: arr(data.picks.uncensored).map(resolve) };
}
export function familyPickRows(data) {
  const colors = familyColors(data);
  const name = (id) => (id ? shortLabel(modelOf(data, id).label) : '');
  return arr(data.picks.families).map((f) => ({
    ...f, color: colorOf(colors, f.family), models: Object.values(obj(data.models)).filter((m) => m.family === f.family).length,
    cells: [['Smartest', name(f.smartest)], ['Fastest competent', name(f.fastest)], ['Uncensored, smartest', name(f.unc_smartest)], ['Uncensored, fastest', name(f.unc_fastest)]],
  }));
}

// ------------------------------------------------------------------ findings
export function findingMetrics(f) {
  return arr(f.metrics).map((m) => {
    const max = Math.max(m.before || 0, m.after || 0) || 1;
    return { ...m, beforePct: m.before == null ? null : (m.before / max) * 100, afterPct: m.after == null ? null : (m.after / max) * 100,
      gain: m.before && m.after != null ? m.after / m.before : null };
  });
}
export function eventKinds(data) {
  const c = new Map();
  for (const e of arr(data.events)) c.set(e.kind, (c.get(e.kind) || 0) + 1);
  return [...c.entries()].sort((a, b) => b[1] - a[1]).map(([kind, n]) => ({ kind, n }));
}

// ------------------------------------------------------------------- motifs
// Numbers behind the decorative chapter motifs. Each entry is a plain list the drawing code turns into SVG, so the
// checker exercises them on mutated data. Everything is in 0..1 unless noted.
export function motifs(data) {
  const colors = familyColors(data);
  const runs = arr(data.runs);
  const out = {};
  out.machine = Object.keys(obj(data.hardware)).map((k, i) => ({ key: k, side: i % 2 ? 1 : -1, pos: i }));
  out.tests = arr(data.tests).map((t) => ({ number: t.number, kind: t.kind, n: testCount(data, t.number) }));
  const famCounts = new Map();
  for (const m of Object.values(obj(data.models))) famCounts.set(m.family, (famCounts.get(m.family) || 0) + 1);
  const famTotal = [...famCounts.values()].reduce((s, n) => s + n, 0) || 1;
  out.picks = familyOrder(data).filter((f) => famCounts.has(f)).map((f) => ({ family: f, color: colorOf(colors, f), share: famCounts.get(f) / famTotal }));
  const scale = logScale(runs.map((r) => r.tps));
  const stars = runs.map((r) => ({ x: scale.pos(r.tps), y: hash01(r.case + '|' + r.model), verdict: r.verdict })).filter((s) => s.x != null);
  const links = [];
  for (let i = 0; i < stars.length; i++) {
    let best = -1, bd = 0.06;
    for (let j = 0; j < stars.length; j++) { if (j === i) continue; const d = Math.hypot((stars[i].x - stars[j].x) * 1.6, stars[i].y - stars[j].y); if (d < bd) { bd = d; best = j; } }
    if (best >= 0 && best > i) links.push([i, best]);
  }
  out.runs = { stars, links };
  const epks = struggleRows(data).map((r) => ({ v: Math.log10(1 + Math.max(0, r.struggle.errors_per_kloc)), verdict: r.verdict }));
  const emax = Math.max(0.3, ...epks.map((e) => e.v));
  out.struggle = epks.map((e) => ({ h: e.v / emax, verdict: e.verdict }));
  const rmax = rubricMax(data);
  const flavors = [...new Set(arr(data.test3).map((r) => r.flavor))].sort();
  const fcols = colorSeries(flavors.length, ['#f2c14e', '#6c8dff', '#ff6bb5', '#2ec4b6']);
  out.test3 = arr(data.test3).map((r) => ({ level: r.rubric == null ? 0 : Math.max(0, Math.min(1, r.rubric / rmax)), color: fcols[flavors.indexOf(r.flavor)] || OTHER_COLOR, right: r.judgement_right }));
  const ab = abGroups(data);
  out.ab = ab.groups.filter((g) => !g.allFailed).map((g) => g.rows.filter((r) => r.decode != null).map((r) => ({ h: ab.max ? r.decode / ab.max : 0, color: ab.colors.get(r.engine) || OTHER_COLOR })));
  out.oneshots = oneshotSets(data).map((s) => {
    const rows = arr(obj(data.oneshots)[s.set]);
    const max = Math.max(1, ...rows.map((r) => r.points.length * s.pointMax));
    return { set: s.set, shape: /orrery|gear|clock/i.test(s.set) ? 'gear' : /pagoda|flower|petal|garden/i.test(s.set) ? 'flower' : 'star',
      values: rows.map((r) => (r.total == null ? 0 : Math.max(0, Math.min(1, r.total / max)))) };
  });
  out.findings = arr(data.findings).flatMap((f) => findingMetrics(f).map((m) => ({ from: m.beforePct == null ? 0 : m.beforePct / 100, to: m.afterPct == null ? 0 : m.afterPct / 100, isNew: m.before == null })));
  const tl = arr(data.timeline).filter((t) => t.date);
  const t0 = tl.length ? Date.parse(tl[0].date) : 0, t1 = tl.length ? Date.parse(tl[tl.length - 1].date) : 1;
  out.timeline = tl.map((t) => { const ms = Date.parse(t.date); return { x: Number.isFinite(ms) && t1 > t0 ? (ms - t0) / (t1 - t0) : 0 }; });
  const kinds = eventKinds(data);
  const kmax = Math.max(1, ...kinds.map((k) => k.n));
  const kcols = colorSeries(kinds.length, ENGINE_BASE);
  out.log = kinds.map((k, i) => ({ kind: k.kind, h: k.n / kmax, color: kcols[i] }));
  out.caveats = arr(data.caveats).map((c, i) => ({ i, len: Math.min(1, c.length / 240) }));
  return out;
}

// Runs every derivation once; the checker calls this on mutated data to prove nothing throws.
export function deriveAll(raw) {
  const data = normalize(raw);
  const out = { summary: summary(data), colors: familyColors(data), planets: heroLayout(heroPlanets(data)), options: runFilterOptions(data) };
  out.tests = data.tests.map((t) => ({ t, n: testCount(data, t.number) }));
  out.scales = { checks: Object.fromEntries(out.options.tests.map((t) => [t, checksMax(data, t)])), point: Object.fromEntries(Object.values(data.oneshots).flat().map((r) => [r.test, pointMax(data, r.test)])), rubric: rubricMax(data) };
  for (const s of ['tps', 'minutes', 'tests', 'verdict', 'finished', 'clean']) out['runs_' + s] = runRows(data, {}, s);
  out.runsFiltered = runRows(data, { test: '2', family: out.options.families[0], verdict: 'pass', uncensored: 'yes', q: 'q' }, 'tps');
  out.runs2T = runRows(data, { test: '2T' });
  out.scale = logScale(out.runs_tps.map((r) => r.tps)); out.ticks = logTicks(out.scale);
  out.struggle = struggleRows(data); out.struggleSummary = struggleSummary(out.struggle); out.cleanest = cleanestRun(out.struggle);
  out.test3 = test3Groups(data); out.ab = abGroups(data);
  out.oneshots = oneshotCards(data); out.oneshotSets = oneshotSets(data);
  for (const s of ['speed', 'model', 'newest']) oneshotCards(data, { sort: s, test: '5', q: 'a' });
  out.picks = pickCards(data); out.familyPicks = familyPickRows(data);
  out.findings = data.findings.map(findingMetrics); out.eventKinds = eventKinds(data);
  out.motifs = motifs(data);
  out.fmt = [fmt(1234.5), fmt(null), fmt(2.5), fmt(13.4), fmt(13.4, 1), fmtMinutes(191), fmtMinutes(null), fmtDate('2026-10-22'), fmtDate(''), fmtDate(null)];
  out.series = colorSeries(14);
  return { data, out };
}
