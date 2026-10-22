# site/data: the data behind the page

`bakeoff.json` is the only file the page reads. `site/index.html` and `site/assets/*.js` are a renderer: every
number, list, chart, chip and count on the page is derived from this file at load time, so adding a run, a model, a
finding, a test or a one-shot result needs **no HTML, CSS or JS change**. Rebuild the file, publish, done.

```
python3 -I site/tools/build_data.py        # rebuilds bakeoff.json, copies frames into site/frames/ and the live pieces into site/live/
node site/tools/check_site.mjs             # proves the page's derivations run on the new file (CI runs this too)
bash site/tools/render_smoke.sh            # local only: renders the real file and every mutated copy in headless Chromium
```

`build_data.py` merges three sources:

| Source | What it supplies |
| --- | --- |
| `reports/dashboard/data.json` | `generated`, `hardware`, `caveats`, `picks` (from `recs`), `timeline`, `events` (results only, latest 80), `models`, `runs`, `test3`, `ab` |
| the build itself | `built`, the time `build_data.py` ran; shown next to `generated` so readers can see the run table is older than the findings |
| `oneshots/{orrery,pagoda}/grades.tsv` + `*/frames/*.webp` + the model's own file | `oneshots.orrery`, `oneshots.pagoda`: frames are copied to `site/frames/`, and the model's own file, byte for byte, to `site/live/<set>/<case>/page.html` or `orrery.svg` (`live` field) |
| `site/data/curated.json` (hand-written) | `title`, `tagline`, `tests`, `findings`, `links` |

Everything that is prose on the page and *not* in this file is a section intro that stays true whatever the data says.
The ornament in each chapter head is also drawn from the data of that chapter (runs as a constellation, orrery scores
as gear teeth, pagoda scores as petals, …); it is decorative and hidden from assistive technology.

## How the page treats the data

- Missing or `null` fields render as `–` or are skipped. Empty lists render an "nothing here yet" line. Unknown
  values (a new `kind`, a new test number, a new one-shot set, a model id with no entry in `models`) render with
  sensible fallbacks: the test number alone, a grey chip, a fallback model card named after the id.
- Model ids are matched exactly: `runs[].model`, `test3[].model`, `ab[].model`, `oneshots.*[].entry` and
  `picks.*.model` should be keys of `models`.
- Family hue: every real family gets its own colour, in the order of `picks.families` then alphabetical: the first
  eight take the fixed jewel palette, later ones get a hue dropped into the widest gap left on the wheel, so adding a
  family never recolours the ones before it. `Other`/`Unknown` are always the neutral silver and no real family is.
  Engine colours in the A/B chart work the same way, one per distinct `ab[].engine` value.
- Scales: "n of m" numbers come from the data. Checks are shown against the largest `checks` seen for that test,
  one-shot points against the largest point value seen for that test, the test-3 rubric against the largest rubric
  seen; `tests[].max_checks`, `tests[].max_point` and `tests[].max_rubric` override those when present.
- Counting: a run is counted on exactly one test card, under its `flavor` when it has one (2T) and under its `test`
  otherwise. In the run filter, picking a test also shows its flavors; picking a flavor shows only those.
- Frames: only relative paths under `frames/` whose every segment starts with a letter, digit, `_` or `-` and ends in
  `.webp` are shown; `..`, dot-files and empty segments are rejected. Anything else is dropped silently. The number in
  the file name (`frame-2000.webp`) is read as milliseconds for the flipbook label and alt text. The flipbook starts
  on the last (richest) frame and only ever steps onto frames that have really loaded; if none loads the card is blank.
