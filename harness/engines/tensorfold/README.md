# TensorFold 0.6.6 + DFlash2 on Titan's RTX 3090

Trial of 2026-10-13 (Model Master 2). TensorFold is a Python inference engine
(github.com/ashhart/TensorFold, Apache-2.0) that compiles its own CUDA kernels on first start. With the DFlash2
drafter it writes Qwen3.8-27B about twice as fast as our llama.cpp MTP entry on the same card. It is not a bake-off
entry and not in llama-swap: it is started by hand, under the GPU lease.

## Result

Qwen3.8-27B, 4-bit, RTX 3090 (24 GiB). Tokens per second after the first token, mean of 5 prompts per task at 400
tokens, thinking off, temperature 0. Three rounds, engines interleaved, a fresh server start for every engine and
round (`rounds.sh`, `tools/bench_tasks.py`). In brackets: the range as `results-2026-10-13/summary.tsv` has it.

| engine | code | prose | structured | first token | VRAM |
|---|---|---|---|---|---|
| TensorFold 0.6.6 + DFlash2 (MLX 4-bit) | **167** (152-188) | **81** (70-96) | **209** (196-242) | 0.19 s | 17,744 MiB at 16k context |
| llama.cpp + MTP (`lcpp6-q38-27b-cyber-mtp`, IQ4_XS) | 93 (88-97) | 64 (55-73) | 100 (96-103) | 0.36 s | 23,738 MiB at 147k context |
| llama.cpp, no drafting (`qwen3.8-27b`, UD-Q4_K_M) | 42 | 42 | 42 | 0.34 s | 23,842 MiB at 213k context |
| TensorFold 0.6.6, no drafter (1 round) | 28 | 28 | 27 | 0.19 s | 16,634 MiB at 16k context |

- TensorFold with the drafter is 1.8 times the MTP entry on code, 1.3 times on prose and 2.1 times on structured
  output; against plain llama.cpp it is 4, 1.9 and 5 times.
- Without the drafter TensorFold is slower than plain llama.cpp (28 against 42). The whole gain is the drafter.
- The published RTX 5090 run this follows had 370 / 174 / 634 for TensorFold + DFlash2 and 186 / 116 / 200 for
  llama.cpp MTP. Our 3090 reaches 45 %, 47 % and 33 % of the first and 50 %, 55 % and 50 % of the second.
- Drafting does not change the output: at temperature 0 all 15 replies of a drafted round are identical to the
  undrafted round's, character for character, and identical from round to round.
- The three rounds ran on patch revision 2. Revisions 3 and 4 changed no kernel and nothing on the default serving
  path (the `--prefill-fp8` refusal, one message, tests, documentation). One more round on revision 3 gave
  172 / 85 / 213 (`results-2026-10-13/tf-dflash2-p3.json`); revision 4 was checked with its tests and one served
  request (`results-2026-10-13/smoke-p4.log`).

### Context window

TensorFold keeps the key-value cache for this model family in bf16 only (`--kv-dtype int8` and `int4` are refused),
so the window is much smaller than llama.cpp's with its 8-bit cache. `context-probe.sh` asks for the native window
and reads the largest one the startup check admits:

| setting | window |
|---|---|
| default (4 GiB memory reserve) | 42,724 tokens |
| `TENSORFOLD_MEMORY_RESERVE_GIB=2` | 73,308 tokens |
| default, no drafter | 60,061 tokens |
| llama.cpp MTP entry, for comparison | 147,456 tokens |
| llama.cpp plain entry, for comparison | 212,992 tokens |

At 73,308 the card is at its edge: 22,854 MiB used, and the server log shows CUDA out-of-memory warnings during long
prompts (`results-2026-10-13/startup-73k.log`). Every request still answered correctly. 42,724 is the safe setting.

### Long prompts

`long_prompt.py` sends N numbered filler lines with one fact hidden in the middle and asks for it. All engines
found it every time. Time to read a prompt nothing has cached (`results-2026-10-13/long-prompt.log`):

