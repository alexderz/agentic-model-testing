# exllamav3 1.6.1 + DFlash2 on Titan's RTX 3090

The third arm of the engine comparison of 2026-10-13 (Model Master 2); the other two are in
`../tensorfold/`. exllamav3 (github.com/turboderp-org/exllamav3, MIT) runs here behind TabbyAPI
(github.com/theroyallab/tabbyAPI, AGPL-3.0), both unpatched: stock exllamav3 has read DFlash2 drafters since v1.5.1.
On our card it writes Qwen3.8-27B almost as fast as TensorFold, holds a larger window, and needs no patch. The trial
below was started by hand under the GPU lease; since 2026-10-14 (operator: "ex+mtp and dflash2 keep") the two drafted
setups are also llama-swap and bake-off entries, see "Entries" at the end.

## Result

Qwen3.8-27B, 4-bit, RTX 3090 (24 GiB). Tokens per second after the first token, mean of 5 prompts per task at 400
tokens, thinking off, temperature 0. Three rounds, a fresh server start for every engine and round, the exllamav3
arms and TensorFold interleaved in one sitting, 22:02 to 22:27 (`rounds.sh`, `tools/bench_tasks.py`). In brackets:
the range over single prompts, as in `results-2026-10-13/summary.tsv`. Memory is what nvidia-smi showed after the
round, at a 16k window.

| engine | code | prose | structured | first token | memory |
|---|---|---|---|---|---|
| TensorFold 0.6.6 + DFlash2 (MLX 4-bit) | **170** (155-192) | **84** (72-97) | **211** (189-244) | 0.19 s | 17,744 MiB |
| exllamav3 1.6.1 + DFlash2 (EXL3 4.00bpw) | 158 (152-166) | 73 (66-82) | 181 (167-209) | 0.14 s | 19,972 MiB |
| exllamav3 1.6.1 + its own MTP head (EXL3 4.00bpw) | 116 (112-120) | 70 (64-74) | 128 (126-131) | 0.14 s | 16,324 MiB |
| exllamav3 1.6.1, no drafting (1 round) | 42 | 42 | 42 | 0.11 s | 15,956 MiB |
| exllamav3 1.6.1 + DFlash2, EXL3 3.00bpw (1 round) | 153 | 74 | 183 | 0.14 s | 17,012 MiB |

From the earlier sitting the same evening (`../tensorfold/README.md`) and the later one with llama.cpp + DFlash2
(`../llamacpp-dflash2/README.md`, 95 / 43 / 108), for comparison: llama.cpp + MTP 93 / 64 / 100,
llama.cpp without drafting 42 / 42 / 42, TensorFold without the drafter 28 / 28 / 27, and TensorFold + DFlash2
167 / 81 / 209, which this sitting repeats within 3 %.

- TensorFold is ahead of exllamav3 with the same drafter by 7 % on code, 15 % on prose and 17 % on structured
  output. In the published RTX 5090 run it was ahead by 43 %, 53 % and 73 % (370 / 174 / 634 against 258 / 114 /
  366). On our card the gap is small.
- Our 3090 reaches 61 %, 64 % and 49 % of the published 5090 numbers for exllamav3 + DFlash2.
- exllamav3 with its own MTP head is faster than our llama.cpp MTP entry (116 / 70 / 128 against 93 / 64 / 100) and
  uses 16,324 MiB at a 16k window. The two are not the same weights: the llama.cpp entry is the Cyber fine-tune.
- Without drafting exllamav3 and llama.cpp write at the same 42 tok/s. TensorFold without its drafter writes 28.
- The drafter costs about 4 GiB of memory on exllamav3 (19,972 against 15,956 MiB). TensorFold holds the same
  drafter in 1.1 GiB more than its undrafted state.
- 3.00bpw weights are as fast as 4.00bpw and take 3 GiB less. Their quality was not measured.
- The exllamav3 rounds are very steady: every round gave the same 15 replies and speeds within 1 %, except one
  structured round at 175.
- In the DFlash2 rounds 47 % of the drafted tokens were accepted, in the MTP rounds 63 % (first round of each,
  from the server log).

### Drafting changes some replies on exllamav3

At temperature 0, TensorFold's drafted replies are identical to its undrafted ones. On exllamav3 they are not always:
7 of 15 DFlash2 replies and 10 of 15 MTP replies differ from the undrafted reply from some point on (for example
"Sort intervals by start point" against "Sort intervals by start, then by end"). The two drafting modes leave the
undrafted reply at the same places in the seven replies they share, so the cause is the engine's checking of several
tokens in one pass, which rounds differently from one token at a time, and not what the drafter proposes. Each mode
gives the same replies in every round. Nobody graded whether the changed replies are better or worse.

