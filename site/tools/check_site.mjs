#!/usr/bin/env node
// Checks that site/data/bakeoff.json renders: runs every derivation in site/assets/data.js on the real
// file and on mutated copies (an empty-ish one, a null root, a garbage root and one with unknown tests,
// null fields, unknown model ids and many families) and asserts nothing throws. Also scans the site's own
// HTML/JS/CSS for forbidden patterns. CI runs this; site/tools/render_smoke.sh additionally renders the
// same copies in a headless browser (local only).
// Usage: node site/tools/check_site.mjs [--emit-mutations DIR]     (no dependencies)
import { readFileSync, readdirSync, statSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join, relative } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, '..');
const D = await import(pathToFileURL(join(site, 'assets', 'data.js')).href);
const emitDir = process.argv.includes('--emit-mutations') ? process.argv[process.argv.indexOf('--emit-mutations') + 1] : null;

let failures = 0;
const ok = (cond, msg) => { if (cond) console.log(`  ok   ${msg}`); else { failures++; console.log(`  FAIL ${msg}`); } };
const tryDerive = (name, raw) => {
  try { const r = D.deriveAll(raw); ok(true, `${name}: derived without throwing`); return r; }
  catch (e) { ok(false, `${name}: threw ${e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e}`); return null; }
};
const realFamilies = (colors) => [...colors.entries()].filter(([f]) => !D.OTHER_FAMILIES.has(f.toLowerCase()));

console.log('allow-lists');
ok(D.isFrameUrl('frames/orrery/t5-qwen3.6-27b/frame-100.webp') && D.isFrameUrl('frames/a/b-1.webp'), 'frame paths under frames/ with safe segments pass');
for (const bad of ['frames/../x.webp', 'frames/a/../b.webp', 'frames/a/..webp', 'frames//a.webp', 'frames/.hidden/a.webp', '/frames/a.webp', 'frames/a.svg', 'https://x/frames/a.webp', 'frames/a b.webp', 'oneshots/a.webp'])
  ok(!D.isFrameUrl(bad), `frame path rejected: ${bad}`);
ok(/^\(\?!\.\*\\\.\\\.\)/.test(D.FRAME_RE.source.replace(/^\^/, '')), 'FRAME_RE itself rejects ".." anywhere');
// live pieces: exactly live/<pagoda|orrery>/<case>/<page.html|orrery.svg>, never "..", never absolute, never another file
for (const good of ['live/pagoda/t6-gemma-4-26b-a4b/page.html', 'live/orrery/t5-qwen3.6-27b/orrery.svg', 'live/orrery/a_b.c-d/orrery.svg'])
  ok(D.isLiveUrl(good), `live path accepted: ${good}`);
for (const bad of ['live/pagoda/../page.html', 'live/pagoda/..x/page.html', 'live/pagoda/a/../b/page.html', 'live/orrery/t5/../../index.html', '/live/pagoda/a/page.html', 'https://example.com/live/pagoda/a/page.html',
  'javascript:alert(1)', 'javascript:/live/pagoda/a/page.html', 'live/pagoda/a/page.htm', 'live/pagoda/a/page.html.svg', 'live/orrery/a/orrery.svgz',
  'live/lantern/a/page.html', 'live/pagoda/a/b/page.html', 'live/pagoda//page.html', 'live/pagoda/a b/page.html', 'live/pagoda/a/page.html?x=1', 'live/pagoda/a/page.html#f', 'frames/pagoda/a/page.html', 'data:text/html,hi', '', null, 42, ['live/pagoda/a/page.html']])
  ok(!D.isLiveUrl(bad), `live path rejected: ${typeof bad === 'string' ? bad || '(empty)' : JSON.stringify(bad)}`);
for (const good of [D.REPO_PREFIX, `${D.REPO_PREFIX}/`, `${D.REPO_PREFIX}/blob/main/docs/x.md`, `${D.REPO_PREFIX}#readme`, `${D.REPO_PREFIX}?tab=issues`])
  ok(D.isRepoUrl(good), `repo URL accepted: ${good.slice(D.REPO_PREFIX.length) || '(exact)'}`);
for (const bad of [`${D.REPO_PREFIX}-evil`, `${D.REPO_PREFIX}x/`, `${D.REPO_PREFIX}/a/../b`, `${D.REPO_PREFIX}/a b`, `${D.REPO_PREFIX}/"x`, 'https://github.com/alexderz/other', 'http://github.com/alexderz/agentic-model-testing', ''])
  ok(!D.isRepoUrl(bad), `repo URL rejected: ${bad || '(empty)'}`);

