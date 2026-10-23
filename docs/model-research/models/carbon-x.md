# Carbon-X

**Status:** Downloaded, not tested yet

| | |
| --- | --- |
| Family | Carbon |
| Source | Carbon-X (HuggingFace Bio), Q8_0 GGUF (15 GB, Apache-2.0) |
| Architecture | Dense, 14.8B, 40k context; a hybrid tokenizer (BPE for text, 6-mers for DNA) |
| Vision | no |

## Summary

An open model for DNA understanding and generation that also chats in English.
It predicts whether a variant is benign or pathogenic, classifies sequences and
explains its reasoning. It was post-trained with thinking off; the card
recommends temperature 0.6, top-p 0.95, top-k 20. It needs llama.cpp b11742 or
newer; older builds load it and tokenize DNA wrongly.

## Verdict

A trial on 2026-10-22, not a pick. On llama.cpp (a newer build, 40k context,
8-bit cache, one slot) it decodes at 52 tok/s, calls a tool correctly, and
missed a needle at 36.7k tokens. On the card's sickle-cell DNA example it said
"pathogenic" but gave the wrong reason. The pagoda and orrery one-shots ran
(51 tok/s; the SVG parses) and are not graded. No agent test has run.

## Trial results

| Check | Result |
| --- | --- |
| Load | 86 s, 18,182 MiB of VRAM |
| Decode, code / prose / structured | 51.8 / 51.8 / 51.7 tok/s |
| Tool call | OK (`get_state` with the right entity) |
| Needle at 36.7k tokens | missed; 24 s to first token; a repeated prompt answered in 0.1 s |
| Multi-session probe | 10 of 11; the check that sends two requests together fails by design with one slot |
| DNA example (sickle-cell variant) | pathogenic, wrong reason |

_Written from the bake-off results on 2026-10-22._