### Context window

exllamav3 keeps the key-value cache in 16-bit floats by default and can store it in fewer bits. `context-probe.sh`
starts the server with a window, sends long prompts with one fact hidden in the middle
(`../tensorfold/long_prompt.py`) and records what the card holds (`results-2026-10-13/context-probe.log`):

| drafting | window | cache | prompt read | memory at the end | result |
|---|---|---|---|---|---|
| DFlash2 | 65,536 | 16-bit | 31,926 tokens in 32.7 s; 63,826 in 72.8 s | 23,616 MiB | answers correct |
| DFlash2 | 98,304 | 8-bit | 31,926 in 32.7 s; 94,626 in 119.9 s | 23,004 MiB | answers correct |
| DFlash2 | 131,072 | 8-bit | none | 24,132 MiB | loads, then out of memory on the first long prompt |
| MTP head | 131,072 | 8-bit | 31,926 in 32.2 s; 127,626 in 188.1 s | 20,896 MiB | answers correct |

- With the DFlash2 drafter exllamav3 holds 65k tokens with the cache as it is and 98k with an 8-bit cache. TensorFold
  holds 42,724 by default and 73,308 at the edge of the card, and has no smaller cache.
- With its own MTP head it holds 131k with an 8-bit cache and 3.6 GiB to spare. Our llama.cpp MTP entry serves 147k.
- Prompts are read at about 1,000 tokens per second up to 32k and more slowly beyond (880 at 64k, 790 at 95k, 680
  at 128k). TensorFold and llama.cpp read 64k in 68 and 64 s; exllamav3 needs 73 s.
- A repeated 32k prompt is answered from cache in 0.6 s.
- The largest window with DFlash2 was not searched for; 98k works and 131k does not. Whether the 8-bit cache
  changes answers was not measured.

## What is compared, and what is not

- The arms run different 4-bit recipes (MLX 4-bit, EXL3 4.00bpw, GGUF IQ4_XS), as in the published run. This
  compares serving recipes, not quantisations of equal quality. No quality test ran on the exllamav3 or TensorFold arm.
- TensorFold and the exllamav3 arms were measured in one sitting. The llama.cpp numbers are from the sitting two
  hours earlier on the same card; TensorFold was in both and agrees within 3 %.
- exllamav3 warms up while it loads (`warmup: true`), so nothing is compiled during the measured requests. The first
  prompt of a round still waits longer for its first token than the 0.14 s of the others (0.26 to 0.28 s with
  DFlash2, 0.85 s in the first MTP round); speed is counted after the first token.
- The drafter proposes 7 tokens a step, the model's own default. Other values and `dynamic_draft` were not tried.
- The prompts are ours, not the ones of the published run. One sitting, one card, default power settings.
- The three recorded rounds ran on the first version of `run.sh` and `rounds.sh`. The review's changes (below) came
  after; one more round with them gave 159 / 73 / 184 (`results-2026-10-13/confirm-round.log`). Each recorded round
  was checked by hand against its server log: warmed up, the drafting mode asked for, the 4.00bpw weights, 15
  requests (`results-2026-10-13/*.server.log`).

## Build and run

Inputs are pinned: TabbyAPI at commit `a3fed43e` (`build.sh`), whose `cu12` extra names the torch 2.9.0+cu128 and
exllamav3 1.6.1 wheels by URL; the Ubuntu base image by digest (`Containerfile`); all wheels by `pip-freeze.txt`,
which holds the sha256 of the two URL wheels and is compared with the image after every build; the weights by
revision, in `/srv/store/models/llm/tensorfold-hf`:

| repository | revision | use |
|---|---|---|
| `turboderp/Qwen3.8-27B-exl3` | `113cf7ab` (branch `4.00bpw`) | the model (`/srv/store/models/dl-2026-10-13-exl3-4bpw.sh`) |
| `turboderp/Qwen3.8-27B-exl3` | `6fe61ad6` (branch `3.00bpw`) | one extra round; downloaded first by mistake for the 4-bit weights |
| `z-lab/Qwen3.8-27B-DFlash2` | `50307d4c` | the drafter, the same file TensorFold uses |

```
./build.sh                                   # on Saturn as operator: clones at the commit, builds on titan
# on titan, in ~/tf-bench (this directory copied to ~/tf-bench/exllamav3), with the GPU lease held and
# llama-swap /running empty:
exllamav3/run.sh dflash2                     # or mtp, or nodraft; a second argument 3bpw takes the 3-bit weights
podman rm -f -t 10 exllamav3                 # stop
exllamav3/rounds.sh                          # the whole comparison; or one arm: exllamav3/rounds.sh ex LABEL mtp
```

