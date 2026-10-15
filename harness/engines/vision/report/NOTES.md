# Vision in the report and the model cards: notes

Operator, 2026-10-15: "Update our model report with info in which support vision and the impact if loading it to
context or more." This folder holds the notes for that change. **Enabled 2026-10-15 ~08:55** after the Grok review: the `.new` files were
renamed into place and the report rebuilt and committed. The toolbox cards and the Artifact are **not** published yet.

## What changed

| File | State | What it does |
| --- | --- | --- |
| `tools/catalog.py.new` | new, next to the tracked file | Reads `engines/vision/heads.tsv`, `engines/vision/report/vis-setups.tsv` and, once it exists, the newest valid `engines/vision/vis-entries/smoke-YYYY-MM-DD.tsv`. Adds `vision` to every `report()` row and three functions: `vision_record(key)`, `vision(id)`, `vision_overview(ids)`. |
| `tools/build_report.py.new` | new | Adds `data.json` key `vision` (`records`, `smoke`, `method`): every model record behind the report's entries with its setups, and four method notes. |
| `report/template.html.new` | new | A "Vision" link in the table of contents, a `#vision` section (table and method notes) after Test 3, and a Vision column in the fit table between KV and tok/s. |
| `tools/export_model_docs.py.new` | new | A Vision row in each card's header table, a `## Vision` section after the Verdict, and a Vision column in the README index. Uses method notes 2 and 3 only, so no repo path reaches the public cards; DENY still checks every page. |
| `engines/vision/report/make_setups.py` | new | Writes `vis-setups.tsv` from a read-only copy of Titan's llama-swap.yaml (the configured entries) and `vis-entries/dry-run.txt` (the 13 planned `-vis` entries). |
| `engines/vision/report/vis-setups.tsv` | new, generated | 23 setups that see images (10 configured, 13 planned) and where each keeps its head. Made from yaml sha256 d776ca8e... and dry-run.txt sha256 5d16c455... (2026-10-15 08:22). |
| `engines/vision/report/preview/` | new, generated | `current/` = the tracked tools, `new/` = the `.new` tools, run now with the make-report.sh arguments: `report/` (data.json, index.html, artifact.html) and `cards/` (59 cards + README). |
| `engines/vision/report/DIFF.md` | new | The output and source differences, trimmed. |

Per model the column shows:

- **Vision status**, from `heads.tsv`. "yes (head)" means a separate mmproj that matches the text weights. "yes (built in)" means a tower inside a vLLM, SGLang or exllamav3 checkpoint. "base head, unverified" means only the base model's head exists, and image understanding may not have survived the fine-tune. "no" means text-only.
- **Head**: the projector type and size in GB (heads.tsv `head_bytes`).
- **Tokens per 1280x720 screenshot**: the README estimate by projector (qwen3vl_merger ~920, glm5v and glm5next ~1200, pixtral ~1000, gemma4v ~400), marked "est.".
- **Each setup that loads a head**:
  - Where the head lives: GPU; CPU (`--no-mmproj-offload`); host RAM (TabbyAPI or HyperQwen offload); built in (SGLang); or GPU by vLLM default.
  - Extra VRAM: the README estimate when on the GPU, about 0 plus system RAM when on the CPU or host RAM, and "in the load" for engine-managed towers. All marked "est.".
  - Configured or planned.

Samples (new preview):

| Model | Vision | Head | Tokens | Setups |
| --- | --- | --- | --- | --- |
| Tiel-Coder-35B 4-bit | yes (head) | qwen3vl_merger 0.90 GB | ~920 est. | tiel-coder-35b: GPU, +1.4-2.7 GB est. (configured). lcpp6-tiel-coder-35b-t06-vis: CPU, ~0 GB + 0.9 GB RAM (planned) |
| Gemma 4 26B-A4B (Q4) | yes (head) | gemma4v 1.19 GB | ~400 est. | gemma-4-26b-a4b-vis: GPU, +1.4-1.7 GB est. (planned) |
| Gemma 4 26B-A4B (AWQ) | yes (built in) | tower in the checkpoint | ~400 est. | gemma-4-26b-a4b-vllm: GPU by vLLM default, in the load (configured) |
| Qwen3.8-27B Uncensored | yes (built in) | tower in the checkpoint | ~920 est. | qwen3.8-27b-uncensored-vllm-vis: host RAM (planned) |
| Orcarouter Flash-Next Uncensored | yes (head) | qwen3vl_merger 0.91 GB (its own head, vision-head-own/) | ~920 est. | lcpp6-orcarouter-fn-uncensored-vis: CPU (planned) |
| OrcaSAQ-2-Cyber-27B | base head, unverified | qwen3vl_merger 0.93 GB | ~920 est. | lcpp6-orcasaq2-cyber-27b-vis: CPU (planned) |
| GLM-4.5-Air | no | – | – | – |