| prompt tokens | TensorFold + DFlash2 | llama.cpp MTP | llama.cpp plain |
|---|---|---|---|
| 31,926 | 30.3 s | 28.1 s | 28.2 s |
| 63,826 | 68.1 s | 65.1 s | 63.7 s |
| 72,626 | 79.2 s | 76.9 s | 75.1 s |

All three read at about 1,000 tokens per second, and all three answer a repeated prompt from cache in 0.4 s.
TensorFold's lead is in writing only. (The first llama.cpp MTP pass in the log overlapped a leftover request and is
marked to be discarded; the table uses the clean rerun.)

## What is compared, and what is not

- The three arms run different 4-bit recipes (MLX 4-bit, GGUF IQ4_XS, GGUF UD-Q4_K_M), as in the published run. This
  compares serving recipes, not quantisations of equal quality. No quality test was run on the TensorFold arm.
- The llama.cpp MTP arm is our Cyber fine-tune of Qwen3.8-27B, the only 27B entry we have with an MTP head. Speed
  should be close to the base model's; it is not the same weights.
- The prompts are ours (`tools/bench_tasks.py`), not the ones of the published run.
- The exllamav3 + DFlash2 arm of the published run ran later the same evening, with TensorFold interleaved
  again (170 / 84 / 211 against 158 / 73 / 181): `../exllamav3/README.md`.
- The memory column is what nvidia-smi showed, in MiB. Until the correction of 2026-10-13 this file gave the
  same figures divided by 1,000 and called them GiB.
- One sitting, one card, default power settings.

## Build and run

Inputs are pinned: TensorFold tag v0.6.6 at commit `cb2ebf05` (`build.sh`), the Ubuntu base image by digest
(`Containerfile`), the Python wheels by `pip-freeze.txt` (torch 2.14.1, triton 3.8.0, cuda-toolkit 13.0.3.0), and
the weights by revision (`/srv/store/models/dl-2026-10-13-tensorfold.sh`, into `/srv/store/models/llm/tensorfold-hf`):

| repository | revision | use |
|---|---|---|
| `TensorFold/Qwen3.8-27B-MLX-4bit` | `22d8d538` | the model |
| `z-lab/Qwen3.8-27B-DFlash2` | `50307d4c` | the drafter |
| `turboderp/Qwen3.8-27B-exl3` | `6fe61ad6` (branch `3.00bpw`) | one extra round of the exllamav3 arm |
| `turboderp/Qwen3.8-27B-exl3` | `113cf7ab` (branch `4.00bpw`) | the exllamav3 arm (`../exllamav3/`) |

```
./build.sh                                   # on Saturn as operator: clones, patches, builds on titan
# on titan, in ~/tf-bench (copies of these scripts), with the GPU lease held and llama-swap /running empty:
./run.sh --context 16384 --no-thinking       # serves on 127.0.0.1:18080, model name "bench"
podman rm -f -t 10 tensorfold                # stop
```

The image is `localhost/tensorfold:v0.6.6-sm86-p<patch revision>`; its id is in `image-id.txt`. The container runs
with all capabilities dropped, as user `tf`, with the models mounted read-only and no network use at run time
(`HF_HUB_OFFLINE=1`, update check off). The compiled kernels live in the podman volume `tensorfold-cache`.

A start loads in 76 to 120 s, and the first request of a normal start gets its first token in 0.8 s. The first
request after a new image or after `kernel-tests.sh` is different: it recompiles the kernels and waited 96 s (p3) and
98 s (p4) for its first token. During that time the log says "waits on the build lock", which is misleading: it is
building. The start after it is normal again (`results-2026-10-13/first-request-p4.log`). So send one throwaway
request after a rebuild before measuring anything.

## The patch