console.log('formatting');
ok(D.fmt(2.5) === '2.5' && D.fmt(5) === '5' && D.fmt(13.4) === '13' && D.fmt(13.4, 1) === '13.4' && D.fmt(1234.5) === '1,235' && D.fmt(null) === '–', 'fmt keeps one decimal below 10 by default and honours an explicit digits');

console.log('colours');
const series = D.colorSeries(24);
ok(new Set(series).size === 24 && series.slice(0, 8).join() === D.JEWELS.join(), '24 generated colours are distinct and start with the jewel palette');
ok(D.colorSeries(10).slice(0, 9).join() === D.colorSeries(9).join(), 'adding a family never recolours the ones before it');

console.log('data');
const raw = JSON.parse(readFileSync(join(site, 'data', 'bakeoff.json'), 'utf8'));
const real = tryDerive('real bakeoff.json', raw);
if (real) {
  const { data, out } = real;
  ok(out.summary.runs === (raw.runs || []).length, `summary.runs = ${out.summary.runs}`);
  ok(out.summary.models === Object.keys(raw.models || {}).length, `summary.models = ${out.summary.models}`);
  ok(out.summary.frames === (raw.counts && raw.counts.frames != null ? raw.counts.frames : out.summary.frames), `frames = ${out.summary.frames} (counts.frames ${raw.counts && raw.counts.frames})`);
  ok(out.summary.passes === (raw.counts && raw.counts.pass != null ? raw.counts.pass : out.summary.passes), `passes = ${out.summary.passes}`);
  ok(!!data.built === !!raw.built && !!data.generated === !!raw.generated, `freshness: generated "${data.generated}", built "${data.built}", newest finding "${out.summary.newestFinding}"`);
  const fams = realFamilies(out.colors);
  ok(fams.length === new Set(fams.map(([, c]) => c)).size && fams.every(([, c]) => c !== D.OTHER_COLOR), `${fams.length} real families have ${new Set(fams.map(([, c]) => c)).size} distinct colours, none the neutral: ${fams.map(([f, c]) => `${f}=${c}`).join(', ')}`);
  ok([...out.colors.entries()].filter(([f]) => D.OTHER_FAMILIES.has(f.toLowerCase())).every(([, c]) => c === D.OTHER_COLOR), 'Other/Unknown use the neutral colour');
  const frames = out.oneshots.flatMap((c) => c.frames.map((f) => f.url));
  ok(frames.every((u) => D.isFrameUrl(u)), `${frames.length} frame URLs all match the allowed pattern`);
  const missing = frames.filter((u) => { try { return !statSync(join(site, u)).isFile(); } catch { return true; } });
  ok(missing.length === 0, `all frame files exist under site/ (${missing.length} missing${missing.length ? ': ' + missing.slice(0, 3).join(', ') : ''})`);
  ok(Object.values(data.links).every(D.isRepoUrl), 'all links point at the repository');
  const lives = out.oneshots.map((c) => c.live).filter(Boolean);
  ok(lives.every(D.isLiveUrl) && lives.length === out.summary.playable, `${lives.length} live paths all match the allow-list (summary.playable ${out.summary.playable})`);
  ok(raw.counts && raw.counts.live != null ? lives.length === raw.counts.live : true, `live count matches counts.live (${raw.counts && raw.counts.live})`);
  const rawLive = Object.values(raw.oneshots || {}).flat().filter((r) => r && r.live).length;
  ok(rawLive === lives.length, `every live path in the file survived the allow-list (${rawLive} in the file)`);
  const missingLive = lives.filter((u) => { try { return !statSync(join(site, u)).isFile(); } catch { return true; } });
  ok(missingLive.length === 0, `all live files exist under site/ (${missingLive.length} missing${missingLive.length ? ': ' + missingLive.slice(0, 3).join(', ') : ''})`);
  ok(out.oneshotSets.reduce((n, s) => n + s.live, 0) === lives.length, `set cards count the same playable pieces: ${out.oneshotSets.map((s) => `${s.set}:${s.live}`).join(' ')}`);
  ok(out.planets.planets.length >= out.summary.models, `hero has ${out.planets.planets.length} planets in ${out.planets.bands.length} bands`);
  // each run is counted on exactly one test card
  const runKeys = new Set(data.runs.map(D.effectiveTest));
  const cardSum = [...runKeys].reduce((s, k) => s + data.runs.filter((r) => D.effectiveTest(r) === k).length, 0);
  ok(cardSum === data.runs.length && out.tests.every((t) => typeof t.n === 'number'), `test counts count each run once: ${out.tests.map((t) => `${t.t.number}:${t.n}`).join(' ')}`);
  const t2 = out.tests.find((t) => t.t.number === '2'), t2t = out.tests.find((t) => t.t.number === '2T');
  if (t2 && t2t) ok(t2.n + t2t.n === data.runs.filter((r) => r.test === '2').length, `test 2 (${t2.n}) + 2T (${t2t.n}) = all test-2 runs`);
  ok(out.scales.checks['1'] === Math.max(...data.runs.filter((r) => r.test === '1').map((r) => r.checks || 0)), `checks scale for test 1 is the max seen (${out.scales.checks['1']})`);
  ok(out.scales.rubric === Math.max(...data.test3.map((r) => r.rubric || 0)), `rubric scale is the max seen (${out.scales.rubric})`);
  ok(Object.values(out.scales.point).every((v) => v > 0), `point scales per one-shot test: ${JSON.stringify(out.scales.point)}`);
  const c = out.cleanest;
  ok(!c || (c.verdict === 'pass' && c.struggle.loc > 0 && c.struggle.compiles >= 1), `cleanest run is a passing build with lines and a compile: ${c ? `${c.case} (${c.struggle.compiles} builds, ${c.struggle.loc} lines, ${c.struggle.errors_per_kloc} err/kloc)` : 'none'}`);
  ok(out.ab.engines.length === out.ab.colors.size && new Set(out.ab.colors.values()).size === out.ab.engines.length, `engine colours: ${[...out.ab.colors.entries()].map(([e, c]) => `${e}=${c}`).join(', ')}`);
  ok(Object.keys(out.motifs).length === 12, `motif data for ${Object.keys(out.motifs).length} chapters`);
}