- Live pieces: `oneshots.*[].live` is shown as a "Play live" control only when it matches
  `^live/(pagoda|orrery)/[A-Za-z0-9._-]+/(page\.html|orrery\.svg)$` and contains no `..`; anything else (an absolute
  URL, `javascript:`, another extension, another set, a deeper path, `null`) gets no control. The viewer rules:
  the piece runs in an `<iframe sandbox="allow-scripts" referrerpolicy="no-referrer" loading="lazy">` created when the
  viewer opens (never `allow-same-origin`, `allow-top-navigation`, `allow-popups`, `allow-forms` or `allow-modals`,
  so the piece has an opaque origin and cannot touch this page, navigate it, open windows or submit forms); the
  `src` is set only on open and set to `about:blank` and the element removed on close or when stepping to the next
  piece, so at most one WebGL page runs at a time; `index.html`'s CSP allows `frame-src 'self'` and nothing else.
  The live files are served as-is and are not covered by `index.html`'s CSP; the pagoda pages load three.js from
  cdn.jsdelivr.net and some load Google Fonts, inside the sandbox. `dom.js` only lets a live path onto an `<iframe>`. The files are also reachable by
  their own URL, where they run without the sandbox (Pages cannot send a CSP header); the site never links them that way.
  An orrery SVG is sized from its root tag (fixed `width`/`height` is laid out at that size and scaled to fit, a
  `viewBox` alone keeps its aspect, neither fills the stage); that needs the file's text, which is fetched
  same-origin and only matched with a regular expression, never parsed into the page.
- Links: only `https://github.com/alexderz/agentic-model-testing` itself, or that followed by `/`, `#` or `?`, becomes
  a link (never with `..`); links open in a new tab with `rel="noopener noreferrer"`.
- Free text (`note`, `verdict`, `text`, …) is always inserted as text, never as markup.
- Lists of any size are fine: the runs ladder shows 40 at a time, the table caps at 300 per filter, the gallery,
  test 3 and the log reveal 12 at a time.

## Schema (`schema: "bakeoff-site/1"`)

Fields marked *opt* may be missing or `null`. Types are what the page expects; it coerces numeric strings.

### Top level

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | str | `bakeoff-site/1`. |
| `generated` | str, opt | When the source dashboard data was generated, shown under the hero stats. |
| `built` | str, opt | When this file was built, shown next to `generated` with the newest run and finding dates. |
| `title`, `tagline` | str | Hero title and one-line pitch (from `curated.json`). |
| `links` | object | `repo`, `cards`, `method`, `conclusions`, `log`: repository URLs for the footer. Extra keys are shown too. |
| `hardware` | object of str | Spec plate. Any key renders; `gpu` also labels the sun of the orrery. |
| `caveats` | list of str | Shown in full in the last section. Never drop these. |
| `tests` | list | The test catalogue, see below. |
| `findings` | list | Headline findings, newest first, see below. |
| `picks` | object | `overall`, `uncensored` (lists of picks) and `families` (one row per family). |
| `timeline` | list | Eras of the work; sorted by `date` on the page. |
| `events` | list | Lab-notebook entries; sorted newest first on the page. |
| `models` | object | Model cards keyed by model id. |
| `runs` | list | Agent runs for tests 1, 2 and 2T. |
| `test3` | list | Test 3 rows. |
| `ab` | list | Engine A/B speed probes. |
| `oneshots` | object of lists | One list per one-shot set (`orrery`, `pagoda`, …). New sets appear automatically. |
| `counts` | object, opt | `models`, `runs`, `test3`, `oneshots`, `frames`, `pass`, `live`. Informational; the page recounts from the lists and the checker compares the two. |

### `tests[]`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | str | Stable id, e.g. `t2t`. |
| `number` | str | What runs refer to: `"1"`, `"2"`, `"2T"`, `"3"`, `"5"`… Matched against `runs[].test`, `runs[].flavor`, `oneshots.*[].test`. |
| `name` | str | Card title. |
| `kind` | str, opt | `agentic` or `one-shot` today; any value becomes a chip and a CSS class. |
| `what` | str, opt | The task in one sentence. |
| `graded` | str, opt | How it is graded. |
| `points` | list of str, opt (wished) | Names for the one-shot rubric points A–E in order, e.g. `["draws","planets","gears","lighting","motion"]`. Letters are shown when absent. |
| `max_checks`, `max_point`, `max_rubric` | number, opt | Scale overrides: checks out of `max_checks`, each one-shot point out of `max_point`, the test-3 rubric out of `max_rubric`. Without them the page uses the largest value seen. |