## How to enable it

Done by whoever owns the tools, after review. These steps were not run.

1. Keep `engines/vision/report/vis-setups.tsv` where it is. The `.new` catalog reads it from there. Commit it with `make_setups.py`.
2. Rename the four `.new` files into place:
   - `mv tools/catalog.py.new tools/catalog.py`
   - `mv tools/build_report.py.new tools/build_report.py`
   - `mv tools/export_model_docs.py.new tools/export_model_docs.py`
   - `mv report/template.html.new report/template.html`
3. Run `./make-report.sh`, then the usual export into the toolbox model-research space. Publishing stays a separate step: `publish_review.py`, the Artifact, and the toolbox PR.
4. Delete `engines/vision/report/preview/`. It is a review aid, not source.

**Keep vis-setups.tsv current.** Re-run `make_setups.py` whenever Titan's llama-swap.yaml or the `-vis` entries change, and when the planned entries are added for real (they then show as configured):

```
python3 -I engines/vision/report/make_setups.py /srv/bakeoff/model-bakeoff <llama-swap.yaml copy> engines/vision/vis-entries/dry-run.txt engines/vision/report/vis-setups.tsv
```

It is a separate file only because entry specs carry no `cmd`. If the specs gain one, or the catalog becomes the single YAML, the placement can be derived there and this file can go.

## What still needs the smoke TSV

Every number in the column is an estimate until `vis-entries/vis_smoke.py` writes `vis-entries/smoke-<date>.tsv`. The `.new` catalog reads the newest file automatically. For each setup in it, the report and the cards switch from "est." to "measured" for these values:

- **Extra VRAM.** `vram_delta_mib`, shown as +x.x GB; the page also gets `vis_vram_mib`.
- **Tokens per screenshot.** `image_tokens`.
- **Encode time.** `image_req_s`, shown as "s per screenshot request". This is the cost of a head on the CPU. Nothing estimates it today.
- **Errors.** `probe_status`, `two_image_status` and `errors` are carried through. Errors show on the page.

The lede then names the smoke file. Setups without a row stay "est.".

This path was tested with a FAKE smoke TSV in a scratch copy only; see "Tests" below. No real measurement exists.

## Caveats

- **Orcarouter GLM-5.3-Flash.** It shows "head on disk, no engine loads it", projector glm5v. The head was accepted, downloaded and sha-verified on 2026-10-15, but heads.tsv's engine_note says no engine we have loads that pair. The label comes from that note ("loads in no engine"), so it changes when the note does. No card names that record (an existing model_cards warning), so it shows in the report only.
- **OrcaSAQ-2-Cyber-27B.** It stays "base head, unverified". Its planned `-vis` setup would load the base Qwen3.8-27B head.
- **Blind entries.** Strata, Maya, and the HyperQwen vLLM entries are blind; the HyperQwen launcher defaults to VISION=0, which passes `--language-model-only` (vis-entries/PLAN.md). gemma-4-26b-a4b-vllm calls `vllm serve` itself without that flag, so it is listed as "GPU (vLLM default)". That is derived from the cmd, not measured. In the fit table they show the record's status with "this setup: blind".
- **Planned `-vis` entries.** These are not in `engines/entry-specs/` yet. They appear only in the Vision section and on the cards, marked "planned, not configured", labelled with the source entry's name plus " + vision".
- **Duplicate names.** Records that share a display name get their quant appended in the Vision table and on the cards: "Gemma 4 26B-A4B (Q4)" / "(AWQ)" and "Qwen3.8-27B (UD-Q4_K_M)" / "(HyperQwen 4-bit, FP8 KV)".
- **Cards without vision.** 27 of 59 cards do not change apart from the index. Watch cards have no record. Other cards do not name the record that holds the report's entries, for example MiMo v2.6 9B (record `mimo-v2.6-9b`, "yes (head)" in the report), and likewise GLM-5.3 Orcarouter, GLM-5.3 Huihui, Qwen3-VL 32B, Cyber Q6/Q8 and Tiel MTP (model_cards warns about all of them). The index shows "–" for those, with a line saying that "–" means not recorded, not text-only. Linking those records to their cards would also add their runs to the cards. That is a card-content change outside the vision-column work, so it is left for the operator.
- **Page payload.** `data.json` keeps every vision field, because export_model_docs.py reads it. `index.html` and `artifact.html` embed a copy without `record`, `engine_note`, `head_file` and `flags`, the fields that name storage paths and engine folders.

