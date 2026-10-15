# Master model catalog (operator 2026-10-10)

"We should maintain a master model catalog in YAML somewhere on Titan, captured probably in our code repo. That should
be the absolute master. We add to it, we modify it, and then we use that to regenerate things like llama-swap configs,
reporting configs, and whatever else. It can be an input to a template, or a generator, or just read directly by code."

Status: DRAFT plan by Model Master. Not built.

## Today (what the catalog replaces)

The same facts are written in several places and kept in step by hand and by checks:
- Titan's `~/ai/config/llama-swap.yaml`: one hand-edited entry per served configuration (the `cmd` text holds the
  weights path, context, cache type, sampling, expert placement, drafting, template switches).
- `engines/entry-specs/<id>.json`: a reviewed description of each entry, tied to the yaml by a hash of its cmd.
- `engines/model-meta/<root>/<dir>.json`: one record per model folder (weights, recommended sampling, quirks).
- `tools/add_*_entry.py`: a table per batch of new entries, each generating yaml text.
- `tools/build_report.py` and `tools/model_cards.py`: their own model lists (being removed, 2026-10-10).

## Target

`catalog/models.yaml` in this repo is the only place a model or a served configuration is described. One section per
model (source, weight files, architecture, family, kind, recommended sampling, template quirks, licence), and under it
one section per entry (engine and version, weights file, context, cache type, placement, sampling, thinking, drafting,
template switches, slots, report label and note, status). Everything else is generated from it or reads it:

| Output | How |
|---|---|
| llama-swap entries on Titan | generated from the entry section through one template per engine |
| entry specs and model records on Titan and the NAS | generated (they become build outputs, no longer reviewed sources) |
| report catalog, model cards' entry lists | read directly through `tools/catalog.py` |
| preflight checks C1 to C15 | read the catalog; C1 (spec matches the yaml) becomes "the yaml matches the generator" |
| matrices | validated against the catalog (entry exists, flags allowed) |

A copy of the catalog is deployed to Titan (`~/ai/config/catalog/`) with the generated yaml, so the host carries its
own description.

## Steps

1. `tools/catalog.py` as the single reader; the report and cards go through it (in progress).
2. Generate the first `catalog/models.yaml` FROM today's specs, records and Titan's yaml, so nothing is retyped.
3. Write the generators and prove them: the yaml generated from the catalog must equal today's llama-swap.yaml entry
   for entry (parsed, not byte for byte), and the generated specs must equal today's specs. No generator writes to
   Titan until that holds for every entry.
4. Switch: new entries are added by editing the catalog and running the generator (with nothing loaded, backup, same
   rules as today). `tools/add_*_entry.py` and the hand-reviewed JSON files are retired.

## Open points

- **Ownership of Titan's yaml.** The file also holds entries that are not the bake-off's (daily drivers and other
  services maintained separately). Options: the catalog covers every entry and the generator owns the whole file, or it
  owns only the bake-off entries and leaves the rest untouched (a marked block). Either way the owner of those
  entries reviews the change before a generator writes that file.
- **Per-case variants.** Matrix rows can override flags for one case (`set_variant`). Either every variant becomes a
  named entry in the catalog, or the catalog lists the allowed overrides.
- **When.** The switch needs a moment with nothing loaded and no queue depending on the old tools, so after the retry
  wave, which still uses `tools/add_retry_entries.py`.
