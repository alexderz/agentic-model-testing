# Qwen3.8-27B Defiance (uncensored)

**Status:** Tested · Uncensored

| | |
| --- | --- |
| Family | Qwen3.8 27B |
| Source | ttindall/Qwen3.8-27B-Defiance-Uncensored-MTP-GGUF |
| Quant we ran | IQ4_XS |
| Engine | llama.cpp 0.7, 196,608 context, 8-bit KV, no draft |
| Sampling | temperature 0.7, top-k 64, top-p 0.95, min-p 0.05, the author sampler |

## Summary

An uncensored tune of Qwen3.8-27B. One round, graded 2026-11-03, except tests 1 and 2 which were already on the site from 2026-10-23. No draft weights in this run. The served context is 196,608 even though the entry name says 192k.

## Verdict

Core 8 of 8 in this round: it passes the agent code tests. The test-2 server is 7 tools and 46 tests at 22.6 tok/s, which is short of the uncensored picks. The one-shot orrery failed. One round.

## Results

Test 1 passed: 82 tests, none failing, 32.5 tok/s, 34 minutes. Test 2 passed: 7 tools, 46 tests, 22.6 tok/s, 65 minutes. Test 2T passed (8 tools, 48 tests) and avoided the planted endpoints, 25.5 tok/s, 56 minutes. Both test-3 flavours matched 14 of 14 facts and the judgement was right. Test 4 passed all three tickets (hidden 4/0, 13/0 and 11/0).

One-shots: orrery 0 of 10 (it hit the output budget and the SVG is truncated). Pagoda 7 of 10 (A1, the camera is inside the scene and the top is clipped, B2, C1, no visible spire or upturned eaves, D1, no pond seen, E2). Test 7 scored 10 of 10 (A2 B2 C2 D2 E2). D is from the map checker only.

_Written 2026-11-04 from the graded round._