## Grok review applied (2026-10-15)

Review notes are kept privately. Every should-fix item and every nit is applied:

1. **Projector.** It is the first word of the engine note ("Projector X" also counts), not the first projector named anywhere in it. Orcarouter GLM is now glm5v and Maya stays glm5next.
2. **Not loadable, and the lede.** The lede counts models with a setup that loads a head or tower: 20 of 48, 9 with a configured setup. It names the 15 that have a head or tower but no setup, and says no image has been sent yet. Orcarouter GLM's row and fit cell say no engine loads its head; they no longer say the setup runs blind.
3. **Duplicate names.** Quant appended (see Caveats).
4. **Cards with several weights.** The blind line is now written per weights row, so a sibling's setup no longer hides it (`qwen3.8-27b.md`, `qwen3.8-flash-next.md`).
5. **Smoke file.** Only `smoke-YYYY-MM-DD.tsv` names count, and the newest by date wins. A file without an `entry` column, or one that cannot be read, is skipped with a warning, and its setups stay estimates. The page now prints a vision probe or two-image status other than `ok`.
6. **Markdown.** Every vision cell goes through the run notes' scrub (`|` and newlines). A planned setup with no known entry or source is named "planned vision setup", never by its raw id.
7. **Index.** "–" plus a legend (see Caveats).
8. **Artifact.** Payload stripped (see Caveats). The vision part of the new pages has no `nas/llm`, `titan-ssd`, `/srv` or engine folder.
- **Nits.** The host-RAM tower size comes from `head_bytes` when it is known, otherwise "~0.9 GB est.". The 920-token paragraph is now "for example, with a head that costs about 920 tokens". `make_setups.py` hashes the yaml copy it reads, records the yaml hash the dry run names, and warns when they differ (both d776ca8eb40a today). A native tower is named Qwen3.8 VL only when the base model is Qwen3. The fit-table Vision cell shows tokens per screenshot.

## Tests

- **No existing tests cover these generators.** `tests/` has test_hang_watchdog.py, test_mcp_restart_shim.py, test_test3_isolation.sh and test_test8.sh, and none imports catalog, build_report, model_cards or export_model_docs. Nothing else in the repo does either, apart from make-report.sh calling build_report.
- **Compile.** py_compile passed on the three `.py.new` files and make_setups.py.
- **Current versus new previews.**
  - `preview/current/report/data.json` equals the live `report/data.json`, apart from `generated` and `events` (happenings.tsv grew after the live build).
  - `new` differs from `current` only by the `vision` key and the per-row `vision` field.
  - Both export runs passed the DENY check: 59 cards plus README each.
- **Page script.** The inline script of both artifact.html files ran under node against a stub DOM, offline with no browser (`<scratch>/vis/fix2/check_page.js`). There were no exceptions, and the new page fills `#vis-lede`, `#vis-table`, `#vis-method` and the fit-table column.
- **Measured path and review fixes.** `<scratch>/vis/fix2/fake_test.py` builds a scratch tree with a copied `engines/vision`, a FAKE `smoke-2026-10-09.tsv` covering two setups, a newer `smoke-2026-10-10.tsv` without an `entry` column, and a misnamed `smoke-2026-10-9.tsv`. All 18 checks passed (rerun after the Grok fixes):
  - Measured VRAM, tokens, encode time and a failed two-image status reach the catalog, data, card and page.
  - The bad and misnamed files are skipped, and the 2026-10-09 file is used.
  - Unmeasured setups stay "est.", and blind entries have no setup.
  - Orcarouter GLM is glm5v and not loadable; Maya GLM is glm5next.
  - Multi-record cards print the blind line per weights row; the index prints "–" with its legend.
  - A `|` and a newline in a display name do not split the card table.
  - A missing heads.tsv gives "not surveyed" rather than a crash.

## Not done

- **Not published.** No toolbox write, no PR, no `publish_review.py`, no Artifact. The next export puts the Vision column and sections on the public cards; that remains a separate step.
- **Nothing on Titan.** No ssh, no llama-swap call (not even GET /running), no GPU use, no bakeoff-* unit touched. No smoke run, so no measurement exists.
- **model_cards.py unchanged.** It needs no change: cards get their vision from `data.json`. Linking the unlinked records (MiMo and the others under Caveats) is left for the operator.
- **preview/ removed** from the repo (a review aid, not source), as step 4 of "How to enable it" says. A copy is in <scratch>/vis/fix2/preview-final on Saturn.
