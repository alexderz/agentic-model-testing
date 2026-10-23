# Ornith-1.5-122B

**Status:** Downloaded, not tested yet

| | |
| --- | --- |
| Family | Ornith |
| Source | Ornith-1.5-122B, Unsloth UD-Q4_K_XL GGUF (3 files, 75 GB) |
| Architecture | MoE, a Qwen3.5 122B mixture, 8 of 256 experts per token, with a vision tower |
| Vision | yes (head), not tried |

## Summary

A fine-tune of a 122B Qwen3.5 mixture. The Q4_K_XL file needs most experts in
system RAM. A DFlash2 draft head and an MTP head are available. Card sampling:
temperature 0.6, top-p 0.95, top-k 20.

## Verdict

No agent test has run. On llama.cpp 0.7.0 with 262k context and an 8-bit cache
the best offload decodes at 16.3 tok/s (40 expert layers on the CPU), 15.8 at
depth; larger batches lift prefill from 116 to 392 tok/s (41 layers). The one-shot pagoda
and orrery ran at about 15 tok/s and are not graded. The sweep (2026-10-20) is below.

## Variants we ran

| Expert layers on the CPU | Draft | Short decode | Decode at depth | Prefill (batch) | VRAM (MiB) |
| --- | --- | --- | --- | --- | --- |
| 42 | – | 13.7 | – | – | 20,426 |
| 41 | – | 16.0 | 15.7 | 116 | 21,722 |
| 40 | – | 16.3 | 15.8 | 118 (`-ub` default) | 23,114 |
| 41 | – | 16.1 | 15.6 | 392 (`-ub 2048`) | 22,660 |
| 44 | MTP, 2 drafts | 16.7 | 16.7 | 108 | 22,334 |
| 44 | MTP, 3 drafts | 16.1 | – | – | 22,930 |
| 45 | DFlash, 4 drafts | 11.5 | 11.8 | 104 | 19,828 |

Loads with 39, 36 and 34 layers on the CPU failed on the compute or KV buffer.
Speeds are tok/s. MTP buys back the VRAM of four layers but not speed.

## Results

None graded. Tests 1 and 2 have not been run.

_Written from the bake-off results on 2026-10-22._
