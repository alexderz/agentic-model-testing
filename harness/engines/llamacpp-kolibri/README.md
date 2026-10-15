# Kolibri-1 on llama.cpp (v0.6.0 + kolibri1 patch)

Aleph-Alpha/Kolibri-1: 78.1B MoE, 3.46B active, EN/DE, ~262k native context, reasoning + tool
calling, Apache 2.0. The `kolibri1` architecture is not in upstream llama.cpp. Hob-forge's patch
(4 commits, written against upstream 836d571, sha256 in `patch.sha256`) applies cleanly to v0.6.0
(d81235049), so the build gets v0.6.0's spec-decoding and MoE fixes too.

- Build: on **Saturn** (operator: compile there), `build.sh` → `localhost/llamacpp-kolibri:v0.6.0-sm86`
  from upstream `.devops/cuda.Dockerfile --target server`, CUDA 12.8.1, `CUDA_DOCKER_ARCH=86`.
  Shallow fetch of the one commit (a full clone crawled next to the NAS downloads).
- Copy to titan: `ssh saturn 'podman save localhost/llamacpp-kolibri:v0.6.0-sm86' | ssh titan 'podman load'`
  (the queue step in run-next.sh does this).
- Weights: Saturn `/srv/store/models/llm/kolibri-1/` (Hob-forge/Kolibri-1-GGUF @ 3fc032594aef):
  `Kolibri-1-Q4_K_M.gguf` 44 GiB, `Q8_0/` 77 GiB (2 shards), the patch, README.
- Entry `kolibri-1` (`tools/add_kolibri_entry.py`): Q8_0, container `llamacpp-kolibri:8097`,
  `--jinja`, temp 1.0 / top-p 0.97 / top-k 128 (card), `reasoning_effort: high`, experts in RAM.
- Caveat from the converter: verified to 8k context only (tokenizer and template identical to HF,
  logits checked against a float64 reference); nothing longer was tested.