Upstream refuses every GPU below compute capability 8.9, because some of its kernels use FP8 matrix instructions
that arrived with the RTX 40 series. The RTX 3090 is 8.6. The kernels a 4-bit MLX or EXL3 checkpoint needs use only
instructions the 3090 has. `patches/0001-sm86-floor-and-fp8-stub.patch` (revision 4, 15 files):

- lowers the floor to 8.6 and names 8.9 as a separate `FP8` level (`cuda/build.py`);
- on a card below 8.9, builds the 4-bit extension with `qmm_prefill8_stub.cu` in place of the one FP8-only kernel
  file, under its own extension name (`tensorfold_qmm_v5_nofp8`), so a cache never mixes the two;
- keeps 8.9 as the floor for NVFP4 and FP8 checkpoints (`cuda/capacity.py`, `cuda/nvfp4/`);
- refuses `--prefill-fp8` on such a card at startup, before the weights load, and says to drop the flag
  (`cli.py`). Prompts run bf16 activations by default, so nothing is lost on the default path;
- updates upstream's tests and the three places in its documentation that state the floor.

Reviewed twice by Grok 4.7 (a different model family, read-only). Review 1 found two things worth fixing, both in
revision 2. Review 2, of revision 3, found nothing that must be fixed on the default path and one thing worth
fixing (the documentation still said 8.9), fixed in revision 4 together with a more exact refusal message. Left as
known limits: the `--prefill-fp8` check runs only for the command-line flag, not for code that switches FP8 prompts
on by other means, and with two GPUs of different generations (`--tp 2`) only the older rank exits.

The patch is local. It has not been offered upstream.

## Tests

`kernel-tests.sh` runs TensorFold's own tests inside the image on the 3090 (`results-2026-10-13/kernel-tests-p4.log`).

| tests | result on image p4 |
|---|---|
| kernels of the 4-bit path: `test_qmm`, `test_qwen27_qmm`, `test_qwen27_forward`, `test_gdn`, `test_prefill_attention`, `test_qwen27_dflash2_blocks`, `test_qwen27_glue`, `test_qwen27_draft_attention` | 112 passed |
| `test_qwen27_prefill` | 15 passed (bf16 prompts), 12 skipped (FP8 prompts, need 8.9) |
| host tests: `test_cuda_build`, `test_cuda_gpu_floor`, `test_cuda_precision`, `test_cuda_cli` | 118 passed, 3 failed |
| `tests/cuda/test_build.py` | 2 failed |

The five failures are not from the patch and do not touch serving:

- Three are about the build lock (`test_the_lock_named_is_the_one_torch_waits_on`, and both tests in
  `tests/cuda/test_build.py`). Shown by hand in the container: torch 2.14.1 leaves its `lock` file in place after a
  successful build and does not wait on it, and with the pip CUDA toolkit TensorFold prints a "CUDA compiler" line
  first. The tests expect the older behaviour.
- Two in `test_cuda_cli.py` call the Flash Next engine, which upstream refuses on any card below SM 12.0. They are
  written for a machine with no GPU or with a Blackwell card, and fail on a real 3090 for that reason.

The server also refuses `--prefill-fp8` on the 3090 with exit code 1 before loading anything
(`results-2026-10-13/prefill-fp8-refusal-p4.log`).

Every start prints "waits on the build lock ... a killed build left it" for each extension. Nothing is wrong and
no build was killed: it is the leftover lock file described above. Do not delete the lock on its account.

## Files

| file | what |
|---|---|
| `Containerfile`, `build.sh`, `image-id.txt`, `pip-freeze.txt` | the image and its pins |
| `patches/` | the patch |
| `run.sh` | start the server on titan |
| `rounds.sh` | the three-round comparison |
| `context-probe.sh` | the largest window that fits |
| `long_prompt.py` | the long-prompt test |
| `kernel-tests.sh` | upstream's tests on our card |
| `results-2026-10-13/` | `summary.tsv`, `rounds.log`, one JSON per engine and round, and the logs named above |
