#!/usr/bin/env bash
# Build the offline knowledge bundle mounted into agent runs.
#
# Premise: the pruned Flash-Next model spent 28 minutes compiling probe
# programs to discover whether std::env::get exists. That is a recall failure,
# not a reasoning failure. An agent with no web search has no way to look up
# an API, so it asks the compiler one guess at a time. This bundle gives it
# what a web search would have returned.
#
# Deliberately NOT summarised: this is the real rustdoc HTML from the exact
# toolchain in the image, the same pages doc.rust-lang.org serves. The point is
# to test whether models can USE reference material, not whether they can read
# a digest we pre-chewed for them.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/offline-docs}"
IMAGE="${AGENT_IMAGE:-localhost/bakeoff-agent}"
mkdir -p "$OUT"

podman run --rm --userns=keep-id -v "$OUT":/out:Z "$IMAGE" bash -c '
set -e
export RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH

echo "=== rust toolchain docs (std, book, reference, by-example, nomicon) ==="
rustup component add rust-docs >/dev/null 2>&1 || true
SYS=$(rustc --print sysroot)
if [ -d "$SYS/share/doc/rust/html" ]; then
  mkdir -p /out/rust
  cp -a "$SYS/share/doc/rust/html/." /out/rust/
  echo "  rust docs: $(du -sh /out/rust | cut -f1)"
else
  echo "  WARNING: rust-docs component not available"
fi

echo "=== crate docs for the dependencies this task actually needs ==="
mkdir -p /tmp/docgen/src && cd /tmp/docgen
cat > Cargo.toml <<TOML
[package]
name = "docgen"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ureq = "2"
reqwest = { version = "0.12", default-features = false, features = ["blocking", "rustls-tls", "json"] }
tokio = { version = "1", features = ["full"] }
anyhow = "1"
thiserror = "2"
clap = { version = "4", features = ["derive"] }
chrono = "0.4"
TOML
echo "fn main() {}" > src/main.rs
cargo doc --quiet 2>&1 | tail -3 || true
if [ -d target/doc ]; then
  mkdir -p /out/crates
  cp -a target/doc/. /out/crates/
  echo "  crate docs: $(du -sh /out/crates | cut -f1)"
fi
rm -rf /tmp/docgen
'

# Strip binary media. The user asked for text as a web search would return it;
# images and fonts are dead weight in a grep-driven workflow.
find "$OUT" -type f \( -name '*.woff*' -o -name '*.ttf' -o -name '*.svg' \
     -o -name '*.png' -o -name '*.jpg' -o -name '*.ico' \) -delete 2>/dev/null || true

cat > "$OUT/README.md" <<'MD'
# Offline reference documentation

You have no network access. These are local copies of the same pages you
would otherwise find online. They are complete and unedited, not summaries.

| path | what it is |
|---|---|
| `rust/std/` | Rust standard library API reference (`doc.rust-lang.org/std`) |
| `rust/book/` | The Rust Programming Language |
| `rust/reference/` | The Rust Reference (language semantics) |
| `rust/rust-by-example/` | Rust by Example |
| `rust/nomicon/` | The Rustonomicon (unsafe Rust) |
| `rust/error_codes/` | Explanations for every `E####` compiler error |
| `rust/cargo/` | The Cargo Book (manifest format, profiles, workspaces) |
| `crates/<name>/` | API reference for third-party crates available offline |

These are HTML files. Searching them is far cheaper than reading them:

    grep -rl "fn var" rust/std/env/          # which page documents it
    grep -rho 'fn [a-z_]*' rust/std/env/     # what functions a module has
    python3 -c "import html,re,sys; t=open(sys.argv[1]).read(); \
      print(re.sub('<[^>]+>','',t))" rust/std/env/index.html | head -60

`rust/error_codes/` is keyed by error number: a build failing with `E0308`
is explained in full at `rust/error_codes/E0308.html`.
MD

echo "=== bundle ==="
du -sh "$OUT"
du -sh "$OUT"/* 2>/dev/null | sort -rh | head
