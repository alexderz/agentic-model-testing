# Flint 40B-A2.5B

**Status:** Downloaded, not tested yet

| | |
| --- | --- |
| Family | Flint |
| Source | Flint (Apache-2.0), Unsloth Dynamic GGUFs UD-Q3_K_XL (18 GB) and UD-Q4_K_XL (24 GB) |
| Architecture | MoE, 39.8B total / about 2.5B active, 49 layers (2 dense, 47 MoE), 35 sliding-window and 14 full-attention layers |
| Vision | no (text only) |

## Summary

A coding-agent mixture-of-experts model. The makers report 54.9 % on
Terminal-Bench 2.1 and 74.2 % on SWE-bench Verified; we have not checked either.
The Q3_K_XL file runs entirely on the GPU at 262k context with an 8-bit cache.
It needs llama.cpp build b11803 or newer; the 0.7.0 image cannot load it.

## Verdict

No agent test has run. Speed only (2026-10-21 and 22): the Q3_K_XL file decodes
at 129 tok/s on a short prompt and 106 at 11.7k of depth, and reads an 11.7k
prompt at 5,357 tok/s. With f16 KV it does not fit. The Q4_K_XL file does not
fit entirely: with 15 expert layers in RAM it decodes at 81 tok/s, with 24 at
64, and with 10 layers at a 150k window at 95. The pagoda and orrery one-shots
(Q3_K_XL) ran at 110 and 102 tok/s and are not graded.

## Variants we ran

| Variant | Engine | Quantization | Context | Expert layers in RAM | Short decode | Decode at 11.7k | Prefill at 11.7k | VRAM (MiB) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Flint · llama.cpp b11803+, all on GPU | llama.cpp | UD-Q3_K_XL | 256k | 0 | 128.7 | 106.4 | 5,357 | 23,234 |
| Flint · llama.cpp b11803+ | llama.cpp | UD-Q4_K_XL | 150k | 10 | 95.0 | 82.0 | 2,799 | 23,134 |
| Flint · llama.cpp b11803+ | llama.cpp | UD-Q4_K_XL | 256k | 15 | 81.4 | 72.3 | 2,208 | 22,708 |
| Flint · llama.cpp b11803+ | llama.cpp | UD-Q4_K_XL | 256k | 19 | 73.1 | 65.8 | 1,888 | 20,596 |
| Flint · llama.cpp b11803+ | llama.cpp | UD-Q4_K_XL | 256k | 24 | 64.2 | 59.2 | 1,624 | 18,348 |

All with `-ctk q8_0 -ctv q8_0 -b 2048 -ub 2048 -t 16 -np 1 -fit off`. Q4_K_XL
with fewer than 10 layers in RAM failed to load at 262k. Speeds are tok/s.

## Results

None graded. Tests 1 and 2 have not been run.

_Written from the bake-off results on 2026-10-22._
