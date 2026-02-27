#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CARGO_HOME="$ROOT_DIR/.cargo"
export RUSTUP_HOME="$ROOT_DIR/.rustup"
if [[ -d "$CARGO_HOME/bin" ]]; then
  export PATH="$CARGO_HOME/bin:$PATH"
fi

PYTHONPATH="$ROOT_DIR/src" python3 -m unittest discover -s tests -p 'test_*.py'
