# Qwen3.8-Flash-Next Gyro-S (TQ1_0)

**Status:** Tested

| | |
| --- | --- |
| Family | Qwen3.8 Flash-Next |
| Source | Qwen3.8-Flash-Next-Gyro-GGUF, Gyro-S-TQ1_0 (a third-party quantization of Qwen/Qwen3.8-Flash-Next, Qwen Community License 1.0) |
| Architecture | MoE, 125B total / 6B active |
| Vision | no (our Strata 0.2 build is text only) |

## Summary

The smallest quant of the Gyro family: the routed experts are stored as
trellis-coded blocks in a Hadamard-rotated basis. The file is about 58 GB, half
of it an n-gram table that stays on a local SSD and is read row by row for every
token; the weights need about 27.6 GB of VRAM and RAM together. Strata reads the
file unchanged, and runs it only with an MTP draft head. Strata's own evaluation
puts it 13 % worse in KL than IQ2_XS with 24 % fewer bytes.

## Verdict

A candidate for the fastest competent role, not a pick. On Strata 0.2.0-beta
with an MTP draft it decodes 119 tok/s on code (the same engine reads the IQ3_S
quant at 35 tok/s), passed test 2 in full in 24 minutes (6 tools, 108 tests, none
failing) and scored 9 of 10 as an agent pagoda in 16 minutes. The tool call and
needle probes at 16k and 64k passed. Strata 0.2.2 raised decode to 144 tok/s on
code in a same-day control (121.6 on 0.2.0), with no agent run on it yet. It is
one test-2 run on a beta engine; test 1 has not been graded. The picks in
[Conclusions](../conclusions.md) do not change until a repeat supports it.

## Vision

| Weights | Vision | Head | Head size | Tokens per 1280x720 screenshot |
| --- | --- | --- | --- | --- |
| Gyro-S | no | – | – | – |

The Gyro files can read pictures with the original model's head, but our
Strata 0.2 image has no vision path, so the agent pagoda ran blind.

## Variants we ran

| Variant | Engine | Quantization | Context | Expert layers in RAM | Best tok/s over a run |
| --- | --- | --- | --- | --- | --- |
| Flash-Next Gyro-S TQ1_0 + MTP draft · Strata 0.2.0-beta, int8 KV | Strata 0.2.0-beta | Gyro-S TQ1_0 (trellis-coded experts) | 256k | – | 89.8 |

## Results

Test 2 builds a Rust MCP server and is graded by connecting to it as a client.
One run. See [Method](../method.md) and [Engines](../engines.md) for the
speed probes.

| Test | Result | Score | Own tests | tok/s | Minutes | Failed builds | Errors per 1k lines | Context | Expert layers in RAM | Engine | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | pass | 6 tools | 108 | 89.8 | 24 | 26/41 | 21.8 | 256k | – | Strata 0.2.0-beta | 4,781 lines of Rust; 0 tests failing |
| 8 | pass | pagoda 9/10 | – | 85.4 | 16 | – | – | 256k | – | Strata 0.2.0-beta | Draws a complete scene; roofs use half-height slabs, the rest cubes (B 1); 54 browser calls, no screenshots, no compactions |

## Speed probes

| Build | Date | Code | Prose | JSON | Notes |
| --- | --- | --- | --- | --- | --- |
| Strata 0.2.0-beta, Gyro-S + MTP | 2026-10-20 | 118.6 tok/s | – | – | prefill about 2,550 tok/s at 64k, peak VRAM 23,862 MiB |
| Strata 0.2.0-beta, IQ3_S + MTP | 2026-10-20 | 35.4 tok/s | – | – | the comparison arm; Strata 0.1.45 read 29.4 |
| Strata 0.2.0-beta, Gyro-S + MTP, control | 2026-10-22 | 121.6 tok/s | 106.4 | 135.2 | one load |
| Strata 0.2.2, Gyro-S + MTP | 2026-10-22 | 144.1 tok/s | 123.4 | 157.7 | one load, 23 s |

_Written from the bake-off results on 2026-10-22._
