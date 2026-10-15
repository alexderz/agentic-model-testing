# Context / offload probes

Measure VRAM and decode throughput for a llama.cpp model across `-ncmoe`
(expert layers pushed to CPU) and `-c` (context) without touching
`llama-swap.yaml`. Runs `llama-server` directly on port 5899 inside the
llama-swap container.

`tps3.sh` is the one to copy: ladder of configs, warmup request to absorb
mmap page-in, then 3 timed reps.

## Four ways these probes lied before they worked

Every one reported a FALSE NEGATIVE -- "it does not work" -- which is the
direction that gets believed. Cost roughly an hour and one wrong conclusion
reported to the user.

1. `POST /unload` -> llama-swap answers **405**; the endpoint is GET. The
   response was sent to /dev/null, so the model stayed resident and the next
   allocation OOMed on an occupied card. Read as "262k context does not fit".
2. Readiness grep for `"server is listening"`. llama.cpp prints
   `llama_server: listening on`. A server that came up in 3.7s was recorded as
   "did not come up" after a 1200s timeout, and the ladder stopped early.
3. `curl 127.0.0.1:5899` from the **host**. The server runs in the container's
   netns. Connection refused, empty body, `curl -s` hid it, JSON parse failed.
4. `du -sh` on the fscache tree as non-root -> reported 16K for a cache holding
   86G, because the tree is root-owned and untraversable.

Rules that fall out of it:

- **Prove the positive.** Confirm the server answers a trivial request before
  recording any measurement. Never infer success from the absence of an error.
- **Never discard a response you are branching on.** `>/dev/null` on the call
  whose status you depend on is how 1 became a silent no-op.
- **Abort, do not measure, when a precondition fails.** If VRAM did not drop,
  stop -- an OOM measured against an occupied card looks exactly like a real
  capacity limit.
- **Check units before calling something incomplete.** `du` is GiB; model
  cards are GB. 92 GiB == 98.8 GB.

## Findings, Swift 1.5 Flash-Next IQ3_XXS, RTX 3090, n=3

| `-ncmoe` | ctx | VRAM | decode tok/s |
|---|---|---|---|
| 36 | 98304 (production) | 19,726 | 10.80 / 11.65 / 11.81 |
| 36 | 262144 | 22,838 | 13.06 / 12.25 / 12.71 |
| 43 | 262144 | 16,450 | 10.89 / 11.44 / 11.26 |
| 48 | 262144 | 11,388 | 6.30 (n=1) |

Full 262k context costs no measurable throughput at the same offload. The
cliff is at `-ncmoe 48`, and this model does not need 48 to reach full context.
~1.0 GiB of VRAM per expert layer returned to the GPU.

KV is q8_0 in the base cmd (48 layers x 2 kv heads x 512 = 51 KiB/token).
mmap + CPU tensor overrides means load is ~4s and the weight IO lands in
first-token latency instead: prefill on the cold request was 3.7 tok/s vs
17.3 warm. `--load-mode none` forces eager load if that matters.

## Cold loads off NFS: prefetch, and set the timeouts for the real read

A 95 GiB IQ4_XS on the NFS models mount reads at ~180 MiB/s when FS-Cache is
cold -- 9 to 20 minutes before the model can answer anything, depending on what
the cache already holds. Two consequences:

**Prefetch it -- for reliability, not speed.** `prefetch-model.sh <dir> <glob>`
reads every shard of the set to /dev/null on titan first, so FS-Cache serves the
load instead of the wire. Run it immediately before the load and never in
parallel with a running case: titan has 125 GB of RAM and these models are
~95 GiB, so streaming a second one evicts the resident model's pages and guts
the case that is executing.

Measured cold sequential rates, correcting an earlier claim in this file:

| model | read | rate | cache state |
|---|---|---|---|
| orcarouter | 90 GiB / 238s | 390 MiB/s | ~89 GiB ALREADY cached |
| heretic2 | 92 GiB / 534s | 177 MiB/s | genuinely cold |

The 390 MiB/s figure was a partly-warm read compared against a fully-cold mmap
load, and was written up here as "2.1x faster than mmap". It is not: cold
sequential is ~177 MiB/s against mmap's ~185. Prefetch does not make the read
faster. What it buys is that the read happens OUTSIDE the load, so llama-swap's
health check cannot kill a load mid-read, and load time becomes predictable
(9s warm instead of a variable 10-20 min). That is worth the 9 minutes; the
speedup claim was wrong.

The cache is 220 GiB with ~90 GiB free and cachefilesd culls at 7% free, so
consecutive 95 GiB models evict each other. Prefetching makes each load fast;
it does not make the read disappear.

**Both timeouts were set for a 24 GB model.** llama-swap's
`healthCheckTimeout` and `lib.sh`'s `warm()` curl were each 900s. A cold 95 GiB
load exceeds that, so llama-swap killed the load mid-read and `warm()` recorded
`LOAD_FAILED` -- a model that was loading correctly, reported as a capability
failure. Both are now 2400s.

## A fifth false negative, same shape as the other four

`pgrep -f "gate-models.sh"` matched the Bash wrapper whose command line
contained that string, so `kill` killed the harness's own shell (exit 144).
This is written down two sections above and in `watchdog-abliterated.sh`, and it
still happened. `-f` matches the full command line of *every* process, including
the one doing the matching. Use `ps -o pid=,args= -C bash | grep <script>`, or
keep the PID from launch.