// Mutation 1: everything empty.
const empty = { schema: 'bakeoff-site/1', title: '', tests: [], findings: [], picks: {}, timeline: [], events: [], models: {}, runs: [], test3: [], ab: [], oneshots: {}, counts: {}, hardware: {}, caveats: [], links: {} };
const e = tryDerive('empty-ish copy', empty);
if (e) ok(e.out.summary.runs === 0 && e.out.planets.planets.length === 0 && e.out.oneshots.length === 0 && e.out.cleanest === null, 'empty copy derives to zeros');
const garbage = { runs: 'nope', models: [1, 2], oneshots: 5, tests: 'x', picks: null, findings: [null, 3, {}], built: 7, generated: { a: 1 } };
tryDerive('null root', null);
tryDerive('garbage root', garbage);

// Mutation 2: unknown test, null fields, unknown model id, new finding kind, new oneshot set, scale overrides, many families.
const weird = JSON.parse(JSON.stringify(raw));
weird.tests.push({ id: 't9', number: '9', name: 'A new test', kind: 'brand-new-kind', what: null, max_checks: 'x' });
weird.tests[0].max_checks = 7;
weird.runs.push({ case: 'zz-mystery', model: 'model-that-does-not-exist', test: 9, agent: null, checks: null, tests_pass: null, tests_fail: null, subcmds: null, tps: null, minutes: null, compactions: null, ctx: null, kv: null, verdict: null, finished: null, struggle: null });
weird.runs.push({ case: 'zz-nulls', model: null, test: null, tps: 'abc', minutes: -1, verdict: 'WEIRD', struggle: { errors_per_kloc: null } });
weird.runs.push({ case: 'zz-flavored', model: 'qwen3.8-27b-vllm', test: 2, flavor: '2X', verdict: 'pass', tps: 10, minutes: 10, struggle: { compiles: 0, failed_compiles: 0, rust_errors: 0, loc: 0, errors_per_kloc: 0 } });
weird.runs.push(null, 42);
weird.test3.push({ case: 't3x-new', model: 'another-unknown', flavor: '3Z', mcp_facts: null, api_facts: 'lots', judgement_right: 'maybe', rubric: 40, note: null, tps: null, minutes: null });
weird.ab.push({ model: 'unknown-ab', engine: null, variant: null, decode: 'x', error: null }, { model: 'qwen3.8-27b-vllm', engine: '0.7.0-rc', variant: 'same flags', decode: 12.5 });
weird.findings.unshift({ date: '2026-11-01', title: 'A finding of a new kind', kind: 'surprise', metrics: [{ label: 'x', before: null, after: null, unit: null }, { label: 'y', before: 2.5, after: 7.25, unit: 'tok/s' }, null], summary: null });
weird.oneshots.lantern = [{ case: 't7-new', entry: 'nobody', test: 7, points: { A: 1, F: 2, G: null }, total: null, frames: ['frames/lantern/t7-new/frame-10.webp', 'https://evil.example/x.webp', '../oneshots/x.svg', 'frames/../../etc/passwd.webp', null] }];
weird.oneshots.orrery.push({ case: 'bad', entry: 'qwen3.8-27b-vllm', test: 5, points: null, frames: 'not-a-list', live: 'live/orrery/../../index.html' });
weird.oneshots.lantern[0].live = 'live/lantern/t7-new/page.html';
weird.oneshots.pagoda.push({ case: 'zz-abs', entry: 'nobody', test: 6, points: {}, frames: [], live: 'https://evil.example/live/pagoda/x/page.html' },
  { case: 'zz-js', entry: 'nobody', test: 6, points: {}, frames: [], live: 'javascript:alert(1)' },
  { case: 'zz-ext', entry: 'nobody', test: 6, points: {}, frames: [], live: 'live/pagoda/x/page.htm' },
  { case: 'zz-num', entry: 'nobody', test: 6, points: {}, frames: [], live: 7 },
  { case: 'zz-ok', entry: 'nobody', test: 6, points: {}, frames: [], live: 'live/pagoda/zz-ok/page.html' });
