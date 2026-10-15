# HyperQwen (vLLM) on Titan

Goal (operator, 2026-10-03): the large-context, smart, fast setup. Not a
reproduction of HyperQwen's published numbers: no 250 W cap, no run of their
benchmark harness. Our own tests decide.

- Engine: ghcr.io/syv-ai/hyperqwen@sha256:34c2e3a4... (= :latest = HyperQwen
  main e1459c7, vLLM 0.30.0 + patch series). Default 350 W.
- Model: Qwen3.8-27B W4A16 AutoRound (dbirks, 1f05c441), DFlash2 W4A16 drafter
  (syvai, 4d30ec73), fast variant (syvai, 124c14e7). Raw on NAS
  `vllm/hyperqwen`, prepared copy local in ~/ai/hyperqwen/models.
- One llama-swap entry, `qwen3.8-27b-vllm` (approved by Titan's agent);
  two entries (same container name), profile set by -e flags:
  - qwen3.8-27b-vllm (D): SPEC=mtp CTX=long -- ~150k context
  - qwen3.8-27b-vllm-240k (E): SPEC=dflash2 CTX=huge -- ~240k, KVarN 4/2-bit KV cache
- Tests: test 1 (HA CLI) and test 2 (Rust MCP server) on each profile,
  compared with qwen3.8-27b on llama.cpp (wave A 5/5 at 33 tok/s; wave B
  test 2 full pass at 213k, 18 tok/s over the run).
- Open question E answers: does the 4/2-bit KV cache cost correctness?
