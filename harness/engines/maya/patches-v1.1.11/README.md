# Our patches, re-ported by hand to Maya v1.1.11 (2026-10-15, Model Master 2)

v1.0.4 carries three patches (`../patches/`). Each one was read against v1.1.11's code (tag `v1.1.11`, commit
`89313399b330600b455603d3c569c1f188f96db1`). None is needed any more: upstream now does each job itself. So this
directory has no `.patch` file, and `build.sh` builds v1.1.11 as upstream ships it, image `localhost/maya:v1.1.11-sm86`.

| v1.0.4 patch | What it did | Where v1.1.11 does it |
|---|---|---|
| `0001-ram-all.patch` (`STRATA_GLM_RAM_ALL=1`) | Sized the RAM tier for every expert of a layer, so a VRAM victim always found a free RAM slot instead of being dropped and read back from disk. | RAM-resident mode, `STRATA_GLM_RAM_RESIDENT=1` (`src/core/glm_fast_path.cu`, `fast_setup` about lines 620-625 and the RAM-tier sizing at about line 1385). The tier gets every expert VRAM does not hold, plus `STRATA_GLM_RAM_SLACK` slots a layer (default 16). A demotion with no free RAM slot keeps the expert in VRAM (`diag_resident_skip`), so nothing drops to disk. The start fails if the tier cannot hold them all (line about 1580). That is stricter than our patch, which shrank the tier silently. |
| `0002-drain-serve.patch` (`STRATA_GLM_DRAIN_SERVE=1`) | Kept a demoted expert's VRAM table entry live until its copy to RAM landed, so a route in that window hit VRAM instead of the disk. | The same mode. In `fast_boundary`, the eviction leaves the VRAM entry when `ram_resident` (about line 4358), and the landing clears it with the RAM entry going live (about line 4283). Upstream ties this to resident mode; we used both of our switches together, so nothing is lost. |
| `0003-glm-tool-calls.patch` | Parsed GLM-5.3's `NAME<arg_key>K</arg_key><arg_value>V</arg_value>` tool calls, which v1.0.4 rejected as malformed. | Upstream since v1.0.13 (issue #5): `serve/frontend.py` `parse_tool_call` / `call_name`. It has the same value rule as ours (a string schema type keeps the text, anything else is JSON-decoded when it parses), and it also streams the calls and leaves calls quoted inside code as text. |

The config `glm-5.3-flash-v1111.json` (written on titan by `tools/add_clone_entry.py`, plan
`../maya1111-entry.json`) therefore sets `STRATA_GLM_RAM_RESIDENT=1` in place of `STRATA_GLM_RAM_ALL=1` and
`STRATA_GLM_DRAIN_SERVE=1`, and keeps `STRATA_GLM_RAM_GB=95`. v1.0.4's RAM tier with RAM_ALL was 81.51 GB for 12,306
slots (273 a layer over 45 layers), with a 44-slot VRAM pool a layer. Resident mode needs about
256 - 44 + spares + 2 + 16 slots a layer, which is fewer, so 95 GB holds it.

## The split-digit fault (TAKEOVER 2026-10-10 15:00)

On v1.0.4, GLM wrote multi-digit numbers in tool arguments split by spaces or commas (`head -2 0`, offset `8 5`,
timeout `6 0 0 0 0 0`, 434 sent as 4343). v1.0.15's notes (#27) give a likely cause. Up to v1.0.14, the server split
every number in a prompt into single digits (Qwen's pre-tokenizer), while GLM groups up to three digits. From about
12k tokens of context on, numbers came back wrong (`504` came back as `5504`). Our pack's `tokenizer/tokenizer.json`
already names `"pre": "glm4"`, which v1.0.4 ignored and v1.1.11 reads (`tools/strata_tokenizer.py`
`Tokenizer.from_dir`). So v1.1.11 should tokenise numbers the way the model was trained, with the same pack. Our
patch 0003 only parsed the calls and did not cause the fault. The A/B step `queue-new.d/50-maya1111-ab.sh` checks the
fault first, on both versions (`tools/maya_digits_probe.py`).

## Other things the build needed

- `git` in the build stage of `../Containerfile`. Since v1.1.6 Maya's CMakeLists applies its own
  `third_party/ggml/mmq-fused-swiglu.patch` to a copy of the pinned ggml with `git apply`. Without git it only warns
  and builds the slower prompt path.
- The same llama.cpp pin (`3cf03257…`, zip sha256 `cbe23c59…`), the same CUDA images and the same Python packages
  (`setup.py` `PY_PACKAGES` is unchanged). The container still starts `serve/server.py` directly, so `maya.py`'s
  launcher-only pack guard (#155) does not apply.