### `findings[]`

| Field | Type | Meaning |
| --- | --- | --- |
| `date` | str `YYYY-MM-DD` | Shown as a date. |
| `title` | str | Heading. |
| `kind` | str, opt | `tuning`, `engine`, … any value becomes a chip. |
| `summary` | str | The finding in a paragraph. |
| `settings` | str, opt | Flags, shown in monospace. |
| `metrics[]` | list, opt | `{label, before, after, unit}`; `before` may be `null` (shown as "new"). The first metric with an `after` is set as big before → after numerals; the rest are before/after bars with the gain ratio. Fractional values keep one decimal. |
| `quality` | str, opt | How quality was checked. |
| `caveat` | str, opt | Shown with a red rule. |

### `picks`

`overall[]` and `uncensored[]`: `{role, model, verdict, tradeoff, cases[]}`. `model` is a model id; `cases` are
`runs[].case` values, and the matching runs are listed on the card.

`families[]`: `{family, smartest, fastest, unc_smartest, unc_fastest, note}`; the four picks are model ids or `null`
("none yet").

### `timeline[]`: `{date, era, title, what, why}`. `events[]`: `{when, kind, text}`.

### `models{id}`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | str | Same as the key. |
| `family` | str | Family name; drives colour and grouping. `Other` is always grey. |
| `label` | str | Full label; the text before the first ` · ` is used as the short name. |
| `base`, `arch`, `engine`, `quant` | str, opt | Shown on pick cards and in tooltips. |
| `kind` | str, opt | `stock`, `abliterated`, `heretic`, `uncensored-tune`, `security-tune`, … |
| `uncensored` | bool | Marks the model (dashed ring in the orrery, chip elsewhere, filter in the ladder). |
| `note` | str, opt | Free text. |
| `vision` | `{label, status}`, opt | Not rendered yet. |

### `runs[]`

| Field | Type | Meaning |
| --- | --- | --- |
| `case` | str | Unique case name. Today a `wt-` prefix marks a test-2T run. |
| `model` | str | Model id. |
| `test` | int or str | `1` or `2` (2T runs are stored as `2`). |
| `flavor` | str, opt (wished) | `"2T"` for trust-the-docs runs. Until present, the page derives it from the `wt-` prefix. |
| `agent` | str, opt | `OpenCode` or `Pi`. |
| `checks` | int, opt | Test 1: checks passed; shown out of the largest `checks` seen for the test (or `tests[].max_checks`). |
| `tests_pass`, `tests_fail` | int, opt | The model's own tests. |
| `subcmds` | int, opt | Test 1: subcommands. |
| `tps` | float | Tokens per second over the whole run; the ladder's x axis (log). |
| `minutes` | int | Wall time. |
| `compactions`, `ctx`, `kv` | opt | Client compactions, context length, KV cache type. |
| `verdict` | str | `pass`, `partial`, `fail` (status colour + glyph). Other values are grey. |
| `finished` | str | `YYYY-MM-DD HH:MM`. |
| `struggle` | object, opt | `{compiles, failed_compiles, rust_errors, loc, errors_per_kloc}`; `errors_per_kloc` drives the struggle strip (test 2 runs only). The "cleanest passing build" stat considers only passing runs with `loc > 0` and `compiles >= 1`. |

### `test3[]`

`{case, model, flavor ("3G" known-good server, "3O" own server), mcp_facts "n/m", api_facts "n/m",
judgement_right bool, rubric int, note, tps, minutes, finished}`. Facts strings are parsed as `got/of` for the pips;
the rubric bar scales to the largest rubric seen (or `tests[].max_rubric` for test 3).

### `ab[]`

