# llama.cpp 0.6.0 + DFlash2 on Titan's RTX 3090

The fourth arm of the engine comparison of 2026-10-13 (Model Master 2), added after the three of the
published RTX 5090 run (`../tensorfold/`, `../exllamav3/`). Our own llama.cpp image, the one the `lcpp6-*` llama-swap
entries run (llama.cpp 0.6.0, build 11429, by digest), reads the DFlash2 drafter as a GGUF with `--spec-type
draft-dflash`. Nothing is built or patched. It works, and it is no faster on code than the MTP entry we already have,
slower on prose and 6 % faster on structured output. It is not a bake-off entry and not in llama-swap: it is started by
hand, under the GPU lease.

## Result

Qwen3.8-27B, RTX 3090 (24 GiB). Tokens per second after the first token, mean of 5 prompts per task at 400 tokens,
thinking off, temperature 0. Three rounds, a fresh server start for every engine and round, with TensorFold
interleaved in every round as the anchor to the other sittings, 22:56 to 23:16 (`rounds.sh`). In brackets: the range
over single prompts (`results-2026-10-13/summary.tsv`). Memory is what nvidia-smi showed after the round, at a 16k
window with the cache in 16-bit floats.

| engine | code | prose | structured | first token | memory |
|---|---|---|---|---|---|
| TensorFold 0.6.6 + DFlash2 (MLX 4-bit) | **170** (157-192) | **85** (75-97) | **213** (197-244) | 0.19 s | 17,744 MiB |
| llama.cpp + DFlash2 (UD-Q4_K_M, drafter BF16 GGUF, one slot) | 95 (87-102) | 43 (37-50) | 108 (101-117) | 0.37 s | 21,812 MiB |
| llama.cpp + MTP head (our entry's weights and drafting) | 95 (91-99) | 63 (56-74) | 102 (97-106) | 0.35 s | 18,612 MiB |
| llama.cpp, no drafting (UD-Q4_K_M, 1 round) | 43 | 43 | 43 | 0.33 s | 16,828 MiB |

From the other sittings the same evening: exllamav3 + DFlash2 158 / 73 / 181, exllamav3 + MTP 116 / 70 / 128;
TensorFold gave 167 / 81 / 209 and 170 / 84 / 211 there, so the three sittings agree within 3 %.

- On llama.cpp the DFlash2 drafter is as fast as the MTP head on code, slower on prose (43 against 63) and a little
  faster on structured output (108 against 102). It needs 3.1 GiB more memory than the MTP entry at this window.
- The drafter does its part: 47 % of its proposed tokens are accepted, the same as with exllamav3 (4,446 of 9,514
  here, 4,559 of 9,625 there), and on code it averages six tokens per step. The difference is the cost of a step:
  llama.cpp needs about 64 ms for one drafting step on code (400 tokens in 4.2 s at 6 tokens a step), against 23 ms
  for one plain token. exllamav3 turns the same acceptance into 158 tok/s.
- The drafter's precision and the server's slots do not change the speed. One round each: BF16 drafter, one slot
  96 / 44 / 109 (21,812 MiB); Q4_K_M drafter, one slot 95 / 44 / 108 (19,218 MiB); Q4_K_M drafter, four slots (the
  server's default) 95 / 44 / 109 (22,988 MiB). The BF16 drafter does not load beside four slots: out of memory even
  at an 8k window with an 8-bit cache.
- The MTP entry measured here as on its own llama-swap entry in the earlier sitting (93 / 64 / 100 at 147k with an
  8-bit cache; 95 / 63 / 102 here at 16k with a 16-bit cache).
- Drafting changes 4 of 15 llama.cpp replies against the undrafted ones (same weights, temperature 0); exllamav3
  changed 7 of 15, TensorFold none. Every mode repeats its own replies exactly in every round.

## What is compared, and what is not

- The llama.cpp + DFlash2 arm runs Qwen3.8-27B UD-Q4_K_M, the weights of our `qwen3.8-27b` entry, because the drafter
  is trained for the base model. The published run used IQ4_XS. The MTP arm is our Cyber fine-tune (IQ4_XS), the
  only 27B GGUF we have with an MTP head; it is not the same weights.
- The drafter's model card asks for llama.cpp with pull request 27342 ("DFlash 2 support"). Whether build 11429
  contains all of it was not checked; it loads the drafter, drafts 7 tokens a step in blocks of 8, and reaches the
  same acceptance as exllamav3. A newer llama.cpp may step faster.
- Window, cache precision and slots differ from our llama-swap entries (16k, 16-bit, one slot for DFlash2). The
  largest window with the DFlash2 drafter was not measured.
- No quality test ran. One sitting, one card, default power settings, our prompts.

## Run

Inputs are pinned: the image by digest (`run.sh`), the drafter by revision
(`/srv/store/models/dl-2026-10-13-dflash2-gguf.sh`, into `/srv/store/models/llm/tensorfold-hf`):

| repository | revision | use |
|---|---|---|
| `z-lab/Qwen3.8-27B-DFlash2-GGUF` | `2d9571f8` | the drafter, `BF16` (3.9 GB) and `Q4_K_M` (1.1 GB) |
| our `qwen3.8-27b` entry's file | `Qwen3.8-27B-UD-Q4_K_M.gguf` | the model |
| our `lcpp6-q38-27b-cyber-mtp` entry's file | `...-IQ4_XS-...-plus-mtp.gguf` | the MTP arm |

```
# on titan, in ~/tf-bench (this directory copied to ~/tf-bench/lcpp-dflash2), with the GPU lease held and
# llama-swap /running empty:
EXTRA="-np 1" lcpp-dflash2/run.sh dflash2    # or dflash2-q4, nodraft, mtp; serves on 127.0.0.1:18082
podman rm -f -t 10 lcpp-dflash2              # stop
lcpp-dflash2/rounds.sh                       # the whole comparison; one arm: lcpp-dflash2/rounds.sh lc LABEL MODE [flags]
```

The container runs read-only, with all capabilities dropped, with the models mounted read-only. The port has no
authentication while the server runs. `rounds.sh` keeps a round only if the server started, its log shows the
drafting mode asked for, and the benchmark finished; it prints the draft acceptance summed from the server log.
`analyze.py` compares replies between rounds and modes.

## Review

Grok 4.7 (xAI, a different model family) reviewed the scripts, the server logs, the results and this README read-only
on 2026-10-13. No must-fix findings: the rounds measure what they claim. The logs show the weights, drafter files,
7-token drafts, one slot and 16k window asked for; thinking stayed off; the client's tok/s matches the server's own
figure (94.6 against 94.57 on the first code prompt); the means in `summary.tsv` match the JSON. Three should-fix
findings in `rounds.sh` were fixed after the run, so the script here is slightly newer than the one that produced the
results: the full run now exits with its failure count; only an out-of-memory start of the BF16 probe switches the
rounds to the Q4_K_M drafter (any other failure stops the run); and the drafting check also requires the drafter file
asked for in the server log (the recorded logs pass it). The review also noted that the headline row has one slot
against four for MTP and no drafting; the Q4_K_M rows with one and four slots (same speed, same replies) show this
does not explain the gap.

## Files

| file | what |
|---|---|
| `run.sh` | start the server on titan |
| `rounds.sh` | the three-round comparison |
| `analyze.py` | reply identity and draft acceptance |
| `results-2026-10-13/` | `summary.tsv`, `rounds.log`, one JSON and one server log per round (`lcpp-dflash2-smoke` is the first try, with the Q4_K_M drafter and four slots), the TensorFold anchor rounds `tf-dflash2-s3-r*.json` |