weird.picks.overall.push({ role: 'Oddest', model: 'ghost-model', cases: ['no-such-case'] });
weird.picks.families.push({ family: 'Brand New Family', smartest: 'ghost', note: null });
for (let i = 0; i < 12; i++) weird.models[`extra-${i}`] = { id: `extra-${i}`, family: `Family ${i}`, label: null };
weird.timeline.push({ date: null, title: null });
weird.events.push({ when: null, kind: null, text: 'an event with no kind' }, { text: null });
weird.hardware.extra_part = 'a new field';
weird.caveats.push(null, 12);
weird.links.evil = 'https://github.com/alexderz/agentic-model-testing-evil';
delete weird.built;
const w = tryDerive('mutated copy (unknown test, nulls, unknown model, many families)', weird);
if (w) {
  const { data, out } = w;
  ok(out.tests.some((t) => t.t.number === '9'), 'unknown test 9 is listed');
  ok(D.modelOf(data, 'model-that-does-not-exist').missing === true, 'unknown model id resolves to a fallback card');
  const lantern = out.oneshots.filter((c) => c.set === 'lantern')[0];
  ok(lantern && lantern.frames.length === 1 && lantern.frames[0].url.startsWith('frames/'), 'only the valid frame URL survived in the new one-shot set');
  const fams = realFamilies(out.colors);
  ok(fams.length === new Set(fams.map(([, c]) => c)).size && fams.every(([, c]) => c !== D.OTHER_COLOR), `with ${out.colors.size} families every real one still has its own colour`);
  ok(out.runs_tps.length === (raw.runs.length + 3), 'non-object runs dropped, odd runs kept');
  ok(out.scales.checks['1'] === 7, 'tests[].max_checks overrides the seen maximum');
  ok(out.scales.rubric === 40, 'rubric scale follows the largest rubric seen');
  ok(out.scales.point['7'] === 2, 'point scale for the new set is the max seen there');
  ok(out.ab.engines.length === 4 && new Set(out.ab.colors.values()).size === 4, `a third engine value gets its own colour (${out.ab.engines.join(', ')})`);
  ok(!Object.keys(data.links).includes('evil'), 'a look-alike repository URL is dropped');
  ok(out.tests.some((t) => t.t.number === '2X') === false && out.options.tests.includes('2X'), 'a new flavor shows in the run filter and is counted on its own card when described');
  ok(out.cleanest && out.cleanest.struggle.compiles >= 1, 'a zero-compile pass with 0 errors is not the cleanest run');
  const liveOf = (k) => (out.oneshots.find((c) => c.case === k) || {}).live;
  ok(liveOf('bad') === null && liveOf('t7-new') === null && liveOf('zz-abs') === null && liveOf('zz-js') === null && liveOf('zz-ext') === null && liveOf('zz-num') === null, 'live paths with "..", an unknown set, an absolute URL, javascript:, a wrong extension or a non-string get no Play control');
  ok(liveOf('zz-ok') === 'live/pagoda/zz-ok/page.html', 'a well-formed live path is kept even when the file is not on disk (the viewer shows a blank frame)');
  ok(out.summary.playable === real.out.summary.playable + 1, `summary.playable counts only accepted paths (${out.summary.playable})`);
}
if (emitDir) {
  mkdirSync(emitDir, { recursive: true });
  for (const [name, value] of [['real', raw], ['empty', empty], ['null', null], ['garbage', garbage], ['weird', weird]]) writeFileSync(join(emitDir, `${name}.json`), JSON.stringify(value));
  console.log(`  wrote real, empty, null, garbage and weird copies to ${emitDir}`);
}

