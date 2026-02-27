#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p .cargo .rustup

if [[ -x "$ROOT_DIR/.cargo/bin/rustup" ]]; then
  echo "local rustup already installed: $ROOT_DIR/.cargo/bin/rustup"
  exit 0
fi

curl -fsSL https://sh.rustup.rs -o /tmp/vsbotfresh-rustup.sh
CARGO_HOME="$ROOT_DIR/.cargo" RUSTUP_HOME="$ROOT_DIR/.rustup" sh /tmp/vsbotfresh-rustup.sh -y --profile minimal

echo "installed local rust toolchain"
echo "export CARGO_HOME=\"$ROOT_DIR/.cargo\""
echo "export RUSTUP_HOME=\"$ROOT_DIR/.rustup\""
echo "export PATH=\"$ROOT_DIR/.cargo/bin:$PATH\""