`{model, engine, variant, decode, quote, prefill, vram, error}`; speeds in tok/s, `vram` MiB. Rows with a `null`
`decode` are listed under "probes failed to load" with the error text. Rows with `variant == "same flags"` on two
engines give the ×gain shown next to the model.

### `oneshots.<set>[]`

| Field | Type | Meaning |
| --- | --- | --- |
| `case` | str | Case name. |
| `entry` | str | Model id (llama-swap entry). |
| `test` | int or str | Test number, matched to `tests[].number`. |
| `finish` | str | `stop` or `length` (cut off by the cap; shown as "hit the cap"). |
| `tokens`, `wall_s`, `tok_s` | float, opt | Reply size and speed. |
| `points` | object | Rubric points keyed `A`…`E`. Any number of keys works; the petal chart grows with it, and each petal is scaled to the largest point value seen for the test (or `tests[].max_point`). |
| `total` | float, opt | Sum of points; recomputed when missing. |
| `note` | str | Grader's note. |
| `frames` | list of str | `frames/<set>/<case>/frame-<ms>.webp`, ascending time. Empty list = blank card. |
| `live` | str or null | `live/<set>/<case>/page.html` (pagoda) or `live/<set>/<case>/orrery.svg` (orrery): the model's own file, copied byte for byte. `null` when the reply produced no file. Shown as "Play live" only when it passes the allow-list above; the hero count, the gallery header line, the set cards and the filter count all count these. |

## Recipes

**Add a finding.** Append an object to `findings` in `curated.json` (newest first), with at least `date`, `title`,
`kind`, `summary`; add `metrics` with `before: null` for numbers that have no baseline. Rebuild.

**Add a test.** Append to `tests` in `curated.json` with a unique `id`, the `number` that runs will carry, `name`,
`kind`, `what`, `graded`. The card appears at once with its run count (0 until runs arrive). Runs of a test that is
*not* in the catalogue still show up, as "Test N: appears in the results but is not described yet".

**Add a run.** Add it to `reports/dashboard/data.json` as today; `build_data.py` carries the fields listed above. A
run whose `model` has no entry in `models` still renders (grey, family "Unknown"), but add the model card so it gets
its family colour and label.

**Add a one-shot set.** Put a `grades.tsv` and frames under `oneshots/<set>/`, register the set in `build_data.py`'s
`oneshots` call, and describe its test in `curated.json`. The gallery, the set summary cards and the test filter pick
it up without page changes. Its pieces will *not* be playable until the live allow-list in `data.js` (`LIVE_RE`) and
the checker's cases know the new set name and file name: that is deliberate, a new kind of file should be looked at
before the site serves it.

## Wished fields

Things the page would use if the data carried them. Each is optional and rendered only when present.

- `runs[].flavor` (`"2T"`): explicit trust-the-docs flag instead of the `wt-` case-name prefix.
- `tests[].max_checks`, `tests[].max_point`, `tests[].max_rubric`: fixed scales (see above) so a round with no perfect
  score does not shrink the bars.
- `runs[].trust` (`tested | avoided | hedged | trusted`): the 2T trust verdict from method.md, to show as a chip.
- `runs[].tools`: number of MCP tools the test-2 server exposes; conclusions quote it ("12 tools, 155 tests") but the
  JSON has only `tests_pass`.
- `runs[].resident` (`gpu | offloaded`): whether the model fit in VRAM, to colour the speed tiers the conclusions
  describe (rule 1).
- `tests[].points`: names of the one-shot rubric points (see above), so the petal chart can say "gears 1" instead of
  "C 1".
- `models[].params_b` and `models[].active_b`: numeric sizes, to size planets by parameter count instead of only by
  appearances.
- `models[].card`: URL of the model card under `docs/model-research/models/`, to link each model name.
- `oneshots.*[].round` or `finished`: a date, so "newest" sorting does not have to rely on the case name.
- `counts.generated_from`: the commit of `reports/dashboard/data.json` the file was built from.