The server answers on 127.0.0.1:18081 once the model is loaded and warmed up (34 s with the files in the page
cache, 142 s on the first read from the NAS). The model name in a request is the snapshot's revision; `/v1/model`
gives it. The container runs read-only, with all capabilities dropped, as user `tabby`, with the models and
`config.yml` mounted read-only and no network use at run time. Authentication is off: anyone logged in on titan can
reach the port while the server runs. `config.yml` holds the settings; `run.sh` chooses weights and drafting mode
with `TABBY_*` variables, which override the file.

## Review

Grok 4.7 (a different model family, read-only) read the recipe and TabbyAPI's source at the pinned commit. It found
nothing that must be fixed and confirmed: environment values override the file and are parsed to the right types,
`draft_mode: disabled` loads no drafter although the file names one, the client's `enable_thinking: false` reaches
the template, an empty `override_preset` leaves temperature 0 greedy, and the port answers only after the warmup.
Worth fixing, and fixed after the recorded rounds:

- `rounds.sh` recorded a round whatever happened. It now removes the old result first and leaves none when the
  server did not start, did not warm up, runs another drafting mode than asked, or the benchmark failed.
- `build.sh` wrote `pip-freeze.txt` anew after every build. It now fails when the image differs from the recorded
  list, and `run.sh` starts the image by the id in `image-id.txt`.
- The container now runs with a read-only root.

Left as it is: the warmup drafts 4 tokens a step and the measurement 7. A round with 7 set for both gave the same
speed (the confirming round above).

## Files

| file | what |
|---|---|
| `Containerfile`, `build.sh`, `image-id.txt`, `pip-freeze.txt` | the image and its pins |
| `config.yml`, `run.sh` | the server's settings and its start on titan |
| `rounds.sh` | the three-round comparison |
| `context-probe.sh` | windows and long prompts |
| `summarize.py` | `summary.tsv` from the round files |
| `results-2026-10-13/` | `summary.tsv`, `rounds.log`, one JSON and one server log per round, `context-probe.log`, `confirm-round.log` |

## Entries (2026-10-14)

Two llama-swap entries serve the same image, weights and config file, and differ only in environment variables
(`tools/add_exl3_entries.py` writes them; specs in `engines/entry-specs/exl3-qwen3.8-27b-*.json`, model record
`engines/model-meta/nas/llm/tensorfold-hf/hub/models--turboderp--Qwen3.8-27B-exl3.json`):

| entry | drafting | window | cache | server thinking budget |
|---|---|---|---|---|
| `exl3-qwen3.8-27b-mtp` | the model's own MTP head | 196,608 | 8-bit | 24,000 |
| `exl3-qwen3.8-27b-dflash2` | z-lab DFlash2 drafter | 98,304 | 8-bit | 18,576 |

The 8-bit cache is the main model's; the DFlash2 drafter's own cache stays FP16 (`draft_cache_mode`). The specs
say `prefix_caching: true` because TabbyAPI reuses a matching prompt prefix by default; no flag sets it.

- Config: `daily/tabby-qwen38.yml`, on titan at `~/ai/config/exllamav3/tabby-qwen38.yml`, mounted read-only. EXL3
  4.00bpw (snapshot `113cf7ab`), reasoning parser on, sampling defaults from the model's generation_config (temperature
  1.0, top_k 20, top_p 0.95; the config also sets min_p 0, which generation_config leaves out; none forced, so a request may override them).
- Per entry: `TABBY_DRAFT_MODEL_DRAFT_MODE` (`mtp` or `model`), `TABBY_MODEL_MAX_SEQ_LEN` and `TABBY_MODEL_CACHE_SIZE`
  (the window), `TABBY_MODEL_CACHE_MODE=8,8`, `TABBY_MODEL_REASONING_BUDGET_TOKENS` (min(24,000, reply limit - 6,000)).
- The window: MTP holds 196k because the head is small; the DFlash2 drafter takes about 4 GiB, so 98k is its window
  with an 8-bit cache.
- A request can set its own budget with `thinking_token_budget` (checked: 300 gave about 820 characters of thinking).
- Container: fixed name `exllamav3`, network `llama`, no published port, all capabilities dropped, no-new-privileges,
  read-only root with a 64 MB tmpfs for logs, models read-only, compiled kernels in the volume `exllamav3-cache`.
- Smoke test 2026-10-14 07:03-07:05: both load through llama-swap, split thinking from the answer, and answer a short
  code task (MTP 96 tok/s with 65 % of drafts accepted; DFlash2 125 tok/s with 53 %), 22.3-22.6 GB in use.

