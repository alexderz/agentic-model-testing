# `bakeoff.spec` and `bakeoff-model.json`: what an entry serves, and what the model is

Operator decisions (2026-10-09): every Titan llama-swap entry points at one JSON file that states, in a fixed schema,
what the server behind it accepts, and every model folder carries one JSON file with the facts about the model.
The runners, `tools/preflight.py` and `tools/audit_runs.py` read limits from these files and nowhere else. Nobody
parses `-c`, `--max-model-len`, HyperQwen's `CTX=` profiles or Strata config files to learn a limit: every miss so far
(Gemma's 262k against a 73k server, for one) came from a second copy of a fact going stale. KrakenViz (llama-bored)
reads the same files for its displays.

There are two kinds of file:

| File | One per | Lives on titan at | Repo copy (the reviewed source) |
| --- | --- | --- | --- |
| Config spec | llama-swap entry | `~/ai/config/specs/<entry-id>.json` | `engines/entry-specs/<entry-id>.json` |
| Model record (`bakeoff-model.json`) | model folder | next to the weights: `~/ai/models/<dir>/` (the NAS, read-only on titan; written from Saturn under `/srv/store/models/<dir>/`) or the SSD folder (`~/ai/hyperqwen/models/<name>/`, `~/ai/models-local/...`) | `engines/model-meta/nas/<dir>.json`, `engines/model-meta/titan-ssd/<dir>.json` |

Several entries can share one model record (`used_by` lists them). The model record travels with the weights, so any
other user of the model finds it in the folder.

The report and the model cards read the same files and keep no list of models of their own (operator 2026-10-10:
a single source of truth). `tools/catalog.py` is their only reader: `tools/build_report.py` builds its catalog from
every spec and its record (`family` and `kind` from the record, `label` and `note` from the spec's `report` block, the
rest derived), and a card in `tools/model_cards.py` names its record(s) and takes its entries from `used_by`. A graded
entry without a spec is shown with a loud warning; a record no card names is warned about. An entry removed from titan
keeps its spec under `engines/entry-specs/retired/` and its place in `used_by`, so its results stay in the report. Four
entries that ran before specs existed (`gemma-4-31b-q8`, `maya-glm-5.3-flash-huihui`, `maya-glm-5.3-flash-orcarouter`,
`lcpp-glm-5.3-flash-orcarouter`) have a retired file with only the identity fields and the `report` block.

## How an entry points at its spec

The entry carries a path, never JSON:

- **Container entries** (`podman run ...`): a label on its own line right after `podman run --name X --rm`:
  `--label bakeoff.spec=/home/operator/ai/config/specs/<entry-id>.json`
- **Native entries** (`${srv}` or `/models/prism/llama-server`, which run inside the llama-swap container and have no
  `podman run`): llama-swap's per-model environment: `env: ['BAKEOFF_SPEC=/home/operator/ai/config/specs/<entry-id>.json']`

The config spec points at its model record through `model_meta`.

## Tools

- `tools/entry_spec.py` is the only reader. It resolves the reference from the yaml, reads and validates the config
  spec and the model record (over ssh, read-only, with `--titan`; from the repo copies with `--yaml COPY`), and reports
  a spec that is stale against the entry's current command (`cmd_sha256`) or has drifted from the repo copy.
  `--limits ID` prints `served reply context thinking` for the runners. `--check` checks every entry.
- `tools/add_entry_specs.py` applies the repo copies: model records to the NAS (from Saturn) and the SSD folders,
  config specs to `~/ai/config/specs/`, and the references into llama-swap.yaml (nothing loaded, backup, every other
  entry unchanged, 20 s reload). Dry run by default; `--apply` in a gap.
- `tools/model_meta.py FOLDER` reads the facts a folder holds (weights and sizes, GGUF header fields, HF config,
  drafters, mmproj). Facts that need judgment (family, base model, quirks, uncensored) are added in the repo copy.
- `lib.sh set_variant` rewrites the entry's spec file on titan (served_context, kv_type, thinking.server_budget,
  placement, cmd_sha256) through `entry_spec.py --rewrite` when a matrix row rewrites the entry's flag line. The yaml
  reference never changes. A matrix note may carry `spec={...}`, which wins over the flags; the runner saves it as
  `spec-override.json` in the case folder, and every case saves the spec it ran with as `entry-spec.json`.

## Config spec, schema 1

`null` means unknown or not applicable. Fields:

| Field | Meaning |
| --- | --- |
| `schema` | 1 |
| `generated` | When the file was written (ISO 8601). |
| `cmd_sha256` | sha256 of the entry's `cmd` with the spec label removed and whitespace collapsed (`entry_spec.cmd_hash`). A mismatch means the command changed since the spec was written. |
| `model_id` | The llama-swap entry id. |
| `model_meta` | Path on titan of the model record (`.../bakeoff-model.json`). |
| `model_file` | Host path on titan of the weights this config serves (a file, or a folder for vLLM/Maya). |
| `engine` | `llama.cpp`, `vllm`, `strata`, `maya`, `sglang`, `exllamav3` (TabbyAPI). |
| `engine_version` | `0.4-native`, `0.6`, `prism`, `kolibri`, `glm5next`, `hyperqwen-0.30`, `strata-0.1.40.3`, `maya-1.3.0`, `sglang-exl3`, `tabbyapi-a3fed43e-exl3-1.6.1`. |
| `served_context` | The most tokens (prompt plus reply) one request may use. The runners derive OpenCode's limits from it. |
| `parallel` | Requests served at once (llama.cpp slots, vLLM `--max-num-seqs`, Strata `parallel`); null if the engine decides. |
| `kv_type` | KV cache type: `f16`, `q8_0`, `q4_0`, `int8`, `auto`. |
| `thinking` | `default_on` (thinking without a per-request switch), `server_budget` (cap the server enforces), `request_field` (body field for a per-request cap: `thinking_token_budget` on vLLM, `thinking_budget_tokens` on llama.cpp 0.6), `budget_tokens` (the cap runners should send; null: computed from the reply limit). |
| `sampling` | Sampling the server applies by default (`temp`, `top_p`, `top_k`, `min_p`, `presence_penalty`); `{}` means engine defaults. Must match the model record's `recommended_sampling` (preflight C13); on llama.cpp every recommended key is set explicitly. A matrix row's sampling flags (`--temp`, `--top-p`, `--top-k`, `--min-p`, `--presence-penalty`) rewrite it. |
| `spec_decode` | Speculative decoding type as configured, or null. |
| `observability` | What KrakenViz can read: `metrics`, `slots_debug`, `prompt_tokens_details`, `force_include_usage`. |
| `storage` | `nas` or `ssd`: where the weights are read from (rule 8a). |
| `multi_agent_ok` | The engine serves several sessions at once without crashing or wedging (test 3 needs it). |
| `placement` | `gpu_layers`, `experts_on_cpu` (the `-ncmoe` count, 0 for none), `mmap` (false with `-lm none`), `ram_pinned_gb` (Maya/Strata RAM tier). |
| `serving` | `port`, `proxy` (llama-swap's upstream URL), `container_name` (`llama-swap` for native entries), `max_num_seqs`, `batch_tokens`, `prefix_caching`, `flash_attn`. |
| `speculative` | `type` (`none` when off), `draft_model`, `n_max`, `acceptance_note`. |
| `templates` | `chat_template_kwargs` sent by the server, `reasoning_parser`, `tool_call_parser`, `reasoning_start`, `reasoning_end`. |
| `endpoints` | `health`, `metrics`, `slots`, `props` (paths on the server, null when absent). |
| `role` | `daily_driver` (`cyber-fast`, `smart`, `fast`, `cyber-smart` or null) and `bakeoff_status` (`pass`, `partial`, `fail`, `untested`, from the report when the spec was written). |
| `report` | Optional. How the report and the model cards name this entry: `label` (the row's name, model and settings in a few words) and `note` (a short remark, omitted when empty). `base`, `arch`, `engine` and `quant` may be added only where the text `tools/catalog.py` derives from the record and the spec is not what the report should say. Flat strings; no effect on what the entry serves, on `cmd_sha256` or on any limit. |

## Model record (`bakeoff-model.json`), schema "bakeoff-model" version 1

| Field | Meaning |
| --- | --- |
| `schema`, `version`, `generated` | `"bakeoff-model"`, 1, when written. |
| `location` | `root` (`nas` or `titan-ssd`), `dir` (relative to `~/ai/models/` for the NAS, to `~/ai/` for the SSD), `titan_path`, `saturn_path` (null for SSD folders). |
| `display_name`, `family`, `base_model`, `arch` (`dense`, `moe`, `hybrid-moe`), `params_total_b`, `params_active_b`, `quant` | Identity. |
| `kind` | Optional, for the report: `stock`, `abliterated`, `heretic`, `uncensored-tune` or `security-tune`. The report marks every kind but `stock` as uncensored. Optional so that a record written before the field existed stays valid. |
| `weights` | `[{file, bytes}]`, relative to the folder; drafters and mmproj are listed separately. |
| `vision` | `supported` and the `mmproj` file. |
| `native_context` | The model's own maximum context (GGUF `<arch>.context_length` or HF `max_position_embeddings`). A config serving more relies on rope scaling. |
| `expert_count` | Routed experts, for MoE models. |
| `uncensored` | Abliterated or uncensored fine-tune. |
| `template_quirks` | Lessons about the chat template, in words (Gemma: thinking is off without `enable_thinking`). |
| `requires` | `chat_template_kwargs` every config must send (preflight check C7). |
| `recommended_sampling` | What the model's makers recommend: `temp` (or `temperature`), `top_p`, `top_k`, `min_p`, optional `presence_penalty`, and optional `from` (`gguf`, `generation_config` or `card`; inferred from the key names when absent). Read from the GGUF `general.sampling.*` keys, `generation_config.json`, or the model card in the folder (cards only when they state the values; nothing invented). Qwen3/3.8 cards: thinking mode `presence_penalty` 0.0; 0 to 2 is allowed against endless repetition, so a `-pp` case (1.5) is a documented deviation and only WARNs. |
| `reasoning_markers`, `tool_call_format` | Read from the chat template. |
| `drafters` | `[{type, file}]`: MTP heads, DFlash drafters, draft models in the folder. |
| `source` | `repo` and `revision`. |
| `license` | From the GGUF header or the README front matter. |
| `used_by` | The entries that serve this model. |

## Sampling the bake-off compares (`entry_spec.sampling_check`, preflight C13)

The effective sampling of a case is the entry's `sampling` plus what the client adds per request: the runner's `-pp`
(`presence_penalty` 1.5) and OpenCode's own temperature for some model ids (`OPENCODE_TEMP_IDS`: 1.0 for ids with
`glm-4.6`, `glm-4.7`, `minimax-m2`; nothing for Qwen, Gemma and the other open models, opencode 1.18.35). A recommended
key that the entry leaves unset FAILs on llama.cpp (not every build on titan is verified to apply the GGUF's own
`general.sampling.*` defaults, and bonsai2-27b-ada degenerated without the flags), WARNs on vLLM (it applies
`generation_config.json` by default) and on Strata, Maya and SGLang (not known). A conflicting value FAILs, except
`presence_penalty`, which WARNs.

## Limits the runners derive (`entry_spec.limits`)

- `reply = min(32000, served / 4)`
- `context = served - margin`, `margin = min(max(reply, 16384) + served / 10, max(28672, served / 10))` since
  2026-10-14 (`entry_spec.opencode_margin`). OpenCode compacts once a step's total passes `context - reply` and asks
  for the full reply on every request, so it reserves the reply itself. The margin covers only the prompt's growth
  since the last step: one large tool result can carry the next prompt past the wall. Growth census, 24,469 steps on
  2026-10-14: 99.9% grew by at most 24,961 tokens, 8 by more than 28,672, the largest by 43,593 (test 4). A growth
  above the margin right at the compaction point overflows the window; vLLM then refuses the request and the case
  ends. Compaction points: a 150k window compacts at about 89k instead of 71k, a 262k window at about 201k instead of
  172k. The margin is never larger than before, so windows under about 80k keep the old one (64k and 57k windows
  overflowed with less: wb-qwen3.8-27b-vllm-64k, wa-qwen3.8-27b-vllm-quote). Until 2026-10-14 the margin was
  `max(reply, 16384) + served / 10`, which held a whole reply on top of OpenCode's own, so a 150k window compacted
  at 71k. Pi gets `context - reply + 16384` as its window, since it reserves only 16,384 itself.
- `thinking = min(24000, reply - 6000)`, always below the reply limit.

Until every entry carries a spec, the runners fall back to their old hand-kept limits with a loud warning; delete the
fallback once `entry_spec.py --titan --check` is clean.

## Mirror for llama-watch

The dashboard's service account cannot read the home folder, so every spec is also copied to `/etc/llama-bored/specs/<entry-id>.json` on titan with its model record embedded under a top-level `model` key. `entry_spec.mirror_on_titan()` rebuilds the copies after each spec write and removes the copy of an entry that no longer exists. The copies are output only: nothing in the bake-off reads them.
