# Qwopus3.8-27B-Coder-Flash

**Status:** Tested

| | |
| --- | --- |
| Family | Qwen3.8 27B |
| Source | Jackrong/Qwopus3.8-27B-Coder-Flash (Apache-2.0; a fine-tune of Qwen3.8-27B) |
| What we graded | Round 1 only, two setups |

## Summary

A coding fine-tune of Qwen3.8-27B, graded one round. On the short coding set it ties stock Qwen3.8-27B: 26 of 28 each on the Q4_K_M gate, the same 2 of 3 init probes, 3 of 3 long-context retrievals and 3 of 3 vision checks. It used about a third fewer reasoning tokens on the items both models solved, and that did not hold on the hard items. Decode on the gate was within 2–3% of stock (41.6 against 42.5 tok/s on a short prompt).

## Setups

The primary is an EXL3 quant at 5.0 bits per weight (6-bit head, MTP head at 4 bits, vision on), served on exllamav3 1.6.2 with its own MTP drafts, 98,304 context and an 8-bit cache. A fit check kept at least 1.5 GiB free through a prompt that fills the window. The bench that chose this arm (thinking off, no image in the prompt) was 98.2 tok/s code, 60.3 prose and 111.5 structured, with 58.7% of drafts accepted. The graded round is that arm with vision on; those agent runs did not record a tok/s. A 6.0 bpw build did not hold 64k context with MTP under that margin. Q6_K on llama.cpp did not fit this card. Q5_K_M on llama.cpp fits 98k and decodes at about 38 tok/s, and its agent round is not in this note.

The other graded setup is the Q4_K_M GGUF on llama.cpp at 98,304 context with 8-bit KV, the gate row.

## Verdict

Not smarter than stock on the evidence we have, and only one round. It does not replace the Qwen3.8-27B pick. Both setups passed the eight core agent tests. Tests 7 and 8 did not run. The one-shots have no hand grade yet (the frames were not scored).

## Results, primary (EXL3 5.0 bpw, MTP, 98k, vision on)

Test 1: 52 tests, none failing. Test 2: the server builds, 5 tools, 27 tests, none failing. Test 2T: 6 tools, 40 tests, trust "avoided". Test 3: 14 of 14 on the known-good server and on its own, judgement right both times. Test 4: all three tickets passed. Per-run tok/s was not in the grade table.

## Results, Q4_K_M on llama.cpp

Test 1: 55 tests, none failing, 28 minutes. Test 2: 8 tools, 55 tests, 63 minutes. Test 2T: 6 tools, 41 tests, trust "avoided", 33 minutes. Test 3: 14 of 14 both flavours (known-good 14 minutes, own server 62 minutes; the own server has 8 tools and 56 tests). Test 4: all three tickets passed (8, 37 and 13 minutes).

_Written 2026-11-04 from round 1. Rounds 2–5 are not graded here._
