# GLM-5.3-Flash chat template for Maya (2026-10-15)

The operator asked to pick up the new GLM-5.3-Flash chat template ("pick up the new glm53 chat templates") after the
daily setup check saw zai-org change it on 2026-10-15.

## Which entries use it

Only `maya-glm-5.3-flash` serves GLM-5.3-Flash on titan. No llama.cpp entry passes a GLM-5.3 `--chat-template-file`.
The retired Huihui and OrcaRouter GLM entries have their own packs and are not touched. Maya renders
`<pack>/tokenizer/chat_template.jinja` with Jinja2 3.1.6 (sandboxed, trim/lstrip blocks, loopcontrols), and it reads
the file once when its container starts. The pack is on Saturn at
`/srv/store/models/llm/glm-5.3-flash-maya/Maya-S-v2-IQ2_XXS/pack/`, and titan reads it over NFS.

## Versions

| file | what |
|---|---|
| `pack-03eb5366.chat_template.jinja` | the pack's template since 2026-10-07: zai-org revision 03eb5366 (2026-08-31), with the four `.0.` index lookups written `[0].` as in the Maya-S GGUF (sha256 a4fddbbf…) |
| `upstream-46a050be.chat_template.jinja` | zai-org/GLM-5.3-Flash at 46a050bec13002ad29ee795c16e61cf4fa3c4a9c (2026-10-15, PR #63 "speed up tool-result validation and reordering"), byte for byte (sha256 2614a3c8…) |
| `chat_template-46a050be.jinja` | the staged file: upstream 46a050be with the same `.0.` → `[0].` rewrite at its four sites, nothing else (sha256 9f48a59d…) |

There are two upstream changes after our copy:
- **690b7052 (2026-09-04):** an early `break` in the tool-result reordering check, `~` for the tool-call name, and a
  none content is no longer printed as the text "None".
- **46a050be (2026-10-15):** the reordering check builds the id lists once and uses `unique` and `sort` in place of
  nested loops. It makes the same decision and gives the same order.

`generation_config.json` is unchanged at every revision (temperature 1.0, top_p 0.95), so sampling stays as it is.

## What it changes for us: nothing in the prompt

`check_render.py` runs in Maya's own image, offline. It renders both templates through Maya's request converters and
also renders raw messages with ids:

    podman run --rm --network none --entrypoint /opt/venv/bin/python3 -v "$PWD:/t:ro,Z" 0b1e71f83065 \
      -I /t/check_render.py /t/pack-03eb5366.chat_template.jinja /t/chat_template-46a050be.jinja

Result on 2026-10-15: ALL PASS. The claims below cover the request shapes in the check, not every possible request.
- **Byte-identical prompts.** This holds for every OpenAI and Anthropic request in the check: plain, one call,
  parallel calls in order and shuffled, a late system message and an image, at every effort and with thinking off.
- **Why.** Maya's converters drop tool-call ids, and they turn a none content into "". So the reordering branch never
  runs for Maya, and the "None" case cannot occur.
- **With ids (raw messages).** Old and new templates give the same output. Each is also checked against a stated
  result order: shuffled results go back to call order, and with a duplicate or unknown id both keep the order given.
  The only difference is a none content: the new output is the old one minus its single "None" (the intended 09-04
  fix).

So the swap keeps Maya on the current upstream template without changing the prompts of these requests.

## Apply

Use `./apply.sh` on Saturn, as operator.
- **Modes.** `--check` shows which template is live. `--rollback` restores the pack's original from
  `pack-03eb5366.chat_template.jinja` in this directory (not from the backup).
- **Checks before the swap.** One run at a time (a lock). It checks both shas and parses titan's `/running` as JSON;
  it refuses while a `maya*` entry is loaded and on any response it cannot parse. It asks only GET /running.
- **The idle check is advisory.** Nothing stops a Maya load between the check and the rename. That is safe: the rename
  is atomic, so Maya reads either the whole old or the whole new file, and both render the same prompts for Maya.
- **The swap.** An existing backup `chat_template.jinja.bak-zai-03eb5366` must be a regular file with the old sha, or
  the run stops; a missing one is created without overwriting anything. The new file goes to a temp file in the same
  directory, is checked against its sha, the live file is checked again, and then an atomic rename puts it in place
  and the result is checked once more. A failed run removes its temp file.
- **What it does not do.** No llama-swap edit, reload or restart. The next load of `maya-glm-5.3-flash` uses the new
  file.
