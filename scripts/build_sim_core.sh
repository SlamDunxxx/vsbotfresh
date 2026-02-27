#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/sim-core"

export CARGO_HOME="$ROOT_DIR/.cargo"
export RUSTUP_HOME="$ROOT_DIR/.rustup"
if [[ -d "$CARGO_HOME/bin" ]]; then
  export PATH="$CARGO_HOME/bin:$PATH"
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not found; cannot build sim-core" >&2
  exit 1
fi

cargo build --release

echo "built: $ROOT_DIR/sim-core/target/release/sim-core"
