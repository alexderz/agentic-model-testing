# TensorFold #603: agent start here

Local review draft: NOT posted, committed or pushed. Navigation and fixture manifest for the **existing harness**, not a new benchmark runner.

## Existing public entry points (immutable)

- [Task runner and original TASKS literal](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/tools/bench_tasks.py)
- [Receipt, method and model revisions](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/README.md)
- [Original interleaved rounds](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/rounds.sh)
- [Server wrapper](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/run.sh)
- [Pinned build](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/build.sh), [Containerfile](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/Containerfile), [wheel lock](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/pip-freeze.txt), [image receipt](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/image-id.txt)
- [Long-context probe](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/context-probe.sh) and [prompt generator](https://github.com/alexderz/agentic-model-testing/blob/0b9187ec944aca3df8a7703be469acff0477e374/harness/engines/tensorfold/long_prompt.py) are separate from these 15 prompts.

Proposed addition (NOT live at that commit): `docs/repro/tensorfold-603/README-agent-start-here.md`, with `fixtures.json`, `fixture-sha256.json` and `verify_fixtures.py` alongside. The [proposed main-branch path](https://github.com/alexderz/agentic-model-testing/blob/main/docs/repro/tensorfold-603/README-agent-start-here.md) is for use only after publication approval.

## Exact recorded inputs

| Item | Receipt pin/configuration |
|---|---|
| Target | RTX 3090, SM 8.6, 24 GiB |
| Model | `TensorFold/Qwen3.8-27B-MLX-4bit@22d8d538154e0e5b6f8dcb1fcc74a60a0798104c` |
| DFlash2 | `z-lab/Qwen3.8-27B-DFlash2@50307d4c4cde6860d4eee73e2547cd786fe8e8a4` |
| Engine | TensorFold 0.6.6, `cb2ebf0540f42604e2759b2ddef497861e928248` (receipt short form `cb2ebf05`), patched Python engine |
| Runtime | torch 2.14.1; triton 3.8.0; CUDA toolkit 13.0.3 (wheel `cuda-toolkit==13.0.3.0`) |
| Server | `--context 16384 --no-thinking`; default DFlash2 enabled; do not add `--no-drafts` |
| Requests | 5 code, then 5 prose, then 5 structured; 15 serial requests per round |
| Generation | maximum 400 completion tokens; temperature 0; `chat_template_kwargs.enable_thinking=false`; no seed recorded or sent |
| Original protocol | One no-draft TF baseline; then three interleaved rounds: TF+DFlash2, llama.cpp MTP, llama.cpp plain; fresh server/load per arm per round |

JSON preserves exact decoded UTF-8 prompt text and task/in-task order from the TASKS literal, not Python-source formatting. Per-prompt SHA-256 hashes cover UTF-8 prompt bytes. The manifest also hashes the source harness, TASKS source span, exported JSON and missing patch.

## Offline first: no GPU, server, network or imported harness

From an existing public-repository checkout with this proposed package present:

```sh
python3 docs/repro/tensorfold-603/verify_fixtures.py --root . --print-command
(cd docs/repro/tensorfold-603 && sha256sum -c SHA256SUMS)
```

The standard-library checker uses AST parsing and literal evaluation, never imports/executes the harness, and prints but never runs its client command. It also supports a source tree with `tools/bench_tasks.py`. All 15 prompts, order/text/hashes, full harness hash, TASKS span, JSON and patch are checked.

## Reuse the existing client (future inference only)

With an already prepared, pinned server on loopback, this is the actual harness CLI: positional base/model, `--output` (not `--out`).

```sh
python3 harness/tools/bench_tasks.py http://127.0.0.1:18080 bench --tasks code,prose,structured --tokens 400 --temperature 0 --label tf-dflash2-r1 --output tf-dflash2-r1.json
```

For the receipt's pinned patched Python engine, the wrapper's server invocation is equivalent to:

```sh
tensorfold serve TensorFold/Qwen3.8-27B-MLX-4bit --name bench --host 127.0.0.1 --port 18080 --context 16384 --no-thinking
```

The command alone does NOT pin downloaded weights: provision/cache model and drafter at the recorded revisions first and use the receipt's offline pinned environment. Existing build/run/round scripts are historical site-specific recipes: inspect/adapt mounts, caches and engine names rather than running unchanged. No new orchestration is supplied. Repeat with fresh server starts and r2/r3 labels for the three-round protocol; a standalone TF pass is not the original interleaved experiment.

## One missing public build dependency

That public commit omits `harness/engines/tensorfold/patches/0001-sm86-floor-and-fp8-stub.patch`; `build.sh` assembles source plus patches for the Containerfile. Local public staging adds ONLY that missing patch at its existing expected path, copied byte-for-byte from the receipt, not a replacement harness. SHA-256: 8617da6b46509962adde7680ac534f3f1da484d36803951588d5f2c0f2729fcc. Source-tree equivalent: `engines/tensorfold/patches/0001-sm86-floor-and-fp8-stub.patch`.

The patch lowers the SM floor, chooses a non-FP8 stub on pre-Ada cards, and includes matching CLI/capacity/precision checks, tests and documentation. It does not provide native-CUDA gate evidence. Unchanged upstream copyright, Apache-2.0, retained MIT and third-party notices are bundled in `UPSTREAM-NOTICES.txt`. The copied patch remains an unchanged diff; its changed files are identified by its diff headers. Legal attribution is not experiment/personal data.

## Limits / inputs not recovered

- **Patched Python-engine receipt, NOT a native-CUDA gate pass.** The combined native implementation still needs its own 3090 gate; reuse these inputs without presenting the old receipt as that result.
- The receipt records short HF revisions `22d8d538` / `50307d4c`; the full immutable pins above were resolved from public HF API metadata and independently verified by the coordinating parent on 2026-10-16: [model snapshot](https://huggingface.co/TensorFold/Qwen3.8-27B-MLX-4bit/tree/22d8d538154e0e5b6f8dcb1fcc74a60a0798104c) / [DFlash2 snapshot](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2/tree/50307d4c4cde6860d4eee73e2547cd786fe8e8a4).
- No seed recorded/sent. Temperature zero is not a cross-engine determinism guarantee.
- Exact compiled image/kernel caches and GPU execution environment are not bundled; existing image/wheel receipts are pointers, not a distributed image. No build, patch-apply, inference or native-gate test was performed for this handoff.
- Different quantization recipes/tokenizers and one card/sitting limit comparisons; see the existing receipt. No outputs, raw results or long-context traces are included.

See `PRIVACY.md` for scope/offline proof and `POST.md` for the unposted draft. Independent scoped privacy and offline fixture checks passed. Publication and GPU build/runtime validation have not been performed.
