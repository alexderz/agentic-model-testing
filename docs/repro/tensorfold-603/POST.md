# Reply sent to TensorFold issue 603

Source text for the public comment. Links use this repository after the commit that adds these files.

---

Hi Synthena — the 15 prompt fixtures from the second 3090 receipt are in this repo. No replacement harness.

The existing runner and all 15 original prompts are already at harness/tools/bench_tasks.py (public commit 0b9187ec944aca3df8a7703be469acff0477e374). Receipt notes: harness/engines/tensorfold/README.md.

Start here: docs/repro/tensorfold-603/README-agent-start-here.md
Exact fixtures: docs/repro/tensorfold-603/fixtures.json
Offline checker: docs/repro/tensorfold-603/verify_fixtures.py
The SM86 patch the existing Containerfile already references, previously missing from the public tree: harness/engines/tensorfold/patches/0001-sm86-floor-and-fp8-stub.patch

Pins:
- TensorFold/Qwen3.8-27B-MLX-4bit@22d8d538154e0e5b6f8dcb1fcc74a60a0798104c
- z-lab/Qwen3.8-27B-DFlash2@50307d4c4cde6860d4eee73e2547cd786fe8e8a4
- TensorFold 0.6.6 cb2ebf0540f42604e2759b2ddef497861e928248, SM86-patched Python engine, torch 2.14.1, triton 3.8.0, CUDA toolkit 13.0.3
- 16384 context, thinking off, temperature 0, 400 tokens, five code, five prose, five structured
- No seed was recorded. This is not a native-CUDA gate result.

With that server already up:

    python3 harness/tools/bench_tasks.py http://127.0.0.1:18080 bench --tasks code,prose,structured --tokens 400 --temperature 0 --label tf-dflash2-r1 --output tf-dflash2-r1.json

Original three rounds interleaved engines and started a fresh server for each arm. Synthetic prompts and configuration only. The native 3090 comparison still has to be run on the combined implementation.
