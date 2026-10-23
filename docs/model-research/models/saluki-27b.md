# Underdog Saluki 27B (2-bit)

**Status:** Tested

| | |
| --- | --- |
| Family | Qwen3.8 27B |
| Source | Underdog-Saluki-27B-1.0, IQ2-mix GGUF (Apache-2.0), a tune of Qwen/Qwen3.8-27B on a GSQ-RCO 2-bit quant |
| Architecture | Dense, 27B |
| Vision | – |

## Summary

Qwen3.8-27B tuned to keep tool calling at 2 bits. The GGUF is 7.9 GB, so the
whole model, a 262k window with an 8-bit cache and the draft-free decode fit
the card with room to spare (18.5 GiB in use). Run with the card's sampling
(temperature 0.6, top-p 0.95, top-k 20) and thinking on.

## Verdict

The smallest model that still calls tools. Test 1 passed 5 of 5 with 72 of its
own tests and 9 subcommands, in 63 minutes at 25.3 tok/s. Test 2 was a partial
pass: it built a server with 17 tools, 47 of its tests passed and 3 failed, in
166 minutes at 22.0 tok/s, and `list_entities` called the invented
`/api/entities`, which the replay answers with a 404. It decodes at about a
third of the speed of the 4-bit 27B on vLLM. One run each, 2026-10-15.

## Variants we ran

| Variant | Engine | Quantization | Context | Expert layers in RAM | Best tok/s over a run |
| --- | --- | --- | --- | --- | --- |
| Underdog Saluki 27B IQ2-mix · llama.cpp 0.6, thinking on, q8_0 cache | llama.cpp 0.6 | IQ2-mix (GSQ-RCO) | 256k | – | 25.3 |

The entry now runs on llama.cpp 0.7.0 with the same flags.

## Results

| Test | Result | Score | Own tests | tok/s | Minutes | Failed builds | Errors per 1k lines | Context | Expert layers in RAM | Engine | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | pass | 5/5 checks | 72 | 25.3 | 63 | 0 | 0.0 | 256k | – | llama.cpp 0.6 | 9 subcommands, 1,643 lines, no compaction |
| 2 | partial | 17 tools | 47 | 22.0 | 166 | 17/18 | 48.9 | 256k | – | llama.cpp 0.6 | 47 tests pass, 3 fail; invented `/api/entities` in `list_entities`; 1 compaction |

The one-shot pagoda ran at 42.8 tok/s; the orrery reply did not parse. Neither
is graded.

_Written from the bake-off results on 2026-10-22._