// Source scan: no innerHTML & co., no external URLs except the repo, no inline handlers.
console.log('sources');
const files = [];
const walk = (dir) => { for (const n of readdirSync(dir)) { const p = join(dir, n); const s = statSync(p); if (s.isDirectory()) { if (!['frames', 'data', 'tools', 'live'].includes(n)) walk(p); } else if (/\.(html|js|mjs|css|svg)$/.test(n)) files.push(p); } };
walk(site);
const bad = [/\binnerHTML\b/, /\bouterHTML\b/, /insertAdjacentHTML/, /document\.write/, /\beval\s*\(/, /new\s+Function\s*\(/, /\bon[a-z]+\s*=\s*["']/i, /javascript:/i];
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  const rel = relative(site, f);
  const hits = bad.filter((re) => re.test(src.replace(/\/\/.*$/gm, '')));
  ok(hits.length === 0, `${rel}: no forbidden DOM/eval patterns${hits.length ? ' (' + hits.map(String).join(' ') + ')' : ''}`);
  const urls = [...src.matchAll(/https?:\/\/[^\s"'<>)]+/g)].map((m) => m[0]).filter((u) => !u.startsWith(D.REPO_PREFIX) && !u.startsWith('http://www.w3.org/'));
  ok(urls.length === 0, `${rel}: no external URLs${urls.length ? ' (' + urls.join(', ') + ')' : ''}`);
}
const dom = readFileSync(join(site, 'assets', 'dom.js'), 'utf8');
ok(/rel:\s*'noopener noreferrer'/.test(dom) && /target:\s*'_blank'/.test(dom), 'external links carry rel="noopener noreferrer"');
const html = readFileSync(join(site, 'index.html'), 'utf8');
ok(/Content-Security-Policy/.test(html) && /default-src 'self'/.test(html) && !/'unsafe-inline'/.test(html), 'index.html has a strict CSP without unsafe-inline');
ok(!/<script(?![^>]*\bsrc=)/.test(html) && !/<style/.test(html) && !/\sstyle="/.test(html), 'index.html has no inline script or style');
const csp = (html.match(/Content-Security-Policy"\s+content="([^"]*)"/) || [])[1] || '';
ok(/(^|;)\s*frame-src 'self'\s*(;|$)/.test(csp), "CSP frame-src is exactly 'self' (the live pieces are same-site, the sandbox gives them an opaque origin)");
ok(/(^|;)\s*default-src 'self'\s*(;|$)/.test(csp) && /script-src 'self'/.test(csp) && /object-src 'none'/.test(csp) && /base-uri 'none'/.test(csp) && !/\*/.test(csp) && !/https?:/.test(csp), 'CSP stays strict: self only, no wildcards or hosts');
ok(!/<iframe/.test(html), 'index.html has no static iframe; the viewer creates one on open');
const viewer = readFileSync(join(site, 'assets', 'viewer.js'), 'utf8');
ok(/sandbox:\s*'allow-scripts'/.test(viewer) && /referrerpolicy:\s*'no-referrer'/.test(viewer) && /loading:\s*'lazy'/.test(viewer), "viewer.js creates the iframe with sandbox='allow-scripts', referrerpolicy='no-referrer', loading='lazy'");
ok((viewer.match(/sandbox/g) || []).length === (viewer.match(/sandbox:\s*'allow-scripts'|\/\/.*sandbox|sandboxed/g) || []).length, 'viewer.js sets sandbox in exactly one place');
for (const tok of ['allow-same-origin', 'allow-top-navigation', 'allow-popups', 'allow-forms', 'allow-modals', 'allow-downloads', 'allow-pointer-lock', 'allow-presentation', 'allow-orientation-lock'])
  ok(files.every((f) => !readFileSync(f, 'utf8').replace(/\/\/.*$/gm, '').includes(tok)), `no site source grants ${tok}`);
ok(/setAttribute\('src', 'about:blank'\)/.test(viewer) && /removeChild\(f\)/.test(viewer), 'viewer.js blanks the iframe src and removes the element on teardown');
ok(/tagName === 'IFRAME' \? isLiveUrl\(s\) : isFrameUrl\(s\)/.test(dom), 'dom.js lets a live path through only on an <iframe>, frames only elsewhere');
const bytes = files.filter((f) => /\.(js|css)$/.test(f) && !f.includes('/tools/')).reduce((s, f) => s + statSync(f).size, 0);
ok(bytes < 170 * 1024, `JS + CSS total ${(bytes / 1024).toFixed(1)} KB (< 170 KB)`);

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
