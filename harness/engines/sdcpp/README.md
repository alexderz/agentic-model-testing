# stable-diffusion.cpp (sd-server) on titan

Operator 2026-10-05: run both ComfyUI and sd.cpp. sd.cpp = the llama.cpp of image models: one C++
binary, GGUF diffusion models, an embedded web UI (since 2026-04) and an OpenAI-style images API
(`examples/server/routes_openai.cpp`), so agents (Hermes, OpenClaw, our tools) need no plugin.

- Image `localhost/sdcpp:sm86`, built on Saturn (`build.sh`), release `master-929-3f8527a`
  (2026-09-27), CUDA 12.8.1 sm86, frontend (leejet/sdcpp-webui submodule) built with pnpm.
- Qwen-Image 2.1 (sd.cpp docs/qwen_image_2.1.md): `--diffusion-model` (Comfy-Org safetensors or a GGUF:
  leejet Q8_0, abenzerps uncensored Q8_0/Q4_K_M), `--vae qwen_image_2.1_vae_bf16.safetensors`
  (the 2.1 VAE; older Qwen-Image/Wan VAEs do not work), `--llm` Qwen3-VL-8B (NAS
  `vision/qwen3vl-8b/Qwen3VL-8B-Instruct-Q4_K_M.gguf`, + `--llm_vision mmproj-…F16.gguf` for edits),
  `--diffusion-fa`, `--offload-to-cpu` if VRAM is tight, cfg 6.0, euler.
- Would-be llama-swap entry: container `sdcpp`, `--listen-ip 0.0.0.0 --listen-port 1234`, models :ro.
