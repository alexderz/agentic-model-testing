# Privacy / review boundary

Local review draft; not published. Independent scoped privacy and offline fixture review completed; no publication was performed. No commit, push or GitHub comment performed.

## Included / excluded

Allowlist: 15 synthetic instruction strings from the existing public TASKS literal; order and SHA-256 hashes; public model/software revisions, versions and benchmark configuration; navigation links; AST-only checker; one omitted engine patch. No prompt rewritten. Requests for fictional employees or calendar attendees are instructions, not an actual employee/calendar dataset.

Excluded: personal/user data, private hostnames/IPs/absolute paths, transcripts, existing model outputs/results, home-automation fixtures (including pseudonymized versions), cloud keys/credentials, environment files and private infrastructure. No environment/credential store scanned. Only explicitly selected source/package files were examined.

Public project/model identifiers and upstream copyright-holder names occur as public identifiers or necessary legal attribution. Loopback addresses in examples/upstream code are not private infrastructure addresses. Existing historical site-specific scripts are linked, not recopied; this addition does not endorse their publication scope.

## Patch and attribution

The missing patch is copied byte-for-byte from the recorded engine patch. Diff headers identify changed upstream source/tests/docs: generic SM86 floor, unsupported FP8 refusal/stub logic and synthetic tests, with no site-specific paths/addresses, outputs or credentials. build.sh assembles source plus patches for the Containerfile. UPSTREAM-NOTICES.txt retains the pinned upstream Apache-2.0, NOTICE, older MIT and third-party notices; the patch is not relicensed under this repository's MIT umbrella.

## Offline proof (2026-10-16)

Preparation checks, standard-library CPU only, without importing/executing the benchmark harness:

- AST literal export/equality: exactly code/prose/structured in order, five strings each.
- Existing pinned public runner and local source runner byte-identical; full source/TASKS hashes recorded.
- JSON roundtrip preserves each prompt's exact UTF-8 bytes; 15 ordered prompt hashes recorded.
- Verifier passes public-layout and source-layout trees; printed CLI matches positional base/model, --tokens, --temperature, --tasks, --label, --output in the existing parser.
- Compile-only checks on checker and runner, without executing/importing runner.
- In-memory negative controls reject changed prompt text, category order and prompt hash.
- All new docs byte-identical between local packages; SHA256SUMS validates every other document; patch hash is in fixture-sha256.json and start-here.
- Targeted scan of selected new files/patch rejects private-path/host/IP markers, key formats and credential assignments; no environment scan.
- Original tracked public files unchanged; only new engine path is the missing patch.

No GPU load, container run/build, model-server inference/network request, restart, native gate or patch-apply test performed. Public GitHub comment/source/license reads were documentary verification only. Offline checks do not establish runtime performance/native correctness or comprehensive secret-detection guarantees.

Full model/drafter commit IDs were resolved from public HF API metadata and independently verified by the coordinating parent on 2026-10-16; the receipt retains its original short IDs. No additional network read was needed for this correction.

Missing inputs: any RNG seed, distributed compiled image/kernel caches and an exact replayable GPU environment. Historical wrappers need site adaptation; this is not a portable build framework.

## Independent coordinating review

Completed 2026-10-16T14:01:15.113541+00:00. Reviewed selected additions only, confirmed mirror equality and patch hash, AST/Python syntax, all 15 original synthetic fixtures, and offline verifier success. Three independent negative controls rejected altered prompt text, category ordering and the actual source-harness hash. Targeted checks found no private paths/domains/IPs or credential-like values in these additions. This is a scoped review, not a claim that the whole existing public repository was re-audited. No inference, container build or GPU action was performed.
