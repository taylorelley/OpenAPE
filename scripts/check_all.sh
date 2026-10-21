#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
python -m scripts.check_reproducibility
python -m scripts.generate_protocol
