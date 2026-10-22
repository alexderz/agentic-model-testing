# One-shot replies: orrery (test 5) and pagoda (test 6)

**Everything under `orrery/*/` and `pagoda/*/` except the frames is model output.** Models wrote these
SVG and HTML files in one reply, without tools, and nobody edited them. The operator read them and judged
the code safe to run, and the project site plays them (see below).

- The site (`site/`, published by `.github/workflows/pages.yml`) copies each `page.html` and `orrery.svg`
  byte for byte into `site/live/` and runs it only inside `<iframe sandbox="allow-scripts">`, without
  `allow-same-origin`, so a piece gets an opaque origin and cannot reach the site, its storage or the
  top window. One piece runs at a time and only when a visitor opens it.
- `page.html` files load three.js from a public CDN, and a few load Google Fonts (`meta.json` lists each
  page's external URLs). Opening one makes those requests and runs the model's script.
- The frames (`*.webp`) were rendered offline, in a container with no network. Grades come from them.

## Layout

```
orrery/grades.tsv            grades for every test 5 case (rubric: harness/suites/test5/README.md)
orrery/<case>/orrery.svg     the model's SVG, as extracted from its reply
orrery/<case>/meta.json      run settings and timing: entry, reply cap, tokens, speed, static checks
orrery/<case>/frames/        frames at 100, 2000 and 6000 ms
pagoda/grades.tsv            grades for every test 6 case (rubric: harness/suites/test6/README.md)
pagoda/<case>/page.html      the model's page
pagoda/<case>/meta.json
pagoda/<case>/frames/        frames at 1500, 5000 and 10000 ms
```

A case name is `t5` or `t6`, an optional round tag (`r2`, `x1`, `unc1`, ...) and the llama-swap
entry, whose spec is in `harness/engines/entry-specs/`. Cases whose reply hit the token cap
before the file was complete have no source file here; they score 0 in `grades.tsv`. The
reference solutions are in `harness/suites/test5/reference/` and `harness/suites/test6/reference/`.

Three orrery cases are graded in `grades.tsv` but their files are not here yet:
`t5-orcasaq2-cyber-27b`, `t5hq1-qwen3.8-27b-vllm-031` and
`t5unc1-lcpp6-flashnext-abliterated-s15`. Number runs in their SVG path data tripped the
publication gate, and they wait for a manual review.

## How they were made

`harness/tools/run_oneshot.py` sends the prompt once and saves the reply. `harness/tools/render_svg.sh`
and `harness/tools/render_html.sh` render frames in a container with no network (three.js is
served from a checked local copy for the render). Frames are WebP (quality 80) converted from the
PNG renders. The full replies and the models' reasoning are evidence and are not published yet.
